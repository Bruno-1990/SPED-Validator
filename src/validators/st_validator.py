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
            # ST_MVA_NAO_MAPEADO: NCM sem MVA na tabela de referencia
            if is_st_debito and vl_bc_st > 0:
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_MVA_NAO_MAPEADO",
                    f"NCM {ncm} sem MVA mapeado na tabela de referencia. "
                    f"Recalculo de ST nao executado para este item. "
                    f"Atualize mva_por_ncm_uf.yaml.",
                    field_no=16, value=f"{vl_bc_st:.2f}",
                ))
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

        # BUG-002 fix: Formula completa ICMS-ST com MVA em 4 etapas
        if is_st_debito and vl_item > 0:
            aliq_interna = ref.get_aliquota_interna(uf_contrib)
            if aliq_interna is None:
                continue

            # Etapa 1: Base ST com MVA original
            # BC_ST = (VL_ITEM + VL_FRT + VL_SEG + VL_OUT_DA - VL_DESC) * (1 + MVA/100)
            vl_frt = to_float(get_field(rec, "VL_FRT")) if get_field(rec, "VL_FRT") else 0.0
            vl_seg = to_float(get_field(rec, "VL_SEG")) if get_field(rec, "VL_SEG") else 0.0
            vl_out_da = to_float(get_field(rec, "VL_OUT_DA")) if get_field(rec, "VL_OUT_DA") else 0.0
            vl_desc = to_float(get_field(rec, "VL_DESC")) if get_field(rec, "VL_DESC") else 0.0
            base_operacao = vl_item + vl_frt + vl_seg + vl_out_da - vl_desc
            if base_operacao <= 0:
                continue
            bc_st_esperada = base_operacao * (1 + mva / 100)

            # Etapa 2: Ajuste MVA para remetente Simples Nacional
            # Se emitente e SN (CRT=1), aplicar MVA ajustado
            cod_part = get_field(rec, "COD_PART") if get_field(rec, "COD_PART") else ""
            participante = context.participantes.get(cod_part, {})
            # Heuristica: se UF do participante != UF contribuinte, verificar aliq interestadual
            uf_part = participante.get("uf", "")
            if uf_part and uf_part != uf_contrib:
                # Operacao interestadual — aplicar aliquota interestadual
                aliq_inter = 12.0  # Default; 4% para importados, 7% para S/SE→N/NE/CO
                bc_st_esperada = base_operacao * (1 + mva / 100)
                # Ajuste para SN nao implementado aqui (requer CRT do emitente — Fase 2)

            # Etapa 3: ICMS-ST esperado
            vl_icms_proprio = vl_icms if vl_icms > 0 else (vl_bc_icms * aliq_interna / 100 if vl_bc_icms > 0 else 0)
            icms_st_esperado = (bc_st_esperada * aliq_interna / 100) - vl_icms_proprio
            if icms_st_esperado < 0:
                icms_st_esperado = 0.0

            # Etapa 4: Divergencia com tolerancia proporcional
            from .tolerance import tolerancia_proporcional
            tol_bc = tolerancia_proporcional(bc_st_esperada)
            tol_icms = tolerancia_proporcional(icms_st_esperado)

            # ST_MVA_AUSENTE: Item com ST mas BC_ST zerada
            if vl_bc_st == 0 and bc_st_esperada > 0:
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_MVA_AUSENTE",
                    f"Produto com NCM {ncm} sujeito a ST (MVA {mva:.1f}%) "
                    f"mas BC_ICMS_ST esta zerada. BC esperada: R${bc_st_esperada:.2f}.",
                    field_no=16, value="0",
                    expected_value=f"{bc_st_esperada:.2f}",
                ))
            # ST_MVA_DIVERGENTE: BC_ST diverge do esperado
            elif vl_bc_st > 0 and abs(vl_bc_st - bc_st_esperada) > tol_bc:
                errors.append(make_error(
                    rec, "VL_BC_ICMS_ST", "ST_MVA_DIVERGENTE",
                    f"BC_ICMS_ST={vl_bc_st:.2f} diverge do esperado R${bc_st_esperada:.2f} "
                    f"(MVA {mva:.1f}%, base operacao R${base_operacao:.2f}).",
                    field_no=16, value=f"{vl_bc_st:.2f}",
                    expected_value=f"{bc_st_esperada:.2f}",
                ))

            # ST_ALIQ_INCORRETA: Aliquota ST diverge da tabela
            if aliq_st > 0 and abs(aliq_st - aliq_interna) > 0.01:
                errors.append(make_error(
                    rec, "ALIQ_ST", "ST_ALIQ_INCORRETA",
                    f"Aliquota ST {aliq_st:.1f}% diverge da aliquota interna {aliq_interna:.1f}% "
                    f"da UF {uf_contrib} para NCM {ncm}.",
                    field_no=17, value=f"{aliq_st:.1f}",
                    expected_value=f"{aliq_interna:.1f}",
                ))

            # VL_ICMS_ST diverge do recalculo
            if vl_icms_st > 0 and abs(vl_icms_st - icms_st_esperado) > tol_icms:
                errors.append(make_error(
                    rec, "VL_ICMS_ST", "ST_MVA_DIVERGENTE",
                    f"VL_ICMS_ST={vl_icms_st:.2f} diverge do esperado R${icms_st_esperado:.2f}. "
                    f"Calculo: (BC_ST R${bc_st_esperada:.2f} x {aliq_interna:.1f}%) "
                    f"- ICMS proprio R${vl_icms_proprio:.2f}.",
                    field_no=18, value=f"{vl_icms_st:.2f}",
                    expected_value=f"{icms_st_esperado:.2f}",
                ))

    return errors


def _sum_e210(e210_records: list[SpedRecord]) -> float:
    """Soma VL_RETENCAO_ST de todos os registros E210."""
    total = 0.0
    for rec in e210_records:
        vl = to_float(get_field(rec, "VL_RETENCAO_ST"))
        if vl > 0:
            total += vl
    return total
