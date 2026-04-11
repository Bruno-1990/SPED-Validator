"""Validador de beneficios fiscais (BENE_001 a BENE_003).

Detecta contaminacao de beneficios na aliquota do documento,
no calculo DIFAL e operacoes nao elegiveis na base do beneficio.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    CFOP_DEVOLUCAO,
    CFOP_REMESSA_RETORNO,
    CST_TRIBUTADO,
    F_0000_UF,
    F_C170_ALIQ_ICMS,
    F_C170_CFOP,
    F_C170_CST_ICMS,
    F_C190_ALIQ,
    F_C190_CFOP,
    F_C190_CST,
    F_C190_VL_OPR,
    F_E111_COD_AJ_APUR,
    F_E111_DESCR_COMPL,
    F_E111_VL_AJ_APUR,
    get_field,
    make_error,
    to_float,
    trib,
)

if TYPE_CHECKING:
    from ..services.context_builder import ValidationContext

# CFOPs de operacoes nao elegiveis para base de beneficio
_CFOP_NAO_ELEGIVEL = CFOP_DEVOLUCAO | CFOP_REMESSA_RETORNO | {
    "5927", "6927",  # cancelamentos
    "5929", "6929",  # lancamentos de cupom fiscal
}

# Palavras-chave que indicam beneficio fiscal no E111
_KW_BENEFICIO = (
    "beneficio", "benefício", "reducao", "redução",
    "presumido", "outorgado", "incentivo", "credito presumido",
    "crédito presumido", "isencao", "isenção",
)


def _is_e111_beneficio(record: SpedRecord) -> bool:
    """Detecta se E111 e um ajuste de beneficio fiscal."""
    descr = get_field(record, F_E111_DESCR_COMPL).lower()
    cod_aj = get_field(record, F_E111_COD_AJ_APUR)
    # Natureza credito (pos[3]=2) ou deducao (pos[3]=4)
    return len(cod_aj) >= 4 and cod_aj[3] in ("2", "4") and any(kw in descr for kw in _KW_BENEFICIO)


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_beneficio(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Valida regras de beneficio fiscal (BENE_001 a BENE_003)."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Identificar E111 de beneficio
    e111_beneficios = [
        r for r in groups.get("E111", []) if _is_e111_beneficio(r)
    ]
    if not e111_beneficios:
        return errors

    errors.extend(_check_beneficio_contaminando_aliquota(
        groups, e111_beneficios,
    ))
    errors.extend(_check_beneficio_contaminando_difal(
        groups, e111_beneficios,
    ))
    errors.extend(_check_base_beneficio_nao_elegivel(
        groups, e111_beneficios,
    ))

    return errors


# ──────────────────────────────────────────────
# BENE_001: Beneficio contaminando aliquota do documento
# ──────────────────────────────────────────────

def _check_beneficio_contaminando_aliquota(
    groups: dict[str, list[SpedRecord]],
    e111_beneficios: list[SpedRecord],
) -> list[ValidationError]:
    """BENE_001: Beneficio no E111 + C190 com aliquota alterada.

    Quando ha beneficio fiscal, ele deve estar na apuracao (E111) e nao
    alterar a aliquota do documento. Se C190 apresenta aliquotas atipicas
    (< 17% em operacoes internas com CST tributado), pode indicar que o
    beneficio esta contaminando os documentos.
    """
    errors: list[ValidationError] = []

    # UF do contribuinte
    _uf = ""
    for r in groups.get("0000", []):
        _uf = get_field(r, F_0000_UF)
        break

    for rec in groups.get("C190", []):
        cst = get_field(rec, F_C190_CST)
        if not cst:
            continue
        t = trib(cst)
        if t not in CST_TRIBUTADO:
            continue

        aliq = to_float(get_field(rec, F_C190_ALIQ))
        cfop = get_field(rec, F_C190_CFOP)

        # Apenas operacoes internas (5xxx) — interestaduais tem aliquotas menores
        if not cfop or not cfop.startswith("5"):
            continue

        # Aliquota atipica: menor que 17% em operacao interna tributada
        if 0 < aliq < 17.0:
            vl_opr = to_float(get_field(rec, F_C190_VL_OPR))
            errors.append(make_error(
                rec, "ALIQ_ICMS", "BENEFICIO_CONTAMINANDO_ALIQUOTA",
                (
                    f"Operacao interna (CFOP {cfop}) com CST {cst} tributado "
                    f"e ALIQ_ICMS={aliq:.2f}%, abaixo do piso de 17%. "
                    f"Ha beneficio fiscal registrado no E111 — a reducao "
                    f"deve ser feita na apuracao (E111), nao na aliquota "
                    f"do documento. VL_OPR={vl_opr:.2f}."
                ),
                value=f"ALIQ={aliq:.2f}% CFOP={cfop} CST={cst}",
            ))

    return errors


# ──────────────────────────────────────────────
# BENE_002: Beneficio contaminando calculo DIFAL
# ──────────────────────────────────────────────

def _check_beneficio_contaminando_difal(
    groups: dict[str, list[SpedRecord]],
    e111_beneficios: list[SpedRecord],
) -> list[ValidationError]:
    """BENE_002: Beneficio fiscal + E300 com valores reduzidos.

    Se ha beneficio no E111 e o E300 (DIFAL) apresenta valores, verificar
    se nao houve reducao indevida no DIFAL por conta do beneficio.
    O beneficio estadual nao deve interferir no calculo do diferencial
    de aliquota interestadual.
    """
    errors: list[ValidationError] = []

    e300_recs = groups.get("E300", [])
    if not e300_recs:
        return errors

    # Calcular total de beneficios no E111
    total_beneficio = sum(
        to_float(get_field(r, F_E111_VL_AJ_APUR))
        for r in e111_beneficios
    )
    if total_beneficio <= 0:
        return errors

    # Verificar C170 interestaduais com CST tributado e aliquota reduzida
    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        if not cfop or not cfop.startswith("6"):
            continue

        cst = get_field(rec, F_C170_CST_ICMS)
        if not cst:
            continue
        t = trib(cst)
        if t not in CST_TRIBUTADO:
            continue

        aliq = to_float(get_field(rec, F_C170_ALIQ_ICMS))
        # Se aliquota interestadual esta abaixo das faixas validas (4,7,12)
        if 0 < aliq < 4.0:
            errors.append(make_error(
                rec, "ALIQ_ICMS", "BENEFICIO_CONTAMINANDO_DIFAL",
                (
                    f"Operacao interestadual (CFOP {cfop}) com "
                    f"ALIQ_ICMS={aliq:.2f}% — abaixo de 4%. "
                    f"Ha beneficio fiscal de R$ {total_beneficio:.2f} no E111. "
                    f"O beneficio nao deve alterar a aliquota interestadual "
                    f"utilizada no calculo do DIFAL."
                ),
                value=f"ALIQ={aliq:.2f}% CFOP={cfop}",
            ))

    return errors


# ──────────────────────────────────────────────
# BENE_003: Base do beneficio com operacoes nao elegiveis
# ──────────────────────────────────────────────

def _check_base_beneficio_nao_elegivel(
    groups: dict[str, list[SpedRecord]],
    e111_beneficios: list[SpedRecord],
) -> list[ValidationError]:
    """BENE_003: E111 ajuste sobre base que inclui devolucao/cancelamento/remessa.

    O total de operacoes no C190 inclui CFOPs de devolucao, cancelamento e
    remessa que nao devem compor a base de calculo do beneficio fiscal.
    Se ha volume significativo dessas operacoes, alerta.
    """
    errors: list[ValidationError] = []

    total_beneficio = sum(
        to_float(get_field(r, F_E111_VL_AJ_APUR))
        for r in e111_beneficios
    )
    if total_beneficio <= 0:
        return errors

    # Somar VL_OPR de CFOPs nao elegiveis no C190
    vl_nao_elegivel = 0.0
    vl_total_c190 = 0.0
    for rec in groups.get("C190", []):
        cfop = get_field(rec, F_C190_CFOP)
        vl_opr = to_float(get_field(rec, F_C190_VL_OPR))
        vl_total_c190 += vl_opr
        if cfop in _CFOP_NAO_ELEGIVEL:
            vl_nao_elegivel += vl_opr

    if vl_nao_elegivel <= 0 or vl_total_c190 <= 0:
        return errors

    # Se operacoes nao elegiveis sao > 5% do total e ha beneficio
    ratio = vl_nao_elegivel / vl_total_c190
    if ratio > 0.05:
        for e111 in e111_beneficios:
            cod_aj = get_field(e111, F_E111_COD_AJ_APUR)
            vl_aj = to_float(get_field(e111, F_E111_VL_AJ_APUR))
            errors.append(make_error(
                e111, "VL_AJ_APUR", "BENEFICIO_BASE_NAO_ELEGIVEL",
                (
                    f"Beneficio fiscal (COD_AJ={cod_aj}, VL={vl_aj:.2f}) "
                    f"pode estar calculado sobre base que inclui "
                    f"R$ {vl_nao_elegivel:.2f} em devolucoes/cancelamentos/"
                    f"remessas ({ratio:.1%} do total). Essas operacoes "
                    f"nao devem compor a base do beneficio."
                ),
                value=f"VL_NAO_ELEGIVEL={vl_nao_elegivel:.2f}",
            ))

    return errors


# ──────────────────────────────────────────────
# Novas regras de beneficio (Fase 3 — BeneficioEngine)
# ──────────────────────────────────────────────

def validate_beneficio_engine(
    records: list[SpedRecord],
    context: "ValidationContext | None" = None,
) -> list[ValidationError]:
    """Valida beneficios usando o BeneficioEngine do contexto.

    Regras novas:
    - SPED_CST_BENEFICIO: CST incompativel com beneficio ativo
    - SPED_ALIQ_BENEFICIO: Aliquota incompativel com beneficio
    - BENEFICIO_SEM_AJUSTE_E111: Beneficio ativo sem E111 correspondente
    """
    errors: list[ValidationError] = []
    if not context or not getattr(context, "beneficio_engine", None):
        return errors

    engine = context.beneficio_engine
    if not engine.has_beneficios:
        return errors

    groups = group_by_register(records)

    # -- SPED_CST_BENEFICIO / SPED_ALIQ_BENEFICIO --
    for rec in groups.get("C170", []):
        cfop = get_field(rec, F_C170_CFOP)
        if not cfop or cfop[0] not in ("5", "6"):
            continue  # Apenas saidas

        cst = get_field(rec, F_C170_CST_ICMS)
        aliq = to_float(get_field(rec, F_C170_ALIQ_ICMS))

        # SPED_CST_BENEFICIO
        cst_validos = engine.get_cst_validos_saida(cfop)
        if cst_validos and cst and cst not in cst_validos:
            errors.append(make_error(
                rec, "CST_ICMS", "SPED_CST_BENEFICIO",
                f"CST {cst} incompativel com beneficios ativos para CFOP {cfop}. "
                f"CSTs validos: {sorted(cst_validos)}.",
                value=cst,
                expected_value=",".join(sorted(cst_validos)),
            ))

        # SPED_ALIQ_BENEFICIO (debito integral COMPETE)
        if engine.get_debito_integral(cfop) and aliq > 0 and aliq < 10.0:
            errors.append(make_error(
                rec, "ALIQ_ICMS", "SPED_ALIQ_BENEFICIO",
                f"Aliquota {aliq:.1f}% em saida com beneficio que exige debito integral. "
                f"COMPETE exige aliquota cheia (17% para ES). Credito presumido "
                f"deve ser via E111, nao por reducao de aliquota em C170.",
                value=f"{aliq:.1f}",
                expected_value="17.0",
            ))

    # -- BENEFICIO_SEM_AJUSTE_E111 --
    e111_records = groups.get("E111", [])
    has_e111_beneficio = any(_is_e111_beneficio(r) for r in e111_records)
    if engine.has_beneficios and not has_e111_beneficio:
        for b in context.beneficios_ativos:
            rec_ref = e111_records[0] if e111_records else records[0]
            errors.append(make_error(
                rec_ref,
                "COD_AJ_APUR", "BENEFICIO_SEM_AJUSTE_E111",
                f"Beneficio '{b.codigo}' ativo no periodo mas nenhum E111 "
                f"corresponde a ajuste de beneficio fiscal.",
                value="ausente",
            ))

    return errors
