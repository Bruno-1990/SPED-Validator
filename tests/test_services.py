"""Testes dos services de persistência (database, file, validation, correction, export)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.services.correction_service import (
    CorrectionNotAllowed,
    MissingJustificativa,
    _enforce_corrigivel,
    apply_correction,
    get_corrections,
    resolve_finding,
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
from src.models import ValidationError
from src.services.validation_service import (
    _calc_materialidade,
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

        result = apply_correction(
            audit_db, file_id, record_id, 2, "COD_VER", "018",
            justificativa="Correcao de teste automatizado",
        )
        assert result is True

        # Verificar que o campo foi atualizado
        updated = audit_db.execute(
            "SELECT fields_json, status FROM sped_records WHERE id = ?", (record_id,)
        ).fetchone()
        fields = json.loads(updated[0])
        assert fields["COD_VER"] == "018"
        assert updated[1] == "corrected"

    def test_apply_correction_invalid_record(self, audit_db: sqlite3.Connection) -> None:
        assert apply_correction(
            audit_db, 999, 999, 1, "X", "Y",
            justificativa="Teste de registro inexistente",
        ) is False

    def test_apply_correction_invalid_field_no(
        self, audit_db: sqlite3.Connection, sped_minimal_path: Path
    ) -> None:
        file_id = upload_file(audit_db, sped_minimal_path)
        rec = audit_db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        assert apply_correction(
            audit_db, file_id, rec[0], 999, "X", "Y",
            justificativa="Teste de field_no invalido",
        ) is False

    def test_get_corrections(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        rec = audit_db.execute(
            "SELECT id FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        apply_correction(
            audit_db, file_id, rec[0], 2, "FIELD", "NEW",
            justificativa="Teste get_corrections",
        )

        corrections = get_corrections(audit_db, file_id)
        assert len(corrections) >= 1

    def test_undo_correction(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        rec = audit_db.execute(
            "SELECT id, fields_json FROM sped_records WHERE file_id = ? LIMIT 1", (file_id,)
        ).fetchone()
        record_id = rec[0]
        original_fields = json.loads(rec[1])

        apply_correction(
            audit_db, file_id, record_id, 2, "FIELD", "CHANGED",
            justificativa="Teste de undo correction",
        )

        # Pegar correction_id
        corr = audit_db.execute(
            "SELECT id FROM corrections WHERE record_id = ?", (record_id,)
        ).fetchone()
        assert undo_correction(audit_db, corr[0]) is True

        # Valor restaurado (apply_correction pode expandir o JSON ao leiaute completo)
        restored = audit_db.execute(
            "SELECT fields_json FROM sped_records WHERE id = ?", (record_id,)
        ).fetchone()
        restored_dict = json.loads(restored[0])
        for k, v in original_fields.items():
            assert restored_dict.get(k) == v, k

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
        assert "Sumário" in report or "Achados" in report

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
        # New format: full report dict with secao4_achados
        if isinstance(data, dict):
            assert "secao4_achados" in data
            achados = data["secao4_achados"]
            assert len(achados) > 0
            assert "mensagem" in achados[0]
        else:
            assert isinstance(data, list)
            assert len(data) > 0

    def test_export_csv_empty(self, audit_db: sqlite3.Connection, sped_valid_path: Path) -> None:
        file_id = upload_file(audit_db, sped_valid_path)
        csv_text = export_errors_csv(audit_db, file_id)
        lines = csv_text.strip().split("\n")
        # Header + optional footer rows (empty row + rodapé legal)
        assert len(lines) >= 1
        assert "linha,registro" in lines[0] or "linha" in lines[0]


# ──────────────────────────────────────────────
# correction_service.py — governanca
# ──────────────────────────────────────────────

class TestCorrectionGovernance:
    """Testes da governanca de correcoes (corrigivel)."""

    def _patch_cache(self, monkeypatch, rule_id: str, corrigivel: str) -> None:
        """Helper: injeta valor no _corrigivel_cache para o rule_id dado."""
        import src.services.correction_service as cs
        monkeypatch.setattr(cs, "_corrigivel_cache", {rule_id: corrigivel})

    def test_enforce_impossivel_raises(self, monkeypatch) -> None:
        """Regra impossivel bloqueia correcao."""
        self._patch_cache(monkeypatch, "R001", "impossivel")
        with pytest.raises(CorrectionNotAllowed, match="nao permite correcao"):
            _enforce_corrigivel("R001", "qualquer justificativa")

    def test_enforce_investigar_raises(self, monkeypatch) -> None:
        """Regra investigar bloqueia correcao."""
        self._patch_cache(monkeypatch, "R002", "investigar")
        with pytest.raises(CorrectionNotAllowed, match="investigacao"):
            _enforce_corrigivel("R002", "qualquer justificativa")

    def test_enforce_proposta_requires_justificativa(self, monkeypatch) -> None:
        """Regra proposta sem justificativa levanta MissingJustificativa."""
        self._patch_cache(monkeypatch, "R003", "proposta")
        with pytest.raises(MissingJustificativa, match="justificativa"):
            _enforce_corrigivel("R003", None)

    def test_enforce_proposta_short_justificativa_raises(self, monkeypatch) -> None:
        """Justificativa < 10 chars levanta MissingJustificativa."""
        self._patch_cache(monkeypatch, "R004", "proposta")
        with pytest.raises(MissingJustificativa):
            _enforce_corrigivel("R004", "curto")

    def test_enforce_proposta_valid_justificativa_passes(self, monkeypatch) -> None:
        """Justificativa >= 10 chars nao levanta excecao."""
        self._patch_cache(monkeypatch, "R005", "proposta")
        _enforce_corrigivel("R005", "justificativa valida e longa")  # nao deve levantar

    def test_enforce_automatico_no_justificativa_passes(self, monkeypatch) -> None:
        """Regra automatico nao exige justificativa."""
        self._patch_cache(monkeypatch, "R006", "automatico")
        _enforce_corrigivel("R006", None)  # nao deve levantar


# ──────────────────────────────────────────────
# correction_service.py — resolve_finding
# ──────────────────────────────────────────────

class TestResolveFinding:
    """Testes do workflow de resolucao de apontamentos."""

    @staticmethod
    def _insert_dummy_file(db: sqlite3.Connection) -> int:
        """Insere registro minimo em sped_files para satisfazer FK do audit_log."""
        db.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES ('test.txt', 'abc123')"
        )
        db.commit()
        return db.execute("SELECT last_insert_rowid()").fetchone()[0]

    def test_resolve_accepted(self, audit_db: sqlite3.Connection) -> None:
        """Status accepted registrado com sucesso."""
        fid = self._insert_dummy_file(audit_db)
        result = resolve_finding(audit_db, fid, 100, "R001", "accepted")
        assert result is True

    def test_resolve_rejected_with_justificativa(self, audit_db: sqlite3.Connection) -> None:
        """Rejeicao com justificativa >= 20 chars aceita."""
        fid = self._insert_dummy_file(audit_db)
        result = resolve_finding(
            audit_db, fid, 101, "R001", "rejected",
            justificativa="Justificativa longa o suficiente para rejeitar",
        )
        assert result is True

    def test_resolve_rejected_short_justificativa(self, audit_db: sqlite3.Connection) -> None:
        """Rejeicao com justificativa < 20 chars retorna False."""
        result = resolve_finding(
            audit_db, 1, 102, "R001", "rejected",
            justificativa="curta",
        )
        assert result is False

    def test_resolve_rejected_no_justificativa(self, audit_db: sqlite3.Connection) -> None:
        """Rejeicao sem justificativa retorna False."""
        result = resolve_finding(audit_db, 1, 103, "R001", "rejected")
        assert result is False

    def test_resolve_deferred(self, audit_db: sqlite3.Connection) -> None:
        """Status deferred com prazo registrado."""
        fid = self._insert_dummy_file(audit_db)
        result = resolve_finding(
            audit_db, fid, 104, "R001", "deferred",
            prazo_revisao="2026-06-30",
        )
        assert result is True
        row = audit_db.execute(
            "SELECT prazo_revisao FROM finding_resolutions WHERE finding_id = '104'"
        ).fetchone()
        assert row is not None
        assert row[0] == "2026-06-30"

    def test_resolve_noted(self, audit_db: sqlite3.Connection) -> None:
        """Status noted registrado."""
        fid = self._insert_dummy_file(audit_db)
        result = resolve_finding(audit_db, fid, 105, "R001", "noted")
        assert result is True

    def test_resolve_invalid_status(self, audit_db: sqlite3.Connection) -> None:
        """Status invalido retorna False."""
        result = resolve_finding(audit_db, 1, 106, "R001", "invalido")
        assert result is False

    def test_resolve_persists_to_db(self, audit_db: sqlite3.Connection) -> None:
        """Resolucao salva na tabela finding_resolutions."""
        fid = self._insert_dummy_file(audit_db)
        resolve_finding(
            audit_db, fid, 200, "R010", "accepted",
            user_id="analista1",
        )
        row = audit_db.execute(
            "SELECT status, user_id, rule_id FROM finding_resolutions "
            "WHERE finding_id = '200'"
        ).fetchone()
        assert row is not None
        assert row[0] == "accepted"
        assert row[1] == "analista1"
        assert row[2] == "R010"

    def test_resolve_upsert(self, audit_db: sqlite3.Connection) -> None:
        """Segunda resolucao atualiza a existente (UPSERT)."""
        fid = self._insert_dummy_file(audit_db)
        resolve_finding(audit_db, fid, 300, "R020", "accepted")
        resolve_finding(
            audit_db, fid, 300, "R020", "rejected",
            justificativa="Motivo detalhado para rejeitar o apontamento",
        )
        rows = audit_db.execute(
            "SELECT status FROM finding_resolutions "
            "WHERE file_id = ? AND finding_id = '300'",
            (str(fid),),
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "rejected"


# ──────────────────────────────────────────────
# _calc_materialidade
# ──────────────────────────────────────────────

def _make_error(**overrides) -> ValidationError:
    """Create a ValidationError with sensible defaults, overridden as needed."""
    defaults = dict(
        line_number=1,
        register="C100",
        field_no=2,
        field_name="VL_MERC",
        value="100.00",
        error_type="SOMA_DIVERGENTE",
        message="erro de teste",
        expected_value=None,
    )
    defaults.update(overrides)
    return ValidationError(**defaults)


class TestMaterialidade:
    """Testes do calculo de materialidade financeira."""

    def test_calc_simple_numeric_difference(self):
        """Diferenca simples entre value e expected_value."""
        err = _make_error(value="1000.00", expected_value="900.00")
        assert _calc_materialidade(err) == pytest.approx(100.0)

    def test_calc_no_expected_returns_zero(self):
        """Sem expected_value retorna 0."""
        err = _make_error(value="1000.00", expected_value=None)
        assert _calc_materialidade(err) == 0.0

    def test_calc_no_value_returns_zero(self):
        """Sem value retorna 0."""
        err = _make_error(value="", expected_value="500.00")
        assert _calc_materialidade(err) == 0.0

    def test_calc_non_numeric_returns_zero(self):
        """Valores nao-numericos retornam 0."""
        err = _make_error(value="ABC", expected_value="DEF")
        assert _calc_materialidade(err) == 0.0

    def test_calc_negative_difference_is_absolute(self):
        """Diferenca negativa retorna valor absoluto."""
        err = _make_error(value="100.00", expected_value="500.00")
        assert _calc_materialidade(err) == pytest.approx(400.0)
