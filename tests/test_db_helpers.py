"""Testes do helper scalar_or (bug #1 hardening defensivo).

Descoberta durante a auditoria: todas as chamadas atuais a `.fetchone()[0]` usam
SELECT COUNT(*), que sempre retorna uma linha. Na pratica nao havia crash real,
mas o helper previne regressao caso a query mude no futuro para uma que possa
retornar None.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

import pytest

from src.services.db_helpers import scalar_or


@pytest.fixture
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE t (id INTEGER PRIMARY KEY, val INTEGER);
        INSERT INTO t (id, val) VALUES (1, 42);
        INSERT INTO t (id, val) VALUES (2, NULL);
    """)
    yield c
    c.close()


class TestScalarOr:
    def test_returns_value_when_row_exists(self, conn):
        cur = conn.execute("SELECT val FROM t WHERE id = 1")
        assert scalar_or(cur) == 42

    def test_returns_default_when_no_rows(self, conn):
        cur = conn.execute("SELECT val FROM t WHERE id = 999")
        assert scalar_or(cur) == 0

    def test_returns_custom_default_when_no_rows(self, conn):
        cur = conn.execute("SELECT val FROM t WHERE id = 999")
        assert scalar_or(cur, default=-1) == -1

    def test_returns_default_when_value_is_null(self, conn):
        cur = conn.execute("SELECT val FROM t WHERE id = 2")
        assert scalar_or(cur) == 0

    def test_works_with_count_star(self, conn):
        cur = conn.execute("SELECT COUNT(*) FROM t")
        assert scalar_or(cur) == 2

    def test_works_with_row_factory_dict_like(self, conn):
        # sqlite3.Row suporta indexacao por numero e por nome
        cur = conn.execute("SELECT val FROM t WHERE id = 1")
        assert scalar_or(cur) == 42
