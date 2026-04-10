"""Testes da API REST (FastAPI + httpx)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.services.database import init_audit_db


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """TestClient com banco de auditoria em diretório temporário."""
    db_path = tmp_path / "audit.db"
    init_audit_db(db_path).close()

    def override_get_db():
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    from api.deps import get_db
    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def valid_sped(sped_valid_path: Path) -> bytes:
    return sped_valid_path.read_bytes()


@pytest.fixture
def error_sped(sped_errors_path: Path) -> bytes:
    return sped_errors_path.read_bytes()


# ──────────────────────────────────────────────
# Health
# ──────────────────────────────────────────────

class TestHealth:
    def test_health(self, client: TestClient) -> None:
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


# ──────────────────────────────────────────────
# Files
# ──────────────────────────────────────────────

class TestFilesAPI:
    def test_upload(self, client: TestClient, valid_sped: bytes) -> None:
        r = client.post("/api/files/upload", files={"file": ("sped.txt", valid_sped)})
        assert r.status_code == 200
        data = r.json()
        assert data["file_id"] > 0
        assert data["total_records"] > 0
        assert data["status"] == "parsed"

    def test_list_files(self, client: TestClient, valid_sped: bytes) -> None:
        client.post("/api/files/upload", files={"file": ("sped.txt", valid_sped)})
        r = client.get("/api/files")
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_get_file(self, client: TestClient, valid_sped: bytes) -> None:
        upload = client.post("/api/files/upload", files={"file": ("sped.txt", valid_sped)})
        file_id = upload.json()["file_id"]
        r = client.get(f"/api/files/{file_id}")
        assert r.status_code == 200
        assert r.json()["company_name"] == "EMPRESA VALIDA LTDA"

    def test_get_file_not_found(self, client: TestClient) -> None:
        r = client.get("/api/files/999")
        assert r.status_code == 404

    def test_delete_file(self, client: TestClient, valid_sped: bytes) -> None:
        upload = client.post("/api/files/upload", files={"file": ("sped.txt", valid_sped)})
        file_id = upload.json()["file_id"]
        r = client.delete(f"/api/files/{file_id}")
        assert r.status_code == 200
        assert r.json()["deleted"] is True

    def test_delete_not_found(self, client: TestClient) -> None:
        r = client.delete("/api/files/999")
        assert r.status_code == 404


# ──────────────────────────────────────────────
# Validation
# ──────────────────────────────────────────────

class TestValidationAPI:
    def _upload(self, client: TestClient, sped_bytes: bytes) -> int:
        r = client.post("/api/files/upload", files={"file": ("sped.txt", sped_bytes)})
        return r.json()["file_id"]

    def test_validate(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        r = client.post(f"/api/files/{file_id}/validate")
        assert r.status_code == 200
        assert r.json()["status"] == "validated"

    def test_validate_errors_file(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload(client, error_sped)
        r = client.post(f"/api/files/{file_id}/validate")
        assert r.status_code == 200
        assert r.json()["total_errors"] > 0

    def test_list_errors(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload(client, error_sped)
        client.post(f"/api/files/{file_id}/validate")
        r = client.get(f"/api/files/{file_id}/errors")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] > 0
        assert len(data["data"]) > 0

    def test_list_errors_with_filter(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload(client, error_sped)
        client.post(f"/api/files/{file_id}/validate")
        r = client.get(f"/api/files/{file_id}/errors?severity=critical")
        assert r.status_code == 200

    def test_summary(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload(client, error_sped)
        client.post(f"/api/files/{file_id}/validate")
        r = client.get(f"/api/files/{file_id}/summary")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] > 0
        assert "by_type" in data


# ──────────────────────────────────────────────
# Records
# ──────────────────────────────────────────────

class TestRecordsAPI:
    def _upload(self, client: TestClient, sped_bytes: bytes) -> int:
        r = client.post("/api/files/upload", files={"file": ("sped.txt", sped_bytes)})
        assert r.status_code == 200, f"Upload falhou: {r.status_code} {r.text}"
        return r.json()["file_id"]

    def test_list_records(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        r = client.get(f"/api/files/{file_id}/records")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] > 0
        assert len(data["data"]) > 0

    def test_list_records_filter_block(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        r = client.get(f"/api/files/{file_id}/records?block=C")
        assert r.status_code == 200
        for rec in r.json()["data"]:
            assert rec["block"] == "C"

    def test_get_record(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        records = client.get(f"/api/files/{file_id}/records?page_size=1").json()
        rec_id = records["data"][0]["id"]
        r = client.get(f"/api/files/{file_id}/records/{rec_id}")
        assert r.status_code == 200

    def test_get_record_not_found(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        r = client.get(f"/api/files/{file_id}/records/99999")
        assert r.status_code == 404

    def test_update_record(self, client: TestClient, valid_sped: bytes) -> None:
        file_id = self._upload(client, valid_sped)
        records = client.get(f"/api/files/{file_id}/records?page_size=1").json()
        rec_id = records["data"][0]["id"]
        r = client.put(
            f"/api/files/{file_id}/records/{rec_id}",
            json={
                "field_no": 2,
                "field_name": "COD_VER",
                "new_value": "018",
                "justificativa": "Correcao do codigo de versao para 018 conforme layout",
                "correction_type": "manual",
                "rule_id": "CAMPO_INVALIDO",
            },
        )
        assert r.status_code == 200
        assert r.json()["corrected"] is True


# ──────────────────────────────────────────────
# Report / Export
# ──────────────────────────────────────────────

class TestReportAPI:
    def _upload_and_validate(self, client: TestClient, sped_bytes: bytes) -> int:
        r = client.post("/api/files/upload", files={"file": ("sped.txt", sped_bytes)})
        assert r.status_code == 200, f"Upload falhou: {r.status_code} {r.text}"
        file_id = r.json()["file_id"]
        client.post(f"/api/files/{file_id}/validate")
        return file_id

    def test_report_markdown(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload_and_validate(client, error_sped)
        r = client.get(f"/api/files/{file_id}/report?format=md")
        assert r.status_code == 200
        assert "Relatório de Auditoria" in r.text

    def test_report_csv(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload_and_validate(client, error_sped)
        r = client.get(f"/api/files/{file_id}/report?format=csv")
        assert r.status_code == 200
        assert "linha,registro" in r.text

    def test_report_json(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload_and_validate(client, error_sped)
        r = client.get(f"/api/files/{file_id}/report?format=json")
        assert r.status_code == 200
        assert r.json() is not None

    def test_report_invalid_format(self, client: TestClient, error_sped: bytes) -> None:
        file_id = self._upload_and_validate(client, error_sped)
        r = client.get(f"/api/files/{file_id}/report?format=xyz")
        assert r.status_code == 400

    def test_download_corrected(self, client: TestClient, valid_sped: bytes) -> None:
        r = client.post("/api/files/upload", files={"file": ("sped.txt", valid_sped)})
        assert r.status_code == 200, f"Upload falhou: {r.status_code} {r.text}"
        file_id = r.json()["file_id"]
        r = client.get(f"/api/files/{file_id}/download")
        assert r.status_code == 200
        assert r.text.startswith("|0000|")


# ──────────────────────────────────────────────
# Search
# ──────────────────────────────────────────────

class TestSearchAPI:
    def test_search_no_db(self, client: TestClient) -> None:
        """Sem banco de documentação, retorna 503."""
        with patch("api.routers.search.get_doc_db_path", return_value=None):
            r = client.get("/api/search?q=ICMS")
            assert r.status_code == 503
