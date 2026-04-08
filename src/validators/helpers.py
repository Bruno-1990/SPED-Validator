"""Helpers e constantes compartilhados por todos os validadores SPED."""

from __future__ import annotations

from ..models import SpedRecord, ValidationError

# ──────────────────────────────────────────────
# MOD-09: Schema nomeado — mapeamento posição → nome
# ──────────────────────────────────────────────

REGISTER_FIELDS: dict[str, list[str]] = {
    "0000": [
        "REG", "COD_VER", "COD_FIN", "DT_INI", "DT_FIN", "NOME", "CNPJ",
        "CPF", "UF", "IE", "COD_MUN", "IM", "SUFRAMA", "IND_PERFIL", "IND_ATIV",
    ],
    "0001": ["REG", "IND_MOV"],
    "0005": [
        "REG", "NOME_FANTASIA", "CEP", "END", "NUM", "COMPL", "BAIRRO",
        "FONE", "FAX", "EMAIL",
    ],
    "0100": [
        "REG", "NOME", "CPF", "CRC", "CNPJ", "CEP", "END", "NUM",
        "COMPL", "BAIRRO", "FONE", "FAX", "EMAIL", "COD_MUN",
    ],
    "0150": [
        "REG", "COD_PART", "NOME", "COD_PAIS", "CNPJ", "CPF", "IE",
        "COD_MUN", "SUFRAMA", "END", "NUM", "COMPL", "BAIRRO", "UF",
    ],
    "0200": [
        "REG", "COD_ITEM", "DESCR_ITEM", "COD_BARRA", "COD_ANT_ITEM",
        "UNID_INV", "TIPO_ITEM", "COD_NCM", "EX_IPI", "COD_GEN",
        "COD_LST", "ALIQ_ICMS",
    ],
    "0400": ["REG", "COD_NAT", "DESCR_NAT"],
    "0990": ["REG", "QTD_LIN_0"],
    "C001": ["REG", "IND_MOV"],
    "C100": [
        "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
        "SER", "NUM_DOC", "CHV_NFE", "DT_DOC", "DT_E_S", "VL_DOC",
        "IND_PGTO", "VL_DESC", "VL_ABAT_NT", "VL_MERC", "IND_FRT",
        "VL_FRT", "VL_SEG", "VL_OUT_DA", "VL_BC_ICMS", "VL_ICMS",
        "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_IPI", "VL_PIS", "VL_COFINS",
        "VL_PIS_ST", "VL_COFINS_ST",
    ],
    "C170": [
        "REG", "NUM_ITEM", "COD_ITEM", "DESCR_COMPL", "QTD", "UNID",
        "VL_ITEM", "VL_DESC", "IND_MOV", "CST_ICMS", "CFOP", "COD_NAT",
        "VL_BC_ICMS", "ALIQ_ICMS", "VL_ICMS", "VL_BC_ICMS_ST", "ALIQ_ST",
        "VL_ICMS_ST", "IND_APUR", "CST_IPI", "COD_ENQ", "VL_BC_IPI",
        "ALIQ_IPI", "VL_IPI", "CST_PIS", "VL_BC_PIS", "ALIQ_PIS",
        "QUANT_BC_PIS", "ALIQ_PIS_REAIS", "VL_PIS", "CST_COFINS",
        "VL_BC_COFINS", "ALIQ_COFINS", "QUANT_BC_COFINS",
        "ALIQ_COFINS_REAIS", "VL_COFINS", "COD_CTA", "VL_ABAT_NT",
    ],
    "C190": [
        "REG", "CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS",
        "VL_ICMS", "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_RED_BC", "VL_IPI",
        "COD_OBS",
    ],
    "C400": [
        "REG", "COD_MOD", "ECF_MOD", "ECF_FAB", "ECF_CX",
    ],
    "C405": [
        "REG", "DT_DOC", "CRO", "CRZ", "NUM_COO_FIN", "GT_FIN", "VL_BRT",
    ],
    "C490": [
        "REG", "CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS",
        "VL_ICMS",
    ],
    "C500": [
        "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
        "SER", "SUB", "NUM_DOC", "DT_DOC", "DT_E_S", "VL_DOC", "VL_ICMS",
        "COD_INF", "VL_PIS", "VL_COFINS", "COD_CTA",
    ],
    "C510": [
        "REG", "NUM_ITEM", "COD_ITEM", "COD_CLASS", "QTD", "UNID",
        "VL_ITEM", "VL_DESC", "CST_ICMS", "CFOP", "VL_BC_ICMS",
        "ALIQ_ICMS", "VL_ICMS", "VL_BC_ICMS_ST", "ALIQ_ST", "VL_ICMS_ST",
        "IND_REC", "COD_PART", "VL_PIS", "VL_COFINS", "COD_CTA",
    ],
    "C590": [
        "REG", "CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS",
        "VL_ICMS", "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_RED_BC", "COD_OBS",
    ],
    "C990": ["REG", "QTD_LIN_C"],
    "D001": ["REG", "IND_MOV"],
    "D100": [
        "REG", "IND_OPER", "IND_EMIT", "COD_PART", "COD_MOD", "COD_SIT",
        "SER", "SUB", "NUM_DOC", "CHV_CTE", "DT_DOC", "DT_A_P", "TP_CT_E",
        "CHV_CTE_REF", "VL_DOC", "VL_DESC", "IND_FRT", "VL_SERV",
        "VL_BC_ICMS", "VL_ICMS", "VL_NT", "COD_INF", "COD_CTA",
    ],
    "D190": [
        "REG", "CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS",
        "VL_ICMS", "VL_RED_BC", "COD_OBS",
    ],
    "D690": [
        "REG", "CST_ICMS", "CFOP", "ALIQ_ICMS", "VL_OPR", "VL_BC_ICMS",
        "VL_ICMS", "VL_BC_ICMS_ST", "VL_ICMS_ST", "VL_RED_BC", "COD_OBS",
    ],
    "D990": ["REG", "QTD_LIN_D"],
    "E001": ["REG", "IND_MOV"],
    "E100": ["REG", "DT_INI", "DT_FIN"],
    "E110": [
        "REG", "VL_TOT_DEBITOS", "VL_AJ_DEBITOS", "VL_TOT_AJ_DEBITOS",
        "VL_ESTORNOS_CRED", "VL_TOT_CREDITOS", "VL_AJ_CREDITOS",
        "VL_TOT_AJ_CREDITOS", "VL_ESTORNOS_DEB", "VL_SLD_CREDOR_ANT",
        "VL_SLD_APURADO", "VL_TOT_DED", "VL_ICMS_RECOLHER",
        "VL_SLD_CREDOR_TRANSPORTAR", "DEB_ESP",
    ],
    "E111": ["REG", "COD_AJ_APUR", "DESCR_COMPL_AJ", "VL_AJ_APUR"],
    "E200": ["REG", "UF", "DT_INI", "DT_FIN"],
    "E210": [
        "REG", "IND_MOV_ST", "VL_SLD_CRED_ANT_ST", "VL_DEVOL_ST",
        "VL_RESSARC_ST", "VL_OUT_CRED_ST", "VL_AJ_CREDITOS_ST",
        "VL_RETENCAO_ST", "VL_OUT_DEB_ST", "VL_AJ_DEBITOS_ST",
        "VL_SLD_DEV_ANT_ST", "VL_DEDUCOES_ST", "VL_ICMS_RECOL_ST",
        "VL_SLD_CRED_ST_TRANSPORTAR", "DEB_ESP_ST",
    ],
    "E300": ["REG", "UF", "DT_INI", "DT_FIN"],
    "E500": ["REG", "IND_APUR", "DT_INI", "DT_FIN"],
    "E510": ["REG", "CFOP", "CST_IPI", "VL_CONT_IPI", "VL_BC_IPI", "VL_IPI"],
    "E520": [
        "REG", "VL_SD_ANT_IPI", "VL_DEB_IPI", "VL_CRED_IPI",
        "VL_OD_IPI", "VL_OC_IPI", "VL_SC_IPI", "VL_SD_IPI",
    ],
    "E530": ["REG", "IND_AJ", "VL_AJ", "COD_AJ", "NUM_DOC", "DESCR_AJ"],
    "E531": [
        "REG", "COD_PART", "CNPJ", "CPF", "COD_MOD",
        "SER", "SUB", "NUM_DOC", "DT_DOC",
    ],
    "E990": ["REG", "QTD_LIN_E"],
    "H001": ["REG", "IND_MOV"],
    "H010": [
        "REG", "COD_ITEM", "UNID", "QTD", "VL_UNIT", "VL_ITEM",
        "IND_PROP", "COD_PART", "TXT_COMPL", "COD_CTA", "VL_ITEM_IR",
    ],
    "H990": ["REG", "QTD_LIN_H"],
    "K001": ["REG", "IND_MOV"],
    "K200": ["REG", "DT_EST", "COD_ITEM", "QTD", "IND_EST", "COD_PART"],
    "K210": ["REG", "DT_INI_OS"],
    "K220": ["REG", "DT_MOV", "COD_ITEM_ORI", "COD_ITEM_DEST", "QTD"],
    "K230": ["REG", "DT_INI_OP", "DT_FIN_OP", "COD_DOC_OP", "COD_ITEM", "QTD_DEST"],
    "K235": ["REG", "DT_SAIDA", "COD_ITEM", "QTD", "COD_INS_SUBS", "QTD_ENC"],
    "K990": ["REG", "QTD_LIN_K"],
    "9001": ["REG", "IND_MOV"],
    "9900": ["REG", "REG_BLC", "QTD_REG_BLC"],
    "9990": ["REG", "QTD_LIN_9"],
    "9999": ["REG", "QTD_LIN"],
}


