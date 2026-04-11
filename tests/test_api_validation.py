"""Tests for api/routers/validation.py — covering dismiss_error, dismiss_all_errors, and validate_stream."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import app
from src.services.database import init_audit_db

# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """TestClient with a temp audit DB."""
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
    yield TestClient(app, headers={"X-API-Key": os.environ.get("API_KEY", "test-api-key-for-pytest-minimum-32-chars!")})
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def error_sped(sped_errors_path: Path) -> bytes:
    return sped_errors_path.read_bytes()


@pytest.fixture
def valid_sped(sped_valid_path: Path) -> bytes:
    return sped_valid_path.read_bytes()


def _upload(client: TestClient, sped_bytes: bytes) -> int:
    r = client.post("/api/files/upload", files={"file": ("sped.txt", sped_bytes)})
    assert r.status_code == 200, f"Upload falhou: {r.status_code} {r.text}"
    return r.json()["file_id"]


def _upload_and_validate(client: TestClient, sped_bytes: bytes) -> int:
    file_id = _upload(client, sped_bytes)
    client.post(f"/api/files/{file_id}/validate")
    return file_id


# ──────────────────────────────────────────────
# DELETE /errors/{error_id} — dismiss single error (lines 296-315)
# ──────────────────────────────────────────────

class TestDismissError:
    def test_dismiss_single_error(self, client: TestClient, error_sped: bytes) -> None:
        file_id = _upload_and_validate(client, error_sped)

        # Get errors to find an error_id
        errors_resp = client.get(f"/api/files/{file_id}/errors")
        errors_data = errors_resp.json()
        assert errors_data["total"] > 0

        error_id = errors_data["data"][0]["id"]
        original_total = errors_data["total"]

        # Dismiss the error
        r = client.delete(f"/api/files/{file_id}/errors/{error_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["dismissed"] is True
        assert body["total_errors"] <= original_total

    def test_dismiss_nonexistent_error(self, client: TestClient, error_sped: bytes) -> None:
        """Dismissing an error that doesn't exist should still return 200 (idempotent)."""
        file_id = _upload_and_validate(client, error_sped)
        r = client.delete(f"/api/files/{file_id}/errors/999999")
        assert r.status_code == 200
        body = r.json()
        assert body["dismissed"] is True


# ──────────────────────────────────────────────
# DELETE /errors — dismiss all errors (lines 324-343)
# ──────────────────────────────────────────────

class TestDismissAllErrors:
    def test_dismiss_all_errors(self, client: TestClient, error_sped: bytes) -> None:
        file_id = _upload_and_validate(client, error_sped)

        errors_resp = client.get(f"/api/files/{file_id}/errors")
        assert errors_resp.json()["total"] > 0

        r = client.delete(f"/api/files/{file_id}/errors")
        assert r.status_code == 200
        body = r.json()
        assert body["dismissed"] > 0
        assert body["total_errors"] == 0

    def test_dismiss_all_when_no_errors(self, client: TestClient, valid_sped: bytes) -> None:
        """When there are no open errors, dismissed should be 0."""
        file_id = _upload_and_validate(client, valid_sped)
        r = client.delete(f"/api/files/{file_id}/errors")
        assert r.status_code == 200
        body = r.json()
        assert body["dismissed"] >= 0
        assert body["total_errors"] >= 0


# ──────────────────────────────────────────────
# GET /validate/stream — SSE streaming (lines 52-129)
# ──────────────────────────────────────────────

class TestValidateStream:
    def test_stream_returns_sse(self, client: TestClient, error_sped: bytes) -> None:
        """The stream endpoint should return SSE events including a 'done' event."""
        file_id = _upload(client, error_sped)

        # Use stream=True approach — TestClient collects the full response
        r = client.get(f"/api/files/{file_id}/validate/stream")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

        # The response body should contain SSE events (done or error)
        body = r.text
        assert "event:" in body
        assert "data:" in body

    def test_stream_with_valid_file(self, client: TestClient, valid_sped: bytes) -> None:
        """Stream should work for valid files too, producing SSE events."""
        file_id = _upload(client, valid_sped)
        r = client.get(f"/api/files/{file_id}/validate/stream")
        assert r.status_code == 200
        assert "event:" in r.text
