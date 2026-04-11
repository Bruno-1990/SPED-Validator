"""Validador de encadeamento fiscal completo (Fase 4).

Implementa as trilhas de fechamento que estavam faltando:
- Trilha 1: C100 → C170 (documento → itens)
- Trilha 5: ICMS-ST na apuracao (E210 vs C170)
- Trilha 6: IPI na apuracao (E510 vs C170)

As trilhas 2-4 (C190→E110→E111→E116) ja estao em apuracao_validator.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    F_C100_VL_DOC,
    F_C100_VL_ICMS_ST,
    F_C100_VL_IPI,
    F_C170_CFOP,
    F_C170_VL_ICMS,
    F_C170_VL_ICMS_ST,
    F_C170_VL_ITEM,
    F_C170_VL_IPI,
    get_field,
    make_error,
    to_float,
)
from .tolerance import tolerancia_proporcional

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext


def validate_encadeamento(
    records: list[SpedRecord],
    context: "ValidationContext | None" = None,
) -> list[ValidationError]:
    """Valida encadeamento fiscal: C100→C170, ST na apuracao, IPI na apuracao."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    errors.extend(_check_c100_c170(groups))
    errors.extend(_check_st_apuracao(groups))
    errors.extend(_check_ipi_apuracao(groups, context))

    return errors


# ──────────────────────────────────────────────
# Trilha 1: C100 → C170 (Documento → Itens)
# ──────────────────────────────────────────────

def _get_c170_for_c100(
    c100_rec: SpedRecord, all_records: list[SpedRecord], groups: dict
) -> list[SpedRecord]:
    """Retorna C170s que pertencem a um C100 (por posicao no arquivo)."""
    c100_line = c100_rec.line_number
    c100_list = groups.get("C100", [])
    # Encontrar proximo C100/C190/C990 apos este C100
    next_boundary = float("inf")
    for r in c100_list:
        if r.line_number > c100_line:
            next_boundary = r.line_number
            break
    for r in groups.get("C190", []):
        if c100_line < r.line_number < next_boundary:
            next_boundary = r.line_number
            break

    return [
        r for r in groups.get("C170", [])
        if c100_line < r.line_number < next_boundary
    ]


