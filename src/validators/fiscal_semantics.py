"""Validação semântica fiscal: CST x alíquota zero, CST x CFOP.

Camada 3 do motor de validação — regras que verificam se o tratamento
tributário informado faz sentido fiscalmente, além da consistência numérica.
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register

# ──────────────────────────────────────────────
# Constantes — CST
# ──────────────────────────────────────────────

# ICMS — CSTs que indicam tributação
_CST_ICMS_TRIBUTADO = {"00", "10", "20", "70", "90"}

# ICMS — CSTs que indicam isenção / não-tributação / suspensão
_CST_ICMS_ISENTO_NT = {"40", "41", "50", "60"}

# ICMS — CST diferimento
_CST_ICMS_DIFERIMENTO = {"51"}

# IPI — CSTs que indicam tributação (saída tributada / entrada com crédito)
_CST_IPI_TRIBUTADO = {"00", "01", "49", "50", "99"}

# PIS/COFINS — CSTs que indicam operação tributável
_CST_PIS_COFINS_TRIBUTAVEL = {"01", "02", "03", "49"}

# ──────────────────────────────────────────────
# Constantes — Famílias de CFOP
# ──────────────────────────────────────────────

# CFOPs de venda / receita de mercadoria (internos e interestaduais)
_CFOP_VENDA = {
    "5101", "5102", "5103", "5104", "5105", "5106", "5109", "5110",
    "5111", "5112", "5113", "5114", "5115", "5116", "5117", "5118",
    "5119", "5120", "5122", "5123", "5124", "5125",
    "6101", "6102", "6103", "6104", "6105", "6106", "6107", "6108",
    "6109", "6110", "6111", "6112", "6113", "6114", "6115", "6116",
    "6117", "6118", "6119", "6120", "6122", "6123", "6124", "6125",
}

# CFOPs de devolução (compra devolvida / venda devolvida)
_CFOP_DEVOLUCAO = {
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411",
    "1503", "1504",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411",
    "2503", "2504",
    "5201", "5202", "5208", "5209", "5210", "5410", "5411",
    "5503", "5504",
    "6201", "6202", "6208", "6209", "6210", "6410", "6411",
    "6503", "6504",
}

# CFOPs de remessa / retorno (não geram receita/débito fiscal típico)
_CFOP_REMESSA_RETORNO = {
    "5901", "5902", "5903", "5904", "5905", "5906", "5907", "5908",
    "5909", "5910", "5911", "5912", "5913", "5914", "5915", "5916",
    "5917", "5918", "5919", "5920", "5921", "5922", "5923", "5924",
    "5925", "5926", "5927", "5928", "5929", "5949",
    "6901", "6902", "6903", "6904", "6905", "6906", "6907", "6908",
    "6909", "6910", "6911", "6912", "6913", "6914", "6915", "6916",
    "6917", "6918", "6919", "6920", "6921", "6922", "6923", "6924",
    "6925", "6926", "6927", "6928", "6929", "6949",
    "1901", "1902", "1903", "1904", "1905", "1906", "1907", "1908",
    "1909", "1910", "1911", "1912", "1913", "1914", "1915", "1916",
    "1917", "1918", "1919", "1920", "1921", "1922", "1923", "1924",
    "1925", "1926", "1949",
    "2901", "2902", "2903", "2904", "2905", "2906", "2907", "2908",
    "2909", "2910", "2911", "2912", "2913", "2914", "2915", "2916",
    "2917", "2918", "2919", "2920", "2921", "2922", "2923", "2924",
    "2925", "2949",
}

# CFOPs de exportação (alíquota zero é esperada)
_CFOP_EXPORTACAO = {
    "7101", "7102", "7105", "7106", "7127", "7201", "7202", "7210",
    "7211", "7251", "7301", "7358", "7501", "7504", "7551", "7553",
    "7556", "7651", "7654", "7667", "7930", "7949",
}

# CFOPs interstaduais (começam com 2 ou 6)
_CFOP_INTERESTADUAL_PREFIXOS = ("2", "6")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get(record: SpedRecord, idx: int) -> str:
    if idx < len(record.fields):
        return record.fields[idx].strip()
    return ""


def _float(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def _trib(cst: str) -> str:
    """Extrai a parte da tributação (últimos 2 dígitos) de um CST."""
    if len(cst) >= 2:
        return cst[-2:]
    return cst


def _make_error(
    record: SpedRecord,
    field_name: str,
    error_type: str,
    message: str,
    field_no: int = 0,
    value: str = "",
) -> ValidationError:
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=field_no,
        field_name=field_name,
        value=value,
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_fiscal_semantics(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa validações semânticas fiscais nos registros C170.

    Regras implementadas:
    - Classificação de cenário alíquota zero (ICMS, IPI, PIS/COFINS)
    - Cruzamento CST x CFOP
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    for rec in groups.get("C170", []):
        errors.extend(_classify_zero_rate_icms(rec))
        errors.extend(_classify_zero_rate_ipi(rec))
        errors.extend(_classify_zero_rate_pis_cofins(rec))
        errors.extend(_validate_cst_cfop(rec))

    return errors


# ──────────────────────────────────────────────
# FRENTE 2 — Classificador de cenário alíquota zero
# ──────────────────────────────────────────────

def _classify_zero_rate_icms(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de ICMS com alíquota/valores zerados.

    Substitui o 'skip condition' cego por análise inteligente:
    - CST tributado + BC > 0 + ALIQ = 0 → alerta forte
    - CST tributado + tudo zero → alerta moderado
    - CST isento/NT + tudo zero → OK (sem alerta)
    - CST diferimento + tudo zero → OK (sem alerta)
    """
    cst_icms = _get(record, 9)
    if not cst_icms:
        return []

    trib = _trib(cst_icms)
    vl_bc = _float(_get(record, 12))
    aliq = _float(_get(record, 13))
    vl_icms = _float(_get(record, 14))

    # Só analisa cenários zerados
    if aliq > 0:
        return []

    # CST isento/NT/suspensão com tudo zero → OK
    if trib in _CST_ICMS_ISENTO_NT:
        return []

    # CST diferimento com tudo zero → OK
    if trib in _CST_ICMS_DIFERIMENTO:
        return []

    # CST tributado com alíquota zero
    if trib in _CST_ICMS_TRIBUTADO:
        cfop = _get(record, 10)

        # Exportação com alíquota zero é esperado
        if cfop in _CFOP_EXPORTACAO:
            return []

        # Remessa/retorno com alíquota zero é comum
        if cfop in _CFOP_REMESSA_RETORNO:
            return []

        if vl_bc > 0 and aliq == 0:
            # Caso 1: BC preenchida mas alíquota zero → forte
            return [_make_error(
                record, "ALIQ_ICMS", "CST_ALIQ_ZERO_FORTE",
                (
                    f"CST {cst_icms} indica tributação, mas ALIQ_ICMS=0 com "
                    f"BC={vl_bc:.2f}. Verifique se o item deveria usar CST de "
                    f"isenção (40), não-tributação (41), suspensão (50) ou "
                    f"diferimento (51), ou se houve erro de parametrização."
                ),
                field_no=14,
                value=f"CST={cst_icms} BC={vl_bc:.2f} ALIQ=0",
            )]

        if vl_bc == 0 and aliq == 0 and vl_icms == 0:
            # Caso 2: Tudo zerado com CST tributado → moderado
            return [_make_error(
                record, "CST_ICMS", "CST_ALIQ_ZERO_MODERADO",
                (
                    f"CST {cst_icms} indica tributação integral, mas base, "
                    f"alíquota e imposto estão zerados. Verifique se há "
                    f"classificação fiscal incorreta ou lançamento incompleto. "
                    f"Se a operação for isenta, utilize CST 40; se não "
                    f"tributada, CST 41; se suspensa, CST 50."
                ),
                field_no=10,
                value=f"CST={cst_icms} BC=0 ALIQ=0 ICMS=0",
            )]

    return []


