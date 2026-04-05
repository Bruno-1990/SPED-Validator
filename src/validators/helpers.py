"""Helpers e constantes compartilhados por todos os validadores SPED."""

from __future__ import annotations

from ..models import SpedRecord, ValidationError


# ──────────────────────────────────────────────
# Helpers de acesso a campos
# ──────────────────────────────────────────────

def get_field(record: SpedRecord, idx: int) -> str:
    """Retorna campo na posição idx, ou string vazia se não existir."""
    if idx < len(record.fields):
        return record.fields[idx].strip()
    return ""


def to_float(value: str) -> float:
    """Converte string para float, tratando vírgula decimal."""
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def trib(cst: str) -> str:
    """Extrai a parte da tributação (últimos 2 dígitos) de um CST."""
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
    """Cria erro genérico não vinculado a um registro específico."""
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

# ICMS — CSTs que indicam tributação
CST_TRIBUTADO = {"00", "10", "20", "70", "90"}

# ICMS — CSTs que indicam isenção/não-tributação/suspensão
CST_ISENTO_NT = {"40", "41", "50", "60"}

# ICMS — CST diferimento
CST_DIFERIMENTO = {"51"}

# CSTs de ST
CST_ST = {"10", "30", "60", "70"}

# Alíquotas interestaduais válidas (Resolução Senado 13/2012)
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
# Posições de campo (layout Guia Prático EFD)
# ──────────────────────────────────────────────

# 0000
F_0000_UF = 8

# 0150
F_0150_COD_PART = 1
F_0150_UF = 13

# 0200
F_0200_COD_ITEM = 1
F_0200_NCM = 7

# C100
F_C100_IND_OPER = 1
F_C100_COD_PART = 3
F_C100_COD_SIT = 5
F_C100_VL_DOC = 11
F_C100_VL_DESC = 13
F_C100_VL_MERC = 15
F_C100_VL_FRT = 17
F_C100_VL_SEG = 18
F_C100_VL_OUT_DA = 19

# C170
F_C170_COD_ITEM = 2
F_C170_VL_ITEM = 6
F_C170_VL_DESC = 7
F_C170_CST_ICMS = 9
F_C170_CFOP = 10
F_C170_VL_BC_ICMS = 12
F_C170_ALIQ_ICMS = 13
F_C170_VL_ICMS = 14
F_C170_VL_BC_ICMS_ST = 15
F_C170_ALIQ_ST = 16
F_C170_VL_ICMS_ST = 17
F_C170_CST_IPI = 19
F_C170_VL_BC_IPI = 21
F_C170_ALIQ_IPI = 22
F_C170_VL_IPI = 23
F_C170_CST_PIS = 24
F_C170_VL_BC_PIS = 25
F_C170_ALIQ_PIS = 26
F_C170_VL_PIS = 29
F_C170_CST_COFINS = 30
F_C170_VL_BC_COFINS = 31
F_C170_ALIQ_COFINS = 32
F_C170_VL_COFINS = 35

# C190
F_C190_CST = 1
F_C190_CFOP = 2
F_C190_ALIQ = 3
F_C190_VL_OPR = 4
F_C190_VL_BC = 5
F_C190_VL_ICMS = 6

# E110
F_E110_VL_TOT_DEBITOS = 1
F_E110_VL_AJ_DEBITOS = 2
F_E110_VL_TOT_AJ_DEBITOS = 3
F_E110_VL_ESTORNOS_CRED = 4
F_E110_VL_TOT_CREDITOS = 5
F_E110_VL_AJ_CREDITOS = 6
F_E110_VL_TOT_AJ_CREDITOS = 7
F_E110_VL_ESTORNOS_DEB = 8
F_E110_VL_SLD_CREDOR_ANT = 9
F_E110_VL_SLD_APURADO = 10
F_E110_VL_TOT_DED = 11
F_E110_VL_ICMS_RECOLHER = 12
F_E110_VL_SLD_CREDOR_TRANSPORTAR = 13

# E111
F_E111_COD_AJ_APUR = 1
F_E111_DESCR_COMPL = 2
F_E111_VL_AJ_APUR = 3

# H010
F_H010_COD_ITEM = 1
F_H010_QTD = 3
F_H010_VL_ITEM = 5
