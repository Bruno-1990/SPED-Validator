"""Service de upload e gerenciamento de arquivos SPED."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .db_types import AuditConnection

from ..models import SpedRecord
from ..parser import parse_sped_file
from .context_builder import build_context, _determine_regime_by_cst, _is_pg


def upload_file(db: AuditConnection, filepath: str | Path) -> int:
    """Processa upload de arquivo SPED: hash, parse, metadados.

    Retorna o file_id criado.
    Nota: build_context completo (MySQL, beneficios) roda na validacao, nao no upload.
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

    # Detecção rápida de regime (só CST, sem consulta MySQL/ReferenceLoader)
    regime, _src = _determine_regime_by_cst(db, file_id)
    db.execute(
        "UPDATE sped_files SET regime_tributario = ? WHERE id = ?",
        (regime.value, file_id),
    )

    # Atualizar status
    db.execute(
        "UPDATE sped_files SET status = 'parsed', total_records = ? WHERE id = ?",
        (len(records), file_id),
    )
    db.commit()

    _log(
        db, file_id, "upload",
        f"Arquivo {filepath.name} processado: {len(records)} registros. Regime: {regime.value}.",
    )

    return file_id


def get_file(db: AuditConnection, file_id: int) -> dict | None:
    """Retorna metadados de um arquivo."""
    row = db.execute("SELECT * FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if row is None:
        return None
    return dict(row) if hasattr(row, "keys") else _row_to_dict(row)


def list_files(db: AuditConnection) -> list[dict]:
    """Lista todos os arquivos processados."""
    rows = db.execute("SELECT * FROM sped_files ORDER BY upload_date DESC").fetchall()
    return [dict(r) if hasattr(r, "keys") else _row_to_dict(r) for r in rows]


def clear_audit(db: AuditConnection, file_id: int) -> int:
    """Limpa todos os dados de validação/audit de um arquivo, mantendo o arquivo e registros.

    Remove: validation_runs (e filhas), validation_errors, cross_validations, corrections, audit_log.
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

    # Filhas de validation_runs primeiro
    _safe_delete(db, "DELETE FROM fiscal_context_snapshots WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))
    _safe_delete(db, "DELETE FROM coverage_gaps WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))
    _safe_delete(db, "DELETE FROM xml_match_index WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))
    _safe_delete(db, "DELETE FROM validation_runs WHERE file_id = ?", (file_id,))
    _safe_delete(db, "DELETE FROM finding_resolutions WHERE file_id = ?", (str(file_id),))

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


def clear_all_audit(db: AuditConnection) -> int:
    """Limpa todos os dados de validação/audit de TODOS os arquivos.

    Remove: validation_runs (e filhas), validation_errors, cross_validations, corrections, audit_log.
    Reseta status para 'parsed' e zera contadores.
    Retorna quantidade total de erros removidos.
    """
    row = db.execute("SELECT COUNT(*) FROM validation_errors").fetchone()
    removed = row[0] if row else 0

    # Filhas de validation_runs primeiro
    _safe_delete(db, "DELETE FROM fiscal_context_snapshots", ())
    _safe_delete(db, "DELETE FROM coverage_gaps", ())
    _safe_delete(db, "DELETE FROM xml_match_index", ())
    _safe_delete(db, "DELETE FROM validation_runs", ())
    _safe_delete(db, "DELETE FROM finding_resolutions", ())

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


def delete_file(db: AuditConnection, file_id: int) -> bool:
    """Remove arquivo e todos os dados associados.

    Ordem de deleção respeita foreign keys (filhas antes das pais).
    """
    existing = db.execute("SELECT id FROM sped_files WHERE id = ?", (file_id,)).fetchone()
    if not existing:
        return False

    # Nível 3: tabelas que referenciam validation_runs / nfe_xmls
    _safe_delete(db, "DELETE FROM fiscal_context_snapshots WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))
    _safe_delete(db, "DELETE FROM coverage_gaps WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))
    _safe_delete(db, "DELETE FROM xml_match_index WHERE run_id IN (SELECT id FROM validation_runs WHERE file_id = ?)", (file_id,))

    # Nível 2: tabelas que referenciam sped_files diretamente (com filhas já limpas)
    _safe_delete(db, "DELETE FROM validation_runs WHERE file_id = ?", (file_id,))

    nfe_ids = _safe_select(db, "SELECT id FROM nfe_xmls WHERE file_id = ?", (file_id,))
    for nfe_id in nfe_ids:
        _safe_delete(db, "DELETE FROM nfe_itens WHERE nfe_id = ?", (nfe_id,))
    _safe_delete(db, "DELETE FROM nfe_cruzamento WHERE file_id = ?", (file_id,))
    _safe_delete(db, "DELETE FROM nfe_xmls WHERE file_id = ?", (file_id,))

    _safe_delete(db, "DELETE FROM finding_resolutions WHERE file_id = ?", (str(file_id),))
    db.execute("DELETE FROM audit_log WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM corrections WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM cross_validations WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM validation_errors WHERE file_id = ?", (file_id,))
    db.execute("DELETE FROM sped_records WHERE file_id = ?", (file_id,))

    # Nível 1: sped_file_versions e auto-referência
    _safe_delete(db, "DELETE FROM sped_file_versions WHERE original_file_id = ? OR retificador_file_id = ?", (file_id, file_id))
    db.execute("UPDATE sped_files SET original_file_id = NULL WHERE original_file_id = ?", (file_id,))
    db.execute("DELETE FROM sped_files WHERE id = ?", (file_id,))
    db.commit()
    return True


def _is_pg(db) -> bool:
    from .db_types import is_pg
    return is_pg(db)


def _safe_select(db, sql: str, params: tuple) -> list:
    """Executa SELECT retornando lista de valores da primeira coluna.

    Usa SAVEPOINT para não abortar a transação se a tabela não existir.
    """
    try:
        db.execute("SAVEPOINT _safe_sel")
        rows = db.execute(sql, params).fetchall()
        db.execute("RELEASE SAVEPOINT _safe_sel")
        return [r[0] for r in rows]
    except Exception:
        try:
            db.execute("ROLLBACK TO SAVEPOINT _safe_sel")
        except Exception:
            pass
        return []


def _safe_delete(db, sql: str, params: tuple | None = None) -> None:
    """Executa DELETE ignorando tabela inexistente.

    Usa SAVEPOINT para que erros não abortem a transação inteira.
    """
    try:
        db.execute("SAVEPOINT _safe_del")
        if params:
            db.execute(sql, params)
        else:
            db.execute(sql)
        db.execute("RELEASE SAVEPOINT _safe_del")
    except Exception as e:
        try:
            db.execute("ROLLBACK TO SAVEPOINT _safe_del")
        except Exception:
            pass
        err = str(e).lower()
        if "does not exist" in err or "no such table" in err:
            return
        raise


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _handle_retificador(db: AuditConnection, file_id: int, records: list[SpedRecord]) -> None:
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


def _update_metadata(db: AuditConnection, file_id: int, records: list[SpedRecord]) -> None:
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


def _insert_records(db: AuditConnection, file_id: int, records: list[SpedRecord]) -> None:
    """Persiste registros parseados no banco (fields_json como dict nomeado)."""
    rows = [
        (file_id, rec.line_number, rec.register,
         rec.register[0] if rec.register else "?",
         json.dumps(rec.fields, ensure_ascii=False), rec.raw_line)
        for rec in records
    ]
    db.executemany(
        """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    db.commit()


def _log(db: AuditConnection, file_id: int, action: str, details: str) -> None:
    db.execute(
        "INSERT INTO audit_log (file_id, action, details) VALUES (?, ?, ?)",
        (file_id, action, details),
    )
    db.commit()


def _row_to_dict(row: tuple) -> dict:
    """Converte tuple para dict com nomes genéricos."""
    return {f"col_{i}": v for i, v in enumerate(row)}
