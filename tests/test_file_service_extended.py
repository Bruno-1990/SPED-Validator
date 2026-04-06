"""Extended tests for src/services/file_service.py — covering uncovered paths.

Targets lines: 97-118 (clear_audit), 128-141 (clear_all_audit), 175-176 (_handle_retificador), 256 (_row_to_dict).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.services.database import init_audit_db
from src.services.file_service import (
    _row_to_dict,
    clear_all_audit,
    clear_audit,
    get_file,
    list_files,
)

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def audit_db(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "audit.db"
    conn = init_audit_db(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_file_raw(db: sqlite3.Connection, **kwargs) -> int:
    """Insert a sped_files row directly."""
    defaults = {
        "filename": "test.txt",
        "hash_sha256": "abc123",
        "status": "validated",
        "total_records": 50,
        "total_errors": 3,
    }
    defaults.update(kwargs)
    cur = db.execute(
        """INSERT INTO sped_files
           (filename, hash_sha256, status, total_records, total_errors)
           VALUES (?, ?, ?, ?, ?)""",
        (defaults["filename"], defaults["hash_sha256"], defaults["status"],
         defaults["total_records"], defaults["total_errors"]),
    )
    db.commit()
    return cur.lastrowid


def _insert_error(db: sqlite3.Connection, file_id: int, **kwargs) -> int:
    defaults = {
        "line_number": 10,
        "register": "C170",
        "error_type": "CAMPO_INVALIDO",
        "severity": "error",
        "message": "Campo invalido",
    }
    defaults.update(kwargs)
    cur = db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, error_type, severity, message)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, defaults["line_number"], defaults["register"],
         defaults["error_type"], defaults["severity"], defaults["message"]),
    )
    db.commit()
    return cur.lastrowid


def _insert_record(db: sqlite3.Connection, file_id: int, line_number: int = 1) -> int:
    cur = db.execute(
        """INSERT INTO sped_records
           (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, 'C170', 'C', '{}', '|C170|1|ITEM|')""",
        (file_id, line_number),
    )
    db.commit()
    return cur.lastrowid


def _insert_correction(db: sqlite3.Connection, file_id: int, record_id: int | None = None) -> int:
    if record_id is None:
        record_id = _insert_record(db, file_id)
    cur = db.execute(
        """INSERT INTO corrections
           (file_id, record_id, field_no, field_name, old_value, new_value)
           VALUES (?, ?, 14, 'VL_ICMS', '100', '120')""",
        (file_id, record_id),
    )
    db.commit()
    return cur.lastrowid


def _insert_cross_validation(db: sqlite3.Connection, file_id: int) -> int:
    cur = db.execute(
        """INSERT INTO cross_validations
           (file_id, validation_type, severity, message)
           VALUES (?, 'CRUZAMENTO', 'error', 'Divergencia')""",
        (file_id,),
    )
    db.commit()
    return cur.lastrowid


def _insert_audit_log(db: sqlite3.Connection, file_id: int) -> int:
    cur = db.execute(
        """INSERT INTO audit_log (file_id, action, details)
           VALUES (?, 'test', 'test entry')""",
        (file_id,),
    )
    db.commit()
    return cur.lastrowid


# ──────────────────────────────────────────────
# clear_audit — lines 97-118
# ──────────────────────────────────────────────

class TestClearAudit:
    def test_clear_audit_removes_errors(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file_raw(audit_db, total_errors=5)
        _insert_error(audit_db, file_id)
        _insert_error(audit_db, file_id, line_number=20)
        _insert_error(audit_db, file_id, line_number=30)

        removed = clear_audit(audit_db, file_id)
        assert removed == 3

        # Verify errors are gone
        count = audit_db.execute(
            "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        assert count == 0

    def test_clear_audit_removes_corrections(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file_raw(audit_db)
        _insert_correction(audit_db, file_id)

        clear_audit(audit_db, file_id)

        count = audit_db.execute(
            "SELECT COUNT(*) FROM corrections WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        assert count == 0

    def test_clear_audit_removes_cross_validations(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file_raw(audit_db)
        _insert_cross_validation(audit_db, file_id)

        clear_audit(audit_db, file_id)

        count = audit_db.execute(
            "SELECT COUNT(*) FROM cross_validations WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        assert count == 0

    def test_clear_audit_resets_status(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file_raw(audit_db, status="validated", total_errors=10)

        clear_audit(audit_db, file_id)

        row = audit_db.execute(
            "SELECT status, total_errors FROM sped_files WHERE id = ?", (file_id,)
        ).fetchone()
        assert row[0] == "parsed"
        assert row[1] == 0

    def test_clear_audit_nonexistent_file(self, audit_db: sqlite3.Connection) -> None:
        result = clear_audit(audit_db, 9999)
        assert result == -1

    def test_clear_audit_logs_action(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file_raw(audit_db)
        _insert_error(audit_db, file_id)

        clear_audit(audit_db, file_id)

        logs = audit_db.execute(
            "SELECT action, details FROM audit_log WHERE file_id = ? AND action = 'clear_audit'",
            (file_id,),
        ).fetchall()
        assert len(logs) >= 1
        assert "limpo" in logs[-1][1].lower() or "removidos" in logs[-1][1].lower()


# ──────────────────────────────────────────────
# clear_all_audit — lines 128-141
# ──────────────────────────────────────────────

class TestClearAllAudit:
    def test_clear_all_audit_removes_everything(self, audit_db: sqlite3.Connection) -> None:
        fid1 = _insert_file_raw(audit_db, hash_sha256="hash1")
        fid2 = _insert_file_raw(audit_db, hash_sha256="hash2")
        _insert_error(audit_db, fid1)
        _insert_error(audit_db, fid2)
        _insert_correction(audit_db, fid1)
        _insert_cross_validation(audit_db, fid2)
        _insert_audit_log(audit_db, fid1)

        removed = clear_all_audit(audit_db)
        assert removed == 2

        # All tables should be empty
        for table in ("validation_errors", "corrections", "cross_validations", "audit_log"):
            count = audit_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]  # noqa: S608
            assert count == 0, f"{table} should be empty"

    def test_clear_all_audit_resets_all_files(self, audit_db: sqlite3.Connection) -> None:
        _fid1 = _insert_file_raw(audit_db, hash_sha256="h1", status="validated", total_errors=5)
        _fid2 = _insert_file_raw(audit_db, hash_sha256="h2", status="validated", total_errors=10)

        clear_all_audit(audit_db)

        rows = audit_db.execute("SELECT status, total_errors FROM sped_files").fetchall()
        for row in rows:
            assert row[0] == "parsed"
            assert row[1] == 0

    def test_clear_all_audit_no_errors(self, audit_db: sqlite3.Connection) -> None:
        _insert_file_raw(audit_db)
        removed = clear_all_audit(audit_db)
        assert removed == 0


# ──────────────────────────────────────────────
# _row_to_dict — line 256
# ──────────────────────────────────────────────

class TestRowToDict:
    def test_row_to_dict_basic(self) -> None:
        row = (1, "test.txt", "abc123", "2024-01-01", None)
        result = _row_to_dict(row)
        assert result["col_0"] == 1
        assert result["col_1"] == "test.txt"
        assert result["col_4"] is None

    def test_row_to_dict_empty(self) -> None:
        result = _row_to_dict(())
        assert result == {}

    def test_row_to_dict_single(self) -> None:
        result = _row_to_dict((42,))
        assert result == {"col_0": 42}


# ──────────────────────────────────────────────
# get_file / list_files with tuple rows (no Row factory)
# ──────────────────────────────────────────────

class TestFileAccessWithTupleRows:
    def test_get_file_with_tuple_rows(self, tmp_path: Path) -> None:
        """When row_factory is not set, get_file should use _row_to_dict."""
        path = tmp_path / "audit.db"
        conn = init_audit_db(path)
        # Do NOT set conn.row_factory = sqlite3.Row
        fid = _insert_file_raw(conn, hash_sha256="testhash")
        result = get_file(conn, fid)
        assert result is not None
        # Should have col_X keys
        assert "col_0" in result or "id" in result
        conn.close()

    def test_list_files_with_tuple_rows(self, tmp_path: Path) -> None:
        path = tmp_path / "audit.db"
        conn = init_audit_db(path)
        _insert_file_raw(conn, hash_sha256="h1")
        _insert_file_raw(conn, hash_sha256="h2")
        result = list_files(conn)
        assert len(result) == 2
        conn.close()
