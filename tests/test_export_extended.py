"""Extended tests for src/services/export_service.py — covering uncovered paths.

Targets lines: 125, 268, 324-433, 481, 527, 560.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.services.database import init_audit_db
from src.validators.helpers import REGISTER_FIELDS, fields_to_dict
from src.services.export_service import (
    _build_section6,
    export_corrected_sped,
    export_errors_csv,
    export_errors_json,
    export_report_markdown,
    export_report_structured,
    generate_report,
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


def _insert_file(db: sqlite3.Connection, *, total_records: int = 100, total_errors: int = 5) -> int:
    """Insert a sped_files row and return its id."""
    cur = db.execute(
        """INSERT INTO sped_files
           (filename, hash_sha256, period_start, period_end,
            company_name, cnpj, uf, total_records, total_errors, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'validated')""",
        ("test.txt", "abc123hash", "01012024", "31012024",
         "EMPRESA TESTE LTDA", "12345678000195", "SP",
         total_records, total_errors),
    )
    db.commit()
    return cur.lastrowid


def _insert_error(
    db: sqlite3.Connection,
    file_id: int,
    *,
    line_number: int = 10,
    register: str = "C170",
    error_type: str = "CAMPO_INVALIDO",
    severity: str = "error",
    message: str = "Campo invalido",
    certeza: str = "objetivo",
    impacto: str = "relevante",
    status: str = "open",
    field_name: str = "VL_ICMS",
    value: str = "100.00",
    expected_value: str = "120.00",
    auto_correctable: int = 0,
    friendly_message: str | None = None,
    legal_basis: str | None = None,
) -> int:
    cur = db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, field_name, value, expected_value,
            error_type, severity, message, friendly_message, legal_basis,
            certeza, impacto, status, auto_correctable)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (file_id, line_number, register, field_name, value, expected_value,
         error_type, severity, message, friendly_message, legal_basis,
         certeza, impacto, status, auto_correctable),
    )
    db.commit()
    return cur.lastrowid


def _insert_correction(
    db: sqlite3.Connection,
    file_id: int,
    record_id: int = 1,
    field_name: str = "VL_ICMS",
    old_value: str = "100.00",
    new_value: str = "120.00",
    justificativa: str = "Correcao de valor",
    applied_by: str = "analista",
) -> int:
    cur = db.execute(
        """INSERT INTO corrections
           (file_id, record_id, field_no, field_name, old_value, new_value,
            justificativa, applied_by)
           VALUES (?, ?, 14, ?, ?, ?, ?, ?)""",
        (file_id, record_id, field_name, old_value, new_value,
         justificativa, applied_by),
    )
    db.commit()
    return cur.lastrowid


def _insert_record(
    db: sqlite3.Connection,
    file_id: int,
    line_number: int = 1,
    register: str = "C170",
    raw_line: str = "|C170|1|ITEM1||10|UN|100.00|",
) -> int:
    cur = db.execute(
        """INSERT INTO sped_records
           (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, line_number, register, register[0], "{}", raw_line),
    )
    db.commit()
    return cur.lastrowid


# ──────────────────────────────────────────────
# _build_section6 — line 268 (checks_nao_realizados non-empty)
# ──────────────────────────────────────────────

class TestBuildSection6:
    def test_all_checks_executed(self) -> None:
        result = _build_section6([], "2024-01-15 10:00:00")
        assert "Nenhuma" in result["texto"]
        assert "RODAPÉ LEGAL" in result["titulo"]

    def test_some_checks_not_executed(self) -> None:
        result = _build_section6(["DIFAL", "ST com MVA"], "2024-01-15 10:00:00")
        assert "DIFAL" in result["texto"]
        assert "ST com MVA" in result["texto"]


# ──────────────────────────────────────────────
# export_report_structured — lines 324-433
# ──────────────────────────────────────────────

