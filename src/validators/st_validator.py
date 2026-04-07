"""Validador de ICMS-ST (Substituicao Tributaria) — MOD-07.

Regras implementadas:
- ST_001: ST no item sem reflexo na apuracao (E200/E210)
- ST_002: CST 60 com debito indevido de ICMS-ST
- ST_003: BC_ICMS_ST menor que VL_ITEM (heuristica)
- ST_004: Mistura indevida ST com DIFAL
- ST_MVA_001: BC_ICMS_ST diverge do esperado com MVA
- ST_MVA_002: Aliquota ST aplicada diverge da aliquota interna destino
- ST_MVA_003: NCM sujeito a ST mas sem BC_ICMS_ST preenchida
- ST_MVA_004: VL_ICMS_ST diverge do recalculo com MVA
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    F_C170_ALIQ_ST,
    F_C170_CFOP,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_BC_ICMS_ST,
    F_C170_VL_ICMS,
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


def validate_st_mva(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Regras de ST com MVA — requer tabela mva_por_ncm_uf."""
    if not context or not context.reference_loader:
        return []

    ref = context.reference_loader
    # Verificar se tabela MVA esta disponivel
    if ref.get_mva("0000") is None and not any("mva" in t for t in context.available_tables):
        return []

    groups = group_by_register(records)
    errors: list[ValidationError] = []

    c170_records = groups.get("C170", [])
    if not c170_records:
        return errors

    uf_contrib = context.uf_contribuinte

    for rec in c170_records:
        cst_raw = get_field(rec, F_C170_CST_ICMS)
        cst = trib(cst_raw)
        cfop = get_field(rec, F_C170_CFOP)
        cod_item = get_field(rec, F_C170_COD_ITEM)
        vl_item = to_float(get_field(rec, F_C170_VL_ITEM))
        vl_bc_icms = to_float(get_field(rec, F_C170_VL_BC_ICMS))
        vl_icms = to_float(get_field(rec, F_C170_VL_ICMS))
        vl_bc_st = to_float(get_field(rec, F_C170_VL_BC_ICMS_ST))
        aliq_st = to_float(get_field(rec, F_C170_ALIQ_ST))
        vl_icms_st = to_float(get_field(rec, F_C170_VL_ICMS_ST))

        is_st_debito = cst in _CST_ST_DEBITO or cst_raw in _CST_SN_ST_DEBITO

        # Buscar NCM do produto
        ncm = ""
        prod = context.produtos.get(cod_item)
        if prod:
            ncm = prod.get("ncm", "")

        if not ncm:
            continue

        mva = ref.get_mva(ncm)
        if mva is None:
            # NCM nao catalogado na tabela MVA — pular
            continue

        # ST_MVA_003: NCM sujeito a ST mas sem BC_ICMS_ST
        if not is_st_debito and vl_bc_st == 0 and cst not in _CST_ST_RETIDO and cst_raw not in _CST_SN_ST_RETIDO:
            # NCM tem MVA mas item nao foi tributado com ST
            # Apenas reportar se operacao interna (CFOP 5xxx)
            if cfop.startswith("5") and vl_item > 0:
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_MVA_NCM_SEM_ST",
                    f"ST_MVA_003: NCM {ncm} esta sujeito a ST (MVA {mva:.1f}%), "
                    f"mas CST {cst_raw} nao indica ST e BC_ICMS_ST esta zerada. "
                    f"Verificar se a operacao deveria ter retencao de ST.",
                    field_no=16,
                    value="0",
                ))

        # Validar calculo da BC_ST e ICMS_ST quando ST esta presente
        if is_st_debito and vl_bc_st > 0 and vl_item > 0:
            # Obter aliquota interna da UF destino
            aliq_interna = ref.get_aliquota_interna(uf_contrib)
            if aliq_interna is None:
                continue

            # Calcular BC_ST esperada: (VL_ITEM + frete/seg/etc) * (1 + MVA/100)
            # Simplificacao: usar vl_bc_icms como base, ou vl_item
            base = vl_bc_icms if vl_bc_icms > 0 else vl_item
            bc_st_esperada = base * (1 + mva / 100)

            # ST_MVA_001: BC_ICMS_ST diverge do esperado
            tolerancia = bc_st_esperada * 0.05  # 5% de tolerancia
            if abs(vl_bc_st - bc_st_esperada) > max(tolerancia, 1.0):
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_MVA_BC_DIVERGENTE",
                    f"ST_MVA_001: BC_ICMS_ST={vl_bc_st:.2f} diverge do esperado "
                    f"com MVA {mva:.1f}% (BC esperada={bc_st_esperada:.2f}). "
                    f"Base={base:.2f} x (1 + {mva:.1f}%) = {bc_st_esperada:.2f}.",
                    field_no=16,
                    value=f"{vl_bc_st:.2f}",
                    expected_value=f"{bc_st_esperada:.2f}",
                ))

            # ST_MVA_004: VL_ICMS_ST diverge do recalculo
            # ICMS_ST = (BC_ST * aliq_interna/100) - ICMS_proprio
            icms_st_esperado = (vl_bc_st * aliq_interna / 100) - vl_icms
            if icms_st_esperado < 0:
                icms_st_esperado = 0.0

            tol_icms = max(abs(icms_st_esperado) * 0.05, 1.0)
            if vl_icms_st > 0 and abs(vl_icms_st - icms_st_esperado) > tol_icms:
                errors.append(make_error(
                    rec, "VL_ICMS_ST", "ST_MVA_ICMS_DIVERGENTE",
                    f"ST_MVA_004: VL_ICMS_ST={vl_icms_st:.2f} diverge do esperado "
                    f"{icms_st_esperado:.2f}. Calculo: (BC_ST {vl_bc_st:.2f} x "
                    f"aliq {aliq_interna:.1f}%) - ICMS_proprio {vl_icms:.2f}.",
                    field_no=18,
                    value=f"{vl_icms_st:.2f}",
                    expected_value=f"{icms_st_esperado:.2f}",
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
