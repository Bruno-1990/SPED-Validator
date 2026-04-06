"""Validador de Base de Calculo ICMS.

Regras implementadas:
- BASE_001: Recalculo ICMS divergente (delega a tax_recalc.recalc_icms_item)
- BASE_002: Base menor que esperado sem justificativa
- BASE_003: Base superior ao razoavel
- BASE_004: Frete CIF nao incluido na base
- BASE_005: Frete FOB incluido indevidamente na base
- BASE_006: Despesas acessorias fora da base

Base legal: Art. 13, LC 87/1996
"""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from ..services.context_builder import ValidationContext
from .helpers import (
    CST_TRIBUTADO,
    get_field,
    make_error,
    to_float,
    trib,
)
from .tax_recalc import recalc_icms_item

# CSTs de reducao de base (justificam BC < VL_ITEM)
_CST_REDUCAO = {"20", "70"}

# IND_FRT: 0=CIF (emitente paga), 1=FOB (destinatario paga), 2=terceiros, 9=sem
_IND_FRT_CIF = "0"
_IND_FRT_FOB = "1"


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_base_calculo(
    records: list[SpedRecord],
    context: ValidationContext | None = None,
) -> list[ValidationError]:
    """Executa validacoes de base de calculo ICMS nos registros SPED."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    c170_parent = _build_parent_map(groups)

    for rec in groups.get("C170", []):
        parent = c170_parent.get(rec.line_number)

        # BASE_001: reutiliza recalculo existente
        errors.extend(recalc_icms_item(rec))

        # BASE_002 a BASE_003: analise da base vs valor do item
        errors.extend(_check_base_002(rec))
        errors.extend(_check_base_003(rec))

        # BASE_004 a BASE_006: requerem C100 pai
        if parent:
            errors.extend(_check_base_004(rec, parent))
            errors.extend(_check_base_005(rec, parent))
            errors.extend(_check_base_006(rec, parent))

    return errors


# ──────────────────────────────────────────────
# Contexto
# ──────────────────────────────────────────────

def _build_parent_map(
    groups: dict[str, list[SpedRecord]],
) -> dict[int, SpedRecord]:
    """Mapa C170.line_number -> C100 pai."""
    all_recs = []
    for reg_type in ("C100", "C170"):
        all_recs.extend(groups.get(reg_type, []))
    all_recs.sort(key=lambda r: r.line_number)

    parent_map: dict[int, SpedRecord] = {}
    current_c100: SpedRecord | None = None
    for r in all_recs:
        if r.register == "C100":
            current_c100 = r
        elif r.register == "C170" and current_c100 is not None:
            parent_map[r.line_number] = current_c100
    return parent_map


# ──────────────────────────────────────────────
# BASE_002: Base menor que esperado sem justificativa
# ──────────────────────────────────────────────

def _check_base_002(record: SpedRecord) -> list[ValidationError]:
    """VL_BC_ICMS < VL_ITEM * 0.5 sem CST de reducao (020, 070)."""
    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []
    # CSTs de reducao justificam base menor
    if t in _CST_REDUCAO:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    if vl_bc < vl_item * 0.5:
        return [make_error(
            record, "VL_BC_ICMS", "BASE_MENOR_SEM_JUSTIFICATIVA",
            (
                f"Base de calculo ICMS (R$ {vl_bc:.2f}) e inferior a 50% do "
                f"valor do item (R$ {vl_item:.2f}), sem CST de reducao "
                f"(020 ou 070). CST informado: {cst}. "
                f"Verifique se ha beneficio fiscal aplicavel ou se a base "
                f"esta incorreta."
            ),
            field_no=13,
            value=f"{vl_bc:.2f}",
            expected_value=f"{vl_item:.2f}",
        )]
    return []


# ──────────────────────────────────────────────
# BASE_003: Base superior ao razoavel
# ──────────────────────────────────────────────

def _check_base_003(record: SpedRecord) -> list[ValidationError]:
    """VL_BC_ICMS > VL_ITEM * 1.5."""
    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    if vl_bc > vl_item * 1.5:
        return [make_error(
            record, "VL_BC_ICMS", "BASE_SUPERIOR_RAZOAVEL",
            (
                f"Base de calculo ICMS (R$ {vl_bc:.2f}) e superior a 150% do "
                f"valor do item (R$ {vl_item:.2f}). Pode indicar frete CIF "
                f"incluido incorretamente ou erro de preenchimento."
            ),
            field_no=13,
            value=f"{vl_bc:.2f}",
        )]
    return []


# ──────────────────────────────────────────────
# BASE_004: Frete CIF nao incluido na base
# ──────────────────────────────────────────────

def _check_base_004(
    record: SpedRecord,
    parent: SpedRecord,
) -> list[ValidationError]:
    """VL_FRT > 0 + modalidade CIF + VL_FRT ausente da BC."""
    ind_frt = get_field(parent, "IND_FRT")
    if ind_frt != _IND_FRT_CIF:
        return []

    vl_frt = to_float(get_field(parent, "VL_FRT"))
    if vl_frt <= 0:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    # Heuristica: se BC <= VL_ITEM (sem frete), o frete CIF nao foi incluido
    if vl_bc <= vl_item:
        return [make_error(
            record, "VL_BC_ICMS", "FRETE_CIF_FORA_BASE",
            (
                f"Frete CIF (IND_FRT=0) de R$ {vl_frt:.2f} no documento, "
                f"mas base ICMS (R$ {vl_bc:.2f}) nao excede o valor do item "
                f"(R$ {vl_item:.2f}), indicando que o frete nao foi incluido "
                f"na base de calculo. Art. 13, §1, II, LC 87/1996."
            ),
            field_no=13,
            value=f"{vl_bc:.2f}",
        )]
    return []


# ──────────────────────────────────────────────
# BASE_005: Frete FOB incluido indevidamente
# ──────────────────────────────────────────────

def _check_base_005(
    record: SpedRecord,
    parent: SpedRecord,
) -> list[ValidationError]:
    """VL_FRT incluido na BC + indicacao FOB."""
    ind_frt = get_field(parent, "IND_FRT")
    if ind_frt != _IND_FRT_FOB:
        return []

    vl_frt = to_float(get_field(parent, "VL_FRT"))
    if vl_frt <= 0:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    # Heuristica: se BC > VL_ITEM, o frete FOB pode ter sido incluido
    if vl_bc > vl_item:
        return [make_error(
            record, "VL_BC_ICMS", "FRETE_FOB_NA_BASE",
            (
                f"Frete FOB (IND_FRT=1) de R$ {vl_frt:.2f} no documento, "
                f"mas base ICMS (R$ {vl_bc:.2f}) excede o valor do item "
                f"(R$ {vl_item:.2f}), indicando possivel inclusao indevida "
                f"do frete na base. No FOB, o frete e por conta do "
                f"destinatario e nao compoem a base do remetente."
            ),
            field_no=13,
            value=f"{vl_bc:.2f}",
        )]
    return []


# ──────────────────────────────────────────────
# BASE_006: Despesas acessorias fora da base
# ──────────────────────────────────────────────

def _check_base_006(
    record: SpedRecord,
    parent: SpedRecord,
) -> list[ValidationError]:
    """VL_OUT_DA > 0 + nao incluido em VL_BC_ICMS para CST tributado.

    Art. 13, LC 87/1996: despesas acessorias integram a base de calculo.
    """
    vl_out_da = to_float(get_field(parent, "VL_OUT_DA"))
    if vl_out_da <= 0:
        return []

    cst = get_field(record, "CST_ICMS")
    if not cst:
        return []
    t = trib(cst)
    if t not in CST_TRIBUTADO:
        return []

    vl_item = to_float(get_field(record, "VL_ITEM"))
    vl_bc = to_float(get_field(record, "VL_BC_ICMS"))

    if vl_item <= 0 or vl_bc <= 0:
        return []

    # Se BC <= VL_ITEM, as despesas acessorias nao foram incluidas
    if vl_bc <= vl_item:
        return [make_error(
            record, "VL_BC_ICMS", "DESPESAS_ACESSORIAS_FORA_BASE",
            (
                f"Despesas acessorias (VL_OUT_DA) de R$ {vl_out_da:.2f} no "
                f"documento, mas base ICMS (R$ {vl_bc:.2f}) nao excede o "
                f"valor do item (R$ {vl_item:.2f}). Art. 13, LC 87/1996: "
                f"despesas acessorias cobradas do adquirente integram a "
                f"base de calculo do ICMS."
            ),
            field_no=13,
            value=f"{vl_bc:.2f}",
        )]
    return []
