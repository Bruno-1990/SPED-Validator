"""Validador de devolucoes (DEV_001 a DEV_003).

Detecta devolucoes sem espelhamento da NF original, sem tratamento
do DIFAL e com aliquota divergente da historica.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    ALIQ_INTERESTADUAIS,
    CFOP_DEVOLUCAO,
    F_C100_COD_PART,
    F_C100_IND_OPER,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    get_field,
    make_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext

# CFOPs de devolucao de entrada (compra devolvida pelo contribuinte)
_CFOP_DEV_SAIDA = {
    "5201", "5202", "5208", "5209", "5210", "5410", "5411",
    "5503", "5504",
    "6201", "6202", "6208", "6209", "6210", "6410", "6411",
    "6503", "6504",
}

# CFOPs de devolucao de saida (venda devolvida ao contribuinte)
_CFOP_DEV_ENTRADA = {
    "1201", "1202", "1203", "1204", "1208", "1209", "1410", "1411",
    "1503", "1504",
    "2201", "2202", "2203", "2204", "2208", "2209", "2410", "2411",
    "2503", "2504",
}

# CFOPs de devolucao interestadual (inicio 2xxx ou 6xxx)
_CFOP_DEV_INTERESTADUAL = {
    c for c in CFOP_DEVOLUCAO if c.startswith("2") or c.startswith("6")
}


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_devolucao(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Valida regras de devolucao (DEV_001 a DEV_003)."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    errors.extend(_check_devolucao_sem_espelhamento(groups))
    errors.extend(_check_devolucao_sem_difal(groups))
    errors.extend(_check_devolucao_aliq_historica(groups))

    return errors


# ──────────────────────────────────────────────
# Contexto: mapear C100 -> C170 filhos
# ──────────────────────────────────────────────

def _build_c100_c170_map(
    groups: dict[str, list[SpedRecord]],
) -> dict[int, SpedRecord]:
    """Mapa line_number do C170 -> C100 pai."""
    parent_map: dict[int, SpedRecord] = {}
    current_c100: SpedRecord | None = None
    # Registros ja vem em ordem de linha
    all_recs = sorted(
        groups.get("C100", []) + groups.get("C170", []),
        key=lambda r: r.line_number,
    )
    for rec in all_recs:
        if rec.register == "C100":
            current_c100 = rec
        elif rec.register == "C170" and current_c100 is not None:
            parent_map[rec.line_number] = current_c100
    return parent_map


# ──────────────────────────────────────────────
# DEV_001: Devolucao sem espelhamento da NF original
# ──────────────────────────────────────────────

def _check_devolucao_sem_espelhamento(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """DEV_001: C100 de devolucao sem C100 correspondente com mesmo COD_PART.

    CFOPs de devolucao devem espelhar uma operacao original com o mesmo
    participante. Se nao ha C100 correspondente (mesmo COD_PART, operacao
    inversa), a devolucao pode estar incorreta.
    """
    errors: list[ValidationError] = []

    c100_list = groups.get("C100", [])
    if not c100_list:
        return errors

    parent_map = _build_c100_c170_map(groups)

    # Agrupar C100 por (COD_PART, IND_OPER)
    c100_by_part_oper: dict[tuple[str, str], list[SpedRecord]] = defaultdict(list)
    for rec in c100_list:
        cod_part = get_field(rec, F_C100_COD_PART)
        ind_oper = get_field(rec, F_C100_IND_OPER)
        if cod_part:
            c100_by_part_oper[(cod_part, ind_oper)].append(rec)

    # Coletar itens (COD_ITEM) por C100 pai
    c170_items_by_c100: dict[int, set[str]] = defaultdict(set)
    for rec in groups.get("C170", []):
        cod_item = get_field(rec, F_C170_COD_ITEM)
        c100_pai = parent_map.get(rec.line_number)
        if c100_pai and cod_item:
            c170_items_by_c100[c100_pai.line_number].add(cod_item)

    # Verificar cada C170 com CFOP de devolucao
    checked_c100: set[int] = set()
    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        if cfop not in CFOP_DEVOLUCAO:
            continue

        c100_pai = parent_map.get(rec.line_number)
        if not c100_pai or c100_pai.line_number in checked_c100:
            continue
        checked_c100.add(c100_pai.line_number)

        cod_part = get_field(c100_pai, F_C100_COD_PART)
        ind_oper = get_field(c100_pai, F_C100_IND_OPER)
        if not cod_part:
            continue

        # Operacao inversa: se devolucao e saida (1), original seria entrada (0)
        oper_inversa = "0" if ind_oper == "1" else "1"

        # Procurar C100 com mesmo COD_PART e operacao inversa
        correspondentes = c100_by_part_oper.get((cod_part, oper_inversa), [])

        if not correspondentes:
            errors.append(make_error(
                c100_pai, "COD_PART", "DEVOLUCAO_SEM_ESPELHAMENTO",
                (
                    f"Devolucao (CFOP {cfop}) para participante '{cod_part}' "
                    f"sem NF de operacao original correspondente no periodo. "
                    f"Verifique se a NF original existe e se o COD_PART "
                    f"esta correto."
                ),
                value=f"CFOP={cfop} COD_PART={cod_part}",
            ))

    return errors


# ──────────────────────────────────────────────
# DEV_002: Devolucao sem tratamento do DIFAL
# ──────────────────────────────────────────────

def _check_devolucao_sem_difal(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """DEV_002: Devolucao interestadual sem reversao no E300.

    Se ha devoluçao interestadual (CFOP 2xxx/6xxx de devolucao) e
    E300 esta presente (DIFAL ativo), deve haver reversao do DIFAL.
    Se nao ha E300 mas ha operacoes interestaduais de devolucao, alerta.
    """
    errors: list[ValidationError] = []

    e300_recs = groups.get("E300", [])
    parent_map = _build_c100_c170_map(groups)

    # Coletar C170 com CFOP de devolucao interestadual
    dev_interestaduais: list[SpedRecord] = []
    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        if cfop in _CFOP_DEV_INTERESTADUAL:
            dev_interestaduais.append(rec)

    if not dev_interestaduais:
        return errors

    # Se ha E300 (DIFAL ativo) mas sem registros, as devoluçoes
    # interestaduais podem estar sem reversao
    if not e300_recs:
        # Sem E300: se ha devolucoes interestaduais, pode faltar DIFAL
        checked_c100: set[int] = set()
        for rec in dev_interestaduais:
            c100_pai = parent_map.get(rec.line_number)
            if not c100_pai or c100_pai.line_number in checked_c100:
                continue
            checked_c100.add(c100_pai.line_number)

            cfop = get_field(rec, F_C170_CFOP)
            errors.append(make_error(
                rec, "CFOP", "DEVOLUCAO_SEM_DIFAL",
                (
                    f"Devolucao interestadual (CFOP {cfop}) sem bloco E300 "
                    f"(DIFAL) no arquivo. Se a operacao original tinha "
                    f"DIFAL, a devolucao deve reverter o diferencial "
                    f"de aliquota."
                ),
                value=f"CFOP={cfop}",
            ))

    return errors


# ──────────────────────────────────────────────
# DEV_003: Devolucao com aliquota atual vs. historica
# ──────────────────────────────────────────────

def _check_devolucao_aliq_historica(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """DEV_003: Devolucao com aliquota diferente das faixas interestaduais.

    Se a devolucao e interestadual, a aliquota deve ser uma das
    interestaduais validas (4, 7 ou 12%). Uma aliquota diferente
    pode indicar uso da aliquota atual em vez da historica.
    """
    errors: list[ValidationError] = []

    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        if cfop not in _CFOP_DEV_INTERESTADUAL:
            continue

        aliq = to_float(get_field(rec, F_C170_ALIQ_ICMS))
        if aliq <= 0:
            continue

        cst = get_field(rec, F_C170_CST_ICMS)
        t = trib(cst) if cst else ""
        # Apenas CSTs tributados
        if t not in {"00", "10", "20", "70", "90"}:
            continue

        # Aliquota deve ser interestadual (4, 7 ou 12)
        if aliq not in ALIQ_INTERESTADUAIS:
            errors.append(make_error(
                rec, "ALIQ_ICMS", "DEVOLUCAO_ALIQ_DIVERGENTE",
                (
                    f"Devolucao interestadual (CFOP {cfop}) com "
                    f"ALIQ_ICMS={aliq:.2f}%, que nao e uma aliquota "
                    f"interestadual valida (4%, 7% ou 12%). Verifique "
                    f"se a aliquota corresponde a da NF original e nao "
                    f"a uma aliquota vigente diferente."
                ),
                value=f"ALIQ={aliq:.2f}% CFOP={cfop}",
            ))

    return errors