def _check_c100_c170(groups: dict) -> list[ValidationError]:
    """Trilha 1: Soma C170 deve fechar com C100."""
    errors: list[ValidationError] = []
    c100_list = groups.get("C100", [])
    c170_all = groups.get("C170", [])

    if not c100_list:
        return errors

    # Indexar C170 por posicao para eficiencia
    c170_by_pos: dict[int, list[SpedRecord]] = {}
    for i, c100 in enumerate(c100_list):
        start = c100.line_number
        end = c100_list[i + 1].line_number if i + 1 < len(c100_list) else float("inf")
        c170_for_doc = [r for r in c170_all if start < r.line_number < end]
        c170_by_pos[c100.line_number] = c170_for_doc

    for c100 in c100_list:
        cod_sit = get_field(c100, "COD_SIT")
        # Pular documentos cancelados/denegados (COD_SIT != 00)
        if cod_sit and cod_sit != "00":
            continue

        c170s = c170_by_pos.get(c100.line_number, [])

        # C100_SEM_ITENS: C100 ativo sem nenhum C170
        vl_doc = to_float(get_field(c100, F_C100_VL_DOC))
        if not c170s and vl_doc > 0:
            errors.append(make_error(
                c100, "VL_DOC", "C100_SEM_ITENS",
                f"C100 (VL_DOC=R${vl_doc:.2f}) sem nenhum C170 vinculado. "
                f"Documento fiscal sem itens detalhados.",
                value=f"{vl_doc:.2f}",
            ))
            continue

        if not c170s:
            continue

        # Soma dos itens
        soma_vl_item = sum(to_float(get_field(r, F_C170_VL_ITEM)) for r in c170s)
        soma_vl_icms = sum(to_float(get_field(r, F_C170_VL_ICMS)) for r in c170s)
        soma_vl_ipi = sum(to_float(get_field(r, F_C170_VL_IPI)) for r in c170s)
        soma_vl_icms_st = sum(to_float(get_field(r, F_C170_VL_ICMS_ST)) for r in c170s)

        # C100_ICMS_INCONSISTENTE: VL_ICMS do C100 vs soma C170
        vl_icms_c100 = to_float(get_field(c100, "VL_ICMS"))
        if vl_icms_c100 > 0 or soma_vl_icms > 0:
            diff = abs(vl_icms_c100 - soma_vl_icms)
            tol = tolerancia_proporcional(max(vl_icms_c100, soma_vl_icms))
            if diff > tol:
                errors.append(make_error(
                    c100, "VL_ICMS", "C100_ICMS_INCONSISTENTE",
                    f"VL_ICMS do C100 (R${vl_icms_c100:.2f}) diverge da soma "
                    f"dos C170 (R${soma_vl_icms:.2f}). Diferenca: R${diff:.2f}.",
                    value=f"{vl_icms_c100:.2f}",
                    expected_value=f"{soma_vl_icms:.2f}",
                ))

        # C100_IPI_INCONSISTENTE: VL_IPI do C100 vs soma C170
        vl_ipi_c100 = to_float(get_field(c100, F_C100_VL_IPI))
        if vl_ipi_c100 > 0 or soma_vl_ipi > 0:
            diff = abs(vl_ipi_c100 - soma_vl_ipi)
            tol = tolerancia_proporcional(max(vl_ipi_c100, soma_vl_ipi))
            if diff > tol:
                errors.append(make_error(
                    c100, "VL_IPI", "C100_IPI_INCONSISTENTE",
                    f"VL_IPI do C100 (R${vl_ipi_c100:.2f}) diverge da soma "
                    f"dos C170 (R${soma_vl_ipi:.2f}). Diferenca: R${diff:.2f}.",
                    value=f"{vl_ipi_c100:.2f}",
                    expected_value=f"{soma_vl_ipi:.2f}",
                ))

        # C100_ICMS_ST_INCONSISTENTE: VL_ICMS_ST do C100 vs soma C170
        vl_st_c100 = to_float(get_field(c100, F_C100_VL_ICMS_ST))
        if vl_st_c100 > 0 or soma_vl_icms_st > 0:
            diff = abs(vl_st_c100 - soma_vl_icms_st)
            tol = tolerancia_proporcional(max(vl_st_c100, soma_vl_icms_st))
            if diff > tol:
                errors.append(make_error(
                    c100, "VL_ICMS_ST", "C100_ICMS_ST_INCONSISTENTE",
                    f"VL_ICMS_ST do C100 (R${vl_st_c100:.2f}) diverge da soma "
                    f"dos C170 (R${soma_vl_icms_st:.2f}). Diferenca: R${diff:.2f}.",
                    value=f"{vl_st_c100:.2f}",
                    expected_value=f"{soma_vl_icms_st:.2f}",
                ))

    # C170_ORFAO: C170 sem C100 pai
    if c170_all and not c100_list:
        for r in c170_all[:5]:  # Limitar a 5 erros
            errors.append(make_error(
                r, "REG", "C170_ORFAO",
                "Registro C170 sem C100 pai no arquivo.",
            ))

    return errors


# ──────────────────────────────────────────────
# Trilha 5: ICMS-ST na Apuracao (E210 vs C170)
# ──────────────────────────────────────────────

