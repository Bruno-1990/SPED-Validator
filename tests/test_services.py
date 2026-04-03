"""Testes dos services de persistência (database, file, validation, correction, export)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.services.correction_service import (
    apply_correction,
    get_corrections,
    undo_correction,
)
from src.services.database import get_connection, init_audit_db
from src.services.export_service import (
    export_corrected_sped,
    export_errors_csv,
    export_errors_json,
    export_report_markdown,
)
from src.services.file_service import (
    delete_file,
    get_file,
    list_files,
    upload_file,
)
from src.services.validation_service import (
    _severity_for,
    get_error_summary,
    get_errors,
    run_full_validation,
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


@pytest.fixture
def audit_db_path(tmp_path: Path) -> Path:
    path = tmp_path / "audit.db"
    init_audit_db(path).close()
    return path


# ──────────────────────────────────────────────
# database.py
# ──────────────────────────────────────────────

class TestInitAuditDb:
    def test_creates_all_tables(self, audit_db: sqlite3.Connection) -> None:
        tables = audit_db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        names = {t[0] for t in tables}
        assert "sped_files" in names
        assert "sped_records" in names
        assert "validation_errors" in names
        assert "cross_validations" in names
        assert "corrections" in names
        assert "audit_log" in names

    def test_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "test.db"
        conn1 = init_audit_db(path)
        conn1.close()
        conn2 = init_audit_db(path)
        conn2.close()

    def test_get_connection(self, audit_db_path: Path) -> None:
        conn = get_connection(audit_db_path)
        assert conn is not None
        conn.close()


# ──────────────────────────────────────────────
# file_service.py
# ──────────────────────────────────────────────

class TestFileService:
    def test_upload_file(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        assert file_id > 0

        info = get_file(audit_db, file_id)
        assert info is not None
        assert info["status"] == "parsed"
        assert info["total_records"] > 0

    def test_upload_extracts_metadata(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        info = get_file(audit_db, file_id)
        assert info["company_name"] == "EMPRESA VALIDA LTDA"
        assert info["cnpj"] == "11222333000181"
        assert info["period_start"] == "01012024"

    def test_upload_duplicate_returns_same_id(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        id1 = upload_file(audit_db, sped_valid_path)
        id2 = upload_file(audit_db, sped_valid_path)
        assert id1 == id2

    def test_list_files(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        upload_file(audit_db, sped_valid_path)
        files = list_files(audit_db)
        assert len(files) == 1

    def test_delete_file(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        assert delete_file(audit_db, file_id) is True
        assert get_file(audit_db, file_id) is None

    def test_delete_nonexistent(self, audit_db: sqlite3.Connection) -> None:
        assert delete_file(audit_db, 999) is False

    def test_get_nonexistent_file(self, audit_db: sqlite3.Connection) -> None:
        assert get_file(audit_db, 999) is None

    def test_records_persisted(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        count = audit_db.execute(
            "SELECT COUNT(*) FROM sped_records WHERE file_id = ?", (file_id,)
        ).fetchone()[0]
        assert count > 0

    def test_audit_log_created(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        logs = audit_db.execute(
            "SELECT * FROM audit_log WHERE file_id = ?", (file_id,)
        ).fetchall()
        assert len(logs) >= 1


# ──────────────────────────────────────────────
# validation_service.py
# ──────────────────────────────────────────────

class TestValidationService:
    def test_run_full_validation(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        errors = run_full_validation(audit_db, file_id)
        assert isinstance(errors, list)

        info = get_file(audit_db, file_id)
        assert info["status"] == "validated"

    def test_errors_persisted(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        errors = run_full_validation(audit_db, file_id)
        assert len(errors) > 0

        db_errors = get_errors(audit_db, file_id)
        assert len(db_errors) > 0

    def test_get_errors_with_filter(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        run_full_validation(audit_db, file_id)

        all_errors = get_errors(audit_db, file_id, limit=1000)
        assert len(all_errors) > 0

    def test_get_error_summary(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        run_full_validation(audit_db, file_id)

        summary = get_error_summary(audit_db, file_id)
        assert summary["total"] > 0
        assert len(summary["by_type"]) > 0

    def test_revalidation_clears_old_errors(
        self, audit_db: sqlite3.Connection, sped_valid_path: Path
    ) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        run_full_validation(audit_db, file_id)
        count1 = audit_db.execute(
            "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?", (file_id,)
        ).fetchone()[0]

        run_full_validation(audit_db, file_id)
        count2 = audit_db.execute(
            "SELECT COUNT(*) FROM validation_errors WHERE file_id = ?", (file_id,)
        ).fetchone()[0]

        assert count1 == count2  # Revalidação não duplica erros

    def test_severity_classification(self) -> None:
        assert _severity_for("CALCULO_DIVERGENTE") == "critical"
        assert _severity_for("CRUZAMENTO_DIVERGENTE") == "critical"
        assert _severity_for("DATE_OUT_OF_PERIOD") == "warning"
        assert _severity_for("REF_INEXISTENTE") == "warning"
        assert _severity_for("WRONG_TYPE") == "error"
        assert _severity_for("INVALID_VALUE") == "error"


# ──────────────────────────────────────────────
# correction_service.py
# ──────────────────────────────────────────────

class TestCorrectionService:
    def test_apply_correction(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)

        # Pegar primeiro registro
        rec = audit_db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        record_id = rec[0]

        result = apply_correction(audit_db, file_id, record_id, 2, "COD_VER", "018")
        assert result is True

        # Verificar que o campo foi atualizado
        updated = audit_db.execute(
            "SELECT fields_json, status FROM sped_records WHERE id = ?", (record_id,)
        ).fetchone()
        fields = json.loads(updated[0])
        assert fields[1] == "018"
        assert updated[1] == "corrected"

    def test_apply_correction_invalid_record(self, audit_db: sqlite3.Connection) -> None:
        assert apply_correction(audit_db, 999, 999, 1, "X", "Y") is False

    def test_apply_correction_invalid_field_no(
        self, audit_db: sqlite3.Connection, sped_minimal_path: Path
    ) -> None:
        file_id = upload_file(audit_db, sped_minimal_path)
        rec = audit_db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        assert apply_correction(audit_db, file_id, rec[0], 999, "X", "Y") is False

    def test_get_corrections(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        rec = audit_db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        apply_correction(audit_db, file_id, rec[0], 2, "FIELD", "NEW")

        corrections = get_corrections(audit_db, file_id)
        assert len(corrections) >= 1

    def test_undo_correction(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        rec = audit_db.execute(
            "SELECT id, fields_json FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        record_id = rec[0]
        original_fields = json.loads(rec[1])

        apply_correction(audit_db, file_id, record_id, 2, "FIELD", "CHANGED")

        # Pegar correction_id
        corr = audit_db.execute(
            "SELECT id FROM corrections WHERE record_id = ?", (record_id,)
        ).fetchone()
        assert undo_correction(audit_db, corr[0]) is True

        # Valor restaurado
        restored = audit_db.execute(
            "SELECT fields_json FROM sped_records WHERE id = ?", (record_id,)
        ).fetchone()
        assert json.loads(restored[0]) == original_fields

    def test_undo_nonexistent(self, audit_db: sqlite3.Connection) -> None:
        assert undo_correction(audit_db, 999) is False


# ──────────────────────────────────────────────
# export_service.py
# ──────────────────────────────────────────────

class TestExportService:
    def test_export_corrected_sped(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        sped_text = export_corrected_sped(audit_db, file_id)
        assert sped_text.startswith("|0000|")
        assert "|9999|" in sped_text
        assert sped_text.count("\n") > 0

    def test_export_report_markdown(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        run_full_validation(audit_db, file_id)

        report = export_report_markdown(audit_db, file_id)
        assert "# Relatório de Auditoria" in report
        assert "Resumo" in report
        assert "Erros por Tipo" in report

    def test_export_report_nonexistent(self, audit_db: sqlite3.Connection) -> None:
        report = export_report_markdown(audit_db, 999)
        assert "não encontrado" in report

    def test_export_errors_csv(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        run_full_validation(audit_db, file_id)

        csv_text = export_errors_csv(audit_db, file_id)
        assert "linha,registro" in csv_text
        lines = csv_text.strip().split("\n")
        assert len(lines) > 1  # header + data

    def test_export_errors_json(self, audit_db: sqlite3.Connection, sped_errors_path: Path) -> None:
        file_id = upload_file(audit_db, sped_errors_path)
        run_full_validation(audit_db, file_id)

        json_text = export_errors_json(audit_db, file_id)
        data = json.loads(json_text)
        assert isinstance(data, list)
        assert len(data) > 0
        assert "tipo_erro" in data[0]
        assert "mensagem" in data[0]

    def test_export_csv_empty(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        csv_text = export_errors_csv(audit_db, file_id)
        lines = csv_text.strip().split("\n")
        assert len(lines) == 1  # Só header
