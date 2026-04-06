"""Validador de ICMS-ST (Substituicao Tributaria) — MOD-07.

Regras implementadas (Fase 3A — sem tabelas externas):
- ST_001: ST no item sem reflexo na apuracao (E200/E210)
- ST_002: CST 60 com debito indevido de ICMS-ST
- ST_003: BC_ICMS_ST menor que VL_ITEM (heuristica)
- ST_004: Mistura indevida ST com DIFAL
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS_ST,
    F_C170_VL_ICMS_ST,
    F_C170_VL_ITEM,
    get_field,
    make_error,
    to_float,
    trib,
)

# CSTs que indicam ST com debito (substituto tributario)
_CST_ST_DEBITO = {"10", "30", "70"}

# CSTs de ST retida anteriormente (substituido)
_CST_ST_RETIDO = {"60"}

# CSTs Simples Nacional com ST
_CST_SN_ST_DEBITO = {"201", "202", "203"}
_CST_SN_ST_RETIDO = {"500"}



def validate_st(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa todas as regras de ICMS-ST."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    c170_records = groups.get("C170", [])
    if not c170_records:
        return errors

    # Pre-computar presenca de E200/E210 e seus totais
    has_e200 = len(groups.get("E200", [])) > 0
    e210_vl_st = _sum_e210(groups.get("E210", []))

    # Pre-computar presenca de E300
    has_e300 = len(groups.get("E300", [])) > 0

    for rec in c170_records:
        cst_raw = get_field(rec, F_C170_CST_ICMS)
        cst = trib(cst_raw)  # ultimos 2 digitos (ex: "201" -> "01")
        cfop = get_field(rec, F_C170_CFOP)
        vl_item = to_float(get_field(rec, F_C170_VL_ITEM))
        vl_bc_st = to_float(get_field(rec, F_C170_VL_BC_ICMS_ST))
        vl_icms_st = to_float(get_field(rec, F_C170_VL_ICMS_ST))

        is_st_debito = cst in _CST_ST_DEBITO or cst_raw in _CST_SN_ST_DEBITO
        is_st_retido = cst in _CST_ST_RETIDO or cst_raw in _CST_SN_ST_RETIDO

        # ST_001 — ST no item sem reflexo na apuracao
        if is_st_debito and vl_icms_st > 0 and (not has_e200 or e210_vl_st == 0):
                errors.append(make_error(
                    rec, "VL_ICMS_ST", "ST_APURACAO_INCONSISTENTE",
                    f"ST_001: CST {cst_raw} com VL_ICMS_ST={vl_icms_st:.2f} "
                    f"mas E200/E210 ausente ou zerado. "
                    f"A ST cobrada no item nao esta refletida na apuracao.",
                    field_no=18,
                    value=f"{vl_icms_st:.2f}",
                ))

        # ST_002 — CST 60 com debito indevido
        if is_st_retido and vl_icms_st > 0:
            errors.append(make_error(
                rec, "VL_ICMS_ST", "ST_CST60_DEBITO_INDEVIDO",
                f"ST_002: CST {cst_raw} indica ST retida anteriormente, "
                f"mas VL_ICMS_ST={vl_icms_st:.2f} (deveria ser zero). "
                f"O substituido nao gera novo debito de ST.",
                field_no=18,
                value=f"{vl_icms_st:.2f}",
                expected_value="0.00",
            ))

        # ST_003 — BC_ICMS_ST menor que VL_ITEM (heuristica)
        if is_st_debito and vl_bc_st > 0 and vl_item > 0 and vl_bc_st < vl_item:
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_BC_MENOR_QUE_ITEM",
                    f"ST_003: BC_ICMS_ST={vl_bc_st:.2f} < VL_ITEM={vl_item:.2f} "
                    f"para CST {cst_raw}. A base ST normalmente inclui MVA e "
                    f"deve ser maior que o valor do item. Verificar MVA/pauta.",
                    field_no=16,
                    value=f"{vl_bc_st:.2f}",
                ))

        # ST_004 — Mistura indevida ST com DIFAL
        if (is_st_debito
                and cfop.startswith("6") and has_e300):
            errors.append(make_error(
                rec, "CST_ICMS", "ST_MISTURA_DIFAL",
                f"ST_004: CST {cst_raw} (ST) + CFOP {cfop} (interestadual) "
                f"com E300 (DIFAL) preenchido simultaneamente. "
                f"ST e DIFAL sao regimes excludentes na mesma operacao.",
                field_no=10,
                value=cst_raw,
            ))

    return errors


def _sum_e210(e210_records: list[SpedRecord]) -> float:
    """Soma VL_ST dos registros E210."""
    total = 0.0
    for rec in e210_records:
        # E210: campo 1 = UF, campo 12 = VL_ICMS_RECOL_ST (posicao varia)
        # Simplificacao: verificar se ha qualquer valor > 0 nos campos numericos
        values = list(rec.fields.values())
        for val in values[2:15]:
            v = to_float(val.strip() if val else "")
            if v > 0:
                return v
    return total
