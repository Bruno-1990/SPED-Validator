"""Regras de parametrizacao: deteccao de erros sistematicos no ERP.

PARAM_001 — Erro sistematico por item (mesmo COD_ITEM, mesmo erro >80%)
PARAM_002 — Erro sistematico por UF destino (mesmo erro >80% por UF)
PARAM_003 — Erro sistematico iniciado em data especifica (janela deslizante)
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CFOP_VENDA,
    CST_ISENTO_NT,
    CST_TRIBUTADO,
    F_0150_COD_PART,
    F_0150_UF,
    F_C100_COD_PART,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_COD_ITEM,
    F_C170_CST_ICMS,
    F_C170_VL_BC_ICMS,
    F_C170_VL_ICMS,
    get_field,
    make_error,
    to_float,
    trib,
)

# Threshold para considerar erro sistematico
_THRESHOLD = 0.80
_MIN_OCORRENCIAS = 3


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_parametrizacao(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa regras de deteccao de erros sistematicos de parametrizacao."""
    groups = group_by_register(records)
    if not groups:
        return []

    errors: list[ValidationError] = []

    # Construir mapa de parentesco C170 -> C100 e participante -> UF
    parent_map, part_uf = _build_maps(groups)

    errors.extend(_check_param_001(groups))
    errors.extend(_check_param_002(groups, parent_map, part_uf))
    errors.extend(_check_param_003(groups, context))

    return errors


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _build_maps(
    groups: dict[str, list[SpedRecord]],
) -> tuple[dict[int, SpedRecord], dict[str, str]]:
    """Constroi mapa C170->C100 pai e COD_PART->UF."""
    part_uf: dict[str, str] = {}
    for r in groups.get("0150", []):
        cod = get_field(r, F_0150_COD_PART)
        uf = get_field(r, F_0150_UF)
        if cod and uf:
            part_uf[cod] = uf

    all_c_records: list[SpedRecord] = []
    for reg_type in ("C100", "C170"):
        all_c_records.extend(groups.get(reg_type, []))
    all_c_records.sort(key=lambda r: r.line_number)

    parent_map: dict[int, SpedRecord] = {}
    current_c100: SpedRecord | None = None
    for r in all_c_records:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            parent_map[r.line_number] = current_c100

    return parent_map, part_uf


def _classify_error(record: SpedRecord) -> str | None:
    """Classifica tipo de erro potencial de um C170 (CST x CFOP)."""
    cfop = get_field(record, F_C170_CFOP)
    cst = get_field(record, F_C170_CST_ICMS)
    if not cfop or not cst:
        return None

    t = trib(cst)
    vl_icms = to_float(get_field(record, F_C170_VL_ICMS))
    vl_bc = to_float(get_field(record, F_C170_VL_BC_ICMS))
    aliq = to_float(get_field(record, F_C170_ALIQ_ICMS))

    # Venda com CST isento/NT
    if cfop in CFOP_VENDA and t in CST_ISENTO_NT:
        return "VENDA_CST_ISENTO"

    # CST tributado sem BC ou sem aliquota
    if t in CST_TRIBUTADO and vl_bc == 0 and aliq == 0 and cfop in CFOP_VENDA:
        return "TRIBUTADO_SEM_BC"

    # CST tributado com ICMS zerado em venda
    if t in CST_TRIBUTADO and vl_icms == 0 and cfop in CFOP_VENDA:
        return "TRIBUTADO_ICMS_ZERO"

    return None


# ──────────────────────────────────────────────
# PARAM_001: Erro sistematico por item
# ──────────────────────────────────────────────

