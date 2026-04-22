"""Camada de abstração PostgreSQL compatível com a interface sqlite3.

O wrapper converte automaticamente:
- Placeholders: ? → %s
- JSONB: psycopg2 retorna dicts para JSONB, mas o código espera strings JSON.
  Configuramos o driver para retornar JSON como string (sem auto-parse).
- Row factory: retorna rows dict-like (como sqlite3.Row).
- conn.execute(): sqlite3 permite; psycopg2 precisa de cursor. O wrapper abstrai.

Uso:
    from src.services.database_pg import get_pg_connection
    conn = get_pg_connection()  # mesma interface de sqlite3.Connection
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
import psycopg2.extensions

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuracao default via env
# ──────────────────────────────────────────────

_DEFAULT_DSN = "postgresql://sped:sped2026@localhost:5434/sped_audit"


def _get_dsn() -> str:
    return os.environ.get("DATABASE_URL", _DEFAULT_DSN)


def _apply_pg_schema_patches(raw_conn) -> None:
    """ALTERs idempotentes para bases PostgreSQL criadas antes de novas colunas."""
    cur = raw_conn.cursor()
    try:
        cur.execute(
            "ALTER TABLE sped_files ADD COLUMN IF NOT EXISTS xml_crossref_completed_at TIMESTAMP"
        )

        # Motor de Cruzamento XC — tabelas (migration 16)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS suggested_action_types (
                code TEXT PRIMARY KEY,
                label_pt TEXT NOT NULL,
                description TEXT
            )
        """)
        cur.execute("""
            INSERT INTO suggested_action_types (code, label_pt, description) VALUES
                ('corrigir_no_sped', 'Corrigir no SPED', 'Campo do arquivo EFD deve ser corrigido'),
                ('revisar_xml_emissor', 'Revisar XML com emissor', 'Inconsistencia na NF-e emitida'),
                ('revisar_parametrizacao_erp', 'Revisar parametrizacao ERP', 'Regra incorreta no sistema'),
                ('revisar_cadastro', 'Revisar cadastro', 'Dado cadastral divergente ou ausente'),
                ('revisar_beneficio', 'Revisar beneficio fiscal', 'Aplicacao incorreta de beneficio'),
                ('revisar_apuracao', 'Revisar apuracao', 'Erro ou omissao no bloco de apuracao'),
                ('investigar', 'Investigar', 'Indicio nao conclusivo')
            ON CONFLICT (code) DO NOTHING
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cross_validation_findings (
                id SERIAL PRIMARY KEY,
                file_id INTEGER NOT NULL,
                document_scope_id INTEGER,
                rule_id TEXT NOT NULL,
                legacy_rule_id TEXT,
                rule_version TEXT,
                reference_pack_version TEXT,
                benefit_context_version TEXT,
                layout_version_detected TEXT,
                config_hash TEXT,
                error_type TEXT NOT NULL,
                rule_outcome TEXT NOT NULL,
                tipo_irregularidade TEXT,
                severity TEXT NOT NULL,
                confidence TEXT,
                sped_register TEXT,
                sped_field TEXT,
                value_sped TEXT,
                xml_field TEXT,
                value_xml TEXT,
                description TEXT,
                evidence TEXT,
                regime_context TEXT,
                benefit_context TEXT,
                suggested_action TEXT NOT NULL DEFAULT 'investigar',
                root_cause_group TEXT,
                is_derived INTEGER DEFAULT 0,
                risk_score REAL,
                technical_risk_score REAL,
                fiscal_impact_estimate REAL,
                action_priority TEXT,
                review_status TEXT DEFAULT 'novo',
                reviewed_by TEXT,
                reviewed_at TIMESTAMP,
                review_reason TEXT,
                review_evidence_ref TEXT,
                chave_nfe TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("ALTER TABLE cross_validation_findings ADD COLUMN IF NOT EXISTS chave_nfe TEXT")

        # cBenef e vICMSDeson nos itens XML (NT 2019.001)
        cur.execute("ALTER TABLE nfe_itens ADD COLUMN IF NOT EXISTS cbenef TEXT DEFAULT ''")
        cur.execute("ALTER TABLE nfe_itens ADD COLUMN IF NOT EXISTS vl_icms_deson REAL DEFAULT 0")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_xvf_file ON cross_validation_findings(file_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_xvf_rule ON cross_validation_findings(file_id, rule_id)")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS field_equivalence_map (
                id SERIAL PRIMARY KEY,
                register_sped TEXT NOT NULL,
                field_sped TEXT NOT NULL,
                xml_xpath TEXT,
                calculo TEXT,
                fonte TEXT,
                tolerancia_abs REAL DEFAULT 0.02,
                tolerancia_rel REAL DEFAULT 0.0,
                leiaute_min TEXT,
                leiaute_max TEXT,
                vigencia_ini DATE,
                vigencia_fim DATE
            )
        """)

        # Migration 17: Hash de deduplicacao (UNIQUE por file_id)
        cur.execute("ALTER TABLE validation_errors ADD COLUMN IF NOT EXISTS error_hash TEXT")
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ve_file_hash ON validation_errors(file_id, error_hash) WHERE error_hash IS NOT NULL")

        raw_conn.commit()
    except Exception as exc:
        raw_conn.rollback()
        logger.warning(
            "Patch de schema PostgreSQL ignorado (tabela ausente ou sem permissao): %s",
            exc,
        )
    finally:
        cur.close()


# ──────────────────────────────────────────────
# Conversao de placeholders ? → %s
# ──────────────────────────────────────────────