class TestExportReportStructured:
    def test_file_not_found(self, audit_db: sqlite3.Connection) -> None:
        result = export_report_structured(audit_db, 9999)
        assert result.get("error") == "Arquivo não encontrado"

    def test_basic_structured_report(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db, total_records=200, total_errors=3)
        _insert_error(audit_db, file_id, severity="critical", error_type="CAMPO_INVALIDO")
        _insert_error(audit_db, file_id, severity="warning", error_type="ALERTA_FISCAL",
                      line_number=20)
        _insert_error(audit_db, file_id, severity="info", error_type="INFORMATIVO",
                      line_number=30)

        result = export_report_structured(audit_db, file_id)

        assert "metadata" in result
        assert result["metadata"]["filename"] == "test.txt"
        assert result["metadata"]["cnpj"] == "12345678000195"

        assert "summary" in result
        assert result["summary"]["total_records"] == 200
        assert result["summary"]["total_errors"] >= 1
        assert result["summary"]["compliance_pct"] <= 100.0

        assert "top_findings" in result
        assert len(result["top_findings"]) > 0

        assert "conclusion" in result
        assert "200" in result["conclusion"]

    def test_structured_report_with_corrections(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db, total_records=50, total_errors=1)
        rec_id = _insert_record(audit_db, file_id)
        _insert_error(audit_db, file_id, auto_correctable=1)
        _insert_correction(audit_db, file_id, record_id=rec_id)

        result = export_report_structured(audit_db, file_id)

        assert result["summary"]["applied_corrections"] >= 1
        assert len(result["corrections"]) >= 1
        assert result["corrections"][0]["field_name"] == "VL_ICMS"
        assert "correções aplicadas" in result["conclusion"].lower() or "correç" in result["conclusion"].lower()

    def test_structured_report_no_errors(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db, total_records=100, total_errors=0)

        result = export_report_structured(audit_db, file_id)
        assert result["summary"]["total_errors"] == 0
        assert result["summary"]["total_warnings"] == 0
        assert "Nenhuma irregularidade" in result["conclusion"]

    def test_structured_report_with_pending_suggestions(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db, total_records=100, total_errors=2)
        _insert_error(audit_db, file_id, auto_correctable=1, severity="error",
                      expected_value="120.00")

        result = export_report_structured(audit_db, file_id)
        assert result["summary"]["pending_suggestions"] >= 1
        assert "sugest" in result["conclusion"].lower()

    def test_structured_report_long_description_truncated(self, audit_db: sqlite3.Connection) -> None:
        """Descriptions longer than 120 chars should be truncated with '...'."""
        file_id = _insert_file(audit_db, total_records=100, total_errors=1)
        long_msg = "A" * 200
        _insert_error(audit_db, file_id, friendly_message=long_msg)

        result = export_report_structured(audit_db, file_id)
        for finding in result["top_findings"]:
            assert len(finding["description"]) <= 120


# ──────────────────────────────────────────────
# generate_report — file not found
# ──────────────────────────────────────────────

