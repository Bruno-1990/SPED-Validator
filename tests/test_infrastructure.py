"""Testes de infraestrutura MOD-19: upload limit, paginacao, embedding metadata."""

from __future__ import annotations

import io
import json
import sqlite3
import warnings
from pathlib import Path
from unittest.mock import patch

import pytest

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)

from fastapi.testclient import TestClient  # noqa: E402

from api.deps import get_db  # noqa: E402
from api.main import app  # noqa: E402
from api.routers.files import MAX_FILE_SIZE  # noqa: E402
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
    """Banco com arquivo, registros e erros para testar paginacao."""
    audit_db.execute(
        """INSERT INTO sped_files (id, filename, hash_sha256, status, total_errors)
           VALUES (1, 'test.txt', 'abc123def456', 'validated', 5)"""
    )

    fields_0000 = {
        "REG": "0000", "COD_VER": "016", "COD_FIN": "0",
        "DT_INI": "01012024", "DT_FIN": "31012024",
        "NOME": "Empresa Teste Ltda", "CNPJ": "12345678000195",
        "UF": "SP", "IND_PERFIL": "A",
    }
    raw_0000 = "|" + "|".join(fields_0000.values()) + "|"
    audit_db.execute(
        """INSERT INTO sped_records (id, file_id, line_number, register, block, fields_json, raw_line)
           VALUES (1, 1, 1, '0000', '0', ?, ?)""",
        (json.dumps(fields_0000, ensure_ascii=False), raw_0000),
    )

    # Inserir 5 registros C170 para paginacao
    for i in range(5):
        fields = {"REG": "C170", "NUM_ITEM": str(i + 1)}
        audit_db.execute(
            """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
               VALUES (1, ?, 'C170', 'C', ?, ?)""",
            (10 + i, json.dumps(fields, ensure_ascii=False), f"|C170|{i+1}|"),
        )

    # Inserir 5 erros de validacao para paginacao
    for i in range(5):
        audit_db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message, categoria)
               VALUES (1, ?, 'C170', 'CALCULO_DIVERGENTE', 'critical',
                       'Erro de calculo teste', 'fiscal')""",
            (10 + i,),
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
    c = TestClient(app)
    yield c
    app.dependency_overrides.pop(get_db, None)


# ──────────────────────────────────────────────
# Upload size limit (413)
# ──────────────────────────────────────────────

class TestUploadSizeLimit:
    """Upload > 100 MB deve retornar 413."""

    def test_upload_over_limit_returns_413(self, client: TestClient) -> None:
        # Usar MAX_FILE_SIZE reduzido via mock para evitar alocar 50MB+
        with patch("api.routers.files.MAX_FILE_SIZE", 1024):
            oversized = b"x" * 2048  # 2KB > 1KB limite mockado
            response = client.post(
                "/api/files/upload",
                files={"file": ("big.txt", io.BytesIO(oversized), "text/plain")},
            )
            assert response.status_code == 413

    def test_upload_small_file_accepted(self, client: TestClient) -> None:
        # Arquivo SPED minimo valido
        content = b"|0000|016|0|01012024|31012024|Teste|12345678000195|SP|\n"
        response = client.post(
            "/api/files/upload",
            files={"file": ("small.txt", io.BytesIO(content), "text/plain")},
        )
        # Pode ser 200 (sucesso) ou outro codigo, mas nao 413
        assert response.status_code != 413


# ──────────────────────────────────────────────
# Paginacao /records
# ──────────────────────────────────────────────

class TestRecordsPagination:
    """GET /records retorna estrutura paginada correta."""

    def test_records_returns_paginated_structure(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/records?page=1&page_size=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_next" in data
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_records_page_size_limits_results(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/records?page=1&page_size=2")
        data = resp.json()
        assert len(data["data"]) <= 2
        assert data["page"] == 1
        assert data["page_size"] == 2

    def test_records_has_next_true_when_more_pages(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/records?page=1&page_size=2")
        data = resp.json()
        # 6 registros total (1 x 0000 + 5 x C170), page_size=2 => has_next=True
        assert data["has_next"] is True
        assert data["total"] == 6

    def test_records_page2_returns_next_items(self, client: TestClient) -> None:
        resp1 = client.get("/api/files/1/records?page=1&page_size=2")
        resp2 = client.get("/api/files/1/records?page=2&page_size=2")
        data1 = resp1.json()
        data2 = resp2.json()
        # Paginas devem ter itens diferentes
        ids1 = {r["id"] for r in data1["data"]}
        ids2 = {r["id"] for r in data2["data"]}
        assert ids1.isdisjoint(ids2)


# ──────────────────────────────────────────────
# Paginacao /errors
# ──────────────────────────────────────────────

class TestErrorsPagination:
    """GET /errors retorna estrutura paginada correta."""

    def test_errors_returns_paginated_structure(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/errors?page=1&page_size=2")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "page_size" in data
        assert "has_next" in data
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_errors_page2_returns_next_page(self, client: TestClient) -> None:
        resp1 = client.get("/api/files/1/errors?page=1&page_size=2")
        resp2 = client.get("/api/files/1/errors?page=2&page_size=2")
        data1 = resp1.json()
        data2 = resp2.json()

        assert data1["page"] == 1
        assert data2["page"] == 2
        assert len(data1["data"]) == 2
        assert len(data2["data"]) == 2
        # IDs devem ser distintos entre paginas
        ids1 = {r["id"] for r in data1["data"]}
        ids2 = {r["id"] for r in data2["data"]}
        assert ids1.isdisjoint(ids2)

    def test_errors_has_next_false_on_last_page(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/errors?page=3&page_size=2")
        data = resp.json()
        assert data["has_next"] is False
        assert len(data["data"]) == 1  # 5 total, page 3 of 2 = 1 item

    def test_errors_total_is_correct(self, client: TestClient) -> None:
        resp = client.get("/api/files/1/errors?page=1&page_size=100")
        data = resp.json()
        assert data["total"] == 5