# Regex que encontra '?' fora de strings entre aspas simples
_PLACEHOLDER_RE = re.compile(
    r"""'[^']*'|(\?)""",
    re.DOTALL,
)


def _convert_placeholders(sql: str) -> str:
    """Converte ? para %s, ignorando ? dentro de strings literais.

    Tambem escapa % literais (ex: LIKE '%texto%') para %%,
    evitando que psycopg2 interprete como formatacao.

    Se o SQL ja usa %s (formato PG nativo), retorna sem modificar.
    """
    # Se ja usa %s como placeholder, nao converter
    if "%s" in sql and "?" not in sql:
        return sql

    def _replacer(m: re.Match) -> str:
        if m.group(1):  # é um ? fora de string
            return "\x00PS\x00"  # marcador temporario
        return m.group(0)  # é parte de uma string literal, manter

    # 1. Marcar placeholders ? com marcador unico
    result = _PLACEHOLDER_RE.sub(_replacer, sql)
    # 2. Escapar todos os % literais restantes (LIKE, etc.)
    result = result.replace("%", "%%")
    # 3. Restaurar marcadores para %s
    result = result.replace("\x00PS\x00", "%s")
    return result


# ──────────────────────────────────────────────
# DictRow — row dict-like compativel com sqlite3.Row
# ──────────────────────────────────────────────

class DictRow:
    """Row que suporta acesso por indice (tuple) e por nome (dict)."""

    __slots__ = ("_data", "_keys", "_values")

    def __init__(self, keys: list[str], values: tuple):
        self._keys = keys
        self._values = values
        self._data = dict(zip(keys, values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key, default=None):
        return self._data.get(key, default)

    def __repr__(self):
        return f"DictRow({self._data})"


# ──────────────────────────────────────────────
# CursorWrapper — cursor com conversao automatica
# ──────────────────────────────────────────────

class CursorWrapper:
    """Wrapper sobre psycopg2 cursor com conversao de placeholders e rows."""

    def __init__(self, cursor):
        self._cursor = cursor
        self._description = None

    def execute(self, sql: str, params=None):
        converted = _convert_placeholders(sql)
        if params is not None:
            # Converter lista para tupla (psycopg2 exige tupla)
            if isinstance(params, list):
                params = tuple(params)
            self._cursor.execute(converted, params)
        else:
            self._cursor.execute(converted)
        self._description = self._cursor.description
        return self

    def executemany(self, sql: str, params_list):
        converted = _convert_placeholders(sql)
        self._cursor.executemany(converted, params_list)
        return self

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._description:
            keys = [d[0] for d in self._description]
            return DictRow(keys, row)
        return row

    def fetchall(self):
        rows = self._cursor.fetchall()
        if not rows or not self._description:
            return rows
        keys = [d[0] for d in self._description]
        return [DictRow(keys, r) for r in rows]

    @property
    def lastrowid(self):
        """Compatibilidade com sqlite3: retorna o ultimo id inserido."""
        try:
            self._cursor.execute("SELECT lastval()")
            return self._cursor.fetchone()[0]
        except Exception:
            return None

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def close(self):
        self._cursor.close()

    def __iter__(self):
        return iter(self.fetchall())


# ──────────────────────────────────────────────
# ConnectionWrapper — conn compativel com sqlite3.Connection
# ──────────────────────────────────────────────

class PgConnection:
    """Wrapper sobre psycopg2 connection com interface sqlite3-compativel.

    Principais adaptacoes:
    - conn.execute(sql, params) funciona direto (cria cursor interno)
    - Placeholders ? convertidos para %s
    - Rows retornadas como DictRow (dict-like + tuple-like)
    - JSONB retornado como string (nao como dict Python)
    """

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or _get_dsn()
        self._conn = psycopg2.connect(self._dsn)
        self._conn.set_session(autocommit=False)
        _apply_pg_schema_patches(self._conn)
        # Fazer JSONB retornar como string (compatibilidade com json.loads existente)
        psycopg2.extras.register_default_json(self._conn, loads=lambda x: x)
        psycopg2.extras.register_default_jsonb(self._conn, loads=lambda x: x)

    def execute(self, sql: str, params=None):
        """Executa SQL retornando CursorWrapper (como sqlite3.Connection.execute)."""
        cursor = self._conn.cursor()
        wrapper = CursorWrapper(cursor)
        wrapper.execute(sql, params)
        return wrapper

    def executemany(self, sql: str, params_list):
        """Executa SQL com multiplos params."""
        cursor = self._conn.cursor()
        wrapper = CursorWrapper(cursor)
        wrapper.executemany(sql, params_list)
        return wrapper

    def executescript(self, sql: str):
        """Executa multiplas statements (compatibilidade sqlite3)."""
        cursor = self._conn.cursor()
        cursor.execute(sql)
        self._conn.commit()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def cursor(self):
        return CursorWrapper(self._conn.cursor())

    @property
    def row_factory(self):
        return None

    @row_factory.setter
    def row_factory(self, value):
        # Ignorar — DictRow já é o default
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        self.close()


# ──────────────────────────────────────────────
# Factory functions
# ──────────────────────────────────────────────

def get_pg_connection(dsn: str | None = None) -> PgConnection:
    """Cria conexão PostgreSQL com interface sqlite3-compativel."""
    return PgConnection(dsn)


@contextmanager
def pg_transaction(dsn: str | None = None):
    """Context manager com commit/rollback automatico."""
    conn = get_pg_connection(dsn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
