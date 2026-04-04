"""Fixtures compartilhadas para todos os testes."""

from __future__ import annotations

import sqlite3
import warnings

# Pydantic emite UserWarning quando um campo se chama "register"
# (ABCMeta.register). O campo é intencional — é o registro SPED.
warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)
from pathlib import Path

import pytest

from src.models import RegisterField, SpedRecord
from src.parser import parse_sped_file
from src.indexer import init_db

# Diretório das fixtures
FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ──────────────────────────────────────────────
# Caminhos dos arquivos SPED
# ──────────────────────────────────────────────

@pytest.fixture
def sped_minimal_path() -> Path:
    return FIXTURES_DIR / "sped_minimal.txt"


@pytest.fixture
def sped_valid_path() -> Path:
    return FIXTURES_DIR / "sped_valid.txt"


@pytest.fixture
def sped_errors_path() -> Path:
    return FIXTURES_DIR / "sped_errors.txt"


# ──────────────────────────────────────────────
# Registros parseados
# ──────────────────────────────────────────────

@pytest.fixture
def minimal_records(sped_minimal_path: Path) -> list[SpedRecord]:
    return parse_sped_file(sped_minimal_path)


@pytest.fixture
def valid_records(sped_valid_path: Path) -> list[SpedRecord]:
    return parse_sped_file(sped_valid_path)


@pytest.fixture
def error_records(sped_errors_path: Path) -> list[SpedRecord]:
    return parse_sped_file(sped_errors_path)


# ──────────────────────────────────────────────
# Banco de dados em memória
# ──────────────────────────────────────────────

@pytest.fixture
def db_conn() -> sqlite3.Connection:
    """Banco SQLite em memória com schema completo."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Banco SQLite em arquivo temporário com schema completo."""
    path = tmp_path / "test_sped.db"
    conn = init_db(str(path))
    conn.close()
    return path


# ──────────────────────────────────────────────
# Definições de campos para teste
# ──────────────────────────────────────────────

@pytest.fixture
def sample_field_defs() -> dict[str, list[RegisterField]]:
    """Definições de campos mínimas para testes de validação."""
    return {
        "0000": [
            RegisterField(register="0000", field_no=1, field_name="REG", field_type="C", field_size=4, required="O"),
            RegisterField(register="0000", field_no=2, field_name="COD_VER", field_type="N", field_size=3, required="O"),
            RegisterField(register="0000", field_no=3, field_name="COD_FIN", field_type="N", field_size=1, required="O",
                          valid_values=["0", "1", "2", "3"]),
            RegisterField(register="0000", field_no=4, field_name="DT_INI", field_type="N", field_size=8, required="O"),
            RegisterField(register="0000", field_no=5, field_name="DT_FIN", field_type="N", field_size=8, required="O"),
            RegisterField(register="0000", field_no=6, field_name="NOME", field_type="C", field_size=100, required="O"),
            RegisterField(register="0000", field_no=7, field_name="CNPJ", field_type="N", field_size=14, required="O"),
        ],
        "C100": [
            RegisterField(register="C100", field_no=1, field_name="REG", field_type="C", field_size=4, required="O"),
            RegisterField(register="C100", field_no=2, field_name="IND_OPER", field_type="C", field_size=1, required="O",
                          valid_values=["0", "1"]),
            RegisterField(register="C100", field_no=3, field_name="IND_EMIT", field_type="C", field_size=1, required="O",
                          valid_values=["0", "1"]),
            RegisterField(register="C100", field_no=4, field_name="COD_PART", field_type="C", field_size=60, required="O"),
            RegisterField(register="C100", field_no=5, field_name="COD_MOD", field_type="C", field_size=2, required="O"),
            RegisterField(register="C100", field_no=6, field_name="COD_SIT", field_type="N", field_size=2, required="O",
                          valid_values=["00", "01", "02", "03", "04", "05", "06", "07", "08"]),
            RegisterField(register="C100", field_no=7, field_name="SER", field_type="C", field_size=3, required="OC"),
            RegisterField(register="C100", field_no=8, field_name="NUM_DOC", field_type="N", field_size=9, required="O"),
            RegisterField(register="C100", field_no=9, field_name="DT_DOC", field_type="N", field_size=8, required="O"),
            RegisterField(register="C100", field_no=10, field_name="DT_E_S", field_type="N", field_size=8, required="OC"),
            RegisterField(register="C100", field_no=11, field_name="VL_DOC", field_type="N", field_size=255, required="O", decimals=2),
        ],
        "C170": [
            RegisterField(register="C170", field_no=1, field_name="REG", field_type="C", field_size=4, required="O"),
            RegisterField(register="C170", field_no=2, field_name="NUM_ITEM", field_type="N", field_size=3, required="O"),
            RegisterField(register="C170", field_no=3, field_name="COD_ITEM", field_type="C", field_size=60, required="O"),
            RegisterField(register="C170", field_no=4, field_name="DESCR_COMPL", field_type="C", field_size=255, required="OC"),
            RegisterField(register="C170", field_no=5, field_name="QTD", field_type="N", field_size=255, required="O", decimals=5),
            RegisterField(register="C170", field_no=6, field_name="UNID", field_type="C", field_size=6, required="O"),
            RegisterField(register="C170", field_no=7, field_name="VL_ITEM", field_type="N", field_size=255, required="O", decimals=2),
        ],
    }


@pytest.fixture
def db_with_field_defs(db_conn: sqlite3.Connection, sample_field_defs: dict[str, list[RegisterField]]) -> sqlite3.Connection:
    """Banco em memória com definições de campos já inseridas."""
    for fields in sample_field_defs.values():
        for f in fields:
            db_conn.execute(
                """INSERT OR REPLACE INTO register_fields
                   (register, field_no, field_name, field_type, field_size,
                    decimals, required, valid_values, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (f.register, f.field_no, f.field_name, f.field_type,
                 f.field_size, f.decimals, f.required,
                 f.valid_values_json(), f.description),
            )
    db_conn.commit()
    return db_conn
