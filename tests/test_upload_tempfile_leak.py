"""Teste de vazamento de tempfile no upload (bug #6).

Se upload_file() raise uma excecao depois do tempfile ser criado, o arquivo
temporario precisa ser limpo mesmo assim. A versao antiga do codigo tinha
o `with tempfile.NamedTemporaryFile(delete=False)` FORA do try/finally, o
que vazava o arquivo em certos caminhos de excecao.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Setup env antes de importar api.main (analogo a outros testes)
os.environ.setdefault("API_KEY", "test-api-key-for-pytest-minimum-32-chars!")
os.environ.setdefault("DISABLE_API_RATE_LIMIT", "1")

from api.deps import get_db  # noqa: E402
from api.main import app  # noqa: E402
from src.services.database import init_audit_db  # noqa: E402

TEST_API_KEY = os.environ["API_KEY"]


@pytest.fixture
def audit_db(tmp_path: Path) -> sqlite3.Connection:
    path = tmp_path / "audit.db"
    conn = init_audit_db(path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def client(audit_db) -> TestClient:
    def _override_db():
        yield audit_db

    app.dependency_overrides[get_db] = _override_db
    try:
        # raise_server_exceptions=False: simula producao (global exception handler
        # retorna 500 em vez de propagar). Sem isso, TestClient da raise direto.
        yield TestClient(
            app,
            headers={"X-API-Key": TEST_API_KEY},
            raise_server_exceptions=False,
        )
    finally:
        app.dependency_overrides.clear()


class TestUploadTempfileLeak:
    def test_tempfile_cleaned_when_upload_file_raises(
        self, client, monkeypatch, tmp_path
    ):
        """Bug #6: se upload_file() raise, tempfile deve ser limpo."""
        # Snapshot dos arquivos .txt no tempdir antes
        tempdir = Path(tempfile.gettempdir())
        before = {
            f.name for f in tempdir.glob("tmp*.txt") if f.is_file()
        }

        # Monkeypatch upload_file para sempre raise IOError
        from api.routers import files as files_router

        def _broken_upload(db, path):
            raise IOError("simulated disk error")

        monkeypatch.setattr(files_router, "upload_file", _broken_upload)

        # POST com conteudo valido
        resp = client.post(
            "/api/files/upload",
            files={"file": ("sample.txt", b"|0000|test|\n", "text/plain")},
        )

        # Deve retornar erro (500 via handler global)
        assert resp.status_code >= 400

        # Assert: nenhum arquivo .txt novo ficou no tempdir
        after = {
            f.name for f in tempdir.glob("tmp*.txt") if f.is_file()
        }
        leaked = after - before
        assert not leaked, f"Tempfile(s) vazaram: {leaked}"
