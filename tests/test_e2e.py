"""Teste end-to-end: upload → parse → validar → corrigir → revalidar → exportar."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.services.correction_service import apply_correction
from src.services.database import init_audit_db
from src.services.export_service import (
    export_corrected_sped,
    export_errors_csv,
    export_errors_json,
    export_report_markdown,
)
from src.services.file_service import get_file, upload_file
from src.services.validation_service import get_error_summary, get_errors, run_full_validation


class TestEndToEnd:
    """Teste do fluxo completo: upload → validar → corrigir → revalidar → exportar."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> sqlite3.Connection:
        path = tmp_path / "e2e.db"
        conn = init_audit_db(path)
        conn.row_factory = sqlite3.Row
        return conn

    def test_full_flow_valid_file(self, db: sqlite3.Connection, sped_valid_path: Path) -> None:
        """Arquivo válido: upload → validar → poucos/nenhum erro → exportar."""
        # 1. Upload
        file_id = upload_file(db, sped_valid_path)
        info = get_file(db, file_id)
        assert info is not None
        assert info["status"] == "parsed"
        assert info["total_records"] > 0
        assert info["company_name"] == "EMPRESA VALIDA LTDA"

        # 2. Validar
        errors = run_full_validation(db, file_id)
        info = get_file(db, file_id)
        assert info["status"] == "validated"

        # 3. Resumo
        summary = get_error_summary(db, file_id)
        assert summary["total"] == len(errors)

        # 4. Exportar relatório
        report_md = export_report_markdown(db, file_id)
        assert "Relatório de Auditoria" in report_md

        report_csv = export_errors_csv(db, file_id)
        assert "linha,registro" in report_csv

        report_json = export_errors_json(db, file_id)
        data = json.loads(report_json)
        assert isinstance(data, (list, dict))

        # 5. Exportar SPED
        sped_out = export_corrected_sped(db, file_id)
        assert sped_out.startswith("|0000|")
        assert "|9999|" in sped_out

    def test_full_flow_error_file(self, db: sqlite3.Connection, sped_errors_path: Path) -> None:
        """Arquivo com erros: upload → validar → corrigir → revalidar → exportar."""
        # 1. Upload
        file_id = upload_file(db, sped_errors_path)
        assert get_file(db, file_id)["status"] == "parsed"

        # 2. Validar — deve encontrar erros
        errors_v1 = run_full_validation(db, file_id)
        assert len(errors_v1) > 0
        info = get_file(db, file_id)
        assert info["total_errors"] > 0

        # 3. Consultar erros
        db_errors = get_errors(db, file_id, limit=1000)
        assert len(db_errors) > 0

        summary = get_error_summary(db, file_id)
        assert summary["total"] > 0
        assert len(summary["by_type"]) > 0
        assert len(summary["by_severity"]) > 0

        # 4. Aplicar correção em um registro
        first_record = db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? AND register = 'C100' LIMIT 1",
            (file_id,),
        ).fetchone()
        if first_record:
            record_id = first_record[0]
            result = apply_correction(db, file_id, record_id, 2, "IND_OPER", "0")
            assert result is True

            # Verificar que registro foi marcado como corrigido
            rec = db.execute(
                "SELECT status FROM sped_records WHERE id = ?", (record_id,)
            ).fetchone()
            assert rec[0] == "corrected"

        # 5. Revalidar
        errors_v2 = run_full_validation(db, file_id)
        assert isinstance(errors_v2, list)

        # Revalidação não duplica erros
        db_errors_v2 = get_errors(db, file_id, limit=1000)
        # Cada erro deve aparecer apenas uma vez
        error_ids = [e["id"] for e in db_errors_v2]
        assert len(error_ids) == len(set(error_ids))

        # 6. Exportar
        sped_out = export_corrected_sped(db, file_id)
        assert len(sped_out) > 0

        report = export_report_markdown(db, file_id)
        assert "Relatório de Auditoria" in report

    def test_duplicate_upload(self, db: sqlite3.Connection, sped_valid_path: Path) -> None:
        """Upload duplicado retorna mesmo file_id."""
        id1 = upload_file(db, sped_valid_path)
        id2 = upload_file(db, sped_valid_path)
        assert id1 == id2

    def test_audit_log_tracks_all_actions(self, db: sqlite3.Connection, sped_valid_path: Path) -> None:
        """Audit log registra upload e validação."""
        file_id = upload_file(db, sped_valid_path)
        run_full_validation(db, file_id)

        logs = db.execute(
            "SELECT action FROM audit_log WHERE file_id = ? ORDER BY id",
            (file_id,),
        ).fetchall()
        actions = [row[0] for row in logs]
        assert "upload" in actions
        assert "validate" in actions
