"""Validador de CSTs, isenções e Bloco H (estoque)."""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register

# ──────────────────────────────────────────────
# CSTs válidos por tipo de imposto
# ──────────────────────────────────────────────

# ICMS - Tabela A (Origem) + Tabela B (Tributação)
# Origem: 0-8, Tributação: 00,10,20,30,40,41,50,51,60,70,90
_CST_ICMS_TRIBUTACAO = {
    "00", "10", "20", "30", "40", "41", "50", "51", "60", "70", "90",
}

# ICMS Simples Nacional (CSOSN)
_CSOSN_VALIDOS = {
    "101", "102", "103", "201", "202", "203",
    "300", "400", "500", "900",
}

# CSTs que indicam tributação integral de ICMS
_CST_ICMS_TRIBUTADO = {"00", "10", "20", "70", "90"}

# CSTs que indicam isenção/não-tributação de ICMS
_CST_ICMS_ISENTO = {"40", "41", "50", "60"}

# CSTs de IPI
_CST_IPI_VALIDOS = {
    "00", "01", "02", "03", "04", "05",
    "49", "50", "51", "52", "53", "54", "55",
    "99",
}

# CSTs de PIS/COFINS
_CST_PIS_COFINS_VALIDOS = {
    "01", "02", "03", "04", "05", "06", "07", "08", "09",
    "49", "50", "51", "52", "53", "54", "55", "56",
    "60", "61", "62", "63", "64", "65", "66", "67",
    "70", "71", "72", "73", "74", "75",
    "98", "99",
}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _get(record: SpedRecord, idx: int) -> str:
    if idx < len(record.fields):
        return record.fields[idx].strip()
    return ""