def fields_to_dict(register: str, fields_list: list[str]) -> dict[str, str]:
    """Converte lista posicional de campos para dict nomeado.

    Usa REGISTER_FIELDS para mapear cada posicao ao nome do campo.
    Campos alem do mapeamento recebem nomes genericos F00, F01, etc.
    """
    names = REGISTER_FIELDS.get(register)
    result: dict[str, str] = {}
    for i, val in enumerate(fields_list):
        name = names[i] if names and i < len(names) else f"F{i:02d}"
        result[name] = val
    return result


# ──────────────────────────────────────────────
# Helpers de acesso a campos
# ──────────────────────────────────────────────

def get_field(record: SpedRecord, field: str) -> str:
    """Retorna campo pelo nome, ou string vazia se nao existir."""
    return record.fields.get(field, "").strip()


def to_float(value: str) -> float:
    """Converte string para float, tratando virgula decimal."""
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def trib(cst: str) -> str:
    """Extrai a parte da tributacao (ultimos 2 digitos) de um CST."""
    return cst[-2:] if len(cst) >= 2 else cst


def make_error(
    record: SpedRecord,
    field_name: str,
    error_type: str,
    message: str,
    field_no: int = 0,
    value: str = "",
    expected_value: str | None = None,
) -> ValidationError:
    """Cria ValidationError vinculado a um registro."""
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=field_no,
        field_name=field_name,
        value=value,
        error_type=error_type,
        message=message,
        expected_value=expected_value,
    )


