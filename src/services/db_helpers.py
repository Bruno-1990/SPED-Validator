"""Helpers para acesso seguro ao banco de dados.

`scalar_or` protege contra queries que podem retornar zero linhas ou NULL —
previne `TypeError: 'NoneType' object is not subscriptable` ao acessar
`.fetchone()[0]` diretamente.
"""

from __future__ import annotations

from typing import Any


def scalar_or(cursor: Any, default: Any = 0) -> Any:
    """Retorna primeira coluna da primeira linha, ou `default` se nao houver linhas
    ou se o valor for NULL.

    Suporta cursores que retornam tupla ou sqlite3.Row.
    """
    row = cursor.fetchone()
    if row is None:
        return default
    try:
        value = row[0]
    except (IndexError, KeyError):
        return default
    return default if value is None else value
