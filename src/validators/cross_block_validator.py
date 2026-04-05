"""Validador de cruzamento entre blocos SPED EFD."""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register
from .helpers import (
    TOLERANCE,
    get_field,
    to_float,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _error(
    source_reg: str,
    source_line: int,
    error_type: str,
    message: str,
    field_name: str = "",
    expected_value: str | None = None,
    value: str = "",
) -> ValidationError:
    """Thin wrapper for cross-block errors that use register/line instead of a record."""
    return ValidationError(
        line_number=source_line,
        register=source_reg,
        field_no=0,
        field_name=field_name,
        value=value,
        error_type=error_type,
        message=message,
        expected_value=expected_value,
    )


# ──────────────────────────────────────────────
# API publica
# ──────────────────────────────────────────────

def validate_cross_blocks(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa todas as validacoes de cruzamento entre blocos."""
    groups = group_by_register(records)
    errors: list[ValidationError] = []

    errors.extend(validate_cadastro_refs(groups))
    errors.extend(validate_c_vs_e(groups))
    errors.extend(validate_block9(records, groups))

    return errors


# ──────────────────────────────────────────────
# Bloco 0 vs C/D - Cadastros referenciados
# ──────────────────────────────────────────────

def validate_cadastro_refs(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Verifica que COD_PART e COD_ITEM referenciados existem no bloco 0."""
    errors: list[ValidationError] = []

    # Coletar cadastros do bloco 0
    cod_parts = set()
    for rec in groups.get("0150", []):
        cod = get_field(rec, 1)
        if cod:
            cod_parts.add(cod)

    cod_items = set()
    for rec in groups.get("0200", []):
        cod = get_field(rec, 1)
        if cod:
            cod_items.add(cod)

    # Verificar referencias em C100 (COD_PART no campo 3)
    for rec in groups.get("C100", []):
        cod_part = get_field(rec, 3)
        if cod_part and cod_parts and cod_part not in cod_parts:
            errors.append(_error(
                "C100", rec.line_number, "REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no C100 nao existe no 0150.",
                field_name="COD_PART",
                value=cod_part,
            ))

    # Verificar referencias em C170 (COD_ITEM no campo 2)
    for rec in groups.get("C170", []):
        cod_item = get_field(rec, 2)
        if cod_item and cod_items and cod_item not in cod_items:
            errors.append(_error(
                "C170", rec.line_number, "REF_INEXISTENTE",
                f"COD_ITEM '{cod_item}' referenciado no C170 nao existe no 0200.",
                field_name="COD_ITEM",
                value=cod_item,
            ))

    # Verificar referencias em D100 (COD_PART no campo 3)
    for rec in groups.get("D100", []):
        cod_part = get_field(rec, 3)
        if cod_part and cod_parts and cod_part not in cod_parts:
            errors.append(_error(
                "D100", rec.line_number, "REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no D100 nao existe no 0150.",
                field_name="COD_PART",
                value=cod_part,
            ))

    return errors


# ──────────────────────────────────────────────
# Bloco C vs E - Documentos vs Apuracao
# ──────────────────────────────────────────────

def validate_c_vs_e(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Cruza totais dos C190 com valores declarados no E110.

    NOTA: validacao E110 completa (com deteccao de E111, D190, DIFAL)
    e feita pelo tax_recalc.recalc_e110_totals(). Esta funcao nao
    duplica essa validacao.
    """
    # Delegado ao tax_recalc.py que considera E111, D190, C390, DIFAL
    return []

    return errors


# ──────────────────────────────────────────────
# Bloco 9 - Contagem de registros
# ──────────────────────────────────────────────

def validate_block9(
    records: list[SpedRecord],
    groups: dict[str, list[SpedRecord]],
) -> list[ValidationError]:
    """Valida contagens do bloco 9.

    9900: contagem de cada tipo de registro deve bater com contagem real.
    9999: QTD_LIN deve ser igual ao total de linhas do arquivo.
    """
    errors: list[ValidationError] = []

    # Contagem real de registros por tipo
    real_counts: dict[str, int] = {}
    for rec in records:
        real_counts[rec.register] = real_counts.get(rec.register, 0) + 1

    # Verificar 9900 (contagem declarada por registro)
    for rec in groups.get("9900", []):
        reg_name = get_field(rec, 1)
        declared_count = int(to_float(get_field(rec, 2)))

        if reg_name in real_counts:
            actual = real_counts[reg_name]
            if actual != declared_count:
                errors.append(_error(
                    "9900", rec.line_number, "CONTAGEM_DIVERGENTE",
                    f"Registro {reg_name}: contagem declarada={declared_count}, real={actual}. "
                    f"Confianca: alta (100 pontos).",
                    field_name="QTD_REG",
                    expected_value=str(actual),
                    value=str(declared_count),
                ))

    # Verificar 9999 (total de linhas)
    for rec in groups.get("9999", []):
        declared_total = int(to_float(get_field(rec, 1)))
        actual_total = len(records)
        if declared_total != actual_total:
            errors.append(_error(
                "9999", rec.line_number, "CONTAGEM_DIVERGENTE",
                f"QTD_LIN declarada={declared_total}, real={actual_total}. "
                f"Confianca: alta (100 pontos).",
                field_name="QTD_LIN",
                expected_value=str(actual_total),
                value=str(declared_total),
            ))

    return errors
