"""Testes do MOD-10: Controle Obrigatório de Correções (Aprovação Humana)."""

from __future__ import annotations

import json
import os
import sqlite3
import warnings
from pathlib import Path

import pytest

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)

from fastapi.testclient import TestClient  # noqa: E402

from api.deps import get_db  # noqa: E402
from api.main import app  # noqa: E402
from src.services.database import init_audit_db  # noqa: E402

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
def seeded_db(audit_db: sqlite3.Connection) -> sqlite3.Connection:
    """Banco com um arquivo e registro SPED para testar correções."""
    audit_db.execute(
        """INSERT INTO sped_files (id, filename, hash_sha256, status)
           VALUES (1, 'test.txt', 'abc123', 'validated')"""
    )
    fields = {
        "REG": "C170",
        "NUM_ITEM": "001",
        "COD_ITEM": "ITEM01",
        "DESCR_COMPL": "Descricao",
        "QTD": "10,00",
        "UNID": "UN",
        "VL_ITEM": "100.00",
    }
    raw_line = "|" + "|".join(fields.values()) + "|"
    audit_db.execute(
        """INSERT INTO sped_records (id, file_id, line_number, register, block, fields_json, raw_line)
           VALUES (1, 1, 10, 'C170', 'C', ?, ?)""",
        (json.dumps(fields, ensure_ascii=False), raw_line),
    )
    audit_db.commit()
    return audit_db


@pytest.fixture
def client(seeded_db: sqlite3.Connection) -> TestClient:
    """TestClient com banco de teste injetado."""
    def _override_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_db
    c = TestClient(app, headers={"X-API-Key": os.environ.get("API_KEY", "test-api-key-for-pytest-minimum-32-chars!")})
    yield c
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _valid_payload(**overrides) -> dict:
    """Payload válido de correção com campos obrigatórios MOD-10."""
    base = {
        "field_no": 5,
        "field_name": "QTD",
        "new_value": "10.00",
        "justificativa": "Correção de formato numérico de vírgula para ponto decimal conforme layout",
        "correction_type": "deterministic",
        "rule_id": "FORMATO_DECIMAL",
    }
    base.update(overrides)
    return base


# ──────────────────────────────────────────────
# Testes
# ──────────────────────────────────────────────

class TestJustificativaObrigatoria:
    """Justificativa é campo obrigatório com mínimo de 20 caracteres."""

    def test_justificativa_vazia_retorna_422(self, client: TestClient):
        payload = _valid_payload(justificativa="")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 422

    def test_justificativa_curta_retorna_422(self, client: TestClient):
        payload = _valid_payload(justificativa="curto demais")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 422

    def test_justificativa_ausente_retorna_422(self, client: TestClient):
        payload = {
            "field_no": 5,
            "field_name": "QTD",
            "new_value": "10.00",
            "correction_type": "deterministic",
            "rule_id": "FORMATO_DECIMAL",
        }
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 422


class TestCamposProibidos:
    """Campos fiscais sensíveis não podem ser corrigidos via API."""

    def test_corrigir_cst_icms_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="CST_ICMS")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400
        assert "CST" in resp.json()["detail"] or "profissional habilitado" in resp.json()["detail"]

    def test_corrigir_cfop_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="CFOP")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400
        assert "profissional habilitado" in resp.json()["detail"]

    def test_corrigir_aliq_icms_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="ALIQ_ICMS")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400

    def test_corrigir_cst_ipi_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="CST_IPI")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400

    def test_corrigir_cod_aj_apur_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="COD_AJ_APUR")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400

    def test_corrigir_vl_aj_apur_retorna_400(self, client: TestClient):
        payload = _valid_payload(field_name="VL_AJ_APUR")
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 400


class TestCorrecaoValida:
    """Correção com justificativa válida em campo permitido deve funcionar."""

    def test_correcao_valida_retorna_200(self, client: TestClient, seeded_db: sqlite3.Connection):
        payload = _valid_payload()
        resp = client.put("/api/files/1/records/1", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["corrected"] is True
        assert data["record_id"] == 1

    def test_correcao_salva_audit_log(self, client: TestClient, seeded_db: sqlite3.Connection):
        payload = _valid_payload()
        client.put("/api/files/1/records/1", json=payload)

        row = seeded_db.execute(
            "SELECT action, details FROM audit_log WHERE file_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["action"] == "correction_applied"

        details = json.loads(row["details"])
        assert details["justificativa"] == payload["justificativa"]
        assert details["correction_type"] == "deterministic"
        assert details["rule_id"] == "FORMATO_DECIMAL"
        assert details["field_name"] == "QTD"

    def test_correcao_salva_justificativa_na_tabela_corrections(
        self, client: TestClient, seeded_db: sqlite3.Connection
    ):
        payload = _valid_payload()
        client.put("/api/files/1/records/1", json=payload)

        row = seeded_db.execute(
            "SELECT justificativa, correction_type, rule_id FROM corrections WHERE file_id = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row["justificativa"] == payload["justificativa"]
        assert row["correction_type"] == "deterministic"
        assert row["rule_id"] == "FORMATO_DECIMAL"