def _float(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return 0.0


def _error(
    record: SpedRecord,
    field_name: str,
    error_type: str,
    message: str,
) -> ValidationError:
    return ValidationError(
        line_number=record.line_number,
        register=record.register,
        field_no=0,
        field_name=field_name,
        value="",
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_cst_and_exemptions(records: list[SpedRecord]) -> list[ValidationError]:
    """Valida CSTs, consistência de isenções e Bloco H."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    # Validar CSTs nos C170
    for rec in groups.get("C170", []):
        errors.extend(_validate_cst_c170(rec))
        errors.extend(_validate_exemptions_c170(rec))

    # Validar Bloco H (estoque) vs cadastro
    errors.extend(_validate_bloco_h(groups))

    return errors


# ──────────────────────────────────────────────
# Validação de CST nos C170
# ──────────────────────────────────────────────

def _validate_cst_c170(record: SpedRecord) -> list[ValidationError]:
    """Valida se CST_ICMS do C170 é um código válido.

    Campos C170 (0-based): 11:CST_ICMS (posição padrão)
    O CST pode ter 2 dígitos (Tabela B) ou 3 dígitos (Origem + Tabela B).
    """
    errors: list[ValidationError] = []
    cst_icms = _get(record, 11)

    if not cst_icms:
        return errors

    # CST pode ser 3 dígitos (origem + tributação) ou 2 dígitos (só tributação)
    if len(cst_icms) == 3:
        origem = cst_icms[0]
        tributacao = cst_icms[1:]
        # Verificar se é CSOSN (Simples Nacional)
        if cst_icms in _CSOSN_VALIDOS:
            return errors
        # Origem deve ser 0-8
        if origem not in "012345678":
            errors.append(_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"Origem do CST ICMS '{origem}' inválida (deve ser 0-8).",
            ))
        if tributacao not in _CST_ICMS_TRIBUTACAO:
            errors.append(_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"Tributação do CST ICMS '{tributacao}' inválida.",
            ))
    elif len(cst_icms) == 2:
        if cst_icms not in _CST_ICMS_TRIBUTACAO:
            errors.append(_error(
                record, "CST_ICMS", "CST_INVALIDO",
                f"CST ICMS '{cst_icms}' não é um código válido.",
            ))
    # CSTs com 1 dígito ou >3 dígitos são inválidos
    elif cst_icms not in _CSOSN_VALIDOS:
        errors.append(_error(
            record, "CST_ICMS", "CST_INVALIDO",
            f"CST ICMS '{cst_icms}' formato inválido (esperado 2 ou 3 dígitos).",
        ))

    return errors


# ──────────────────────────────────────────────
# Validação de isenções/exclusões
# ──────────────────────────────────────────────

def _validate_exemptions_c170(record: SpedRecord) -> list[ValidationError]:
    """Valida consistência entre CST e valores de ICMS.

    Se CST indica isenção (40,41,50), BC e VL_ICMS devem ser zero.
    Se CST indica tributação (00,10,20,70,90), BC e VL_ICMS devem existir.
    """
    errors: list[ValidationError] = []
    cst_icms = _get(record, 11)

    if not cst_icms:
        return errors

    # Extrair parte da tributação (últimos 2 dígitos)
    trib = cst_icms[-2:] if len(cst_icms) >= 2 else cst_icms

    vl_bc_icms = _float(_get(record, 12))
    vl_icms = _float(_get(record, 14))

    # CST isento/não-tributado: valores devem ser zero
    if trib in _CST_ICMS_ISENTO and (vl_bc_icms > 0 or vl_icms > 0):
        errors.append(_error(
            record, "VL_ICMS", "ISENCAO_INCONSISTENTE",
            f"CST {cst_icms} indica isenção/não-tributação, "
            f"mas BC={vl_bc_icms:.2f} e ICMS={vl_icms:.2f} (deveriam ser zero).",
        ))

    # CST tributado: se BC > 0, ICMS não pode ser zero
    if trib in _CST_ICMS_TRIBUTADO and vl_bc_icms > 0 and vl_icms == 0:
        errors.append(_error(
            record, "VL_ICMS", "TRIBUTACAO_INCONSISTENTE",
            f"CST {cst_icms} indica tributação, BC={vl_bc_icms:.2f} "
            f"mas ICMS=0 (deveria ter valor).",
        ))

    return errors


# ──────────────────────────────────────────────
# Bloco H - Estoque vs Cadastro
# ──────────────────────────────────────────────

def _validate_bloco_h(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Valida Bloco H (inventário).

    H010: itens do inventário
    - COD_ITEM do H010 deve existir no 0200 (cadastro de itens)
    - VL_ITEM do H010 não pode ser negativo
    - QTD do H010 não pode ser negativa

    H010 campos (0-based): 0:REG, 1:COD_ITEM, 2:UNID, 3:QTD, 4:VL_UNIT, 5:VL_ITEM
    """
    errors: list[ValidationError] = []

    h010_records = groups.get("H010", [])
    if not h010_records:
        return errors

    # Cadastro de itens
    cod_items_cadastro = set()
    for rec in groups.get("0200", []):
        cod = _get(rec, 1)
        if cod:
            cod_items_cadastro.add(cod)

    for rec in h010_records:
        cod_item = _get(rec, 1)
        qtd = _float(_get(rec, 3))
        vl_item = _float(_get(rec, 5))

        # Item deve existir no cadastro
        if cod_item and cod_items_cadastro and cod_item not in cod_items_cadastro:
            errors.append(_error(
                rec, "COD_ITEM", "REF_INEXISTENTE",
                f"COD_ITEM '{cod_item}' no H010 não existe no cadastro 0200.",
            ))

        # Quantidade não pode ser negativa
        if qtd < 0:
            errors.append(_error(
                rec, "QTD", "VALOR_NEGATIVO",
                f"Quantidade negativa no inventário: {qtd}.",
            ))

        # Valor não pode ser negativo
        if vl_item < 0:
            errors.append(_error(
                rec, "VL_ITEM", "VALOR_NEGATIVO",
                f"Valor negativo no inventário: {vl_item}.",
            ))

    return errors