def make_generic_error(
    error_type: str,
    message: str,
    register: str = "SPED",
    value: str = "",
) -> ValidationError:
    """Cria erro generico nao vinculado a um registro especifico."""
    return ValidationError(
        line_number=0,
        register=register,
        field_no=0,
        field_name="",
        value=value,
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# Constantes — CST
# ──────────────────────────────────────────────

# ICMS — CSTs que indicam tributacao (debito proprio)
CST_TRIBUTADO = {"00", "02", "10", "12", "13", "15", "20", "70", "90"}

# ICMS — CSTs que indicam isencao/nao-tributacao/suspensao
CST_ISENTO_NT = {"30", "40", "41", "50", "60", "61"}

# ICMS — CST diferimento
CST_DIFERIMENTO = {"51", "52", "53"}

# CSTs de ST (substituicao tributaria)
CST_ST = {"10", "12", "13", "15", "30", "60", "61", "70", "72", "74"}

# CSTs monofasico combustiveis (LC 192/2022)
CST_MONOFASICO = {"02", "15", "53", "61"}

# Aliquotas interestaduais validas (Resolucao Senado 13/2012)
ALIQ_INTERESTADUAIS = {4.0, 7.0, 12.0}

TOLERANCE = 0.02


# ──────────────────────────────────────────────
# Constantes — CFOP
# ──────────────────────────────────────────────

CFOP_VENDA = {
    "5101", "5102", "5103", "5104", "5105", "5106", "5109", "5110",
    "5111", "5112", "5113", "5114", "5115", "5116", "5117", "5118",
    "5119", "5120", "5122", "5123", "5124", "5125",
    "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108",
    "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116",
    "6117", "6118", "6119", "6120", "6122", "6123", "6124", "6125",
}

CFOP_DEVOLUCAO = {
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411",
    "1503", "1504",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411",
    "2503", "2504",
    "5201", "5202", "5208", "5209", "5210", "5410", "5411",
    "5503", "5504",
    "6201", "6202", "6208", "6209", "6210", "6410", "6411",
    "6503", "6504",
}

CFOP_REMESSA_SAIDA = {
    "5901", "5902", "5903", "5904", "5905", "5906", "5907", "5908",
    "5909", "5910", "5911", "5912", "5913", "5914", "5915", "5916",
    "5917", "5918", "5919", "5920", "5921", "5922", "5923", "5924",
    "5925", "5926", "5927", "5928", "5929", "5949",
    "6901", "6902", "6903", "6904", "6905", "6906", "6907", "6908",
    "6909", "6910", "6911", "6912", "6913", "6914", "6915", "6916",
    "6917", "6918", "6919", "6920", "6921", "6922", "6923", "6924",
    "6925", "6926", "6927", "6928", "6929", "6949",
}

CFOP_RETORNO_ENTRADA = {
    "1901", "1902", "1903", "1904", "1905", "1906", "1907", "1908",
    "1909", "1910", "1911", "1912", "1913", "1914", "1915", "1916",
    "1917", "1918", "1919", "1920", "1921", "1922", "1923", "1924",
    "1925", "1926", "1949",
    "2901", "2902", "2903", "2904", "2905", "2906", "2907", "2908",
    "2909", "2910", "2911", "2912", "2913", "2914", "2915", "2916",
    "2917", "2918", "2919", "2920", "2921", "2922", "2923", "2924",
    "2925", "2949",
}

CFOP_REMESSA_RETORNO = CFOP_REMESSA_SAIDA | CFOP_RETORNO_ENTRADA

CFOP_EXPORTACAO = {
    "7101", "7102", "7105", "7106", "7127", "7201", "7202", "7210",
    "7211", "7251", "7301", "7358", "7501", "7504", "7551", "7553",
    "7556", "7651", "7654", "7667", "7930", "7949",
}


# ──────────────────────────────────────────────
# Nomes de campo (schema nomeado — MOD-09)
# ──────────────────────────────────────────────

# 0000
F_0000_UF = "UF"

# 0150
F_0150_COD_PART = "COD_PART"
F_0150_UF = "UF"

# 0200
F_0200_COD_ITEM = "COD_ITEM"
F_0200_NCM = "COD_NCM"

# C100
F_C100_IND_OPER = "IND_OPER"
F_C100_COD_PART = "COD_PART"
F_C100_COD_SIT = "COD_SIT"
F_C100_VL_DOC = "VL_DOC"
F_C100_VL_DESC = "VL_DESC"
F_C100_VL_MERC = "VL_MERC"
F_C100_VL_FRT = "VL_FRT"
F_C100_VL_SEG = "VL_SEG"
F_C100_VL_OUT_DA = "VL_OUT_DA"
F_C100_VL_ICMS_ST = "VL_ICMS_ST"
F_C100_VL_IPI = "VL_IPI"

# C170
F_C170_COD_ITEM = "COD_ITEM"
F_C170_VL_ITEM = "VL_ITEM"
F_C170_VL_DESC = "VL_DESC"
F_C170_CST_ICMS = "CST_ICMS"
F_C170_CFOP = "CFOP"
F_C170_VL_BC_ICMS = "VL_BC_ICMS"
F_C170_ALIQ_ICMS = "ALIQ_ICMS"
F_C170_VL_ICMS = "VL_ICMS"
F_C170_VL_BC_ICMS_ST = "VL_BC_ICMS_ST"
F_C170_ALIQ_ST = "ALIQ_ST"
F_C170_VL_ICMS_ST = "VL_ICMS_ST"
F_C170_CST_IPI = "CST_IPI"
F_C170_VL_BC_IPI = "VL_BC_IPI"
F_C170_ALIQ_IPI = "ALIQ_IPI"
F_C170_VL_IPI = "VL_IPI"
F_C170_CST_PIS = "CST_PIS"
F_C170_VL_BC_PIS = "VL_BC_PIS"
F_C170_ALIQ_PIS = "ALIQ_PIS"
F_C170_VL_PIS = "VL_PIS"
F_C170_CST_COFINS = "CST_COFINS"
F_C170_VL_BC_COFINS = "VL_BC_COFINS"
F_C170_ALIQ_COFINS = "ALIQ_COFINS"
F_C170_VL_COFINS = "VL_COFINS"

# C190
F_C190_CST = "CST_ICMS"
F_C190_CFOP = "CFOP"
F_C190_ALIQ = "ALIQ_ICMS"
F_C190_VL_OPR = "VL_OPR"
F_C190_VL_BC = "VL_BC_ICMS"
F_C190_VL_ICMS = "VL_ICMS"

# E110
F_E110_VL_TOT_DEBITOS = "VL_TOT_DEBITOS"
F_E110_VL_AJ_DEBITOS = "VL_AJ_DEBITOS"
F_E110_VL_TOT_AJ_DEBITOS = "VL_TOT_AJ_DEBITOS"
F_E110_VL_ESTORNOS_CRED = "VL_ESTORNOS_CRED"
F_E110_VL_TOT_CREDITOS = "VL_TOT_CREDITOS"
F_E110_VL_AJ_CREDITOS = "VL_AJ_CREDITOS"
F_E110_VL_TOT_AJ_CREDITOS = "VL_TOT_AJ_CREDITOS"
F_E110_VL_ESTORNOS_DEB = "VL_ESTORNOS_DEB"
F_E110_VL_SLD_CREDOR_ANT = "VL_SLD_CREDOR_ANT"
F_E110_VL_SLD_APURADO = "VL_SLD_APURADO"
F_E110_VL_TOT_DED = "VL_TOT_DED"
F_E110_VL_ICMS_RECOLHER = "VL_ICMS_RECOLHER"
F_E110_VL_SLD_CREDOR_TRANSPORTAR = "VL_SLD_CREDOR_TRANSPORTAR"

# E111
F_E111_COD_AJ_APUR = "COD_AJ_APUR"
F_E111_DESCR_COMPL = "DESCR_COMPL_AJ"
F_E111_VL_AJ_APUR = "VL_AJ_APUR"

# H010
F_H010_COD_ITEM = "COD_ITEM"
F_H010_QTD = "QTD"
F_H010_VL_ITEM = "VL_ITEM"
