"""Validador de campos de registros SPED EFD."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from .models import RegisterField, SpedRecord, ValidationError


def load_field_definitions(db_path: str | Path) -> dict[str, list[RegisterField]]:
    """Carrega todas as definições de campos do banco em memória.

    Retorna dict[register_code] → lista de RegisterField ordenada por field_no.
    """
    conn = sqlite3.connect(str(db_path))
    rows = conn.execute(
        """SELECT register, field_no, field_name, field_type, field_size,
                  decimals, required, valid_values, description
           FROM register_fields ORDER BY register, field_no"""
    ).fetchall()
    conn.close()

    defs: dict[str, list[RegisterField]] = {}
    for row in rows:
        rf = RegisterField(
            register=row[0],
            field_no=row[1],
            field_name=row[2],
            field_type=row[3],
            field_size=row[4],
            decimals=row[5],
            required=row[6],
            valid_values=RegisterField.valid_values_from_json(row[7]),
            description=row[8],
        )
        defs.setdefault(rf.register, []).append(rf)

    return defs


# Registros de abertura/encerramento têm layout fixo (REG + QTD_LIN ou IND_MOV).
# Nunca devem ser validados com mais de 2 campos, independente do que o banco diga.
_STRUCTURAL_REGISTERS = re.compile(r"^[A-Z](001|990)$|^9999$")


def validate_records(
    records: list[SpedRecord],
    field_defs: dict[str, list[RegisterField]],
) -> list[ValidationError]:
    """Valida todos os registros contra as definições de campos.

    Retorna lista de erros encontrados.
    """
    errors: list[ValidationError] = []

    for record in records:
        # Registros de abertura/encerramento têm apenas REG + QTD_LIN/IND_MOV.
        # Pular validação campo-a-campo para evitar falsos positivos.
        if _STRUCTURAL_REGISTERS.match(record.register):
            continue

        reg_defs = field_defs.get(record.register)
        if not reg_defs:
            continue  # Registro sem definição na documentação
        errors.extend(_validate_record(record, reg_defs))

    return errors


def _validate_record(
    record: SpedRecord,
    field_defs: list[RegisterField],
) -> list[ValidationError]:
    """Valida um único registro contra suas definições de campo."""
    errors: list[ValidationError] = []

    for fdef in field_defs:
        # Campo ausente
        if fdef.field_name not in record.fields:
            if fdef.required == "O":
                errors.append(ValidationError(
                    line_number=record.line_number,
                    register=record.register,
                    field_no=fdef.field_no,
                    field_name=fdef.field_name,
                    value="",
                    error_type="MISSING_REQUIRED",
                    message=f"Campo obrigatório '{fdef.field_name}' (posição {fdef.field_no}) ausente.",
                ))
            continue

        value = record.fields[fdef.field_name].strip()

        # Campo obrigatório vazio
        if fdef.required == "O" and not value:
            errors.append(ValidationError(
                line_number=record.line_number,
                register=record.register,
                field_no=fdef.field_no,
                field_name=fdef.field_name,
                value=value,
                error_type="MISSING_REQUIRED",
                message=f"Campo obrigatório '{fdef.field_name}' está vazio.",
            ))
            continue

        if not value:
            continue  # Campo opcional vazio — ok

        # Validar tipo numérico
        if fdef.field_type == "N":
            cleaned = value.replace(",", ".")
            if not _is_numeric(cleaned):
                errors.append(ValidationError(
                    line_number=record.line_number,
                    register=record.register,
                    field_no=fdef.field_no,
                    field_name=fdef.field_name,
                    value=value,
                    error_type="WRONG_TYPE",
                    message=f"Campo '{fdef.field_name}' deveria ser numérico, mas contém '{value}'.",
                ))
                continue

        # Validar tamanho
        if fdef.field_size and len(value) > fdef.field_size:
            errors.append(ValidationError(
                line_number=record.line_number,
                register=record.register,
                field_no=fdef.field_no,
                field_name=fdef.field_name,
                value=value,
                error_type="WRONG_SIZE",
                message=(
                    f"Campo '{fdef.field_name}' excede tamanho máximo "
                    f"({len(value)} > {fdef.field_size})."
                ),
            ))

        # Validar valores válidos
        if fdef.valid_values and value not in fdef.valid_values:
            errors.append(ValidationError(
                line_number=record.line_number,
                register=record.register,
                field_no=fdef.field_no,
                field_name=fdef.field_name,
                value=value,
                error_type="INVALID_VALUE",
                message=(
                    f"Campo '{fdef.field_name}' contém valor '{value}' inválido. "
                    f"Valores aceitos: {fdef.valid_values}"
                ),
            ))

    return errors


def _is_numeric(value: str) -> bool:
    """Verifica se um valor é numérico (inteiro ou decimal)."""
    try:
        float(value)
        return True
    except ValueError:
        return False


def generate_report(
    errors: list[ValidationError],
    docs: dict[int, list[str]] | None = None,
) -> str:
    """Gera relatório de validação em Markdown.

    Args:
        errors: Lista de erros encontrados.
        docs: Opcional — dict[error_index] → lista de trechos de documentação.
    """
    if not errors:
        return "# Relatório de Validação SPED\n\nNenhum erro encontrado.\n"

    lines = [
        "# Relatório de Validação SPED\n",
        f"**Total de erros:** {len(errors)}\n",
        "---\n",
    ]

    # Agrupar por tipo de erro
    by_type: dict[str, list[ValidationError]] = {}
    for e in errors:
        by_type.setdefault(e.error_type, []).append(e)

    for error_type, type_errors in sorted(by_type.items()):
        lines.append(f"\n## {error_type} ({len(type_errors)} ocorrências)\n")

        for _i, e in enumerate(type_errors):
            lines.append(
                f"### Linha {e.line_number} | {e.register} | "
                f"Campo {e.field_no:02d} ({e.field_name})\n"
            )
            lines.append(f"- **Valor encontrado:** `{e.value}`")
            lines.append(f"- **Problema:** {e.message}")

            # Adicionar documentação se disponível
            error_idx = errors.index(e)
            if docs and error_idx in docs:
                lines.append("\n**Documentação relevante:**\n")
                for doc in docs[error_idx]:
                    lines.append(f"> {doc}\n")

            lines.append("")

    return "\n".join(lines)
