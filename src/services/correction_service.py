"""Service de correcao de registros SPED."""

from __future__ import annotations

import json
import sqlite3

from ..validators.helpers import REGISTER_FIELDS, fields_to_dict


def _ensure_dict(fields_raw: str, register: str) -> dict[str, str]:
    """Carrega fields_json suportando dict (novo) e list (legado)."""
    parsed = json.loads(fields_raw)
    if isinstance(parsed, list):
        return fields_to_dict(register, parsed)
    return dict(parsed)


def _field_name_for(register: str, field_no: int) -> str | None:
    """Converte field_no (1-based) para nome de campo usando REGISTER_FIELDS."""
    names = REGISTER_FIELDS.get(register, [])
    idx = field_no - 1
    if 0 <= idx < len(names):
        return names[idx]
    return None


def apply_correction(
    db: sqlite3.Connection,
    file_id: int,
    record_id: int,
    field_no: int,
    field_name: str,
    new_value: str,
    error_id: int | None = None,
    justificativa: str | None = None,
    correction_type: str | None = None,
    rule_id: str | None = None,
) -> bool:
    """Aplica correcao em um campo de um registro SPED.

    Atualiza o fields_json do registro, salva historico e marca erro como corrigido.
    """
    row = db.execute(
        "SELECT fields_json, register FROM sped_records WHERE id = ? AND file_id = ?",
        (record_id, file_id),
    ).fetchone()
    if not row:
        return False

    fields = _ensure_dict(row[0], row[1])

    # Resolver nome do campo: preferir field_name passado, senao converter de field_no
    fname = field_name
    if fname not in fields:
        resolved = _field_name_for(row[1], field_no)
        if resolved and resolved in fields:
            fname = resolved
        else:
            return False

    old_value = fields[fname]
    fields[fname] = new_value

    # Atualizar registro
    new_raw = "|" + "|".join(fields.values()) + "|"
    db.execute(
        """UPDATE sped_records
           SET fields_json = ?, raw_line = ?, status = 'corrected'
           WHERE id = ?""",
        (json.dumps(fields, ensure_ascii=False), new_raw, record_id),
    )

    # Salvar historico
    db.execute(
        """INSERT INTO corrections
           (file_id, record_id, field_no, field_name, old_value, new_value, error_id,
            justificativa, correction_type, rule_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, record_id, field_no, field_name, old_value, new_value, error_id,
         justificativa, correction_type, rule_id),
    )

    # Marcar erro como corrigido (se informado)
    if error_id:
        db.execute(
            "UPDATE validation_errors SET status = 'corrected' WHERE id = ?",
            (error_id,),
        )

    db.commit()

    # Log
    log_details = json.dumps({
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "justificativa": justificativa,
        "correction_type": correction_type,
        "rule_id": rule_id,
        "record_id": record_id,
        "field_no": field_no,
    }, ensure_ascii=False)
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, "correction_applied", log_details),
    )
    db.commit()

    return True


def get_corrections(db: sqlite3.Connection, file_id: int) -> list[dict]:
    """Lista todas as correcoes aplicadas em um arquivo."""
    rows = db.execute(
        """SELECT * FROM corrections WHERE file_id = ? ORDER BY applied_at DESC""",
        (file_id,),
    ).fetchall()
    return [dict(r) if hasattr(r, "keys") else {} for r in rows]


def undo_correction(db: sqlite3.Connection, correction_id: int) -> bool:
    """Desfaz uma correcao, restaurando o valor original."""
    row = db.execute(
        "SELECT file_id, record_id, field_no, old_value, error_id FROM corrections WHERE id = ?",
        (correction_id,),
    ).fetchone()
    if not row:
        return False

    _file_id, record_id, field_no, old_value, error_id = row[0], row[1], row[2], row[3], row[4]

    # Restaurar valor no registro
    rec_row = db.execute(
        "SELECT fields_json, register FROM sped_records WHERE id = ?", (record_id,)
    ).fetchone()
    if not rec_row:
        return False

    fields = _ensure_dict(rec_row[0], rec_row[1])

    # Resolver nome do campo
    fname = _field_name_for(rec_row[1], field_no)
    if fname and fname in fields:
        fields[fname] = old_value

    new_raw = "|" + "|".join(fields.values()) + "|"
    db.execute(
        "UPDATE sped_records SET fields_json = ?, raw_line = ?, status = 'pending' WHERE id = ?",
        (json.dumps(fields, ensure_ascii=False), new_raw, record_id),
    )

    # Reabrir erro
    if error_id:
        db.execute(
            "UPDATE validation_errors SET status = 'open' WHERE id = ?",
            (error_id,),
        )

    # Remover correcao
    db.execute("DELETE FROM corrections WHERE id = ?", (correction_id,))
    db.commit()

    return True
