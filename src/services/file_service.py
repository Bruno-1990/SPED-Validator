"""Service de upload e gerenciamento de arquivos SPED."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from ..models import SpedRecord
from ..parser import parse_sped_file
from .context_builder import build_context


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
        return int(existing[0] if isinstance(existing, tuple) else existing["id"])

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

    # Detectar COD_VER e vincular retificador
    _handle_retificador(db, file_id, records)

    # Persistir registros
    _insert_records(db, file_id, records)

    # Construir contexto e salvar regime tributário
    ctx = build_context(file_id, db)
    db.execute(
        "UPDATE sped_files SET regime_tributario = ? WHERE id = ?",
        (ctx.regime.value, file_id),
    )

    # Atualizar status
    db.execute(
        "UPDATE sped_files SET status = 'parsed', total_records = ? WHERE id = ?",
        (len(records), file_id),
    )
    db.commit()

    # Log
    msg_cliente = ""
    if ctx.cliente and ctx.cliente.encontrado:
        beneficios = ", ".join(ctx.cliente.beneficios_fiscais) if ctx.cliente.beneficios_fiscais else "nenhum"
        msg_cliente = (
            f" Cliente encontrado: {ctx.cliente.razao_social}."
            f" Regime MySQL: {ctx.cliente.regime_tributario}."
            f" Beneficios: {beneficios}."
        )
    _log(
        db, file_id, "upload",
        f"Arquivo {filepath.name} processado: {len(records)} registros. Regime: {ctx.regime.value}.{msg_cliente}",
    )

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


def clear_audit(db: sqlite3.Connection, file_id: int) -> int:
    """Limpa todos os dados de validação/audit de um arquivo, mantendo o arquivo e registros.

    Remove: validation_errors, cross_validations, corrections, audit_log.
    Reseta status para 'parsed' e zera contadores.
    Retorna quantidade de erros removidos.
    """
    existing = db.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not existing:
        return -1

    row = db.execute(
        "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?", (file_id,),
    ).fetchone()
    removed = row[0] if row else 0

    db.execute("DELETE FROM audit_log WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM cross_validations WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))
    db.execute(
        "UPDATE sped_files SET status = 'parsed', total_errors = 0, "
        "auto_corrections_applied = 0, validation_stage = NULL WHERE id = ?",
        (file_id,),
    )
    db.commit()

    _log(db, file_id, "clear_audit", f"Audit limpo: {removed} apontamentos removidos.")
    return removed


def clear_all_audit(db: sqlite3.Connection) -> int:
    """Limpa todos os dados de validação/audit de TODOS os arquivos.

    Remove: validation_errors, cross_validations, corrections, audit_log.
    Reseta status para 'parsed' e zera contadores.
    Retorna quantidade total de erros removidos.
    """
    row = db.execute("SELECT COUNT(*) FROM validation_errors").fetchone()
    removed = row[0] if row else 0

    db.execute("DELETE FROM audit_log")
    db.execute("DELETE FROM corrections")
    db.execute("DELETE FROM cross_validations")
    db.execute("DELETE FROM validation_errors")
    db.execute(
        "UPDATE sped_files SET status = 'parsed', total_errors = 0, "
        "auto_corrections_applied = 0, validation_stage = NULL",
    )
    db.commit()

    return removed


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

def _handle_retificador(db: sqlite3.Connection, file_id: int, records: list[SpedRecord]) -> None:
    """Detecta COD_FIN do registro 0000 e vincula retificador ao original.

    COD_FIN: 0=original, 1=retificadora, 2=retificadora sem alteracao de itens.
    O valor e armazenado na coluna cod_ver por compatibilidade com o modelo.
    """
    for rec in records:
        if rec.register == "0000":
            cod_fin_raw = rec.fields.get("COD_FIN", "0")
            try:
                cod_ver = int(cod_fin_raw)
            except (ValueError, TypeError):
                cod_ver = 0

            is_retificador = 1 if cod_ver > 0 else 0
            original_file_id = None

            if is_retificador:
                cnpj = rec.fields.get("CNPJ", "")
                dt_ini = rec.fields.get("DT_INI", "")
                dt_fin = rec.fields.get("DT_FIN", "")
                if cnpj and dt_ini and dt_fin:
                    row = db.execute(
                        """SELECT id FROM sped_files
                           WHERE cnpj = ? AND period_start = ? AND period_end = ?
                             AND cod_ver = 0 AND id != ?
                           ORDER BY id LIMIT 1""",
                        (cnpj, dt_ini, dt_fin, file_id),
                    ).fetchone()
                    if row:
                        original_file_id = row[0] if isinstance(row, tuple) else row["id"]
                        db.execute(
                            """INSERT INTO sped_file_versions
                               (original_file_id, retificador_file_id, cod_ver)
                               VALUES (?, ?, ?)""",
                            (original_file_id, file_id, cod_ver),
                        )

            db.execute(
                """UPDATE sped_files
                   SET cod_ver = ?, is_retificador = ?, original_file_id = ?
                   WHERE id = ?""",
                (cod_ver, is_retificador, original_file_id, file_id),
            )
            db.commit()
            break


def _update_metadata(db: sqlite3.Connection, file_id: int, records: list[SpedRecord]) -> None:
    """Extrai metadados do registro 0000."""
    for rec in records:
        if rec.register == "0000" and len(rec.fields) >= 7:
            f = rec.fields
            db.execute(
                """UPDATE sped_files
                   SET period_start = ?, period_end = ?, company_name = ?,
                       cnpj = ?, uf = ?
                   WHERE id = ?""",
                (
                    f.get("DT_INI"),
                    f.get("DT_FIN"),
                    f.get("NOME"),
                    f.get("CNPJ"),
                    f.get("UF"),
                    file_id,
                ),
            )
            break


def _insert_records(db: sqlite3.Connection, file_id: int, records: list[SpedRecord]) -> None:
    """Persiste registros parseados no banco (fields_json como dict nomeado)."""
    for rec in records:
        block = rec.register[0] if rec.register else "?"
        db.execute(
            """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (file_id, rec.line_number, rec.register, block, json.dumps(rec.fields, ensure_ascii=False), rec.raw_line),
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
