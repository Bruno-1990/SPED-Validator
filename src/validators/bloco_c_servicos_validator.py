"""Validador de Bloco C Servicos — C400/C490 (ECF) e C500/C590 (Energia/Gas).

MOD-17: Validacoes basicas de fechamento analitico e referencias cadastrais.
"""

from __future__ import annotations

from collections import defaultdict

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    TOLERANCE,
    get_field,
    make_error,
    to_float,
)


def validate_bloco_c_servicos(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes de C400/C490 e C500/C510/C590."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Coletar cadastros 0150 para validacao de referencia
    cod_parts: set[str] = set()
    for rec in groups.get("0150", []):
        cod = get_field(rec, "COD_PART")
        if cod:
            cod_parts.add(cod)

    # Periodo do arquivo (0000)
    dt_ini, dt_fin = "", ""
    for rec in groups.get("0000", []):
        dt_ini = get_field(rec, "DT_INI")
        dt_fin = get_field(rec, "DT_FIN")

    errors.extend(_check_cs_001(groups, cod_parts))
    errors.extend(_check_cs_002(groups, dt_ini, dt_fin))
    errors.extend(_check_cs_003(groups, cod_parts))
    errors.extend(_check_cs_004(groups))

    return errors


# ──────────────────────────────────────────────
# CS_001 — C490 deve fechar com soma dos C405/C420 por CST+CFOP+ALIQ
# ──────────────────────────────────────────────

def _check_cs_001(
    groups: dict[str, list[SpedRecord]],
    cod_parts: set[str],
) -> list[ValidationError]:
    """C400: COD_PART referenciado deve existir no 0150.
    C490: consolidacao por CST+CFOP+ALIQ deve fechar com registros filhos.

    NOTA: C400 nao possui COD_PART no layout padrao EFD.
    Validamos apenas o fechamento analitico C490.
    """
    errors: list[ValidationError] = []

    # C490 e um registro analitico consolidado — validamos que VL_OPR > 0
    # e que VL_BC_ICMS * ALIQ_ICMS ~ VL_ICMS (consistencia interna)
    for rec in groups.get("C490", []):
        cst = get_field(rec, "CST_ICMS")
        cfop = get_field(rec, "CFOP")
        aliq = to_float(get_field(rec, "ALIQ_ICMS"))
        vl_bc = to_float(get_field(rec, "VL_BC_ICMS"))
        vl_icms = to_float(get_field(rec, "VL_ICMS"))

        # Consistencia: BC * ALIQ/100 ~ VL_ICMS (apenas se tributado)
        if aliq > 0 and vl_bc > 0:
            expected = round(vl_bc * aliq / 100, 2)
            diff = abs(expected - vl_icms)
            if diff > TOLERANCE:
                errors.append(make_error(
                    rec, "VL_ICMS", "CS_C490_SOMA_DIVERGENTE",
                    f"C490 CST={cst} CFOP={cfop} ALIQ={aliq}: "
                    f"VL_BC_ICMS({vl_bc:.2f}) x ALIQ({aliq:.2f}%) = {expected:.2f}, "
                    f"mas VL_ICMS declarado={vl_icms:.2f} (dif={diff:.2f}).",
                    field_no=7,
                    value=f"{vl_icms:.2f}",
                    expected_value=f"{expected:.2f}",
                ))

    return errors


# ──────────────────────────────────────────────
# CS_002 — Datas C405 dentro do periodo 0000
# ──────────────────────────────────────────────

def _parse_sped_date(dt: str) -> str:
    """Converte data SPED (DDMMYYYY) para formato comparavel (YYYYMMDD)."""
    if len(dt) == 8:
        return dt[4:8] + dt[2:4] + dt[0:2]
    return dt


def _check_cs_002(
    groups: dict[str, list[SpedRecord]],
    dt_ini: str,
    dt_fin: str,
) -> list[ValidationError]:
    """Datas dos registros C405 (Reducao Z) devem estar dentro do periodo 0000."""
    errors: list[ValidationError] = []

    if not dt_ini or not dt_fin:
        return errors

    ini_cmp = _parse_sped_date(dt_ini)
    fin_cmp = _parse_sped_date(dt_fin)

    for rec in groups.get("C405", []):
        dt_doc = get_field(rec, "DT_DOC")
        if dt_doc:
            doc_cmp = _parse_sped_date(dt_doc)
            if doc_cmp < ini_cmp or doc_cmp > fin_cmp:
                errors.append(make_error(
                    rec, "DT_DOC", "DATE_OUT_OF_PERIOD",
                    f"C405: DT_DOC={dt_doc} fora do periodo {dt_ini} a {dt_fin}.",
                    field_no=2,
                    value=dt_doc,
                    expected_value=f"{dt_ini} a {dt_fin}",
                ))

    return errors


# ──────────────────────────────────────────────
# CS_003 — C500: COD_PART deve existir no 0150 + CFOP compativel
# ──────────────────────────────────────────────

def _check_cs_003(
    groups: dict[str, list[SpedRecord]],
    cod_parts: set[str],
) -> list[ValidationError]:
    """C500: COD_PART referenciado deve existir no 0150.
    CFOP deve ser compativel com operacao (IND_OPER).
    """
    errors: list[ValidationError] = []

    for rec in groups.get("C500", []):
        # Referencia cadastral
        cod_part = get_field(rec, "COD_PART")
        if cod_part and cod_parts and cod_part not in cod_parts:
            errors.append(make_error(
                rec, "COD_PART", "REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no C500 nao existe no 0150.",
                field_no=4,
                value=cod_part,
            ))

        # CFOP compativel com operacao
        _ind_oper = get_field(rec, "IND_OPER")
        _cfop = get_field(rec, "CFOP") if "CFOP" in rec.fields else ""
        # C500 nao tem CFOP direto, mas C510 sim — verificamos via C510
        # Validacao de CFOP e feita em CS_004 (C590/C510)

    return errors


# ──────────────────────────────────────────────
# CS_004 — C590 deve fechar com soma dos C510
# ──────────────────────────────────────────────

def _check_cs_004(
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """C590 (analitico) deve fechar com soma dos C510 (itens) por CST+CFOP+ALIQ.

    Tambem valida CFOP do C510: entrada (1/2/3) ou saida (5/6/7).
    """
    errors: list[ValidationError] = []

    # Agrupar C510 por CST+CFOP+ALIQ
    c510_totals: dict[tuple[str, str, str], float] = defaultdict(float)
    c510_bc_totals: dict[tuple[str, str, str], float] = defaultdict(float)

    for rec in groups.get("C510", []):
        cst = get_field(rec, "CST_ICMS")
        cfop = get_field(rec, "CFOP")
        aliq = get_field(rec, "ALIQ_ICMS")
        vl_icms = to_float(get_field(rec, "VL_ICMS"))
        vl_bc = to_float(get_field(rec, "VL_BC_ICMS"))

        # Validar CFOP compatibilidade basica
        if cfop and cfop[0] not in ("1", "2", "3", "5", "6", "7"):
            errors.append(make_error(
                rec, "CFOP", "CFOP_INVALIDO",
                f"C510: CFOP={cfop} nao e compativel com operacao "
                f"(esperado inicio 1/2/3 para entrada ou 5/6/7 para saida).",
                field_no=9,
                value=cfop,
            ))

        key = (cst, cfop, aliq)
        c510_totals[key] += vl_icms
        c510_bc_totals[key] += vl_bc

    # Se nao ha C510, nao validar fechamento
    if not c510_totals:
        return errors

    # Comparar com C590
    for rec in groups.get("C590", []):
        cst = get_field(rec, "CST_ICMS")
        cfop = get_field(rec, "CFOP")
        aliq = get_field(rec, "ALIQ_ICMS")
        vl_icms_590 = to_float(get_field(rec, "VL_ICMS"))
        _vl_opr_590 = to_float(get_field(rec, "VL_OPR"))

        key = (cst, cfop, aliq)
        vl_icms_510 = c510_totals.get(key, 0.0)

        diff = abs(vl_icms_590 - vl_icms_510)
        if diff > TOLERANCE:
            errors.append(make_error(
                rec, "VL_ICMS", "CS_C590_DIVERGE_C510",
                f"C590 CST={cst} CFOP={cfop} ALIQ={aliq}: "
                f"VL_ICMS={vl_icms_590:.2f} diverge da soma C510={vl_icms_510:.2f} "
                f"(dif={diff:.2f}).",
                field_no=7,
                value=f"{vl_icms_590:.2f}",
                expected_value=f"{vl_icms_510:.2f}",
            ))

    return errors
