"""Validador de cruzamento entre blocos SPED EFD."""

from __future__ import annotations

from ..models import SpedRecord, ValidationError
from ..parser import group_by_register

TOLERANCE = 0.02


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
    source_reg: str,
    source_line: int,
    error_type: str,
    message: str,
    field_name: str = "",
) -> ValidationError:
    return ValidationError(
        line_number=source_line,
        register=source_reg,
        field_no=0,
        field_name=field_name,
        value="",
        error_type=error_type,
        message=message,
    )


# ──────────────────────────────────────────────
# API pública
# ──────────────────────────────────────────────

def validate_cross_blocks(records: list[SpedRecord]) -> list[ValidationError]:
    """Executa todas as validações de cruzamento entre blocos."""
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
        cod = _get(rec, 1)
        if cod:
            cod_parts.add(cod)

    cod_items = set()
    for rec in groups.get("0200", []):
        cod = _get(rec, 1)
        if cod:
            cod_items.add(cod)

    # Verificar referências em C100 (COD_PART no campo 3)
    for rec in groups.get("C100", []):
        cod_part = _get(rec, 3)
        if cod_part and cod_parts and cod_part not in cod_parts:
            errors.append(_error(
                "C100", rec.line_number, "REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no C100 não existe no 0150.",
                field_name="COD_PART",
            ))

    # Verificar referências em C170 (COD_ITEM no campo 2)
    for rec in groups.get("C170", []):
        cod_item = _get(rec, 2)
        if cod_item and cod_items and cod_item not in cod_items:
            errors.append(_error(
                "C170", rec.line_number, "REF_INEXISTENTE",
                f"COD_ITEM '{cod_item}' referenciado no C170 não existe no 0200.",
                field_name="COD_ITEM",
            ))

    # Verificar referências em D100 (COD_PART no campo 3)
    for rec in groups.get("D100", []):
        cod_part = _get(rec, 3)
        if cod_part and cod_parts and cod_part not in cod_parts:
            errors.append(_error(
                "D100", rec.line_number, "REF_INEXISTENTE",
                f"COD_PART '{cod_part}' referenciado no D100 não existe no 0150.",
                field_name="COD_PART",
            ))

    return errors


# ──────────────────────────────────────────────
# Bloco C vs E - Documentos vs Apuração
# ──────────────────────────────────────────────

def validate_c_vs_e(groups: dict[str, list[SpedRecord]]) -> list[ValidationError]:
    """Cruza totais dos C190 com valores declarados no E110.

    C190 com CFOP de saída (5xxx, 6xxx, 7xxx) → débitos
    C190 com CFOP de entrada (1xxx, 2xxx, 3xxx) → créditos
    """
    errors: list[ValidationError] = []

    c190_records = groups.get("C190", [])
    e110_records = groups.get("E110", [])

    if not c190_records or not e110_records:
        return errors

    # Somar ICMS dos C190 separando por tipo de operação
    soma_debitos = 0.0
    soma_creditos = 0.0

    for rec in c190_records:
        cfop = _get(rec, 2)
        vl_icms = _float(_get(rec, 6))

        if cfop and cfop[0] in ("5", "6", "7"):
            soma_debitos += vl_icms
        elif cfop and cfop[0] in ("1", "2", "3"):
            soma_creditos += vl_icms

    # Comparar com E110
    for e110 in e110_records:
        vl_tot_debitos = _float(_get(e110, 1))
        vl_tot_creditos = _float(_get(e110, 5))

        if abs(soma_debitos - vl_tot_debitos) > TOLERANCE:
            errors.append(_error(
                "E110", e110.line_number, "CRUZAMENTO_DIVERGENTE",
                f"VL_TOT_DEBITOS do E110 ({vl_tot_debitos:.2f}) diverge da soma "
                f"dos C190 de saída ({soma_debitos:.2f}).",
                field_name="VL_TOT_DEBITOS",
            ))

        if abs(soma_creditos - vl_tot_creditos) > TOLERANCE:
            errors.append(_error(
                "E110", e110.line_number, "CRUZAMENTO_DIVERGENTE",
                f"VL_TOT_CREDITOS do E110 ({vl_tot_creditos:.2f}) diverge da soma "
                f"dos C190 de entrada ({soma_creditos:.2f}).",
                field_name="VL_TOT_CREDITOS",
            ))

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
        reg_name = _get(rec, 1)
        declared_count = int(_float(_get(rec, 2)))

        if reg_name in real_counts:
            actual = real_counts[reg_name]
            if actual != declared_count:
                errors.append(_error(
                    "9900", rec.line_number, "CONTAGEM_DIVERGENTE",
                    f"Registro {reg_name}: contagem declarada={declared_count}, real={actual}.",
                    field_name="QTD_REG",
                ))

    # Verificar 9999 (total de linhas)
    for rec in groups.get("9999", []):
        declared_total = int(_float(_get(rec, 1)))
        actual_total = len(records)
        if declared_total != actual_total:
            errors.append(_error(
                "9999", rec.line_number, "CONTAGEM_DIVERGENTE",
                f"QTD_LIN declarada={declared_total}, real={actual_total}.",
                field_name="QTD_LIN",
            ))

    return errors
