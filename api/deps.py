"""Dependências compartilhadas da API."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path

from src.services.database import get_connection, init_audit_db

# Caminhos configuráveis
AUDIT_DB_PATH = Path("db/audit.db")
DOC_DB_PATH = Path("db/sped.db")


def _ensure_db() -> None:
    """Garante que o banco de auditoria existe."""
    AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = init_audit_db(AUDIT_DB_PATH)
    conn.close()


def get_db() -> Generator[sqlite3.Connection, None, None]:
    """Dependency injection do banco de auditoria."""
    _ensure_db()
    conn = get_connection(AUDIT_DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


def get_doc_db_path() -> str | None:
    """Retorna caminho do banco de documentação, se existir."""
    if DOC_DB_PATH.exists():
        return str(DOC_DB_PATH)
    return None
