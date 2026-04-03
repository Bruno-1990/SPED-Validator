"""Service de correção de registros SPED."""

from __future__ import annotations

import json
import sqlite3


def apply_correction(
    db: sqlite3.Connection,
    file_id: int,
    record_id: int,
    field_no: int,
    field_name: str,
    new_value: str,
    error_id: int | None = None,
) -> bool:
    """Aplica correção em um campo de um registro SPED.

    Atualiza o fields_json do registro, salva histórico e marca erro como corrigido.
    """
    row = db.execute(
        "SELECT fields_json FROM sped_records WHERE id = ? AND file_id = ?",
        (record_id, file_id),
    ).fetchone()
    if not row:
        return False

    fields = json.loads(row[0])
    idx = field_no - 1  # field_no é 1-based

    if idx < 0 or idx >= len(fields):
        return False

    old_value = fields[idx]
    fields[idx] = new_value

    # Atualizar registro
    new_raw = "|" + "|".join(fields) + "|"
    db.execute(
        """UPDATE sped_records
           SET fields_json = ?, raw_line = ?, status = 'corrected'
           WHERE id = ?""",
        (json.dumps(fields), new_raw, record_id),
    )

    # Salvar histórico
    db.execute(
        """INSERT INTO corrections
           (file_id, record_id, field_no, field_name, old_value, new_value, error_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (file_id, record_id, field_no, field_name, old_value, new_value, error_id),
    )

    # Marcar erro como corrigido (se informado)
    if error_id:
        db.execute(
            "UPDATE validation_errors SET status = 'corrected' WHERE id = ?",
            (error_id,),
        )

    db.commit()

    # Log
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, "correction",
         f"Registro {record_id}, campo {field_no} ({field_name}): '{old_value}' -> '{new_value}'"),
    )
    db.commit()

    return True


def get_corrections(db: sqlite3.Connection, file_id: int) -> list[dict]:
    """Lista todas as correções aplicadas em um arquivo."""
    rows = db.execute(
        """SELECT * FROM corrections WHERE file_id = ? ORDER BY applied_at DESC""",
        (file_id,),
    ).fetchall()
    return [dict(r) if hasattr(r, "keys") else {} for r in rows]


def undo_correction(db: sqlite3.Connection, correction_id: int) -> bool:
    """Desfaz uma correção, restaurando o valor original."""
    row = db.execute(
        "SELECT file_id, record_id, field_no, old_value, error_id FROM corrections WHERE id = ?",
        (correction_id,),
    ).fetchone()
    if not row:
        return False

    _file_id, record_id, field_no, old_value, error_id = row[0], row[1], row[2], row[3], row[4]

    # Restaurar valor no registro
    rec_row = db.execute(
        "SELECT fields_json FROM sped_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not rec_row:
        return False

    fields = json.loads(rec_row[0])
    idx = field_no - 1
    if 0 <= idx < len(fields):
        fields[idx] = old_value

    new_raw = "|" + "|".join(fields) + "|"
    db.execute(
        "UPDATE sped_records SET fields_json = ?, raw_line = ?, status = 'pending' WHERE id = ?",
        (json.dumps(fields), new_raw, record_id),
    )

    # Reabrir erro
    if error_id:
        db.execute(
            "UPDATE validation_errors SET status = 'open' WHERE id = ?",
            (error_id,),
        )

    # Remover correção
    db.execute("DELETE FROM corrections WHERE id = ?", (correction_id,))
    db.commit()

    return True
