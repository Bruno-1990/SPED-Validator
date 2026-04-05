"""Recalculo tributario: ICMS, ICMS-ST, IPI, PIS/COFINS e totalizacao E110."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    TOLERANCE,
    get_field,
    make_error,
    to_float,
)


# ──────────────────────────────────────────────
# Helpers locais
# ──────────────────────────────────────────────

def _float_opt(value: str) -> float | None:
    """Converte string para float, retornando None se vazio."""
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _check_calc(
    record: SpedRecord,
    field_name: str,
    field_no: int,
    vl_bc: float,
    aliq: float,
    vl_declarado: float,
    tributo_label: str,
) -> list[ValidationError]:
    """Verifica calculo imposto = BC * ALIQ / 100 com deteccao de arredondamento.

    Se a divergencia decorre de arredondamento de aliquota (ERP usa
    precisao maior que 2 decimais), gera CALCULO_ARREDONDAMENTO com
    explicacao e botao de correcao. Caso contrario, gera CALCULO_DIVERGENTE.
    """
    calc = vl_bc * aliq / 100
    diff = abs(calc - vl_declarado)

    if diff <= TOLERANCE:
        return []

    # Verificar arredondamento: taxa efetiva arredondada bate com aliquota?
    if vl_bc > 0 and vl_declarado > 0:
        taxa_efetiva = vl_declarado / vl_bc * 100
        if round(taxa_efetiva, 2) == round(aliq, 2):
            return [make_error(
                record, field_name, "CALCULO_ARREDONDAMENTO",
                f"{tributo_label}: diferenca de R$ {diff:.2f} entre calculado "
                f"({calc:.2f} = BC {vl_bc:.2f} x {aliq:.2f}%) "
                f"e declarado ({vl_declarado:.2f}). "
                f"A taxa efetiva ({taxa_efetiva:.4f}%) arredondada em 2 decimais "
                f"coincide com a aliquota informada ({aliq:.2f}%), indicando "
                f"que o ERP calculou com precisao maior (comum em operacoes do "
                f"Simples Nacional, LC 123/2006). "
                f"Caso deseje padronizar, clique em Corrigir para usar o valor "
                f"recalculado com a aliquota de 2 decimais.",
                field_no=field_no,
                expected_value=f"{calc:.2f}",
                value=f"{vl_declarado:.2f}",
            )]

    return [make_error(
        record, field_name, "CALCULO_DIVERGENTE",
        f"{tributo_label}: calculado={calc:.2f} (BC {vl_bc:.2f} x {aliq:.2f}%) "
        f"vs declarado={vl_declarado:.2f} (dif={diff:.2f}).",
        field_no=field_no,
        expected_value=f"{calc:.2f}",
        value=f"{vl_declarado:.2f}",
    )]


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def recalculate_taxes(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa todos os recalculos tributarios.

    Retorna lista de erros onde valor declarado diverge do recalculado.
    """
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Recalculo por item (C170)
    for rec in groups.get("C170", []):
        errors.extend(recalc_icms_item(rec))
        errors.extend(recalc_icms_st_item(rec))
        errors.extend(recalc_ipi_item(rec))
        errors.extend(recalc_pis_cofins_item(rec))

    # Totalizacao E110
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

    vl_item = to_float(get_field(record, 6))
    vl_desc = to_float(get_field(record, 7))
    vl_bc_icms = _float_opt(get_field(record, 12))
    aliq_icms = _float_opt(get_field(record, 13))
    vl_icms = _float_opt(get_field(record, 14))

    if vl_bc_icms is None or aliq_icms is None or vl_icms is None:
        return errors

    if vl_bc_icms == 0 and aliq_icms == 0:
        return errors  # Item nao tributado

    # Caso especial: ALIQ=0 mas VL_ICMS > 0 com BC > 0
    # Tratado pelo correction_hypothesis.py com analise de confianca.
    if aliq_icms == 0 and vl_icms > 0 and vl_bc_icms > 0:
        return errors

    errors.extend(_check_calc(record, "VL_ICMS", 15, vl_bc_icms, aliq_icms, vl_icms, "ICMS"))
    return errors


