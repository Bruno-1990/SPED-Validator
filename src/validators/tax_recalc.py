"""Recálculo tributário: ICMS, ICMS-ST, IPI, PIS/COFINS e totalização E110."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register

TOLERANCE = 0.02  # Tolerância monetária para comparações


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


def _float_opt(value: str) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _error(
    record: SpedRecord,
    field_name: str,
    message: str,
    field_no: int = 0,
    expected_value: str | None = None,
    value: str = "",
) -> ValidationError:
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=field_no,
        field_name=field_name,
        value=value,
        error_type="CALCULO_DIVERGENTE",
        message=message,
        expected_value=expected_value,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def recalculate_taxes(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa todos os recálculos tributários.

    Retorna lista de erros onde valor declarado diverge do recalculado.
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Recálculo por item (C170)
    for rec in groups.get("C170", []):
        errors.extend(recalc_icms_item(rec))
        errors.extend(recalc_icms_st_item(rec))
        errors.extend(recalc_ipi_item(rec))
        errors.extend(recalc_pis_cofins_item(rec))

    # Totalização E110
    errors.extend(recalc_e110_totals(groups))

    return errors


# ──────────────────────────────────────────────
# ICMS por item (C170)
# ──────────────────────────────────────────────

def recalc_icms_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula ICMS de um item C170.

    Campos C170 relevantes (0-based):
    6:VL_ITEM, 7:VL_DESC, 12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS

    Regra: BC_ICMS = VL_ITEM - VL_DESC (quando tributado)
           ICMS = BC_ICMS * ALIQ / 100
    """
    errors: list[ValidationError] = []

    vl_item = _float(_get(record, 6))
    vl_desc = _float(_get(record, 7))
    vl_bc_icms = _float_opt(_get(record, 12))
    aliq_icms = _float_opt(_get(record, 13))
    vl_icms = _float_opt(_get(record, 14))

    if vl_bc_icms is None or aliq_icms is None or vl_icms is None:
        return errors

    if vl_bc_icms == 0 and aliq_icms == 0:
        return errors  # Item não tributado

    # Verificar BC: deveria ser VL_ITEM - VL_DESC
    bc_calc = vl_item - vl_desc
    if bc_calc > 0 and vl_bc_icms > 0:
        diff_bc = abs(bc_calc - vl_bc_icms)
        if diff_bc > TOLERANCE:
            errors.append(_error(
                record, "VL_BC_ICMS",
                f"BC ICMS: calculado={bc_calc:.2f} (VL_ITEM - VL_DESC) "
                f"vs declarado={vl_bc_icms:.2f} (dif={diff_bc:.2f}).",
                field_no=13,
                expected_value=f"{bc_calc:.2f}",
                value=f"{vl_bc_icms:.2f}",
            ))

    # Verificar ICMS = BC * ALIQ / 100
    icms_calc = vl_bc_icms * aliq_icms / 100
    diff = abs(icms_calc - vl_icms)
    if diff > TOLERANCE:
        errors.append(_error(
            record, "VL_ICMS",
            f"ICMS: calculado={icms_calc:.2f} (BC {vl_bc_icms:.2f} × {aliq_icms:.2f}%) "
            f"vs declarado={vl_icms:.2f} (dif={diff:.2f}).",
            field_no=15,
            expected_value=f"{icms_calc:.2f}",
            value=f"{vl_icms:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# ICMS-ST por item (C170)
# ──────────────────────────────────────────────

# CSTs que indicam substituição tributária
_CST_ST = {"10", "30", "60", "70", "201", "202", "203", "500"}


def recalc_icms_st_item(record: SpedRecord) -> list[ValidationError]:
    """Verifica consistência do ICMS-ST de um item C170.

    Campos C170 relevantes (0-based):
    9:CST_ICMS (posição pode variar), 15:VL_BC_ICMS_ST, 16:ALIQ_ST, 17:VL_ICMS_ST

    Para CSTs de ST, BC_ST e VL_ICMS_ST devem ser consistentes.
    """
    errors: list[ValidationError] = []

    # CST_ICMS na posição 9 (campo 10 do C170)
    cst_icms = _get(record, 9)

    # Só valida se CST indica ST
    if cst_icms not in _CST_ST:
        return errors

    # Posições para ICMS-ST no C170 (podem variar por versão)
    # Tentamos posições comuns: 15, 16, 17
    vl_bc_st = _float_opt(_get(record, 15))
    aliq_st = _float_opt(_get(record, 16))
    vl_icms_st = _float_opt(_get(record, 17))

    if vl_bc_st is None or vl_icms_st is None:
        return errors

    # Se tem BC_ST mas ICMS_ST é zero (ou vice-versa), pode ser inconsistência
    if vl_bc_st > 0 and vl_icms_st == 0:
        expected_st = (vl_bc_st * aliq_st / 100) if aliq_st and aliq_st > 0 else None
        errors.append(_error(
            record, "VL_ICMS_ST",
            f"CST {cst_icms} indica ST, BC_ST={vl_bc_st:.2f} mas VL_ICMS_ST=0.",
            field_no=18,
            expected_value=f"{expected_st:.2f}" if expected_st else None,
            value="0.00",
        ))

    # Se tem alíquota, recalcular
    if aliq_st is not None and aliq_st > 0 and vl_bc_st > 0:
        st_calc = vl_bc_st * aliq_st / 100
        diff = abs(st_calc - vl_icms_st)
        if diff > TOLERANCE:
            errors.append(_error(
                record, "VL_ICMS_ST",
                f"ICMS-ST: calculado={st_calc:.2f} (BC_ST {vl_bc_st:.2f} × {aliq_st:.2f}%) "
                f"vs declarado={vl_icms_st:.2f}.",
                field_no=18,
                expected_value=f"{st_calc:.2f}",
                value=f"{vl_icms_st:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# IPI por item (C170)
# ──────────────────────────────────────────────

def recalc_ipi_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula IPI de um item C170.

    Campos C170 relevantes (posições aproximadas):
    18 ou 19: VL_BC_IPI, 19 ou 20: ALIQ_IPI, 20 ou 21: VL_IPI

    Regra: IPI = VL_BC_IPI * ALIQ_IPI / 100
    """
    errors: list[ValidationError] = []

    # Posições do IPI no C170: campo 22=VL_BC_IPI, 23=ALIQ_IPI, 24=VL_IPI
    vl_bc_ipi = _float_opt(_get(record, 21))
    aliq_ipi = _float_opt(_get(record, 22))
    vl_ipi = _float_opt(_get(record, 23))

    if vl_bc_ipi is None or aliq_ipi is None or vl_ipi is None:
        return errors

    if vl_bc_ipi == 0 and aliq_ipi == 0:
        return errors

    ipi_calc = vl_bc_ipi * aliq_ipi / 100
    diff = abs(ipi_calc - vl_ipi)
    if diff > TOLERANCE:
        errors.append(_error(
            record, "VL_IPI",
            f"IPI: calculado={ipi_calc:.2f} (BC {vl_bc_ipi:.2f} × {aliq_ipi:.2f}%) "
            f"vs declarado={vl_ipi:.2f} (dif={diff:.2f}).",
            field_no=22,
            expected_value=f"{ipi_calc:.2f}",
            value=f"{vl_ipi:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# PIS/COFINS por item (C170)
# ──────────────────────────────────────────────

def recalc_pis_cofins_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula PIS e COFINS de um item C170.

    Campos C170 (posições aproximadas):
    PIS: 22:VL_BC_PIS, 23:ALIQ_PIS, 24:VL_PIS
    COFINS: 25:VL_BC_COFINS, 26:ALIQ_COFINS, 27:VL_COFINS
    """
    errors: list[ValidationError] = []

    # PIS: campo 26=VL_BC_PIS, 27=ALIQ_PIS(%), 30=VL_PIS
    vl_bc_pis = _float_opt(_get(record, 25))
    aliq_pis = _float_opt(_get(record, 26))
    vl_pis = _float_opt(_get(record, 29))

    if (vl_bc_pis is not None and aliq_pis is not None and vl_pis is not None
            and vl_bc_pis > 0 and aliq_pis > 0):
        pis_calc = vl_bc_pis * aliq_pis / 100
        diff = abs(pis_calc - vl_pis)
        if diff > TOLERANCE:
            errors.append(_error(
                record, "VL_PIS",
                f"PIS: calculado={pis_calc:.2f} (BC {vl_bc_pis:.2f} × {aliq_pis:.2f}%) vs declarado={vl_pis:.2f}.",
                field_no=25,
                expected_value=f"{pis_calc:.2f}",
                value=f"{vl_pis:.2f}",
            ))

    # COFINS: campo 32=VL_BC_COFINS, 33=ALIQ_COFINS(%), 36=VL_COFINS
    vl_bc_cofins = _float_opt(_get(record, 31))
    aliq_cofins = _float_opt(_get(record, 32))
    vl_cofins = _float_opt(_get(record, 35))

    if (vl_bc_cofins is not None and aliq_cofins is not None and vl_cofins is not None
            and vl_bc_cofins > 0 and aliq_cofins > 0):
        cofins_calc = vl_bc_cofins * aliq_cofins / 100
        diff = abs(cofins_calc - vl_cofins)
        if diff > TOLERANCE:
            errors.append(_error(
                record, "VL_COFINS",
                f"COFINS: calculado={cofins_calc:.2f} (BC {vl_bc_cofins:.2f} × "
                f"{aliq_cofins:.2f}%) vs declarado={vl_cofins:.2f}.",
                field_no=28,
                expected_value=f"{cofins_calc:.2f}",
                value=f"{vl_cofins:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Totalização E110
# ──────────────────────────────────────────────

@dataclass
class E110Totals:
    """Totais recalculados para o E110."""
    debitos_c190: float = 0.0
    creditos_c190: float = 0.0
    debitos_d: float = 0.0
    creditos_d: float = 0.0

    @property
    def total_debitos(self) -> float:
        return self.debitos_c190 + self.debitos_d

    @property
    def total_creditos(self) -> float:
        return self.creditos_c190 + self.creditos_d


def recalc_e110_totals(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Recalcula totalização do E110 a partir dos C190 e D690.

    Soma ICMS dos C190 com CFOP de saída → débitos
    Soma ICMS dos C190 com CFOP de entrada → créditos
    Compara com VL_TOT_DEBITOS e VL_TOT_CREDITOS do E110.
    """
    errors: list[ValidationError] = []

    e110_records = groups.get("E110", [])
    if not e110_records:
        return errors

    totals = E110Totals()

    # C190: CFOP na posição 2, VL_ICMS na posição 6
    for rec in groups.get("C190", []):
        cfop = _get(rec, 2)
        vl_icms = _float(_get(rec, 6))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_c190 += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_c190 += vl_icms

    # D690 (se existir): VL_ICMS na posição 4
    for rec in groups.get("D690", []):
        cfop = _get(rec, 2)
        vl_icms = _float(_get(rec, 4))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_d += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_d += vl_icms

    for e110 in e110_records:
        vl_tot_debitos = _float(_get(e110, 1))
        vl_tot_creditos = _float(_get(e110, 5))

        # Débitos
        diff_deb = abs(totals.total_debitos - vl_tot_debitos)
        if diff_deb > TOLERANCE:
            errors.append(_error(
                e110, "VL_TOT_DEBITOS",
                f"Totalização E110: débitos recalculados={totals.total_debitos:.2f} "
                f"(C190={totals.debitos_c190:.2f} + D={totals.debitos_d:.2f}) "
                f"vs declarado={vl_tot_debitos:.2f} (dif={diff_deb:.2f}).",
                field_no=2,
                expected_value=f"{totals.total_debitos:.2f}",
                value=f"{vl_tot_debitos:.2f}",
            ))

        # Créditos
        diff_cred = abs(totals.total_creditos - vl_tot_creditos)
        if diff_cred > TOLERANCE:
            errors.append(_error(
                e110, "VL_TOT_CREDITOS",
                f"Totalização E110: créditos recalculados={totals.total_creditos:.2f} "
                f"(C190={totals.creditos_c190:.2f} + D={totals.creditos_d:.2f}) "
                f"vs declarado={vl_tot_creditos:.2f} (dif={diff_cred:.2f}).",
                field_no=6,
                expected_value=f"{totals.total_creditos:.2f}",
                value=f"{vl_tot_creditos:.2f}",
            ))

    return errors
