"""Tests for src/services/auto_correction_service.py.

Covers:
- auto_correct_errors with no rows
- Prohibited field => suggested only
- Prohibited error_type => suggested only
- Non-deterministic type => suggested only
- Deterministic type => applied via apply_correction
- Missing expected_value / record_id / field_no => skipped
"""

from __future__ import annotations

import json
import sqlite3
import warnings

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)

import pytest  # noqa: E402

from src.services.auto_correction_service import auto_correct_errors  # noqa: E402


def _create_schema(db: sqlite3.Connection) -> None:
    """Create minimal tables needed for auto_correct_errors."""
    db.executescript("""
        CREATE TABLE IF NOT EXISTS sped_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            hash_sha256 TEXT NOT NULL,
            upload_date TEXT DEFAULT (datetime('now')),
            period_start TEXT, period_end TEXT,
            company_name TEXT, cnpj TEXT, uf TEXT,
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
            expected_value TEXT,
            auto_correctable INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (file_id) REFERENCES sped_files(id),
            FOREIGN KEY (record_id) REFERENCES sped_records(id)
        );

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
            justificativa TEXT,
            correction_type TEXT,
            rule_id TEXT,
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
    """)


def _setup_file_and_record(db: sqlite3.Connection, file_id: int = 1) -> int:
    """Insert a sped_file and sped_record, return record_id."""
    db.execute(
        "INSERT INTO sped_files (id, filename, hash_sha256) VALUES (?, 'test.txt', 'abc')",
        (file_id,),
    )
    fields = {"REG": "C190", "CST_ICMS": "000", "CFOP": "5102",
              "ALIQ_ICMS": "18", "VL_OPR": "1000", "VL_BC_ICMS": "1000",
              "VL_ICMS": "180", "VL_BC_ICMS_ST": "0", "VL_ICMS_ST": "0",
              "VL_RED_BC": "0", "VL_IPI": "0", "COD_OBS": ""}
    db.execute(
        """INSERT INTO sped_records (id, file_id, line_number, register, block, fields_json, raw_line)
           VALUES (1, ?, 10, 'C190', 'C', ?, '|C190|...|')""",
        (file_id, json.dumps(fields)),
    )
    db.commit()
    return 1


def _insert_error(db: sqlite3.Connection, file_id: int, record_id: int,
                  error_type: str, field_name: str = "VL_ICMS",
                  field_no: int = 7, expected_value: str = "200",
                  value: str = "180") -> int:
    """Insert a validation error and return its id."""
    cur = db.execute(
        """INSERT INTO validation_errors
           (file_id, record_id, line_number, register, field_no, field_name,
            value, error_type, severity, message, status, auto_correctable, expected_value)
           VALUES (?, ?, 10, 'C190', ?, ?, ?, ?, 'error', 'Test error', 'open', 1, ?)""",
        (file_id, record_id, field_no, field_name, value, error_type, expected_value),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    _create_schema(conn)
    yield conn
    conn.close()


class TestAutoCorrectNoRows:
    def test_no_errors_returns_empty(self, db):
        _setup_file_and_record(db)
        results = auto_correct_errors(db, file_id=1)
        assert results == []


class TestProhibitedField:
    def test_prohibited_field_returns_suggestion(self, db):
        """Error with field_name in _PROHIBITED_AUTO_FIELDS => suggested=True."""
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="CST_ICMS",
                      field_no=2, expected_value="010")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["suggested"] is True
        assert results[0]["applied"] is False

    def test_prohibited_cfop(self, db):
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="CFOP",
                      field_no=3, expected_value="5101")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["suggested"] is True


class TestProhibitedErrorType:
    def test_prohibited_error_type_returns_suggestion(self, db):
        """Error with error_type in _PROHIBITED_ERROR_TYPES => suggested=True."""
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "CST_HIPOTESE", field_name="VL_ICMS",
                      expected_value="200")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["suggested"] is True
        assert results[0]["applied"] is False


class TestNonDeterministicType:
    def test_non_deterministic_returns_suggestion(self, db):
        """Error type not in _DETERMINISTIC_TYPES => suggested only."""
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "SOME_OTHER_TYPE", field_name="VL_ICMS",
                      expected_value="200")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["suggested"] is True
        assert results[0]["applied"] is False


class TestDeterministicAutoCorrection:
    def test_deterministic_type_applies_correction(self, db):
        """CALCULO_DIVERGENTE with safe field => applied=True."""
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="VL_ICMS",
                      field_no=7, expected_value="200")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["applied"] is True
        assert results[0]["suggested"] is False
        assert results[0]["new_value"] == "200"

        # Verify the corrections table was updated
        corr = db.execute(
            "SELECT applied_by FROM corrections WHERE file_id = 1"
        ).fetchone()
        assert corr is not None
        assert corr[0] == "auto"

    def test_soma_divergente_applies(self, db):
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "SOMA_DIVERGENTE", field_name="VL_ICMS",
                      field_no=7, expected_value="300")
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 1
        assert results[0]["applied"] is True


class TestSkippedRows:
    def test_missing_expected_value(self, db):
        _setup_file_and_record(db)
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="VL_ICMS",
                      expected_value="")
        # Row with empty expected_value is skipped
        results = auto_correct_errors(db, file_id=1)
        # Should be skipped entirely (the continue branch)
        assert len(results) == 0

    def test_null_expected_value(self, db):
        _setup_file_and_record(db)
        # Insert with NULL expected_value
        db.execute(
            """INSERT INTO validation_errors
               (file_id, record_id, line_number, register, field_no, field_name,
                value, error_type, severity, message, status, auto_correctable, expected_value)
               VALUES (1, 1, 10, 'C190', 7, 'VL_ICMS', '180', 'CALCULO_DIVERGENTE',
                       'error', 'Test', 'open', 1, NULL)""",
        )
        db.commit()
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 0

    def test_missing_field_no(self, db):
        _setup_file_and_record(db)
        db.execute(
            """INSERT INTO validation_errors
               (file_id, record_id, line_number, register, field_no, field_name,
                value, error_type, severity, message, status, auto_correctable, expected_value)
               VALUES (1, 1, 10, 'C190', NULL, 'VL_ICMS', '180', 'CALCULO_DIVERGENTE',
                       'error', 'Test', 'open', 1, '200')""",
        )
        db.commit()
        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 0


class TestMultipleErrors:
    def test_mix_of_types(self, db):
        """Multiple errors: one deterministic, one prohibited, one non-deterministic."""
        _setup_file_and_record(db)
        # Deterministic
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="VL_ICMS",
                      field_no=7, expected_value="200")
        # Prohibited field
        _insert_error(db, 1, 1, "CALCULO_DIVERGENTE", field_name="CST_ICMS",
                      field_no=2, expected_value="010")
        # Non-deterministic
        _insert_error(db, 1, 1, "UNKNOWN_TYPE", field_name="VL_OPR",
                      field_no=5, expected_value="999")

        results = auto_correct_errors(db, file_id=1)
        assert len(results) == 3

        applied = [r for r in results if r["applied"]]
        suggested = [r for r in results if r["suggested"]]
        assert len(applied) == 1
        assert len(suggested) == 2
