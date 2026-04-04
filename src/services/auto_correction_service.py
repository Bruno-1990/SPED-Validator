"""Motor de auto-correção determinística para erros SPED."""

from __future__ import annotations

import json
import sqlite3

from .correction_service import apply_correction


def auto_correct_errors(
    db: sqlite3.Connection,
    file_id: int,
    doc_db_path: str | None = None,
) -> list[dict]:
    """Aplica correções automáticas para erros determinísticos.

    Três categorias de correção:
    1. Recálculo numérico — CALCULO_DIVERGENTE/SOMA_DIVERGENTE com expected_value
    2. Contagem — CONTAGEM_DIVERGENTE no Bloco 9 com expected_value
    3. Valor único — INVALID_VALUE onde valid_values tem exatamente 1 opção

    Retorna lista de correções aplicadas.
    """
    corrections_applied: list[dict] = []

    # Buscar erros auto-corrigíveis
    rows = db.execute(
        """SELECT ve.id, ve.record_id, ve.register, ve.field_no, ve.field_name,
                  ve.value, ve.error_type, ve.expected_value
           FROM validation_errors ve
           WHERE ve.file_id = ? AND ve.status = 'open' AND ve.auto_correctable = 1
           ORDER BY ve.line_number""",
        (file_id,),
    ).fetchall()

    for row in rows:
        error_id = row[0]
        record_id = row[1]
        register = row[2]
        field_no = row[3]
        field_name = row[4] or ""
        current_value = row[5] or ""
        error_type = row[6]
        expected_value = row[7]

        if not expected_value or not record_id or not field_no:
            continue

        # Aplicar correção usando o serviço existente
        success = apply_correction(
            db=db,
            file_id=file_id,
            record_id=record_id,
            field_no=field_no,
            field_name=field_name,
            new_value=expected_value,
            error_id=error_id,
        )

        if success:
            # Marcar como auto-corrigido (applied_by já é 'user' por padrão,
            # vamos atualizar para 'auto')
            db.execute(
                """UPDATE corrections
                   SET applied_by = 'auto'
                   WHERE file_id = ? AND record_id = ? AND field_no = ?
                   AND applied_by = 'user'
                   ORDER BY applied_at DESC LIMIT 1""",
                (file_id, record_id, field_no),
            )
            db.commit()

            corrections_applied.append({
                "error_id": error_id,
                "record_id": record_id,
                "register": register,
                "field_no": field_no,
                "field_name": field_name,
                "old_value": current_value,
                "new_value": expected_value,
                "error_type": error_type,
            })

    # Buscar e corrigir INVALID_VALUE com valor único
    corrections_applied.extend(
        _auto_correct_single_valid_value(db, file_id, doc_db_path)
    )

    return corrections_applied


def _auto_correct_single_valid_value(
    db: sqlite3.Connection,
    file_id: int,
    doc_db_path: str | None,
) -> list[dict]:
    """Corrige INVALID_VALUE quando há exatamente 1 valor válido."""
    corrections: list[dict] = []

    if not doc_db_path:
        return corrections

    # Buscar erros INVALID_VALUE que ainda estão abertos
    rows = db.execute(
        """SELECT id, record_id, register, field_no, field_name, value
           FROM validation_errors
           WHERE file_id = ? AND status = 'open' AND error_type = 'INVALID_VALUE'
           ORDER BY line_number""",
        (file_id,),
    ).fetchall()

    if not rows:
        return corrections

    # Carregar definições de campo para consultar valid_values
    doc_conn = sqlite3.connect(doc_db_path)
    field_defs_cache: dict[tuple[str, int], list[str] | None] = {}

    for row in rows:
        error_id, record_id, register, field_no, field_name, value = (
            row[0], row[1], row[2], row[3], row[4] or "", row[5] or "",
        )

        if not record_id or not field_no:
            continue

        # Cache de valid_values por (register, field_no)
        cache_key = (register, field_no)
        if cache_key not in field_defs_cache:
            fd_row = doc_conn.execute(
                """SELECT valid_values FROM register_fields
                   WHERE register = ? AND field_no = ?""",
                (register, field_no),
            ).fetchone()
            if fd_row and fd_row[0]:
                field_defs_cache[cache_key] = json.loads(fd_row[0])
            else:
                field_defs_cache[cache_key] = None

        valid_values = field_defs_cache[cache_key]

        # Só auto-corrige se há exatamente 1 valor válido
        if valid_values and len(valid_values) == 1:
            correct_value = valid_values[0]

            success = apply_correction(
                db=db,
                file_id=file_id,
                record_id=record_id,
                field_no=field_no,
                field_name=field_name,
                new_value=correct_value,
                error_id=error_id,
            )

            if success:
                db.execute(
                    """UPDATE corrections
                       SET applied_by = 'auto'
                       WHERE file_id = ? AND record_id = ? AND field_no = ?
                       AND applied_by = 'user'
                       ORDER BY applied_at DESC LIMIT 1""",
                    (file_id, record_id, field_no),
                )
                db.commit()

                corrections.append({
                    "error_id": error_id,
                    "record_id": record_id,
                    "register": register,
                    "field_no": field_no,
                    "field_name": field_name,
                    "old_value": value,
                    "new_value": correct_value,
                    "error_type": "INVALID_VALUE",
                })

    doc_conn.close()
    return corrections