def _classify_zero_rate_ipi(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de IPI com CST tributado e valores zerados."""
    cst_ipi = _get(record, 19)
    if not cst_ipi:
        return []

    vl_bc_ipi = _float(_get(record, 21))
    aliq_ipi = _float(_get(record, 22))
    vl_ipi = _float(_get(record, 23))

    if cst_ipi not in _CST_IPI_TRIBUTADO:
        return []

    if vl_bc_ipi == 0 and aliq_ipi == 0 and vl_ipi == 0:
        return [_make_error(
            record, "CST_IPI", "IPI_CST_ALIQ_ZERO",
            (
                f"CST_IPI {cst_ipi} indica tributação, mas base, alíquota "
                f"e valor de IPI estão zerados. Verifique se o CST deveria "
                f"ser 02 (isento), 03 (não tributado), 04 (imune) ou "
                f"05 (suspenso)."
            ),
            field_no=20,
            value=f"CST_IPI={cst_ipi}",
        )]

    return []


def _classify_zero_rate_pis_cofins(record: SpedRecord) -> list[ValidationError]:
    """Classifica cenários de PIS/COFINS com CST tributável e valores zerados."""
    errors: list[ValidationError] = []

    # PIS: CST na posição 24, BC=25, ALIQ=26, VL=29
    cst_pis = _get(record, 24)
    if cst_pis and cst_pis in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = _float(_get(record, 25))
        aliq = _float(_get(record, 26))
        vl_pis = _float(_get(record, 29))
        if vl_bc == 0 and aliq == 0 and vl_pis == 0:
            errors.append(_make_error(
                record, "CST_PIS", "PIS_CST_ALIQ_ZERO",
                (
                    f"CST_PIS {cst_pis} indica operação tributável, mas base, "
                    f"alíquota e valor estão zerados. Verifique se o CST "
                    f"deveria ser 04 (não tributado), 06 (alíquota zero), "
                    f"07 (isento) ou 08 (sem incidência)."
                ),
                field_no=25,
                value=f"CST_PIS={cst_pis}",
            ))

    # COFINS: CST na posição 30, BC=31, ALIQ=32, VL=35
    cst_cofins = _get(record, 30)
    if cst_cofins and cst_cofins in _CST_PIS_COFINS_TRIBUTAVEL:
        vl_bc = _float(_get(record, 31))
        aliq = _float(_get(record, 32))
        vl_cofins = _float(_get(record, 35))
        if vl_bc == 0 and aliq == 0 and vl_cofins == 0:
            errors.append(_make_error(
                record, "CST_COFINS", "COFINS_CST_ALIQ_ZERO",
                (
                    f"CST_COFINS {cst_cofins} indica operação tributável, mas "
                    f"base, alíquota e valor estão zerados. Verifique se o "
                    f"CST deveria ser 04 (não tributado), 06 (alíquota zero), "
                    f"07 (isento) ou 08 (sem incidência)."
                ),
                field_no=31,
                value=f"CST_COFINS={cst_cofins}",
            ))

    return errors


# ──────────────────────────────────────────────
# FRENTE 1 — Cruzamento CST x CFOP
# ──────────────────────────────────────────────

def _validate_cst_cfop(record: SpedRecord) -> list[ValidationError]:
    """Valida compatibilidade semântica entre CST e CFOP.

    Regras:
    - CFOP de venda tributada + CST isento/NT → alerta
    - CFOP interestadual + alíquota zero (CST tributado) → alerta
    - CFOP de exportação + CST tributado com alíquota > 0 → alerta
    """
    cst_icms = _get(record, 9)
    cfop = _get(record, 10)

    if not cst_icms or not cfop:
        return []

    trib = _trib(cst_icms)
    aliq = _float(_get(record, 13))
    errors: list[ValidationError] = []

    # REGRA 1: CFOP de venda + CST isento/NT (sem remessa/exportação)
    if cfop in _CFOP_VENDA and trib in _CST_ICMS_ISENTO_NT:
        errors.append(_make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica venda de mercadoria, mas CST {cst_icms} "
                f"indica isenção/não-tributação. Verifique se a operação "
                f"possui benefício fiscal que justifique a combinação, ou se "
                f"o CST ou o CFOP estão incorretos."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop}",
        ))

    # REGRA 2: CFOP interestadual + CST tributado + alíquota zero
    if (cfop[:1] in _CFOP_INTERESTADUAL_PREFIXOS
            and trib in _CST_ICMS_TRIBUTADO
            and aliq == 0
            and cfop not in _CFOP_REMESSA_RETORNO
            and cfop not in _CFOP_DEVOLUCAO):
        errors.append(_make_error(
            record, "ALIQ_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"Operação interestadual (CFOP {cfop}) com CST tributado "
                f"{cst_icms} e alíquota zero. Operações interestaduais "
                f"normalmente possuem alíquota de 4%, 7% ou 12%. Verifique "
                f"se há benefício fiscal ou se a alíquota está incorreta."
            ),
            field_no=14,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ=0",
        ))

    # REGRA 3: CFOP de exportação + CST tributado com alíquota > 0
    if cfop in _CFOP_EXPORTACAO and trib in _CST_ICMS_TRIBUTADO and aliq > 0:
        errors.append(_make_error(
            record, "CST_ICMS", "CST_CFOP_INCOMPATIVEL",
            (
                f"CFOP {cfop} indica exportação, mas CST {cst_icms} indica "
                f"tributação com alíquota {aliq:.2f}%. Exportações "
                f"normalmente têm imunidade de ICMS. Verifique se o CST "
                f"deveria ser 41 (não tributado) ou se o CFOP está incorreto."
            ),
            field_no=10,
            value=f"CST={cst_icms} CFOP={cfop} ALIQ={aliq:.2f}",
        ))

    return errors