# ──────────────────────────────────────────────
# ICMS-ST por item (C170)
# ──────────────────────────────────────────────

# CSTs que indicam substituicao tributaria
_CST_ST = {"10", "30", "60", "70", "201", "202", "203", "500"}


def recalc_icms_st_item(record: SpedRecord) -> list[ValidationError]:
    """Verifica consistencia do ICMS-ST de um item C170.

    Campos C170 relevantes (0-based):
    9:CST_ICMS (posicao pode variar), 15:VL_BC_ICMS_ST, 16:ALIQ_ST, 17:VL_ICMS_ST

    Para CSTs de ST, BC_ST e VL_ICMS_ST devem ser consistentes.
    """
    errors: list[ValidationError] = []

    # CST_ICMS na posicao 9 (campo 10 do C170)
    cst_icms = get_field(record, 9)

    # So valida se CST indica ST
    if cst_icms not in _CST_ST:
        return errors

    # Posicoes para ICMS-ST no C170 (podem variar por versao)
    # Tentamos posicoes comuns: 15, 16, 17
    vl_bc_st = _float_opt(get_field(record, 15))
    aliq_st = _float_opt(get_field(record, 16))
    vl_icms_st = _float_opt(get_field(record, 17))

    if vl_bc_st is None or vl_icms_st is None:
        return errors

    # Se tem BC_ST mas ICMS_ST e zero (ou vice-versa), pode ser inconsistencia
    if vl_bc_st > 0 and vl_icms_st == 0:
        expected_st = (vl_bc_st * aliq_st / 100) if aliq_st and aliq_st > 0 else None
        errors.append(make_error(
            record, "VL_ICMS_ST", "CALCULO_DIVERGENTE",
            f"CST {cst_icms} indica ST, BC_ST={vl_bc_st:.2f} mas VL_ICMS_ST=0.",
            field_no=18,
            expected_value=f"{expected_st:.2f}" if expected_st else None,
            value="0.00",
        ))

    # Se tem aliquota, recalcular
    if aliq_st is not None and aliq_st > 0 and vl_bc_st > 0:
        errors.extend(_check_calc(record, "VL_ICMS_ST", 18, vl_bc_st, aliq_st, vl_icms_st, "ICMS-ST"))

    return errors


# ──────────────────────────────────────────────
# IPI por item (C170)
# ──────────────────────────────────────────────

