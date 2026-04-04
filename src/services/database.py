"""Schema e gerenciamento do banco de auditoria SPED."""

from __future__ import annotations

import sqlite3
from pathlib import Path

_AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS sped_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    hash_sha256 TEXT NOT NULL,
    upload_date TEXT DEFAULT (datetime('now')),
    period_start TEXT,
    period_end TEXT,
    company_name TEXT,
    cnpj TEXT,
    uf TEXT,
    total_records INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    status TEXT DEFAULT 'uploaded'
);

CREATE TABLE IF NOT EXISTS sped_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    block TEXT NOT NULL,
    parent_id INTEGER,
    fields_json TEXT NOT NULL,
    raw_line TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

CREATE INDEX IF NOT EXISTS idx_sped_records_file ON sped_records(file_id);
CREATE INDEX IF NOT EXISTS idx_sped_records_register ON sped_records(register);
CREATE INDEX IF NOT EXISTS idx_sped_records_status ON sped_records(status);

CREATE TABLE IF NOT EXISTS validation_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    record_id INTEGER,
    line_number INTEGER NOT NULL,
    register TEXT NOT NULL,
    field_no INTEGER,
    field_name TEXT,
    value TEXT,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    doc_suggestion TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id),
    FOREIGN KEY (record_id) REFERENCES sped_records(id)
);

CREATE INDEX IF NOT EXISTS idx_val_errors_file ON validation_errors(file_id);
CREATE INDEX IF NOT EXISTS idx_val_errors_type ON validation_errors(error_type);

CREATE TABLE IF NOT EXISTS cross_validations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    validation_type TEXT NOT NULL,
    source_register TEXT,
    source_line INTEGER,
    target_register TEXT,
    target_line INTEGER,
    expected_value TEXT,
    actual_value TEXT,
    difference REAL,
    severity TEXT NOT NULL DEFAULT 'error',
    message TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);

CREATE INDEX IF NOT EXISTS idx_cross_val_file ON cross_validations(file_id);

CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    record_id INTEGER NOT NULL,
    field_no INTEGER NOT NULL,
    field_name TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL,
    error_id INTEGER,
    applied_by TEXT DEFAULT 'user',
    applied_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id),
    FOREIGN KEY (record_id) REFERENCES sped_records(id),
    FOREIGN KEY (error_id) REFERENCES validation_errors(id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (file_id) REFERENCES sped_files(id)
);
"""


_MIGRATIONS: dict[int, list[str]] = {
    1: [
        "ALTER TABLE validation_errors ADD COLUMN friendly_message TEXT",
        "ALTER TABLE validation_errors ADD COLUMN legal_basis TEXT",
        "ALTER TABLE validation_errors ADD COLUMN expected_value TEXT",
        "ALTER TABLE validation_errors ADD COLUMN auto_correctable INTEGER DEFAULT 0",
        "ALTER TABLE sped_files ADD COLUMN validation_stage TEXT",
        "ALTER TABLE sped_files ADD COLUMN auto_corrections_applied INTEGER DEFAULT 0",
    ],
}


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Executa migrações incrementais usando PRAGMA user_version."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    for version in sorted(_MIGRATIONS):
        if version > current:
            for stmt in _MIGRATIONS[version]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower():
                        raise
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()


def init_audit_db(db_path: str | Path) -> sqlite3.Connection:
    """Cria o banco de auditoria com todas as tabelas."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_AUDIT_SCHEMA)
    _run_migrations(conn)
    return conn


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Abre conexão com o banco de auditoria existente."""
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    _run_migrations(conn)
    return conn
