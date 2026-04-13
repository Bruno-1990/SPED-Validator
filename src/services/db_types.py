"""Tipos e helpers da conexao de auditoria: SQLite nativo ou wrapper PostgreSQL."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, TypeAlias, Union

if TYPE_CHECKING:
    from src.services.database_pg import PgConnection

# Union com forward ref: em runtime nao exige import de PgConnection; mypy resolve via TYPE_CHECKING.
AuditConnection: TypeAlias = Union[sqlite3.Connection, "PgConnection"]


def is_pg(db: AuditConnection) -> bool:
    """Detecta se a conexao e PostgreSQL (PgConnection)."""
    return type(db).__name__ == "PgConnection"


def json_text(column: str, key: str) -> str:
    """Retorna expressao SQL para extrair campo JSON como texto.

    PG:     column->>'key'
    SQLite: json_extract(column, '$.key')

    Nota: requer chamada com is_pg() para selecionar o dialeto correto.
    Uso: sql = f"SELECT {json_text_pg('fields_json', 'CST_ICMS')} FROM ..."
    """
    # Padrao PG (producao). Para SQLite (testes), usar json_text_sqlite.
    return f"{column}->>'{key}'"


def json_text_sqlite(column: str, key: str) -> str:
    """Expressao SQLite para extrair campo JSON como texto."""
    return f"json_extract({column}, '$.{key}')"


def json_field(db: AuditConnection, column: str, key: str) -> str:
    """Retorna expressao SQL para extrair campo JSON como texto, adaptada ao banco."""
    if is_pg(db):
        return f"{column}->>'{key}'"
    return f"json_extract({column}, '$.{key}')"


__all__ = ["AuditConnection", "is_pg", "json_field"]