def recalc_ipi_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula IPI de um item C170.

    Campos C170 relevantes (posicoes aproximadas):
    18 ou 19: VL_BC_IPI, 19 ou 20: ALIQ_IPI, 20 ou 21: VL_IPI

    Regra: IPI = VL_BC_IPI * ALIQ_IPI / 100
    """
    errors: list[ValidationError] = []

    # Posicoes do IPI no C170: campo 22=VL_BC_IPI, 23=ALIQ_IPI, 24=VL_IPI
    vl_bc_ipi = _float_opt(get_field(record, 21))
    aliq_ipi = _float_opt(get_field(record, 22))
    vl_ipi = _float_opt(get_field(record, 23))

    if vl_bc_ipi is None or aliq_ipi is None or vl_ipi is None:
        return errors

    if vl_bc_ipi == 0 and aliq_ipi == 0:
        return errors

    errors.extend(_check_calc(record, "VL_IPI", 22, vl_bc_ipi, aliq_ipi, vl_ipi, "IPI"))
    return errors


# ──────────────────────────────────────────────
# PIS/COFINS por item (C170)
# ──────────────────────────────────────────────

def recalc_pis_cofins_item(record: SpedRecord) -> list[ValidationError]:
    """Recalcula PIS e COFINS de um item C170.

    Campos C170 (posicoes aproximadas):
    PIS: 22:VL_BC_PIS, 23:ALIQ_PIS, 24:VL_PIS
    COFINS: 25:VL_BC_COFINS, 26:ALIQ_COFINS, 27:VL_COFINS
    """
    errors: list[ValidationError] = []

    # PIS: campo 26=VL_BC_PIS, 27=ALIQ_PIS(%), 30=VL_PIS
    vl_bc_pis = _float_opt(get_field(record, 25))
    aliq_pis = _float_opt(get_field(record, 26))
    vl_pis = _float_opt(get_field(record, 29))

    if (vl_bc_pis is not None and aliq_pis is not None and vl_pis is not None
            and vl_bc_pis > 0 and aliq_pis > 0):
        errors.extend(_check_calc(record, "VL_PIS", 25, vl_bc_pis, aliq_pis, vl_pis, "PIS"))

    # COFINS: campo 32=VL_BC_COFINS, 33=ALIQ_COFINS(%), 36=VL_COFINS
    vl_bc_cofins = _float_opt(get_field(record, 31))
    aliq_cofins = _float_opt(get_field(record, 32))
    vl_cofins = _float_opt(get_field(record, 35))

    if (vl_bc_cofins is not None and aliq_cofins is not None and vl_cofins is not None
            and vl_bc_cofins > 0 and aliq_cofins > 0):
        errors.extend(_check_calc(record, "VL_COFINS", 28, vl_bc_cofins, aliq_cofins, vl_cofins, "COFINS"))

    return errors


# ──────────────────────────────────────────────
# Totalizacao E110
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
    """Recalcula totalizacao do E110 a partir dos C190 e D690.

    Soma ICMS dos C190 com CFOP de saida -> debitos
    Soma ICMS dos C190 com CFOP de entrada -> creditos
    Compara com VL_TOT_DEBITOS e VL_TOT_CREDITOS do E110.
    """
    errors: list[ValidationError] = []

    e110_records = groups.get("E110", [])
    if not e110_records:
        return errors

    totals = E110Totals()

    # C190: CFOP na posicao 2, VL_ICMS na posicao 6
    for rec in groups.get("C190", []):
        cfop = get_field(rec, 2)
        vl_icms = to_float(get_field(rec, 6))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_c190 += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_c190 += vl_icms

    # D690 (se existir): VL_ICMS na posicao 4
    for rec in groups.get("D690", []):
        cfop = get_field(rec, 2)
        vl_icms = to_float(get_field(rec, 4))
        if cfop and cfop[0] in ("5", "6", "7"):
            totals.debitos_d += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            totals.creditos_d += vl_icms

    for e110 in e110_records:
        vl_tot_debitos = to_float(get_field(e110, 1))
        vl_tot_creditos = to_float(get_field(e110, 5))

        # Debitos
        diff_deb = abs(totals.total_debitos - vl_tot_debitos)
        if diff_deb > TOLERANCE:
            errors.append(make_error(
                e110, "VL_TOT_DEBITOS", "CALCULO_DIVERGENTE",
                f"Totalizacao E110: debitos recalculados={totals.total_debitos:.2f} "
                f"(C190={totals.debitos_c190:.2f} + D={totals.debitos_d:.2f}) "
                f"vs declarado={vl_tot_debitos:.2f} (dif={diff_deb:.2f}).",
                field_no=2,
                expected_value=f"{totals.total_debitos:.2f}",
                value=f"{vl_tot_debitos:.2f}",
            ))

        # Creditos
        diff_cred = abs(totals.total_creditos - vl_tot_creditos)
        if diff_cred > TOLERANCE:
            errors.append(make_error(
                e110, "VL_TOT_CREDITOS", "CALCULO_DIVERGENTE",
                f"Totalizacao E110: creditos recalculados={totals.total_creditos:.2f} "
                f"(C190={totals.creditos_c190:.2f} + D={totals.creditos_d:.2f}) "
                f"vs declarado={vl_tot_creditos:.2f} (dif={diff_cred:.2f}).",
                field_no=6,
                expected_value=f"{totals.total_creditos:.2f}",
                value=f"{vl_tot_creditos:.2f}",
            ))

    return errors
