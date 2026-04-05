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

    # Nota: NAO comparamos VL_BC_ICMS com VL_ITEM - VL_DESC.
    # Sao conceitos diferentes: a base de calculo pode incluir frete,
    # seguro, IPI (quando nao recuperavel), ou excluir valores por
    # reducao de base, descontos condicionados, etc. A unica validacao
    # confiavel e a coerencia matematica ICMS = BC x ALIQ.

    # Verificar ICMS = BC * ALIQ / 100 (vale para todos os CSTs)
    icms_calc = vl_bc_icms * aliq_icms / 100
    diff = abs(icms_calc - vl_icms)
    if diff > TOLERANCE:
        # Caso especial: ALIQ=0 mas VL_ICMS > 0 com BC > 0
        # Tratado pelo correction_hypothesis.py com analise de confianca,
        # cruzamento com itens irmaos e C190. Nao duplicar aqui.
        if aliq_icms == 0 and vl_icms > 0 and vl_bc_icms > 0:
            return errors

        # Verificar se a divergencia decorre de arredondamento da aliquota.
        # ERPs frequentemente calculam com aliquota de precisao maior
        # (ex: Simples Nacional 3,090909...%) mas gravam arredondada
        # no SPED (3,09%). Se a taxa efetiva (VL_ICMS/VL_BC) arredondada
        # em 2 decimais bate com ALIQ_ICMS, o calculo esta correto.
        if vl_bc_icms > 0 and vl_icms > 0:
            taxa_efetiva = vl_icms / vl_bc_icms * 100
            if round(taxa_efetiva, 2) == round(aliq_icms, 2):
                return errors  # Coerente com arredondamento

        errors.append(make_error(
            record, "VL_ICMS", "CALCULO_DIVERGENTE",
            f"ICMS: calculado={icms_calc:.2f} (BC {vl_bc_icms:.2f} x {aliq_icms:.2f}%) "
            f"vs declarado={vl_icms:.2f} (dif={diff:.2f}).",
            field_no=15,
            expected_value=f"{icms_calc:.2f}",
            value=f"{vl_icms:.2f}",
        ))

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
        st_calc = vl_bc_st * aliq_st / 100
        diff = abs(st_calc - vl_icms_st)
        if diff > TOLERANCE:
            # Verificar arredondamento de aliquota
            if vl_icms_st > 0:
                taxa_ef = vl_icms_st / vl_bc_st * 100
                if round(taxa_ef, 2) == round(aliq_st, 2):
                    pass  # Coerente com arredondamento
                else:
                    errors.append(make_error(
                        record, "VL_ICMS_ST", "CALCULO_DIVERGENTE",
                        f"ICMS-ST: calculado={st_calc:.2f} (BC_ST {vl_bc_st:.2f} x {aliq_st:.2f}%) "
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

    ipi_calc = vl_bc_ipi * aliq_ipi / 100
    diff = abs(ipi_calc - vl_ipi)
    if diff > TOLERANCE:
        # Verificar arredondamento de aliquota
        if vl_ipi > 0 and vl_bc_ipi > 0:
            taxa_ef = vl_ipi / vl_bc_ipi * 100
            if round(taxa_ef, 2) == round(aliq_ipi, 2):
                return errors  # Coerente com arredondamento

        errors.append(make_error(
            record, "VL_IPI", "CALCULO_DIVERGENTE",
            f"IPI: calculado={ipi_calc:.2f} (BC {vl_bc_ipi:.2f} x {aliq_ipi:.2f}%) "
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
        pis_calc = vl_bc_pis * aliq_pis / 100
        diff = abs(pis_calc - vl_pis)
        if diff > TOLERANCE:
            # Verificar arredondamento de aliquota
            taxa_ef = vl_pis / vl_bc_pis * 100
            if round(taxa_ef, 2) != round(aliq_pis, 2):
                errors.append(make_error(
                    record, "VL_PIS", "CALCULO_DIVERGENTE",
                    f"PIS: calculado={pis_calc:.2f} (BC {vl_bc_pis:.2f} x {aliq_pis:.2f}%) vs declarado={vl_pis:.2f}.",
                    field_no=25,
                    expected_value=f"{pis_calc:.2f}",
                    value=f"{vl_pis:.2f}",
                ))

    # COFINS: campo 32=VL_BC_COFINS, 33=ALIQ_COFINS(%), 36=VL_COFINS
    vl_bc_cofins = _float_opt(get_field(record, 31))
    aliq_cofins = _float_opt(get_field(record, 32))
    vl_cofins = _float_opt(get_field(record, 35))

    if (vl_bc_cofins is not None and aliq_cofins is not None and vl_cofins is not None
            and vl_bc_cofins > 0 and aliq_cofins > 0):
        cofins_calc = vl_bc_cofins * aliq_cofins / 100
        diff = abs(cofins_calc - vl_cofins)
        if diff > TOLERANCE:
            # Verificar arredondamento de aliquota
            taxa_ef = vl_cofins / vl_bc_cofins * 100
            if round(taxa_ef, 2) == round(aliq_cofins, 2):
                return errors  # Coerente com arredondamento

            errors.append(make_error(
                record, "VL_COFINS", "CALCULO_DIVERGENTE",
                f"COFINS: calculado={cofins_calc:.2f} (BC {vl_bc_cofins:.2f} x "
                f"{aliq_cofins:.2f}%) vs declarado={vl_cofins:.2f}.",
                field_no=28,
                expected_value=f"{cofins_calc:.2f}",
                value=f"{vl_cofins:.2f}",
            ))

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