def _check_st_apuracao(groups: dict) -> list[ValidationError]:
    """E210.VL_ICMS_RECOL_ST ≈ SUM(C170.VL_ICMS_ST) saidas."""
    errors: list[ValidationError] = []
    e210_list = groups.get("E210", [])
    if not e210_list:
        return errors

    # Somar ICMS_ST de saidas (CFOP 5xxx/6xxx/7xxx)
    soma_st_saida = 0.0
    for r in groups.get("C170", []):
        cfop = get_field(r, F_C170_CFOP)
        vl_st = to_float(get_field(r, F_C170_VL_ICMS_ST))
        if cfop and cfop[0] in ("5", "6", "7") and vl_st > 0:
            soma_st_saida += vl_st

    for e210 in e210_list:
        # Campo VL_ICMS_RECOL_ST (posicao varia, buscar por nome)
        vl_recol = to_float(get_field(e210, "VL_ICMS_RECOL_ST"))
        if vl_recol <= 0 and soma_st_saida <= 0:
            continue

        diff = abs(vl_recol - soma_st_saida)
        tol = tolerancia_proporcional(max(vl_recol, soma_st_saida))
        if diff > tol:
            errors.append(make_error(
                e210, "VL_ICMS_RECOL_ST", "ST_APURACAO_DIVERGENTE",
                f"E210.VL_ICMS_RECOL_ST (R${vl_recol:.2f}) diverge da soma "
                f"de ICMS-ST de saidas nos C170 (R${soma_st_saida:.2f}). "
                f"Diferenca: R${diff:.2f}.",
                value=f"{vl_recol:.2f}",
                expected_value=f"{soma_st_saida:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Trilha 6: IPI na Apuracao (E510 vs C170)
# ──────────────────────────────────────────────

def _check_ipi_apuracao(
    groups: dict, context: "ValidationContext | None" = None,
) -> list[ValidationError]:
    """IPI na apuracao: E510 vs SUM(C170.VL_IPI) + reflexo na BC ICMS."""
    errors: list[ValidationError] = []

    # Apenas para industriais (IND_ATIV=0)
    if context and getattr(context, "ind_ativ", "1") != "0":
        return errors

    e510_list = groups.get("E510", [])

    # IPI_REFLEXO_BC_AUSENTE: BC_ICMS deve incluir VL_IPI se industrial
    for r in groups.get("C170", []):
        vl_ipi = to_float(get_field(r, F_C170_VL_IPI))
        vl_bc_icms = to_float(get_field(r, "VL_BC_ICMS"))
        vl_item = to_float(get_field(r, F_C170_VL_ITEM))
        cst_ipi = get_field(r, "CST_IPI")

        # Se IPI tributado (CST 00, 49, 50, 99) e VL_IPI > 0
        if vl_ipi > 0 and cst_ipi in ("00", "49", "50", "99"):
            # BC_ICMS deveria incluir IPI para compras industriais
            # Se VL_BC_ICMS < VL_ITEM (sem IPI incluso), pode ser erro
            if vl_bc_icms > 0 and vl_bc_icms < (vl_item + vl_ipi * 0.5):
                cfop = get_field(r, F_C170_CFOP)
                # Apenas entradas (CFOP 1xxx/2xxx/3xxx)
                if cfop and cfop[0] in ("1", "2", "3"):
                    errors.append(make_error(
                        r, "VL_BC_ICMS", "IPI_REFLEXO_BC_AUSENTE",
                        f"BC_ICMS (R${vl_bc_icms:.2f}) parece nao incluir "
                        f"VL_IPI (R${vl_ipi:.2f}) em operacao de entrada "
                        f"para empresa industrial. BC esperada >= VL_ITEM + VL_IPI.",
                        value=f"{vl_bc_icms:.2f}",
                    ))

    # IPI_CST_MONETARIO_ZERADO: CST IPI tributado com VL_IPI = 0
    for r in groups.get("C170", []):
        cst_ipi = get_field(r, "CST_IPI")
        vl_ipi = to_float(get_field(r, F_C170_VL_IPI))
        if cst_ipi in ("00", "49", "50") and vl_ipi == 0:
            vl_item = to_float(get_field(r, F_C170_VL_ITEM))
            if vl_item > 0:
                errors.append(make_error(
                    r, "VL_IPI", "IPI_CST_MONETARIO_ZERADO",
                    f"CST IPI {cst_ipi} indica tributacao mas VL_IPI esta zerado "
                    f"em item com VL_ITEM=R${vl_item:.2f}.",
                    value="0.00",
                ))

    return errors