def _check_param_001(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """PARAM_001: mesmo COD_ITEM com mesmo tipo de erro em >80% das ocorrencias."""
    errors: list[ValidationError] = []

    # Agrupar C170 por COD_ITEM
    item_records: dict[str, list[SpedRecord]] = defaultdict(list)
    for r in groups.get("C170", []):
        cod = get_field(r, F_C170_COD_ITEM)
        if cod:
            item_records[cod].append(r)

    for cod_item, recs in item_records.items():
        if len(recs) < _MIN_OCORRENCIAS:
            continue

        # Contar erros por tipo
        error_counts: dict[str, int] = defaultdict(int)
        for r in recs:
            err_type = _classify_error(r)
            if err_type:
                error_counts[err_type] += 1

        for err_type, count in error_counts.items():
            ratio = count / len(recs)
            if ratio >= _THRESHOLD and count >= _MIN_OCORRENCIAS:
                sample = recs[0]
                errors.append(make_error(
                    sample, "CST_ICMS", "PARAM_ERRO_SISTEMATICO_ITEM",
                    (
                        f"Possivel erro de parametrizacao no ERP para o produto "
                        f"{cod_item}: {err_type} em {count} de {len(recs)} "
                        f"ocorrencias ({ratio:.0%}). Revise o cadastro fiscal "
                        f"deste produto no sistema de origem."
                    ),
                    field_no=10,
                    value=f"COD_ITEM={cod_item} {err_type} {count}/{len(recs)}",
                ))

    return errors


# ──────────────────────────────────────────────
# PARAM_002: Erro sistematico por UF destino
# ──────────────────────────────────────────────

def _check_param_002(
    groups: dict[str, list[SpedRecord]],
    parent_map: dict[int, SpedRecord],
    part_uf: dict[str, str],
) -> list[ValidationError]:
    """PARAM_002: mesmo tipo de erro em >80% das operacoes para mesma UF destino."""
    errors: list[ValidationError] = []

    # Agrupar C170 por UF destino
    uf_records: dict[str, list[SpedRecord]] = defaultdict(list)
    for r in groups.get("C170", []):
        parent = parent_map.get(r.line_number)
        if not parent:
            continue
        cod_part = get_field(parent, F_C100_COD_PART)
        uf = part_uf.get(cod_part, "")
        if uf:
            uf_records[uf].append(r)

    for uf, recs in uf_records.items():
        if len(recs) < _MIN_OCORRENCIAS:
            continue

        error_counts: dict[str, int] = defaultdict(int)
        for r in recs:
            err_type = _classify_error(r)
            if err_type:
                error_counts[err_type] += 1

        for err_type, count in error_counts.items():
            ratio = count / len(recs)
            if ratio >= _THRESHOLD and count >= _MIN_OCORRENCIAS:
                sample = recs[0]
                errors.append(make_error(
                    sample, "CST_ICMS", "PARAM_ERRO_SISTEMATICO_UF",
                    (
                        f"Possivel erro de parametrizacao para operacoes com "
                        f"destino UF {uf}: {err_type} em {count} de {len(recs)} "
                        f"operacoes ({ratio:.0%}). Verifique as regras fiscais "
                        f"configuradas para essa UF no ERP."
                    ),
                    field_no=10,
                    value=f"UF={uf} {err_type} {count}/{len(recs)}",
                ))

    return errors


# ──────────────────────────────────────────────
# PARAM_003: Erro sistematico iniciado em data especifica
# ──────────────────────────────────────────────

def _parse_dt_doc(record: SpedRecord) -> date | None:
    """Extrai data do documento do C100 pai (DT_DOC campo indice 9)."""
    dt_str = record.fields.get("DT_DOC", "")
    if not dt_str or len(dt_str) != 8:
        return None
    try:
        return date(int(dt_str[4:8]), int(dt_str[2:4]), int(dt_str[0:2]))
    except (ValueError, IndexError):
        return None


def _check_param_003(
    groups: dict[str, list[SpedRecord]],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """PARAM_003: tipo de erro concentrado apos determinada data (janela deslizante)."""
    errors: list[ValidationError] = []

    if not context or not context.periodo_ini or not context.periodo_fim:
        return []

    # Precisamos de C100 com DT_DOC para associar datas aos C170
    _c100_by_line: dict[int, SpedRecord] = {}
    all_c_records: list[SpedRecord] = []
    for reg_type in ("C100", "C170"):
        all_c_records.extend(groups.get(reg_type, []))
    all_c_records.sort(key=lambda r: r.line_number)

    current_c100: SpedRecord | None = None
    c170_dates: list[tuple[SpedRecord, date]] = []

    for r in all_c_records:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            dt = _parse_dt_doc(current_c100)
            if dt:
                c170_dates.append((r, dt))

    if len(c170_dates) < _MIN_OCORRENCIAS * 2:
        return []

    # Ordenar por data
    c170_dates.sort(key=lambda x: x[1])

    # Dividir periodo ao meio e comparar taxa de erro antes/depois
    mid_idx = len(c170_dates) // 2
    first_half = c170_dates[:mid_idx]
    second_half = c170_dates[mid_idx:]

    def error_rate(items: list[tuple[SpedRecord, date]]) -> tuple[int, int, str]:
        total = len(items)
        err_counts: dict[str, int] = defaultdict(int)
        for r, _ in items:
            et = _classify_error(r)
            if et:
                err_counts[et] += 1
        if not err_counts:
            return 0, total, ""
        top_err = max(err_counts, key=err_counts.get)  # type: ignore[arg-type]
        return err_counts[top_err], total, top_err

    err_before, total_before, _ = error_rate(first_half)
    err_after, total_after, top_err = error_rate(second_half)

    if total_before == 0 or total_after == 0 or not top_err:
        return []

    rate_before = err_before / total_before
    rate_after = err_after / total_after

    # Erro concentrado na segunda metade: taxa >80% depois vs <20% antes
    if rate_after >= _THRESHOLD and rate_before < 0.20 and err_after >= _MIN_OCORRENCIAS:
        data_inicio = second_half[0][1]
        sample = second_half[0][0]
        errors.append(make_error(
            sample, "CST_ICMS", "PARAM_ERRO_INICIADO_EM_DATA",
            (
                f"Possivel mudanca de parametrizacao no ERP em "
                f"{data_inicio.strftime('%d/%m/%Y')}: {top_err} passou a "
                f"ocorrer em {err_after} de {total_after} registros "
                f"({rate_after:.0%}) apos essa data, contra {err_before} de "
                f"{total_before} ({rate_before:.0%}) antes. Verifique "
                f"alteracoes de cadastro fiscal nessa data."
            ),
            field_no=10,
            value=f"data={data_inicio.isoformat()} {top_err} {err_after}/{total_after}",
        ))

    return errors
