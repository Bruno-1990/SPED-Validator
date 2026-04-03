"""Service de upload e gerenciamento de arquivos SPED."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..models import SpedRecord
from ..parser import parse_sped_file


def upload_file(db: sqlite3.Connection, filepath: str | Path) -> int:
    """Processa upload de arquivo SPED: hash, parse, metadados.

    Retorna o file_id criado.
    """
    filepath = Path(filepath)
    raw_bytes = filepath.read_bytes()
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Verificar duplicata
    existing = db.execute(
        "SELECT id FROM sped_files WHERE hash_sha256 = ?", (sha256,)
    ).fetchone()
    if existing:
        return existing[0] if isinstance(existing, tuple) else existing["id"]

    # Criar registro do arquivo
    cursor = db.execute(
        """INSERT INTO sped_files (filename, hash_sha256, status)
           VALUES (?, ?, 'parsing')""",
        (filepath.name, sha256),
    )
    file_id = cursor.lastrowid
    assert file_id is not None
    db.commit()

    # Parsear
    records = parse_sped_file(filepath)

    # Extrair metadados do 0000
    _update_metadata(db, file_id, records)

    # Persistir registros
    _insert_records(db, file_id, records)

    # Atualizar status
    db.execute(
        "UPDATE sped_files SET status = 'parsed', total_records = ? WHERE id = ?",
        (len(records), file_id),
    )
    db.commit()

    # Log
    _log(db, file_id, "upload", f"Arquivo {filepath.name} processado: {len(records)} registros.")

    return file_id


def get_file(db: sqlite3.Connection, file_id: int) -> dict | None:
    """Retorna metadados de um arquivo."""
    row = db.execute("SELECT * FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        return None
    return dict(row) if hasattr(row, "keys") else _row_to_dict(row)


def list_files(db: sqlite3.Connection) -> list[dict]:
    """Lista todos os arquivos processados."""
    rows = db.execute("SELECT * FROM sped_files ORDER BY upload_date DESC").fetchall()
    return [dict(r) if hasattr(r, "keys") else _row_to_dict(r) for r in rows]


def delete_file(db: sqlite3.Connection, file_id: int) -> bool:
    """Remove arquivo e todos os dados associados."""
    existing = db.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not existing:
        return False

    db.execute("DELETE FROM audit_log WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM cross_validations WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM sped_records WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM sped_files WHERE id = ?", (file_id,))
    db.commit()
    return True


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _update_metadata(db: sqlite3.Connection, file_id: int, records: list[SpedRecord]) -> None:
    """Extrai metadados do registro 0000."""
    for rec in records:
        if rec.register == "0000" and len(rec.fields) >= 7:
            db.execute(
                """UPDATE sped_files
                   SET period_start = ?, period_end = ?, company_name = ?, cnpj = ?
                   WHERE id = ?""",
                (
                    rec.fields[3] if len(rec.fields) > 3 else None,
                    rec.fields[4] if len(rec.fields) > 4 else None,
                    rec.fields[5] if len(rec.fields) > 5 else None,
                    rec.fields[6] if len(rec.fields) > 6 else None,
                    file_id,
                ),
            )
            break


def _insert_records(db: sqlite3.Connection, file_id: int, records: list[SpedRecord]) -> None:
    """Persiste registros parseados no banco."""
    for rec in records:
        block = rec.register[0] if rec.register else "?"
        db.execute(
            """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, rec.line_number, rec.register, block, json.dumps(rec.fields), rec.raw_line),
        )
    db.commit()


def _log(db: sqlite3.Connection, file_id: int, action: str, details: str) -> None:
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, action, details),
    )
    db.commit()


def _row_to_dict(row: tuple) -> dict:
    """Converte tuple para dict com nomes genéricos."""
    return {f"col_{i}": v for i, v in enumerate(row)}