class TestGenerateReport:
    def test_file_not_found(self, audit_db: sqlite3.Connection) -> None:
        result = generate_report(audit_db, 9999)
        assert result.get("error") == "Arquivo não encontrado"

    def test_full_report_with_all_sections(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        rec_id = _insert_record(audit_db, file_id)
        _insert_error(audit_db, file_id, severity="critical", certeza="objetivo",
                      legal_basis="Art 5 RICMS")
        _insert_error(audit_db, file_id, severity="warning", certeza="provavel",
                      line_number=20, error_type="ALERTA")
        _insert_correction(audit_db, file_id, record_id=rec_id)

        result = generate_report(audit_db, file_id)
        assert "secao1_cabecalho" in result
        assert "secao2_cobertura" in result
        assert "secao3_sumario" in result
        assert "secao4_achados" in result
        assert "secao5_correcoes" in result
        assert "secao6_rodape" in result

        # Section 3 details
        s3 = result["secao3_sumario"]
        assert s3["por_severidade"]["critical"] >= 1
        assert s3["por_certeza"]["objetivo"] >= 1

        # Section 4 details
        assert len(result["secao4_achados"]) >= 2

        # Section 5 details
        assert len(result["secao5_correcoes"]) >= 1


# ──────────────────────────────────────────────
# Markdown — line 481 (no tabelas_disponiveis), 527 (no achados)
# ──────────────────────────────────────────────

class TestExportMarkdownExtended:
    def test_markdown_no_errors(self, audit_db: sqlite3.Connection) -> None:
        """File with no errors -> 'Nenhum achado' in markdown (line 527)."""
        file_id = _insert_file(audit_db, total_errors=0)

        md = export_report_markdown(audit_db, file_id)
        assert "Nenhum achado" in md
        assert "Nenhuma correção" in md

    def test_markdown_with_errors_and_corrections(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        rec_id = _insert_record(audit_db, file_id)
        _insert_error(audit_db, file_id, legal_basis="Art 5 RICMS", severity="critical")
        _insert_correction(audit_db, file_id, record_id=rec_id)

        md = export_report_markdown(audit_db, file_id)
        assert "Base legal" in md
        assert "Correções Aplicadas" in md

    def test_markdown_file_not_found(self, audit_db: sqlite3.Connection) -> None:
        md = export_report_markdown(audit_db, 9999)
        assert "Arquivo não encontrado" in md


# ──────────────────────────────────────────────
# CSV — line 560 (file not found returns empty)
# ──────────────────────────────────────────────

class TestExportCsvExtended:
    def test_csv_file_not_found(self, audit_db: sqlite3.Connection) -> None:
        result = export_errors_csv(audit_db, 9999)
        assert result == ""

    def test_csv_with_errors(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        _insert_error(audit_db, file_id)

        csv_text = export_errors_csv(audit_db, file_id)
        assert "linha" in csv_text
        assert "registro" in csv_text
        assert "AVISO LEGAL" in csv_text


# ──────────────────────────────────────────────
# JSON export
# ──────────────────────────────────────────────

class TestExportJsonExtended:
    def test_json_file_not_found(self, audit_db: sqlite3.Connection) -> None:
        result = export_errors_json(audit_db, 9999)
        parsed = json.loads(result)
        assert parsed.get("error") == "Arquivo não encontrado"

    def test_json_with_data(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        _insert_error(audit_db, file_id)

        result = export_errors_json(audit_db, file_id)
        parsed = json.loads(result)
        assert "secao1_cabecalho" in parsed


# ──────────────────────────────────────────────
# export_corrected_sped
# ──────────────────────────────────────────────

class TestExportCorrectedSped:
    def test_corrected_sped_output(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        _insert_record(audit_db, file_id, line_number=1, raw_line="|0000|016|0|01012024|")
        _insert_record(audit_db, file_id, line_number=2, raw_line="|C100|0|0|PART1|")

        result = export_corrected_sped(audit_db, file_id)
        assert "|0000|016|0|01012024|" in result
        assert "|C100|0|0|PART1|" in result
        assert result.endswith("\n")

    def test_corrected_sped_no_records(self, audit_db: sqlite3.Connection) -> None:
        file_id = _insert_file(audit_db)
        result = export_corrected_sped(audit_db, file_id)
        assert result == "\n"

    def test_export_rebuilds_from_fields_json_when_coherent(
        self, audit_db: sqlite3.Connection,
    ) -> None:
        """Export alinha raw_line ao fields_json quando o JSON reflete o leiaute completo."""
        file_id = _insert_file(audit_db)
        ch = "2" * 44
        fields_list = [
            "C100", "0", "0", "", "55", "00", "1", "1", ch,
            "01012024", "", "100,00",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ]
        assert len(fields_list) == len(REGISTER_FIELDS["C100"])
        d = fields_to_dict("C100", fields_list)
        d["VL_DOC"] = "999,99"
        fj = json.dumps(d, ensure_ascii=False)
        stale = "|C100|stub|wrong|"
        audit_db.execute(
            """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
               VALUES (?, 1, 'C100', 'C', ?, ?)""",
            (file_id, fj, stale),
        )
        audit_db.commit()
        result = export_corrected_sped(audit_db, file_id)
        assert "999,99" in result
        assert stale not in result
