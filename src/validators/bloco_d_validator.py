"""Validador do Bloco D: CT-e e Documentos de Transporte (MOD-08).

Regras implementadas:
- D_001: COD_PART do D100 deve existir no 0150
- D_002: CFOP do D190 compativel com direcao da operacao (IND_OPER do D100)
- D_003: D190 deve fechar com soma dos D100 correspondentes por CST+CFOP+ALIQ
- D_004: D190/D690 deve compor VL_TOT_DEBITOS do E110
- D_005: CST_ICMS do D190 compativel com regime tributario
- D_006: Chave CT-e (CHV_CTE) deve ter 44 digitos com DV valido modulo 11
"""

from __future__ import annotations

import re

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import TaxRegime, ValidationContext
from .helpers import (
    CST_DIFERIMENTO,
    CST_ISENTO_NT,
    CST_RESIDUAL,
    CST_TRIBUTADO,
    CSOSN_VALIDOS,
    get_field,
    make_error,
    to_float,
)
from .tolerance import get_tolerance

# CSTs validos por regime (construidos do JSON via helpers)
_CST_TABELA_A = CST_TRIBUTADO | CST_ISENTO_NT | CST_DIFERIMENTO | CST_RESIDUAL
_CST_TABELA_B = CSOSN_VALIDOS


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_bloco_d(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes do Bloco D (CT-e e Documentos de Transporte)."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    errors.extend(_check_d_001(groups))
    errors.extend(_check_d_002(records))
    errors.extend(_check_d_003(records))
    errors.extend(_check_d_004(groups))
    errors.extend(_check_d_005(groups, context))
    errors.extend(_check_d_006(groups))

    return errors


# ──────────────────────────────────────────────
# D_001: COD_PART do D100 deve existir no 0150
# ──────────────────────────────────────────────

def _check_d_001(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Verifica que COD_PART referenciado no D100 existe no cadastro 0150."""
    errors: list[ValidationError] = []

    cod_parts = set()
    for rec in groups.get("0150", []):
        cod = get_field(rec, "COD_PART")
        if cod:
            cod_parts.add(cod)

    if not cod_parts:
        return errors

    for rec in groups.get("D100", []):
        cod_part = get_field(rec, "COD_PART")
        if cod_part and cod_part not in cod_parts:
            errors.append(make_error(
                rec, "COD_PART", "D_REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no D100 nao existe no cadastro 0150.",
                field_no=3,
                value=cod_part,
            ))

    return errors


# ──────────────────────────────────────────────
# D_002: CFOP do D190 compativel com direcao (IND_OPER do D100)
# ──────────────────────────────────────────────

def _check_d_002(records: list[SpedRecord]) -> list[ValidationError]:
    """Verifica que CFOP do D190 e compativel com IND_OPER do D100 pai.

    IND_OPER=0 (entrada): CFOP deve iniciar com 1, 2 ou 3
    IND_OPER=1 (saida): CFOP deve iniciar com 5, 6 ou 7
    """
    errors: list[ValidationError] = []

    for d100, d190_list in _group_d100_d190(records):
        ind_oper = get_field(d100, "IND_OPER")
        if ind_oper == "0":
            valid_prefixes = ("1", "2", "3")
            direcao = "entrada"
        elif ind_oper == "1":
            valid_prefixes = ("5", "6", "7")
            direcao = "saida"
        else:
            continue

        for d190 in d190_list:
            cfop = get_field(d190, "CFOP")
            if cfop and cfop[0] not in valid_prefixes:
                errors.append(make_error(
                    d190, "CFOP", "D_CFOP_DIRECAO_INCOMPATIVEL",
                    (
                        f"D190 com CFOP {cfop} incompativel com D100 "
                        f"IND_OPER={ind_oper} ({direcao}). "
                        f"CFOPs de {direcao} devem iniciar com "
                        f"{'/'.join(valid_prefixes)}."
                    ),
                    field_no=2,
                    value=cfop,
                ))

    return errors


# ──────────────────────────────────────────────
# D_003: D190 deve fechar com D100 por CST+CFOP+ALIQ
# ──────────────────────────────────────────────

def _check_d_003(records: list[SpedRecord]) -> list[ValidationError]:
    """Verifica que D190 fecha com D100: soma de VL_OPR e VL_ICMS.

    Para cada D100, soma dos D190 filhos:
    - Sum(D190.VL_OPR) deve ≈ D100.VL_DOC
    - Sum(D190.VL_ICMS) deve ≈ D100.VL_ICMS
    """
    errors: list[ValidationError] = []

    for d100, d190_list in _group_d100_d190(records):
        if not d190_list:
            continue

        vl_doc = to_float(get_field(d100, "VL_DOC"))
        vl_icms_d100 = to_float(get_field(d100, "VL_ICMS"))

        if vl_doc == 0:
            continue

        soma_vl_opr = sum(to_float(get_field(d, "VL_OPR")) for d in d190_list)
        soma_vl_icms = sum(to_float(get_field(d, "VL_ICMS")) for d in d190_list)

        n_items = len(d190_list)
        tol = get_tolerance("consolidacao", n_items=n_items)

        diff_opr = abs(soma_vl_opr - vl_doc)
        if diff_opr > tol:
            errors.append(make_error(
                d190_list[0], "VL_OPR", "D190_DIVERGE_D100",
                (
                    f"Soma D190.VL_OPR={soma_vl_opr:.2f} diverge de "
                    f"D100.VL_DOC={vl_doc:.2f} (dif={diff_opr:.2f}). "
                    f"D100 na linha {d100.line_number}."
                ),
                field_no=4,
                value=f"{soma_vl_opr:.2f}",
                expected_value=f"{vl_doc:.2f}",
            ))

        diff_icms = abs(soma_vl_icms - vl_icms_d100)
        if diff_icms > tol and (soma_vl_icms > 0 or vl_icms_d100 > 0):
            errors.append(make_error(
                d190_list[0], "VL_ICMS", "D190_DIVERGE_D100",
                (
                    f"Soma D190.VL_ICMS={soma_vl_icms:.2f} diverge de "
                    f"D100.VL_ICMS={vl_icms_d100:.2f} (dif={diff_icms:.2f}). "
                    f"D100 na linha {d100.line_number}."
                ),
                field_no=6,
                value=f"{soma_vl_icms:.2f}",
                expected_value=f"{vl_icms_d100:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# D_004: D190/D690 deve compor VL_TOT_DEBITOS do E110
# ──────────────────────────────────────────────

def _check_d_004(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Verifica que VL_ICMS de D190/D690 de saida esta refletido no E110.

    Se Bloco D tem ICMS de saida, E110.VL_TOT_DEBITOS deve ser >= soma D.
    """
    errors: list[ValidationError] = []

    debitos_d = 0.0

    for reg_type in ("D190", "D690"):
        for rec in groups.get(reg_type, []):
            cfop = get_field(rec, "CFOP")
            vl_icms = to_float(get_field(rec, "VL_ICMS"))
            if cfop and cfop[0] in ("5", "6", "7"):
                debitos_d += vl_icms

    if debitos_d == 0:
        return errors

    e110_records = groups.get("E110", [])
    if not e110_records:
        return errors

    e110 = e110_records[0]
    vl_tot_debitos = to_float(get_field(e110, "VL_TOT_DEBITOS"))
    tol = get_tolerance("apuracao_e110")

    if debitos_d > vl_tot_debitos + tol:
        errors.append(make_error(
            e110, "VL_TOT_DEBITOS", "D_DEBITOS_EXCEDE_E110",
            (
                f"Soma ICMS de saida do Bloco D (D190+D690)={debitos_d:.2f} "
                f"excede E110.VL_TOT_DEBITOS={vl_tot_debitos:.2f}. "
                f"O E110 deveria incluir todos os debitos de ICMS do Bloco D."
            ),
            field_no=1,
            value=f"{vl_tot_debitos:.2f}",
            expected_value=f">= {debitos_d:.2f}",
        ))

    return errors


# ──────────────────────────────────────────────
# D_005: CST_ICMS compativel com regime tributario
# ──────────────────────────────────────────────

def _check_d_005(
    groups: dict[str, list[SpedRecord]],
    context: ValidationContext | None,
) -> list[ValidationError]:
    """Verifica que CST_ICMS do D190 e compativel com o regime tributario."""
    errors: list[ValidationError] = []

    if not context or context.regime == TaxRegime.UNKNOWN:
        return errors

    for rec in groups.get("D190", []):
        cst = get_field(rec, "CST_ICMS")
        if not cst:
            continue

        cst_trib = cst[-2:] if len(cst) >= 2 else cst

        if context.regime == TaxRegime.SIMPLES_NACIONAL:
            if cst_trib in _CST_TABELA_A and cst not in _CST_TABELA_B:
                errors.append(make_error(
                    rec, "CST_ICMS", "D_CST_REGIME_INCOMPATIVEL",
                    (
                        f"D190 com CST {cst} (Tabela A — Regime Normal) "
                        f"mas empresa esta no Simples Nacional. "
                        f"Deveria usar CSOSN (Tabela B): "
                        f"{', '.join(sorted(_CST_TABELA_B))}."
                    ),
                    field_no=1,
                    value=cst,
                ))
        elif context.regime == TaxRegime.NORMAL and cst in _CST_TABELA_B:
                errors.append(make_error(
                    rec, "CST_ICMS", "D_CST_REGIME_INCOMPATIVEL",
                    (
                        f"D190 com CSOSN {cst} (Tabela B — Simples Nacional) "
                        f"mas empresa esta no Regime Normal. "
                        f"Deveria usar CST (Tabela A): "
                        f"{', '.join(sorted(_CST_TABELA_A))}."
                    ),
                    field_no=1,
                    value=cst,
                ))

    return errors


# ──────────────────────────────────────────────
# D_006: CHV_CTE com 44 digitos e DV valido
# ──────────────────────────────────────────────

def _check_d_006(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Valida chave CT-e: 44 digitos numericos com digito verificador modulo 11."""
    errors: list[ValidationError] = []

    for rec in groups.get("D100", []):
        chv = get_field(rec, "CHV_CTE")
        if not chv:
            continue

        if not _validate_chave_cte(chv):
            errors.append(make_error(
                rec, "CHV_CTE", "D_CHAVE_CTE_INVALIDA",
                (
                    f"Chave CT-e '{chv}' invalida. "
                    f"Deve conter 44 digitos numericos com digito verificador "
                    f"valido (modulo 11)."
                ),
                field_no=9,
                value=chv,
            ))

    return errors


def _validate_chave_cte(chave: str) -> bool:
    """Valida chave de acesso CT-e: 44 digitos com DV modulo 11.

    Mesma logica da chave NFe (validate_chave_nfe em format_validator).
    """
    chave = chave.strip()
    if not re.fullmatch(r"\d{44}", chave):
        return False

    digits = [int(c) for c in chave[:43]]
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = sum(d * weights[i % 8] for i, d in enumerate(reversed(digits)))
    remainder = total % 11
    dv_calc = 0 if remainder < 2 else 11 - remainder

    return int(chave[43]) == dv_calc


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _group_d100_d190(
    records: list[SpedRecord],
) -> list[tuple[SpedRecord, list[SpedRecord]]]:
    """Agrupa D190 sob seu D100 pai por ordem de linhas."""
    result: list[tuple[SpedRecord, list[SpedRecord]]] = []
    current_d100: SpedRecord | None = None
    current_d190s: list[SpedRecord] = []

    d_records = sorted(
        [r for r in records if r.register in ("D100", "D190")],
        key=lambda r: r.line_number,
    )

    for r in d_records:
        if r.register == "D100":
            if current_d100 is not None:
                result.append((current_d100, current_d190s))
            current_d100 = r
            current_d190s = []
        elif r.register == "D190" and current_d100 is not None:
            current_d190s.append(r)

    if current_d100 is not None:
        result.append((current_d100, current_d190s))

    return result
