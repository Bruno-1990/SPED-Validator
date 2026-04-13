"""Dependências compartilhadas da API."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

from api.auth import verify_api_key  # noqa: F401 — re-export para uso nos routers
from src.services.database import get_connection, init_audit_db
from src.services.db_types import AuditConnection

# Caminho SQLite (fallback para testes sem DATABASE_URL)
AUDIT_DB_PATH = Path(os.environ.get("SPED_DB_PATH", "db/audit.db"))
DOC_DB_PATH = Path("db/sped.db")

_db_ready = False


def _ensure_db() -> None:
    """Garante que o banco existe. PG: noop. SQLite fallback: cria arquivo."""
    global _db_ready
    if _db_ready:
        return
    if not os.environ.get("DATABASE_URL"):
        # Fallback SQLite (testes locais)
        AUDIT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = init_audit_db(AUDIT_DB_PATH)
        conn.close()
    _db_ready = True


def get_db() -> Generator[AuditConnection, None, None]:
    """Dependency injection do banco de auditoria (PostgreSQL)."""
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
