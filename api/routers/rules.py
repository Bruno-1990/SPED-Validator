"""Endpoints para gerenciamento de regras de validacao."""

from __future__ import annotations

import re
from datetime import date
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


class RuleCoverageMatch(BaseModel):
    """Uma regra existente que potencialmente ja abrange o cenario descrito."""
    rule_id: str
    description: str
    register: str
    fields: list[str]
    error_type: str
    severity: str
    match_reason: str
    match_score: float  # 0.0 a 1.0


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
    corrigivel: str = "investigar"
    corrigivel_nota: str | None = None
    certeza: str = "subjetivo"
    impacto: str = "relevante"
    vigencia_de: str | None = None
    version: str = "1.0"
    last_updated: str | None = None
    error_type_exists: bool = False
    error_type_suggestion: str | None = None
    objections: list[RuleCoverageMatch] = []


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
    Retorna objecoes quando regras existentes ja abrangem o cenario.
    """
    description = req.description.strip()
    if not description:
        raise HTTPException(status_code=400, detail="Descricao da regra nao pode ser vazia")

    existing = _load_existing_rules()

    # Verificar duplicata exata (texto quase identico) — bloqueia
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

    # Verificar abrangencia — regras existentes que ja cobrem este cenario
    rule.objections = _find_coverage_objections(rule, existing)

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

    # Criar entrada YAML com todos os campos de governanca
    new_entry: dict = {
        "id": rule.id,
        "register": rule.register,
        "fields": rule.fields,
        "error_type": rule.error_type,
        "severity": rule.severity,
        "corrigivel": rule.corrigivel,
        "description": rule.description,
        "condition": rule.condition,
        "implemented": False,
        "module": rule.module,
        "vigencia_de": rule.vigencia_de or date.today().isoformat(),
        "vigencia_ate": None,
        "version": rule.version or "1.0",
        "last_updated": date.today().isoformat(),
        "certeza": rule.certeza,
        "impacto": rule.impacto,
    }
    if rule.corrigivel_nota:
        new_entry["corrigivel_nota"] = rule.corrigivel_nota
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


def _find_coverage_objections(
    rule: GeneratedRule, existing: list[dict],
) -> list[RuleCoverageMatch]:
    """Detecta regras existentes que ja abrangem o cenario da nova regra.

    Analisa 4 dimensoes de sobreposicao:
    1. Mesmo registro (ou registro generico '*')
    2. Campos em comum
    3. Mesmo error_type ou error_type do mesmo dominio
    4. Condicao/descricao semanticamente similar

    Retorna lista de objecoes ordenada por score (maior primeiro).
    """
    objections: list[RuleCoverageMatch] = []
    new_fields = set(rule.fields)
    new_error_prefix = rule.error_type.split("_")[0] if rule.error_type else ""

    # Normalizar descricao da nova regra para comparacao semantica
    desc_stopwords = {
        "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no",
        "na", "nos", "nas", "um", "uma", "com", "por", "para", "que", "se",
        "nao", "não", "ou", "e", "ao", "quando", "deve", "ser", "esta",
        "ter", "pode", "campo", "valor", "registro",
    }

    def normalize_words(text: str) -> set[str]:
        words = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).split()
        return {w for w in words if w not in desc_stopwords and len(w) > 2}

    new_desc_words = normalize_words(rule.description)
    new_cond_words = normalize_words(rule.condition)
    new_all_words = new_desc_words | new_cond_words

    for entry in existing:
        score = 0.0
        reasons: list[str] = []
        ex_register = entry.get("register", "*")
        ex_fields = set(entry.get("fields", []))
        ex_error_type = entry.get("error_type", "")
        ex_desc = entry.get("description", "")
        ex_cond = entry.get("condition", "")

        # 1. Registro — mesmo registro ou generico
        register_match = False
        if ex_register == rule.register:
            score += 0.30
            register_match = True
            reasons.append(f"mesmo registro ({rule.register})")
        elif ex_register == "*":
            score += 0.15
            register_match = True
            reasons.append(f"regra existente cobre todos os registros (*)")
        elif rule.register == "*":
            score += 0.10
            register_match = True

        if not register_match:
            continue  # registros diferentes — nao pode abranger

        # 2. Campos em comum
        if ex_fields and new_fields:
            common_fields = new_fields & ex_fields
            if common_fields:
                field_ratio = len(common_fields) / len(new_fields)
                score += 0.25 * field_ratio
                if field_ratio >= 1.0:
                    reasons.append(f"todos os campos cobertos ({', '.join(sorted(common_fields))})")
                else:
                    reasons.append(f"campos em comum: {', '.join(sorted(common_fields))}")

        # 3. Error type — mesmo ou mesmo dominio
        if ex_error_type == rule.error_type:
            score += 0.30
            reasons.append(f"mesmo tipo de erro ({ex_error_type})")
        elif ex_error_type and new_error_prefix:
            ex_prefix = ex_error_type.split("_")[0]
            if ex_prefix == new_error_prefix:
                score += 0.15
                reasons.append(f"mesmo dominio de erro ({ex_prefix}_*)")

        # 4. Similaridade de descricao + condicao
        ex_all_words = normalize_words(ex_desc) | normalize_words(ex_cond)
        if new_all_words and ex_all_words:
            overlap = len(new_all_words & ex_all_words)
            max_size = max(len(new_all_words), len(ex_all_words))
            if max_size > 0:
                semantic_score = overlap / max_size
                if semantic_score >= 0.3:
                    score += 0.15 * min(semantic_score / 0.5, 1.0)
                    common_concepts = sorted(new_all_words & ex_all_words)[:5]
                    reasons.append(f"conceitos em comum: {', '.join(common_concepts)}")

        # Threshold: score >= 0.45 indica abrangencia provavel
        if score >= 0.45 and reasons:
            objections.append(RuleCoverageMatch(
                rule_id=entry.get("id", "?"),
                description=ex_desc,
                register=ex_register,
                fields=list(ex_fields),
                error_type=ex_error_type,
                severity=entry.get("severity", "warning"),
                match_reason=" | ".join(reasons),
                match_score=round(min(score, 1.0), 2),
            ))

    # Ordenar por score decrescente, top 5
    objections.sort(key=lambda o: o.match_score, reverse=True)
    return objections[:5]


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


def _get_known_error_types() -> set[str]:
    """Importa error_types conhecidos do src/rules.py."""
    try:
        from src.rules import _KNOWN_ERROR_TYPES
        return _KNOWN_ERROR_TYPES
    except ImportError:
        return set()


def _find_similar_error_type(error_type: str, known: set[str]) -> str | None:
    """Encontra error_type existente mais similar ao gerado.

    Compara tokens do error_type gerado contra os existentes.
    Retorna o melhor match se tiver >= 50% de overlap.
    """
    if not known:
        return None
    gen_tokens = set(error_type.split("_"))
    best_match = None
    best_score = 0.0
    for existing in known:
        ex_tokens = set(existing.split("_"))
        if not ex_tokens:
            continue
        overlap = len(gen_tokens & ex_tokens)
        score = overlap / max(len(gen_tokens), len(ex_tokens))
        if score > best_score:
            best_score = score
            best_match = existing
    return best_match if best_score >= 0.5 else None


# ── Mapa bloco → modulo padrao ──

_BLOCK_MODULE_MAP: dict[str, str] = {
    "formato": "format_validator.py",
    "campo_a_campo": "validator.py",
    "intra_registro": "intra_register_validator.py",
    "cruzamento": "cross_block_validator.py",
    "recalculo": "tax_recalc.py",
    "cst_isencoes": "cst_validator.py",
    "cst_expandido": "cst_validator.py",
    "semantica_aliquota_zero": "fiscal_semantics.py",
    "semantica_cst_cfop": "fiscal_semantics.py",
    "monofasicos": "fiscal_semantics.py",
    "pendentes": "pendentes_validator.py",
    "auditoria_beneficios": "beneficio_audit_validator.py",
    "beneficio_fiscal": "beneficio_validator.py",
    "aliquotas": "aliquota_validator.py",
    "c190_consolidacao": "c190_validator.py",
    "difal": "difal_validator.py",
    "base_calculo": "base_calculo_validator.py",
    "devolucoes": "devolucao_validator.py",
    "parametrizacao": "parametrizacao_validator.py",
    "ncm": "ncm_validator.py",
    "governanca": "audit_rules.py",
    "simples_nacional": "simples_validator.py",
    "bloco_k": "bloco_k_validator.py",
    "bloco_d": "bloco_d_validator.py",
    "bloco_c_servicos": "bloco_c_servicos_validator.py",
    "ipi": "ipi_validator.py",
    "st": "st_validator.py",
    "destinatario": "destinatario_validator.py",
}


def _parse_rule_description(description: str, legal_sources: list[dict]) -> GeneratedRule:
    """Analisa descricao livre e gera regra estruturada."""
    desc_lower = description.lower()

    register = _detect_register(desc_lower, legal_sources)
    fields = _detect_fields(desc_lower, legal_sources)
    block = _detect_block(desc_lower, fields)
    severity = _detect_severity(desc_lower)
    rule_id = _generate_id(description, block)
    error_type = _generate_error_type(description, block, fields)
    condition = _generate_condition(description, register, fields)
    legislation = _extract_legislation(legal_sources, description)
    module = _BLOCK_MODULE_MAP.get(block, "fiscal_semantics.py")
    corrigivel, corrigivel_nota = _infer_corrigivel(desc_lower, fields, severity)
    certeza = _infer_certeza(desc_lower, condition)
    impacto = _infer_impacto(desc_lower, severity)

    # Validar error_type contra tipos conhecidos
    known = _get_known_error_types()
    error_type_exists = error_type in known
    error_type_suggestion = None
    if not error_type_exists:
        error_type_suggestion = _find_similar_error_type(error_type, known)

    return GeneratedRule(
        id=rule_id,
        block=block,
        register=register,
        fields=fields,
        error_type=error_type,
        severity=severity,
        description=description,
        condition=condition,
        module=module,
        legislation=legislation,
        legal_sources=legal_sources[:3] if legal_sources else None,
        corrigivel=corrigivel,
        corrigivel_nota=corrigivel_nota,
        certeza=certeza,
        impacto=impacto,
        vigencia_de=date.today().isoformat(),
        version="1.0",
        last_updated=date.today().isoformat(),
        error_type_exists=error_type_exists,
        error_type_suggestion=error_type_suggestion,
    )


def _detect_register(text: str, sources: list[dict] | None = None) -> str:
    """Detecta registro SPED mencionado no texto ou nas fontes legais."""
    # 1. Busca direta no texto (todos os registros conhecidos)
    reg_match = re.search(
        r'\b([0-9A-Z](?:0{3}|[0-9]{3})|[BCDEGGHK]\d{3})\b',
        text, re.IGNORECASE,
    )
    if reg_match:
        candidate = reg_match.group(1).upper()
        # Validar que parece registro SPED (nao numero qualquer)
        if re.match(r'^(0[0-9]{3}|[BCDEGGHK][0-9]{3})$', candidate):
            return candidate

    # 2. Busca explicita de registros comuns
    explicit = re.search(
        r'\b(C100|C170|C190|C200|C300|C400|C500|C800|C850|'
        r'D100|D150|D190|D500|D600|D610|D690|'
        r'E100|E110|E112|E200|E210|E500|E510|E530|'
        r'H001|H005|H010|H020|'
        r'K001|K200|K210|K215|K220|K230|K235|K250|'
        r'0000|0001|0100|0150|0190|0200|0220|0300|0400|'
        r'B001|B030|B350|B440|B460|B470|B500|B510|'
        r'G001|G110|G126|G130|G140)\b',
        text, re.IGNORECASE,
    )
    if explicit:
        return explicit.group(1).upper()

    # 3. Usar registro das fontes legais (se disponivel)
    if sources:
        for src in sources:
            reg = src.get("register")
            if reg and re.match(r'^[A-Z0-9]\d{3}$', reg):
                return reg

    # 4. Inferir pelo contexto semantico
    context_map = [
        (["item", "produto", "ncm", "cst_pis", "cst_cofins", "monofas",
          "mercadoria", "unidade", "quantidade", "aliquota pis", "aliquota cofins"], "C170"),
        (["nota", "documento", "nf-e", "nfe", "chave", "emitente", "emissao",
          "cancelada", "cancelado", "cod_sit"], "C100"),
        (["totaliza", "consolida", "soma c170", "rateio"], "C190"),
        (["apuracao", "apuração", "debito", "credito", "saldo",
          "recolher", "credor", "deducao", "estorno"], "E110"),
        (["estoque", "inventario", "inventário", "h010"], "H010"),
        (["difal", "fcp", "fundo combate", "consumo final",
          "consumidor final", "diferencial aliquota"], "E200"),
        (["transporte", "frete", "conhecimento", "ct-e", "cte"], "D100"),
        (["producao", "produção", "insumo", "ordem producao",
          "componente", "bloco k"], "K200"),
        (["beneficio", "ajuste", "e111", "e112", "e113"], "E110"),
        (["simples nacional", "csosn", "simples", "lc 123"], "C170"),
        (["cadastro", "participante", "fornecedor", "cliente"], "0150"),
        (["item cadastro", "cod_item", "descricao item"], "0200"),
        (["substituicao", "substituição", "st ", "icms-st", "icms st"], "C170"),
        (["ipi", "ipi reflexo", "aliq_ipi"], "C170"),
        (["devolucao", "devolução", "espelhamento"], "C100"),
    ]
    for keywords, reg in context_map:
        if any(w in text for w in keywords):
            return reg

    return "C170"


# Mapa completo de campos SPED com padroes de deteccao
_FIELD_PATTERNS: dict[str, str] = {
    # ICMS
    "CST_ICMS": r'cst[_ ]?icms|cst[_ ]?(?:00|10|20|30|40|41|50|51|60|70|90)\b|cst[_ ]?tributad|tabela[_ ]?[ab]',
    "CFOP": r'\bcfop\b|codigo[_ ]?fiscal|operacao[_ ]?fiscal',
    "ALIQ_ICMS": r'al[ií]q(?:uota)?[_ ]?icms|al[ií]quota[_ ]?interna|al[ií]quota[_ ]?interestadual',
    "VL_ICMS": r'\bvl?[_ ]?icms\b|valor[_ ]?(?:do[_ ]?)?icms(?![_-]st)',
    "VL_BC_ICMS": r'base[_ ]?(?:de[_ ]?)?c[aá]lc(?:ulo)?[_ ]?icms|bc[_ ]?icms|vl_bc_icms',
    # ICMS-ST
    "VL_BC_ICMS_ST": r'bc[_ ]?(?:icms[_ ]?)?st|base[_ ]?st|vl_bc_icms_st',
    "ALIQ_ST": r'al[ií]q(?:uota)?[_ ]?st',
    "VL_ICMS_ST": r'vl?[_ ]?icms[_ ]?st|valor[_ ]?(?:do[_ ]?)?icms[_ ]?st',
    # PIS
    "CST_PIS": r'cst[_ ]?pis',
    "ALIQ_PIS": r'al[ií]q(?:uota)?[_ ]?pis',
    "VL_PIS": r'\bvl?[_ ]?pis\b|valor[_ ]?(?:do[_ ]?)?pis(?![_/])',
    "VL_BC_PIS": r'bc[_ ]?pis|base[_ ]?(?:de[_ ]?)?c[aá]lc(?:ulo)?[_ ]?pis|vl_bc_pis',
    # COFINS
    "CST_COFINS": r'cst[_ ]?cofins',
    "ALIQ_COFINS": r'al[ií]q(?:uota)?[_ ]?cofins',
    "VL_COFINS": r'\bvl?[_ ]?cofins\b|valor[_ ]?(?:do[_ ]?)?cofins',
    "VL_BC_COFINS": r'bc[_ ]?cofins|base[_ ]?(?:de[_ ]?)?c[aá]lc(?:ulo)?[_ ]?cofins|vl_bc_cofins',
    # IPI
    "CST_IPI": r'cst[_ ]?ipi',
    "ALIQ_IPI": r'al[ií]q(?:uota)?[_ ]?ipi',
    "VL_IPI": r'\bvl?[_ ]?ipi\b|valor[_ ]?(?:do[_ ]?)?ipi',
    "VL_BC_IPI": r'bc[_ ]?ipi|base[_ ]?(?:de[_ ]?)?c[aá]lc(?:ulo)?[_ ]?ipi|vl_bc_ipi',
    # Valores
    "VL_DOC": r'vl?[_ ]?doc|valor[_ ]?(?:do[_ ]?)?documento',
    "VL_ITEM": r'vl?[_ ]?item|valor[_ ]?(?:do[_ ]?)?item',
    "VL_DESC": r'vl?[_ ]?desc|valor[_ ]?desconto|desconto',
    "VL_OPR": r'vl?[_ ]?opr|valor[_ ]?opera[cç][aã]o',
    "VL_FRETE": r'vl?[_ ]?frete|valor[_ ]?(?:do[_ ]?)?frete|frete[_ ]?cif|frete[_ ]?fob',
    # Campos de referencia
    "NCM": r'\bncm\b|nomenclatura|classifica[cç][aã]o[_ ]?fiscal',
    "COD_ITEM": r'cod[_ ]?item|c[oó]digo[_ ]?(?:do[_ ]?)?item',
    "COD_PART": r'cod[_ ]?part|c[oó]digo[_ ]?(?:do[_ ]?)?participante|participante',
    "IND_OPER": r'ind[_ ]?oper|indicador[_ ]?(?:de[_ ]?)?opera[cç][aã]o|entrada[_ ]?sa[ií]da',
    "IND_EMIT": r'ind[_ ]?emit|indicador[_ ]?(?:de[_ ]?)?emitente|emiss[aã]o[_ ]?pr[oó]pria',
    "COD_SIT": r'cod[_ ]?sit|situa[cç][aã]o[_ ]?(?:do[_ ]?)?documento|cancelad[ao]',
    "CHV_NFE": r'chv[_ ]?nfe|chave[_ ]?(?:de[_ ]?)?acesso|chave[_ ]?nf-?e',
    "DT_DOC": r'dt[_ ]?doc|data[_ ]?(?:do[_ ]?)?documento',
    "DT_E_S": r'dt[_ ]?e[_ ]?s|data[_ ]?(?:de[_ ]?)?entrada|data[_ ]?(?:de[_ ]?)?sa[ií]da',
    # DIFAL/FCP
    "VL_ICMS_UF_DEST": r'icms[_ ]?uf[_ ]?dest|difal|diferencial[_ ]?al[ií]quota',
    "VL_FCP_UF_DEST": r'fcp|fundo[_ ]?combate[_ ]?pobreza',
    # Simples Nacional
    "CSOSN": r'\bcsosn\b|c[oó]digo[_ ]?situa[cç][aã]o[_ ]?opera[cç][aã]o[_ ]?simples',
    "IND_PERFIL": r'ind[_ ]?perfil|perfil[_ ]?(?:de[_ ]?)?apresenta[cç][aã]o',
    # Bloco K
    "QTD": r'\bqtd\b|quantidade',
    "COD_CCUS": r'cod[_ ]?ccus|centro[_ ]?(?:de[_ ]?)?custo',
    # Ajustes
    "COD_AJ": r'cod[_ ]?aj|c[oó]digo[_ ]?(?:de[_ ]?)?ajuste',
    "VL_AJ": r'vl[_ ]?aj|valor[_ ]?(?:do[_ ]?)?ajuste',
    # Inventario
    "VL_UNIT": r'vl?[_ ]?unit|valor[_ ]?unit[aá]rio',
    "UNID": r'\bunid\b|unidade[_ ]?(?:de[_ ]?)?medida',
    "UNID_INV": r'unid[_ ]?inv|unidade[_ ]?(?:de[_ ]?)?invent[aá]rio',
    # Apuracao
    "VL_TOT_DEBITOS": r'total[_ ]?d[eé]bitos|vl_tot_debitos',
    "VL_TOT_CREDITOS": r'total[_ ]?cr[eé]ditos|vl_tot_creditos',
    "VL_SLD_APURADO": r'saldo[_ ]?apurado|vl_sld_apurado',
    "VL_ICMS_RECOLHER": r'icms[_ ]?(?:a[_ ]?)?recolher|vl_icms_recolher',
}


def _detect_fields(text: str, sources: list[dict] | None = None) -> list[str]:
    """Detecta campos SPED mencionados no texto e nas fontes legais."""
    found: list[str] = []
    for field, pattern in _FIELD_PATTERNS.items():
        if re.search(pattern, text, re.IGNORECASE):
            found.append(field)

    # Enriquecer com campos das fontes legais (se campo aparece no heading)
    if sources and not found:
        for src in sources:
            heading = (src.get("heading") or "").upper()
            for field in _FIELD_PATTERNS:
                if field in heading and field not in found:
                    found.append(field)
            if len(found) >= 3:
                break

    return found if found else ["CST_ICMS"]


def _detect_block(text: str, fields: list[str]) -> str:
    """Detecta bloco/categoria da regra usando texto + campos detectados."""
    # Ordem importa: mais especifico primeiro
    block_rules: list[tuple[list[str], str]] = [
        (["monofas", "monofásic", "cst 04", "cst 06"], "monofasicos"),
        (["bloco k", "producao", "produção", "ordem producao", "k200", "k230", "k235"], "bloco_k"),
        (["bloco d", "transporte", "ct-e", "cte", "d100", "d150"], "bloco_d"),
        (["bloco c servico", "servico no bloco c", "issqn no bloco c"], "bloco_c_servicos"),
        (["simples nacional", "csosn", "simples", "lc 123", "lc 155",
          "ind_perfil", "anexo simples"], "simples_nacional"),
        (["difal", "diferencial aliquota", "diferencial de alíquota",
          "fcp", "fundo combate", "consumo final", "uf destino"], "difal"),
        (["substituicao", "substituição", "icms-st", "icms st",
          "mva", "pauta fiscal", "st sem reflexo"], "st"),
        (["devolucao", "devolução", "espelhamento", "nota devolvida"], "devolucoes"),
        (["beneficio", "incentivo", "ajuste e111", "ajuste e112",
          "beneficio fiscal", "credito presumido", "reducao base"], "beneficio_fiscal"),
        (["auditoria beneficio", "lastro documental", "sobreposicao beneficio",
          "desproporcional", "governanca beneficio", "trilha beneficio"], "auditoria_beneficios"),
        (["aliquota interestadual", "alíquota interestadual", "aliquota interna",
          "alíquota interna", "aliquota media", "alíquota média",
          "aliquota divergente", "alíquota divergente"], "aliquotas"),
        (["c190 vs c170", "c190 consolida", "c190 diverge", "rateio despesa",
          "combinacao incompativel"], "c190_consolidacao"),
        (["base calculo", "base cálculo", "base inflada", "frete cif",
          "frete fob", "despesa acessoria", "recalculo bc"], "base_calculo"),
        (["ncm tributacao", "ncm generico", "ncm incompativel"], "ncm"),
        (["ipi reflexo", "ipi cst", "ipi recalculo"], "ipi"),
        (["destinatario", "ie inconsistente", "uf vs ie", "uf vs cep"], "destinatario"),
        (["parametrizacao", "parametrização", "erro sistematico",
          "sistêmico", "erro recorrente"], "parametrizacao"),
        (["cfop vs cst", "cst x cfop", "cfop incompativel",
          "venda isento", "exportacao tributado"], "semantica_cst_cfop"),
        (["aliquota zero", "alíquota zero", "zerado", "tudo zero",
          "aliq zero", "alíq zero"], "semantica_aliquota_zero"),
        (["isencao", "isenção", "isento", "tributado sem icms",
          "cst isento", "cst tributado"], "cst_isencoes"),
        (["cst 020", "cst reducao", "cst diferimento", "ipi cst campo"], "cst_expandido"),
        (["recalc", "calculo diverge", "cálculo diverge", "bc x aliq",
          "base x aliquota", "soma diverge"], "recalculo"),
        (["cruzamento", "0150 vs", "0200 vs", "bloco 9",
          "e110 vs c190", "referencia inexistente"], "cruzamento"),
        (["governanca", "classificacao erro", "grau confianca",
          "checklist", "amostragem"], "governanca"),
        (["formato", "cnpj invalido", "cpf invalido", "data invalida",
          "cep invalido", "chave nfe"], "formato"),
        (["campo obrigatorio", "tamanho", "tipo numerico", "valor invalido"], "campo_a_campo"),
        (["intra registro", "c100 dt", "c170 cfop", "c190 soma",
          "e110 formula"], "intra_registro"),
        (["pendente contexto", "beneficio nao vinculado",
          "desoneracao sem motivo"], "pendentes"),
    ]
    for keywords, block in block_rules:
        if any(w in text for w in keywords):
            return block

    # Inferir pelo campo detectado
    field_block_map = {
        "CST_PIS": "monofasicos",
        "CST_COFINS": "monofasicos",
        "CSOSN": "simples_nacional",
        "VL_ICMS_UF_DEST": "difal",
        "VL_FCP_UF_DEST": "difal",
        "VL_BC_ICMS_ST": "st",
        "COD_AJ": "auditoria_beneficios",
        "IND_PERFIL": "simples_nacional",
    }
    for field in fields:
        if field in field_block_map:
            return field_block_map[field]

    return "semantica_cst_cfop"


def _detect_severity(text: str) -> str:
    """Detecta severidade sugerida a partir de palavras-chave."""
    # critical: divergencias de calculo, cruzamentos quebrados
    critical_kw = [
        "critico", "crítico", "divergen", "soma nao bate",
        "soma não bate", "calculo errado", "cálculo errado",
        "cruzamento falh", "inconsistencia grave", "inconsistência grave",
    ]
    # error: proibicoes, invalidos, incorretos
    error_kw = [
        "erro", "invalido", "inválido", "incorreto", "proibid",
        "nao pode", "não pode", "vedado", "ilegal", "obrigatorio faltando",
        "obrigatório faltando",
    ]
    # info: observacoes, alertas leves
    info_kw = [
        "informati", "atenção", "atencao", "observ", "sugestao",
        "sugestão", "pode indicar", "verificar", "atentar",
    ]

    if any(w in text for w in critical_kw):
        return "critical"
    if any(w in text for w in error_kw):
        return "error"
    if any(w in text for w in info_kw):
        return "info"
    return "warning"


_STOPWORDS = frozenset({
    "o", "a", "os", "as", "de", "do", "da", "dos", "das", "em", "no",
    "na", "nos", "nas", "um", "uma", "com", "por", "para", "que", "se",
    "nao", "não", "ou", "e", "ao", "quando", "deve", "ser", "esta",
    "este", "esse", "essa", "ter", "the", "and", "is", "of", "to",
    "in", "it", "if", "pode", "campo", "valor", "registro",
})


def _significant_words(text: str, max_words: int = 4) -> list[str]:
    """Extrai palavras significativas (sem stopwords, > 2 chars)."""
    words = re.sub(r'[^a-zA-Z0-9\s]', '', text.lower()).split()
    return [w.upper() for w in words if w not in _STOPWORDS and len(w) > 2][:max_words]


def _generate_id(description: str, block: str) -> str:
    """Gera ID unico baseado no bloco + palavras-chave."""
    # Prefixo do bloco
    block_prefixes: dict[str, str] = {
        "formato": "FMT",
        "campo_a_campo": "CAMPO",
        "intra_registro": "INTRA",
        "cruzamento": "CROSS",
        "recalculo": "RECALC",
        "cst_isencoes": "CST",
        "cst_expandido": "CST_EXP",
        "semantica_aliquota_zero": "ALIQ_ZERO",
        "semantica_cst_cfop": "CST_CFOP",
        "monofasicos": "MONO",
        "pendentes": "PEND",
        "auditoria_beneficios": "AUD_BEN",
        "beneficio_fiscal": "BEN",
        "aliquotas": "ALIQ",
        "c190_consolidacao": "C190",
        "difal": "DIFAL",
        "base_calculo": "BC",
        "devolucoes": "DEVOL",
        "parametrizacao": "PARAM",
        "ncm": "NCM",
        "governanca": "GOV",
        "simples_nacional": "SN",
        "bloco_k": "BK",
        "bloco_d": "BD",
        "bloco_c_servicos": "BCS",
        "ipi": "IPI",
        "st": "ST",
        "destinatario": "DEST",
    }
    prefix = block_prefixes.get(block, "RULE")
    significant = _significant_words(description, 3)
    suffix = "_".join(significant) if significant else "NOVA"
    return f"{prefix}_{suffix}"


def _generate_error_type(description: str, block: str, fields: list[str]) -> str:
    """Gera error_type tentando reaproveitar tipo existente ou criar coerente."""
    desc_lower = description.lower()
    known = _get_known_error_types()

    # 1. Mapeamento direto por dominio semantico
    domain_map: list[tuple[list[str], str]] = [
        (["monofasico ncm", "ncm monofasico"], "MONOFASICO_NCM_INCOMPATIVEL"),
        (["monofasico cst", "cst monofasico", "cst 04"], "MONOFASICO_CST_INCORRETO"),
        (["monofasico aliquota", "monofasico aliq"], "MONOFASICO_ALIQ_INVALIDA"),
        (["monofasico valor"], "MONOFASICO_VALOR_INDEVIDO"),
        (["monofasico entrada"], "MONOFASICO_ENTRADA_CST04"),
        (["cfop incompativel", "cfop cst"], "CST_CFOP_INCOMPATIVEL"),
        (["aliquota zero forte", "aliq zero bc"], "CST_ALIQ_ZERO_FORTE"),
        (["aliquota zero moderado", "tudo zerado"], "CST_ALIQ_ZERO_MODERADO"),
        (["isencao inconsistente", "isento com valor"], "ISENCAO_INCONSISTENTE"),
        (["tributacao inconsistente", "tributado sem"], "TRIBUTACAO_INCONSISTENTE"),
        (["difal faltante", "difal ausente"], "DIFAL_FALTANTE_CONSUMO_FINAL"),
        (["difal indevido"], "DIFAL_INDEVIDO_REVENDA"),
        (["difal uf"], "DIFAL_UF_DESTINO_INCONSISTENTE"),
        (["fcp ausente", "fcp faltante"], "DIFAL_FCP_AUSENTE"),
        (["c190 diverge", "c190 vs c170"], "C190_DIVERGE_C170"),
        (["c190 combinacao", "combinacao incompativel"], "C190_COMBINACAO_INCOMPATIVEL"),
        (["cst 020", "cst reducao"], "CST_020_SEM_REDUCAO"),
        (["ipi cst"], "IPI_CST_INCOMPATIVEL"),
        (["soma diverge", "soma nao bate"], "SOMA_DIVERGENTE"),
        (["calculo diverge", "calculo errado"], "CALCULO_DIVERGENTE"),
        (["referencia inexistente", "cod nao existe"], "REF_INEXISTENTE"),
        (["aliquota interestadual invalida"], "ALIQ_INTERESTADUAL_INVALIDA"),
        (["aliquota interna em interestadual"], "ALIQ_INTERNA_EM_INTERESTADUAL"),
        (["aliquota media"], "ALIQ_MEDIA_INDEVIDA"),
        (["beneficio debito"], "BENEFICIO_DEBITO_NAO_INTEGRAL"),
        (["ajuste sem lastro"], "AJUSTE_SEM_LASTRO_DOCUMENTAL"),
        (["devolucao inconsistente", "devolução inconsistente"], "DEVOLUCAO_INCONSISTENTE"),
        (["parametrizacao", "erro sistematico"], "PARAMETRIZACAO_SISTEMICA_INCORRETA"),
        (["base inflada"], "BASE_BENEFICIO_INFLADA"),
        (["csosn", "simples nacional cst"], "CST_INVALIDO"),
        (["ncm generico"], "NCM_GENERICO"),
        (["ncm tributacao"], "NCM_TRIBUTACAO_INCOMPATIVEL"),
        (["formato invalido", "formato errado"], "FORMATO_INVALIDO"),
        (["cnpj invalido", "cpf invalido"], "FORMATO_INVALIDO"),
        (["data invalida", "data fora"], "INVALID_DATE"),
    ]
    for keywords, etype in domain_map:
        if any(kw in desc_lower for kw in keywords):
            return etype

    # 2. Construir error_type a partir do bloco + campos
    block_prefix_map: dict[str, str] = {
        "monofasicos": "MONOFASICO",
        "difal": "DIFAL",
        "aliquotas": "ALIQ",
        "c190_consolidacao": "C190",
        "base_calculo": "BC",
        "beneficio_fiscal": "BENEFICIO",
        "auditoria_beneficios": "BENEFICIO",
        "devolucoes": "DEVOLUCAO",
        "parametrizacao": "PARAMETRIZACAO",
        "simples_nacional": "SN",
        "bloco_k": "BLOCO_K",
        "bloco_d": "BLOCO_D",
        "st": "ST",
        "ipi": "IPI",
        "ncm": "NCM",
        "governanca": "GOV",
        "formato": "FORMATO",
        "semantica_cst_cfop": "CST_CFOP",
        "semantica_aliquota_zero": "ALIQ_ZERO",
        "cst_isencoes": "CST",
        "cst_expandido": "CST",
        "cruzamento": "CRUZAMENTO",
        "recalculo": "CALCULO",
        "intra_registro": "INTRA",
        "campo_a_campo": "CAMPO",
    }
    prefix = block_prefix_map.get(block, "REGRA")
    suffix_words = _significant_words(description, 2)
    candidate = f"{prefix}_{'_'.join(suffix_words)}" if suffix_words else f"{prefix}_CUSTOM"

    # 3. Se o candidato existe nos conhecidos, usar direto
    if candidate in known:
        return candidate

    # 4. Tentar match similar
    similar = _find_similar_error_type(candidate, known)
    if similar:
        return similar

    return candidate


def _generate_condition(description: str, register: str, fields: list[str]) -> str:
    """Gera condicao logica estruturada a partir da descricao."""
    desc_lower = description.lower()
    conditions: list[str] = []

    # Extrair operadores logicos e valores do texto
    # "CST PIS for/igual 01" → CST_PIS == "01"
    for field in fields:
        field_lower = field.lower().replace("_", "[_ ]?")
        val_match = re.search(
            rf'{field_lower}\s+(?:for|igual|=|==|seja|ser)\s+["\']?(\w+)["\']?',
            desc_lower,
        )
        if val_match:
            conditions.append(f'{field} == "{val_match.group(1).upper()}"')

    # "NCM comecar com / prefixo 3004" → NCM.startswith("3004")
    ncm_prefix = re.search(r'ncm\s+(?:come[cç]ar?\s+com|prefixo|inici[ae]\s+com)\s+(\d+)', desc_lower)
    if ncm_prefix:
        conditions.append(f'NCM.startswith("{ncm_prefix.group(1)}")')

    # "NCM farmaceutico / NCM medicamento" → NCM.startswith("3001"-"3006")
    ncm_categories = {
        "farmaceutic": 'NCM.startswith("3001"-"3006")',
        "medicament": 'NCM.startswith("3001"-"3006")',
        "combustivel": 'NCM.startswith("2710", "2711")',
        "lubrificante": 'NCM.startswith("2710", "3403")',
        "bebida": 'NCM.startswith("2106", "2201", "2202")',
        "higiene": 'NCM.startswith("3303"-"3307")',
        "perfumaria": 'NCM.startswith("3303"-"3307")',
        "veiculo": 'NCM.startswith("8701"-"8706")',
        "autopeca": 'NCM.startswith("4011", "8407"-"8708")',
    }
    for keyword, ncm_cond in ncm_categories.items():
        if keyword in desc_lower and ncm_cond not in conditions:
            conditions.append(ncm_cond)

    # "aliquota > 0" / "valor > 0" / "valor = 0"
    comp_match = re.findall(
        r'(al[ií]quota|valor|base|bc|icms|pis|cofins|ipi)\s*(>|<|>=|<=|=|==|!=|diferente)\s*(\d+(?:[.,]\d+)?)',
        desc_lower,
    )
    for name, op, val in comp_match:
        field_guess = {
            "aliquota": "ALIQ_ICMS", "base": "VL_BC_ICMS", "bc": "VL_BC_ICMS",
            "icms": "VL_ICMS", "pis": "VL_PIS", "cofins": "VL_COFINS", "ipi": "VL_IPI",
        }.get(name, name.upper())
        op_norm = "==" if op in ("=", "==") else ("!=" if op == "diferente" else op)
        if field_guess not in [c.split()[0] for c in conditions]:
            conditions.append(f'{field_guess} {op_norm} {val}')

    # "alertar / erro / warning" → extrair acao
    action_match = re.search(r'(?:alertar|avisar|erro|bloquear|informar|reportar)\s+(?:que\s+)?(.{10,60})', desc_lower)
    action_text = action_match.group(1).rstrip(".,:;") if action_match else None

    if conditions:
        result = " AND ".join(conditions)
        if action_text:
            result += f" => {action_text}"
        return result

    # Fallback: reformular descricao como pseudo-condicao
    # Remover "quando", "se", "caso" do inicio e formatar
    cleaned = re.sub(r'^(?:quando|se|caso|verificar se|checar se)\s+', '', desc_lower)
    cleaned = cleaned.rstrip(".,:;")
    # Capitalizar campos SPED encontrados
    for field in fields:
        cleaned = re.sub(rf'\b{field.lower()}\b', field, cleaned, flags=re.IGNORECASE)
    return cleaned if len(cleaned) > 10 else f"Verificar {register}: {', '.join(fields)}"


def _extract_legislation(sources: list[dict], description: str = "") -> str | None:
    """Extrai referencias legislativas das fontes e da descricao."""
    legislations: set[str] = set()

    # Buscar em todas as fontes textuais
    texts_to_search = [description]
    for s in sources:
        texts_to_search.append(s.get("fonte", ""))
        texts_to_search.append(s.get("heading", ""))
        texts_to_search.append(s.get("content", "")[:500])

    combined = " ".join(texts_to_search).lower()

    lei_patterns = [
        r'lei\s+(?:complementar\s+)?(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
        r'decreto\s+(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
        r'conv[eê]nio\s+icms\s+[\d.]+(?:/\d+)?',
        r'ajuste\s+sinief\s+[\d.]+(?:/\d+)?',
        r'ato\s+cotepe\s+[\d.]+(?:/\d+)?',
        r'resolu[cç][aã]o\s+(?:senado\s+)?(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
        r'portaria\s+(?:n[.°º]?\s*)?[\d.]+(?:-r)?(?:/\d+)?',
        r'in\s+rfb\s+(?:n[.°º]?\s*)?[\d.]+(?:/\d+)?',
        r'guia\s+pr[aá]tico\s+efd(?:\s+v[\d.]+)?',
        r'nota\s+t[eé]cnica\s+[\d.]+(?:/\d+)?',
    ]
    for p in lei_patterns:
        matches = re.findall(p, combined, re.IGNORECASE)
        legislations.update(m.strip().title() for m in matches)

    if legislations:
        return "; ".join(sorted(legislations)[:5])
    return None


def _infer_corrigivel(text: str, fields: list[str], severity: str) -> tuple[str, str | None]:
    """Infere nivel de corrigibilidade e nota explicativa.

    Retorna (corrigivel, corrigivel_nota).
    """
    # Campos sensiveis: nunca correcao automatica
    sensitive_fields = {"CNPJ", "CPF", "COD_PART", "CHV_NFE", "VL_DOC", "VL_ITEM"}
    if any(f in sensitive_fields for f in fields):
        return (
            "investigar",
            "Campos identificadores/valores nao podem ser corrigidos automaticamente — "
            "consulte o documento fiscal original.",
        )

    # Formato simples (data, cep) → automatico
    format_kw = ["formato", "digito", "tamanho", "mascara"]
    if any(w in text for w in format_kw) and severity != "critical":
        return ("automatico", None)

    # CST/CFOP com regra clara → proposta
    code_fields = {"CST_ICMS", "CST_PIS", "CST_COFINS", "CST_IPI", "CSOSN", "CFOP"}
    if any(f in code_fields for f in fields):
        return (
            "proposta",
            "O sistema sugere correcao com base na regra, mas requer revisao do usuario.",
        )

    # Calculos → proposta (recalculavel)
    calc_kw = ["recalc", "calculo", "cálculo", "diverge", "soma"]
    if any(w in text for w in calc_kw):
        return ("proposta", "Valor pode ser recalculado, mas requer confirmacao.")

    # Critical → investigar sempre
    if severity == "critical":
        return ("investigar", "Severidade critica requer analise humana.")

    return ("investigar", None)


def _infer_certeza(text: str, condition: str) -> str:
    """Infere grau de certeza da regra.

    objetivo = regra deterministica (formato, calculo exato)
    subjetivo = requer interpretacao (semantica, contexto fiscal)
    """
    objective_kw = [
        "formato", "digito", "tamanho", "calculo", "cálculo",
        "soma", "igual", "== ", "!= ", "> 0", "< 0", "modulo 11",
        "recalc", "contagem", "deve ser zero", "obrigatorio",
    ]
    if any(w in text.lower() for w in objective_kw) or "==" in condition:
        return "objetivo"
    return "subjetivo"


def _infer_impacto(text: str, severity: str) -> str:
    """Infere impacto da regra.

    relevante = afeta calculo/obrigacao fiscal
    informativo = alerta/boas praticas
    """
    if severity in ("critical", "error"):
        return "relevante"
    info_kw = ["observ", "boa pratica", "sugest", "verificar", "atentar"]
    if any(w in text for w in info_kw):
        return "informativo"
    return "relevante"
