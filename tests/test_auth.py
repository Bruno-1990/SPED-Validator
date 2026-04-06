"""Testes de autenticação por API Key (MOD-15)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def _clear_api_key(monkeypatch: pytest.MonkeyPatch):
    """Remove API_KEY do ambiente."""
    monkeypatch.delenv("API_KEY", raising=False)


@pytest.fixture()
def _set_api_key(monkeypatch: pytest.MonkeyPatch):
    """Define API_KEY no ambiente."""
    monkeypatch.setenv("API_KEY", "test-key-with-at-least-32-characters!!")


@pytest.fixture()
def client():
    """Cria TestClient fresh (importa app após env estar configurado)."""
    from api.main import app
    return TestClient(app)


# ── Health check é sempre público ──────────────────────────────────


class TestHealthPublic:
    """O endpoint /api/health não exige autenticação."""

    @pytest.mark.usefixtures("_set_api_key")
    def test_health_no_key_returns_200(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    @pytest.mark.usefixtures("_clear_api_key")
    def test_health_dev_mode_returns_200(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200


# ── Modo produção (API_KEY configurada) ───────────────────────────


class TestAuthEnforced:
    """Quando API_KEY está definida, endpoints protegidos exigem a key."""

    @pytest.mark.usefixtures("_set_api_key")
    def test_no_key_returns_401(self, client: TestClient):
        resp = client.get("/api/files")
        assert resp.status_code == 401

    @pytest.mark.usefixtures("_set_api_key")
    def test_wrong_key_returns_401(self, client: TestClient):
        resp = client.get("/api/files", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    @pytest.mark.usefixtures("_set_api_key")
    def test_correct_key_returns_200(self, client: TestClient):
        resp = client.get(
            "/api/files",
            headers={"X-API-Key": "test-key-with-at-least-32-characters!!"},
        )
        assert resp.status_code == 200


# ── Modo desenvolvimento (API_KEY não configurada) ────────────────


class TestDevMode:
    """Sem API_KEY no ambiente, qualquer request é aceito."""

    @pytest.mark.usefixtures("_clear_api_key")
    def test_no_key_accepted(self, client: TestClient):
        resp = client.get("/api/files")
        assert resp.status_code == 200

    @pytest.mark.usefixtures("_clear_api_key")
    def test_any_key_accepted(self, client: TestClient):
        resp = client.get("/api/files", headers={"X-API-Key": "qualquer-coisa"})
        assert resp.status_code == 200
