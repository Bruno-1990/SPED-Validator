"""Modelos de dados do Motor de Cruzamento NF-e XML x SPED EFD.

Define enums, dataclasses e constantes usados pelo cross_engine.py,
document_scope_builder.py e regras XC001-XC095.

Especificacao: motor_cruzamento_v_final.txt
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ───────────────────��──────────────────────────────────────────────────
# 1.6 — Estados de execucao de regra (rule_outcome)
# ──────────────────────────────────────────────────────────────────────

class RuleOutcome(str, Enum):
    EXECUTED_ERROR = "EXECUTED_ERROR"
    EXECUTED_OK = "EXECUTED_OK"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    NOT_EXECUTED_MISSING_DATA = "NOT_EXECUTED_MISSING_DATA"
    SUPPRESSED_BY_ROOT_CAUSE = "SUPPRESSED_BY_ROOT_CAUSE"
    NEUTRALIZED_BY_BENEFIT = "NEUTRALIZED_BY_BENEFIT"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"


# ──────────────────────────────────────────────────────────────────────
# 1.7 — Estados de pareamento de itens
# ──────────────────────────────────────────────────────────────────────

class ItemMatchState(str, Enum):
    MATCH_EXATO = "MATCH_EXATO"
    MATCH_PROVAVEL = "MATCH_PROVAVEL"
    MATCH_HEURISTICO = "MATCH_HEURISTICO"
    AMBIGUO = "AMBIGUO"
    SEM_MATCH = "SEM_MATCH"


# ──────────────────────────────────────────────────────────────────────
# 1.5 — Elegibilidade por tipo de item (item_nature)
# ────────────────────────────────────────��─────────────────────────────

class ItemNature(str, Enum):
    REVENDA = "revenda"
    USO_CONSUMO = "uso_consumo"
    ATIVO = "ativo"
    SERVICO = "servico"
    BONIFICACAO = "bonificacao"
    OUTRO = "outro"


# ──────────────────────────────────────────────────────────────────────
# 1.3 — Modelos elegiveis para cruzamento XML
# ──────────────────────────────────────────────────────────────────────

XML_ELIGIBLE_MODELS = {"55", "65"}

# ──────────────────────────────────────────────────────────────────────
# 1.8 — Grupos sem campo de calculo ICMS
# ──────────────────────────────────────────────────────────────────────

GRUPOS_SEM_BC_ICMS = {
    "ICMS40", "ICMS41", "ICMS50", "ICMSST",
    "ICMSSN102", "ICMSSN103", "ICMSSN300", "ICMSSN400",
}

# ──────────────────────────────────────────────────────────────────────
# 1.9 — Grupos PIS/COFINS e modalidade de tributacao
# ──────────────────────────────────────────────────────────────────────

PIS_GRUPO_MAP = {
    "PISAliq":  {"tipo": "ad_valorem", "bc": "vBC",     "aliq": "pPIS",      "vl": "vPIS"},
    "PISQtde":  {"tipo": "qtde",       "bc": "qBCProd", "aliq": "vAliqProd", "vl": None},
    "PISNT":    {"tipo": "nao_trib",   "bc": None,      "aliq": None,        "vl": None},
    "PISOutr":  {"tipo": "outros",     "bc": "vBC",     "aliq": "pPIS",      "vl": "vPIS"},
}

COFINS_GRUPO_MAP = {
    "COFINSAliq":  {"tipo": "ad_valorem", "bc": "vBC",     "aliq": "pCOFINS",   "vl": "vCOFINS"},
    "COFINSQtde":  {"tipo": "qtde",       "bc": "qBCProd", "aliq": "vAliqProd", "vl": None},
    "COFINSNT":    {"tipo": "nao_trib",   "bc": None,      "aliq": None,        "vl": None},
    "COFINSOutr":  {"tipo": "outros",     "bc": "vBC",     "aliq": "pCOFINS",   "vl": "vCOFINS"},
}


# ─────────────────────────────────────────────────────��────────────────
# Severidade e confianca
# ──────────────────────────────────────────────────────────────────────

class Severity(str, Enum):
    CRITICO = "critico"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Confidence(str, Enum):
    ALTA = "alta"
    MEDIA = "media"
    BAIXA = "baixa"
    INDICIO = "indicio"


class ActionPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


# ─────────────────────���────────────────────────────────────────────────
# Acoes sugeridas
# ──────────────────────────────────────────────────────────────────────

SUGGESTED_ACTIONS = {
    "corrigir_no_sped":           "Corrigir no SPED",
    "revisar_xml_emissor":        "Revisar XML com emissor",
    "revisar_parametrizacao_erp": "Revisar parametrização ERP",
    "revisar_cadastro":           "Revisar cadastro",
    "revisar_beneficio":          "Revisar benefício fiscal",
    "revisar_apuracao":           "Revisar apuração",
    "investigar":                 "Investigar",
}


# ──────────────────────────────────────────────────────────────────────
# Mapeamento legacy XML### -> XC###
# ──────────────────────────────────────────────────────────────────────

LEGACY_RULE_MAP = {
    "XML001": "XC001", "XML002": "XC002", "XML003": "XC003",
    "XML004": "XC004", "XML005": "XC005", "XML006": "XC006",
    "XML007": "XC018", "XML008": "XC019", "XML009": "XC021",
    "XML010": "XC022", "XML011": "XC023", "XML012": "XC014",
    "XML013": "XC015", "XML014": "XC016", "XML015": "XC017",
    "XML016": "XC012", "XML017": "XC013",
}

XC_TO_LEGACY = {v: k for k, v in LEGACY_RULE_MAP.items()}


# ───────────────��──────────────────────────────────────────────────────
# CST derivado do grupo ICMS do XML
# ──────────────────────────────────────────────────────────────────────

CST_FROM_XML_GROUP = {
    "ICMS00": "000", "ICMS02": "002", "ICMS10": "010",
    "ICMS15": "015", "ICMS20": "020", "ICMS30": "030",
    "ICMS40": "040", "ICMS41": "041", "ICMS50": "050",
    "ICMS51": "051", "ICMS53": "053", "ICMS60": "060",
    "ICMS61": "061", "ICMS70": "070", "ICMS90": "090",
    "ICMSSN101": "101", "ICMSSN102": "102", "ICMSSN103": "103",
    "ICMSSN201": "201", "ICMSSN202": "202", "ICMSSN203": "203",
    "ICMSSN300": "300", "ICMSSN400": "400", "ICMSSN500": "500",
    "ICMSSN900": "900",
}

# CFOPs por natureza de item
_CFOP_REVENDA = {"1102", "2102", "5102", "6102", "1403", "2403"}
_CFOP_USO_CONSUMO = {"1556", "2556", "5556", "6556", "1407", "2407"}
_CFOP_ATIVO = {"1551", "2551", "5551", "6551", "1406", "2406"}
_CFOP_DEVOLUCAO = {
    "1201", "1202", "1410", "2201", "2202", "2410",
    "5201", "5202", "5410", "6201", "6202", "6410",
}
_CFOP_REMESSA = {"5901", "5902", "5903", "5906", "6901", "6902", "6903", "6906"}


def classify_item_nature(cfop: str, vl_desc: float = 0.0, vl_prod: float = 0.0) -> ItemNature:
    """Classifica natureza do item pelo CFOP (seção 1.5 da spec)."""
    cfop4 = (cfop or "")[:4]
    if cfop4 in _CFOP_REVENDA:
        return ItemNature.REVENDA
    if cfop4 in _CFOP_USO_CONSUMO:
        return ItemNature.USO_CONSUMO
    if cfop4 in _CFOP_ATIVO:
        return ItemNature.ATIVO
    if vl_desc > 0 and abs(vl_desc - vl_prod) < 0.02:
        return ItemNature.BONIFICACAO
    return ItemNature.OUTRO


# ──────────────────────────────────────────────────────────────────────
# CrossValidationFinding — finding principal
# ────────────────────────────────────────────────���─────────────────────

@dataclass
class CrossValidationFinding:
    """Finding de cruzamento XML x SPED (seção 2.1 da spec)."""

    # Identificacao da regra
    rule_id: str                          # ex: "XC024"
    legacy_rule_id: str = ""              # ex: "XML010"
    rule_version: str = ""
    reference_pack_version: str = ""
    benefit_context_version: str = ""
    layout_version_detected: str = ""
    config_hash: str = ""

    # Tipologia
    error_type: str = ""                  # ex: "BC_ICMS_INDEVIDA_EM_CST_SEM_TRIBUTACAO"
    rule_outcome: RuleOutcome = RuleOutcome.EXECUTED_ERROR
    tipo_irregularidade: str = ""         # CANCELAMENTO, DENEGACAO, etc.

    # Severidade e confianca
    severity: str = "error"
    confidence: str = "alta"

    # Localizacao SPED
    sped_register: str = ""               # ex: "C170"
    sped_field: str = ""                  # ex: "VL_BC_ICMS"
    value_sped: str = ""

    # Localizacao XML
    xml_field: str = ""                   # ex: "ICMS00/vBC"
    value_xml: str = ""

    # Evidencias e contexto
    description: str = ""
    evidence: str = ""                    # JSON serializado
    regime_context: str = ""
    benefit_context: str = ""

    # Acao sugerida
    suggested_action: str = "investigar"

    # Causa raiz e deduplicacao
    root_cause_group: str = ""
    is_derived: bool = False

    # Scores e priorizacao
    risk_score: float = 0.0
    technical_risk_score: float = 0.0
    fiscal_impact_estimate: float = 0.0
    action_priority: str = ""             # P1/P2/P3/P4

    # Workflow de revisao humana
    review_status: str = "novo"

    # Referencia ao escopo
    file_id: int = 0
    document_scope_id: int = 0
    chave_nfe: str = ""
    nfe_id: int = 0

    def build_cache_key(self) -> str:
        """Gera cache key para IA (seção 2.6 da spec)."""
        parts = [
            self.rule_id,
            self.sped_register or "",
            self.sped_field or "",
            _bucket_value(self.value_sped),
            self.xml_field or "",
            _bucket_value(self.value_xml),
            self.regime_context or "",
            self.benefit_context or "",
        ]
        return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _bucket_value(v: str | None) -> str:
    """Discretiza valor para cache key (seção 2.6)."""
    if v is None or v == "":
        return ""
    try:
        n = float(v)
        if n == 0:
            return "zero"
        if n < 10:
            return "centavos"
        if n < 100:
            return "dezenas"
        if n < 1000:
            return "centenas"
        if n < 10000:
            return "milhares"
        return "alto"
    except ValueError:
        return v  # valor nominal (CST, CFOP) → usar literal


# ──────────────────────────────────────────────────────────────────────
# DocumentScope — escopo de documento (NF-e pareada)
# ──────────────────────────────────────────────────────────────────────

@dataclass
class XmlItemParsed:
    """Item parseado do XML NF-e para cruzamento."""
    num_item: int = 0
    cod_produto: str = ""
    ncm: str = ""
    cfop: str = ""
    vl_prod: float = 0.0
    vl_desc: float = 0.0
    qtd: float | None = None
    cst_icms: str = ""
    vbc_icms: float = 0.0
    aliq_icms: float = 0.0
    vl_icms: float = 0.0
    vbc_icms_st: float = 0.0
    vl_icms_st: float = 0.0
    cst_ipi: str = ""
    vl_ipi: float = 0.0
    cst_pis: str = ""
    vl_pis: float = 0.0
    cst_cofins: str = ""
    vl_cofins: float = 0.0
    grupo_icms: str = ""       # "ICMS00", "ICMS40", "ICMSSN101", etc.
    grupo_ipi: str | None = None   # "IPITrib", "IPINT", ou None
    grupo_pis: str | None = None   # "PISAliq", "PISNT", etc.
    grupo_cofins: str | None = None
    # Campos extras para heuristica de match
    unidade: str = ""
    # Campos PIS/COFINS detalhados
    q_bc_prod_pis: float = 0.0
    v_aliq_prod_pis: float = 0.0
    q_bc_prod_cofins: float = 0.0
    v_aliq_prod_cofins: float = 0.0


@dataclass
class SpedC170Item:
    """Registro C170 do SPED para cruzamento."""
    record_id: int = 0
    line_number: int = 0
    num_item: int = 0
    cod_item: str = ""
    ncm: str = ""
    cfop: str = ""
    vl_item: float = 0.0
    vl_desc: float = 0.0
    qtd: float = 0.0
    unid: str = ""
    cst_icms: str = ""
    vl_bc_icms: float = 0.0
    aliq_icms: float = 0.0
    vl_icms: float = 0.0
    vl_bc_icms_st: float = 0.0
    vl_icms_st: float = 0.0
    cst_ipi: str = ""
    vl_ipi: float = 0.0
    cst_pis: str = ""
    vl_pis: float = 0.0
    cst_cofins: str = ""
    vl_cofins: float = 0.0
    ind_apur: str = ""
    fields: dict = field(default_factory=dict)  # campos originais


@dataclass
class ItemPair:
    """Par (C170, XML item) com estado de pareamento."""
    c170: SpedC170Item | None = None
    xml_item: XmlItemParsed | None = None
    match_state: ItemMatchState = ItemMatchState.SEM_MATCH
    match_score: float = 0.0
    item_nature: ItemNature = ItemNature.OUTRO


@dataclass
class DocumentScope:
    """Escopo de documento para cruzamento (seção 2.2 da spec).

    Representa um par (C100, NF-e XML) com seus itens pareados.
    """
    id: int = 0
    file_id: int = 0
    chave_nfe: str = ""
    nfe_id: int = 0

    # Dados C100
    c100_record_id: int = 0
    c100_line_number: int = 0
    c100_fields: dict = field(default_factory=dict)

    # Dados XML resumo
    xml_data: dict = field(default_factory=dict)

    # Itens pareados
    item_pairs: list[ItemPair] = field(default_factory=list)
    # Itens XML sem par C170
    xml_items_sem_match: list[XmlItemParsed] = field(default_factory=list)
    # C170 sem par XML
    c170_sem_match: list[SpedC170Item] = field(default_factory=list)

    # C190 do documento (para validacao triangular XC051)
    c190_records: list[dict] = field(default_factory=list)

    # Flags de escopo
    is_complementar: int = 0       # 1 = dois sinais (COD_SIT=06 + C113)
    xml_eligible: int = 1          # 0 se COD_MOD nao elegivel
    match_status: str = "matched"  # matched|sem_xml|sem_c100|fora_periodo|cancelada|NAO_APLICAVEL
    xml_effective_version: str = ""
    xml_effective_event_set: str = ""
    xml_resolution_reason: str = ""

    # Regime do declarante
    regime: str = ""
    ind_emit: str = ""  # 0=emitente, 1=destinatario

    # Totais do C100 para comparacao rapida
    vl_doc: float = 0.0
    vl_merc: float = 0.0
    vl_icms: float = 0.0
    vl_icms_st: float = 0.0
    vl_ipi: float = 0.0
    vl_pis: float = 0.0
    vl_cofins: float = 0.0
    vl_frt: float = 0.0
    vl_seg: float = 0.0
    vl_out_da: float = 0.0
    cod_sit: str = ""
    cod_mod: str = ""
    dt_doc: str = ""
    dt_e_s: str = ""

    # Findings gerados para este escopo
    findings: list[CrossValidationFinding] = field(default_factory=list)

    def get_c100_field(self, name: str) -> str:
        """Retorna campo do C100 normalizado."""
        return str(self.c100_fields.get(name, "")).strip()

    @property
    def has_xml(self) -> bool:
        return bool(self.xml_data)

    @property
    def xml_totais(self) -> dict:
        return self.xml_data.get("totais", {})
