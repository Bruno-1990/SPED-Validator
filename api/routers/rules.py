"""Endpoints para gerenciamento de regras de validacao."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.deps import get_doc_db_path

router = APIRouter(prefix="/api/rules", tags=["rules"])

_RULES_CANDIDATES = [
    Path("rules.yaml"),  # CWD (uvicorn roda da raiz do projeto)
    Path(__file__).resolve().parent.parent.parent / "rules.yaml",  # via __file__
]


def _get_rules_path() -> Path:
    """Resolve o caminho do rules.yaml (lazy, funciona com --reload)."""
    for p in _RULES_CANDIDATES:
        if p.exists():
            return p
    return _RULES_CANDIDATES[0]  # fallback para mensagem de erro


# ── Schemas ──

class GenerateRuleRequest(BaseModel):
    description: str


class GeneratedRule(BaseModel):
    id: str
    block: str
    register: str
    fields: list[str]
    error_type: str
    severity: str
    description: str
    condition: str
    module: str
    legislation: str | None = None
    legal_sources: list[dict] | None = None


class ImplementRuleRequest(BaseModel):
    rule: GeneratedRule


class RuleSummary(BaseModel):
    id: str
    block: str
    register: str
    error_type: str
    severity: str
    description: str
    implemented: bool


# ── Endpoints ──

@router.get("", response_model=list[RuleSummary])
def list_rules() -> list[RuleSummary]:
    """Lista todas as regras definidas no rules.yaml."""
    if not _get_rules_path().exists():
        raise HTTPException(
            status_code=404,
            detail=f"rules.yaml nao encontrado em {_get_rules_path()}",
        )

    with open(_get_rules_path(), encoding="utf-8") as f:
        data = yaml.safe_load(f)

    rules: list[RuleSummary] = []
    for block_name, block_rules in data.items():
        if block_name in ("version", "tolerance") or not isinstance(block_rules, list):
            continue
        for entry in block_rules:
            rules.append(RuleSummary(
                id=entry["id"],
                block=block_name,
                register=entry.get("register", "*"),
                error_type=entry.get("error_type", ""),
                severity=entry.get("severity", "error"),
                description=entry.get("description", ""),
                implemented=entry.get("implemented", False),
            ))

    return rules


@router.post("/generate", response_model=GeneratedRule)
def generate_rule(req: GenerateRuleRequest) -> GeneratedRule:
    """Gera uma regra estruturada a partir de descricao livre.

    Busca na base de documentacao para encontrar base legal relevante
    e estrutura a regra com campos padronizados.
    """
    description = req.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Descricao da regra nao pode ser vazia")

    # Verificar duplicidade antes de gerar
    existing = _load_existing_rules()
    duplicate = _find_duplicate(description, existing)
    if duplicate:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Regra semelhante ja existe: [{duplicate['id']}] "
                f"{duplicate['description']}"
            ),
        )

    # Buscar na documentacao
    legal_sources = _search_legal_basis(description)

    # Analisar a descricao para extrair campos
    rule = _parse_rule_description(description, legal_sources)

    return rule


@router.post("/implement")
def implement_rule(req: ImplementRuleRequest) -> dict:
    """Adiciona uma regra gerada ao rules.yaml."""
    rule = req.rule

    if not _get_rules_path().exists():
        raise HTTPException(status_code=500, detail="rules.yaml nao encontrado")

    with open(_get_rules_path(), encoding="utf-8") as f:
        data = yaml.safe_load(f)

    # Verificar duplicata por ID e por conteudo
    existing = _load_existing_rules()
    for entry in existing:
        if entry["id"] == rule.id:
            raise HTTPException(
                status_code=409,
                detail=f"Regra com ID '{rule.id}' ja existe no rules.yaml",
            )
        if entry.get("error_type") == rule.error_type and entry.get("register") == rule.register:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Regra com mesmo error_type '{rule.error_type}' e "
                    f"registro '{rule.register}' ja existe: [{entry['id']}] "
                    f"{entry.get('description', '')}"
                ),
            )
    dup = _find_duplicate(rule.description, existing)
    if dup:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Regra com descricao semelhante ja existe: [{dup['id']}] "
                f"{dup['description']}"
            ),
        )

    # Criar entrada YAML
    new_entry: dict = {
        "id": rule.id,
        "register": rule.register,
        "fields": rule.fields,
        "error_type": rule.error_type,
        "severity": rule.severity,
        "description": rule.description,
        "condition": rule.condition,
        "implemented": False,
        "module": rule.module,
    }
    if rule.legislation:
        new_entry["legislation"] = rule.legislation

    # Adicionar ao bloco adequado
    block = rule.block
    if block not in data:
        data[block] = []
    data[block].append(new_entry)

    # Salvar YAML
    with open(_get_rules_path(), "w", encoding="utf-8") as f:
        yaml.dump(
            data, f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            width=120,
        )

    return {"added": True, "rule_id": rule.id, "block": block}


# ── Helpers ──

def _load_existing_rules() -> list[dict]:
    """Carrega todas as regras existentes do YAML como lista de dicts."""
    if not _get_rules_path().exists():
        return []
    with open(_get_rules_path(), encoding="utf-8") as f:
        data = yaml.safe_load(f)
    rules: list[dict] = []
    for block_name, block_rules in data.items():
        if block_name in ("version", "tolerance") or not isinstance(block_rules, list):
            continue
        for entry in block_rules:
            entry["_block"] = block_name
            rules.append(entry)
    return rules


def _find_duplicate(description: str, existing: list[dict]) -> dict | None:
    """Verifica se ja existe regra com descricao semelhante.

    Compara palavras significativas — se >= 60% das palavras coincidem,
    considera duplicata.
    """
    stopwords = {
        "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no",
        "na", "nos", "nas", "um", "uma", "com", "por", "para", "que", "se",
        "nao", "ou", "e", "ao", "quando", "deve", "ser", "esta", "ter",
        "the", "and", "is", "of", "to", "in", "it", "if",
    }

    def normalize(text: str) -> set[str]:
        words = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).split()
        return {w for w in words if w not in stopwords and len(w) > 2}

    new_words = normalize(description)
    if not new_words:
        return None

    for entry in existing:
        existing_desc = entry.get("description", "")
        existing_words = normalize(existing_desc)
        if not existing_words:
            continue
        # Interseção sobre a menor das duas
        overlap = len(new_words & existing_words)
        min_size = min(len(new_words), len(existing_words))
        if min_size > 0 and overlap / min_size >= 0.6:
            return entry

    return None


def _search_legal_basis(description: str) -> list[dict]:
    """Busca base legal na documentacao indexada."""
    doc_db = get_doc_db_path()
    if not doc_db:
        return []

    try:
        from src.searcher import search
        results = search(query=description, db_path=doc_db, top_k=5)

        sources = []
        for r in results:
            fonte = r.chunk.source_file
            if fonte.endswith(".md"):
                fonte = fonte[:-3]
            fonte = fonte.replace("_", " ").replace("-", " ")

            sources.append({
                "fonte": fonte,
                "heading": r.chunk.heading or "",
                "content": r.chunk.content[:500] if r.chunk.content else "",
                "register": r.chunk.register,
                "score": round(r.score, 3),
            })
        return sources
    except Exception:
        return []


def _parse_rule_description(description: str, legal_sources: list[dict]) -> GeneratedRule:
    """Analisa descricao livre e gera regra estruturada."""
    desc_lower = description.lower()

    # Detectar registro
    register = _detect_register(desc_lower)

    # Detectar campos
    fields = _detect_fields(desc_lower)

    # Detectar bloco/categoria
    block = _detect_block(desc_lower)

    # Detectar severidade
    severity = _detect_severity(desc_lower)

    # Gerar ID
    rule_id = _generate_id(description)

    # Gerar error_type
    error_type = _generate_error_type(description)

    # Gerar condicao
    condition = _generate_condition(description)

    # Extrair legislacao das fontes
    legislation = _extract_legislation(legal_sources)

    return GeneratedRule(
        id=rule_id,
        block=block,
        register=register,
        fields=fields,
        error_type=error_type,
        severity=severity,
        description=description,
        condition=condition,
        module="fiscal_semantics.py",
        legislation=legislation,
        legal_sources=legal_sources[:3] if legal_sources else None,
    )


def _detect_register(text: str) -> str:
    """Detecta registro SPED mencionado no texto."""
    patterns = [
        (r'\b(c100|c170|c190|c200|c300|c400|c500)\b', None),
        (r'\b(d100|d150|d190|d500)\b', None),
        (r'\b(e100|e110|e200|e210)\b', None),
        (r'\b(h010|h020)\b', None),
        (r'\b(0000|0100|0150|0200|0300)\b', None),
    ]
    for pattern, _ in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).upper()

    # Inferir pelo contexto
    if any(w in text for w in ["item", "produto", "ncm", "cst_pis", "cst_cofins", "monofas"]):
        return "C170"
    if any(w in text for w in ["nota", "documento", "nf-e", "nfe"]):
        return "C100"
    if any(w in text for w in ["apuracao", "apuração", "debito", "credito", "saldo"]):
        return "E110"
    if any(w in text for w in ["estoque", "inventario"]):
        return "H010"
    return "C170"


def _detect_fields(text: str) -> list[str]:
    """Detecta campos SPED mencionados no texto."""
    field_patterns = {
        "CST_ICMS": r'cst[_ ]?icms|cst[_ ]?00|cst[_ ]?tributad',
        "CST_PIS": r'cst[_ ]?pis',
        "CST_COFINS": r'cst[_ ]?cofins',
        "CST_IPI": r'cst[_ ]?ipi',
        "CFOP": r'\bcfop\b',
        "NCM": r'\bncm\b',
        "ALIQ_ICMS": r'aliq.*icms|aliquota.*icms',
        "ALIQ_PIS": r'aliq.*pis',
        "ALIQ_COFINS": r'aliq.*cofins',
        "VL_ICMS": r'vl?[_ ]?icms|valor.*icms',
        "VL_BC_ICMS": r'base.*calc.*icms|bc.*icms|vl_bc_icms',
        "VL_PIS": r'vl?[_ ]?pis|valor.*pis',
        "VL_COFINS": r'vl?[_ ]?cofins|valor.*cofins',
        "VL_IPI": r'vl?[_ ]?ipi|valor.*ipi',
        "VL_DOC": r'vl?[_ ]?doc|valor.*doc',
        "COD_ITEM": r'cod[_ ]?item|codigo.*item',
        "COD_PART": r'cod[_ ]?part|participante',
        "IND_OPER": r'ind[_ ]?oper|operacao',
    }
    found = []
    for field, pattern in field_patterns.items():
        if re.search(pattern, text, re.IGNORECASE):
            found.append(field)
    return found if found else ["CST_ICMS"]


def _detect_block(text: str) -> str:
    """Detecta bloco/categoria da regra."""
    if any(w in text for w in ["monofas", "monofásic"]):
        return "monofasicos"
    if any(w in text for w in ["cfop", "venda", "exporta", "interestadual"]):
        return "semantica_cst_cfop"
    if any(w in text for w in ["aliquota zero", "alíquota zero", "zerado", "tudo zero"]):
        return "semantica_aliquota_zero"
    if any(w in text for w in ["isencao", "isenção", "isento", "tributado", "cst "]):
        return "cst_isencoes"
    if any(w in text for w in ["recalc", "calculo", "cálculo", "bc x", "base x"]):
        return "recalculo"
    if any(w in text for w in ["cruzamento", "0150", "0200", "bloco 9", "e110 vs"]):
        return "cruzamento"
    if any(w in text for w in ["formato", "cnpj", "cpf", "data", "cep"]):
        return "formato"
    return "semantica_cst_cfop"


def _detect_severity(text: str) -> str:
    """Detecta severidade sugerida."""
    if any(w in text for w in ["erro", "invalido", "inválido", "incorreto", "proibid"]):
        return "error"
    if any(w in text for w in ["critico", "crítico", "divergen"]):
        return "critical"
    if any(w in text for w in ["informati", "atenção", "atencao", "observ"]):
        return "info"
    return "warning"


def _generate_id(description: str) -> str:
    """Gera ID unico a partir da descricao."""
    words = re.sub(r'[^a-zA-Z0-9\s]', '', description.lower()).split()
    # Pegar as 4 palavras mais significativas
    stopwords = {
        "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no",
        "na", "nos", "nas", "um", "uma", "com", "por", "para", "que", "se",
        "nao", "não", "ou", "e", "ao", "quando", "deve", "ser", "esta",
        "este", "esse", "essa", "ter",
    }
    significant = [w.upper() for w in words if w not in stopwords and len(w) > 2][:4]
    return "RULE_" + "_".join(significant) if significant else "RULE_NOVA"


def _generate_error_type(description: str) -> str:
    """Gera error_type a partir da descricao."""
    desc_lower = description.lower()
    if "monofas" in desc_lower:
        return "MONOFASICO_REGRA_CUSTOM"
    if "cfop" in desc_lower and "cst" in desc_lower:
        return "CST_CFOP_REGRA_CUSTOM"
    if "aliquota" in desc_lower or "alíquota" in desc_lower:
        return "ALIQ_REGRA_CUSTOM"
    if "isencao" in desc_lower or "isenção" in desc_lower:
        return "ISENCAO_REGRA_CUSTOM"

    words = re.sub(r'[^a-zA-Z\s]', '', description.lower()).split()
    stopwords = {
        "o", "a", "os", "as", "de", "do", "da", "em", "no", "na", "um",
        "uma", "com", "por", "para", "que", "se", "nao", "ou", "e",
    }
    significant = [w.upper() for w in words if w not in stopwords and len(w) > 3][:3]
    return "_".join(significant) if significant else "REGRA_CUSTOM"


def _generate_condition(description: str) -> str:
    """Gera descricao da condicao a partir do texto livre."""
    # A condicao e basicamente a descricao reformulada como condicao logica
    return f"Descrito pelo usuario: {description}"


def _extract_legislation(sources: list[dict]) -> str | None:
    """Extrai referencias legislativas das fontes encontradas."""
    legislations: set[str] = set()
    for s in sources:
        fonte = s.get("fonte", "")
        heading = s.get("heading", "")
        combined = f"{fonte} {heading}".lower()

        # Detectar leis e decretos
        lei_patterns = [
            r'lei\s+(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
            r'decreto\s+(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
            r'convênio\s+icms\s+[\d.]+(?:/\d+)?',
            r'ajuste\s+sinief\s+[\d.]+(?:/\d+)?',
            r'ato\s+cotepe\s+[\d.]+(?:/\d+)?',
            r'resolução?\s+(?:senado\s+)?[\d.]+(?:/\d+)?',
            r'portaria\s+[\d.]+(?:-r)?',
            r'in\s+rfb\s+[\d.]+(?:/\d+)?',
        ]
        for p in lei_patterns:
            matches = re.findall(p, combined, re.IGNORECASE)
            legislations.update(m.strip().title() for m in matches)

    if legislations:
        return "; ".join(sorted(legislations)[:3])
    return None
