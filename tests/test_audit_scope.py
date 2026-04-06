"""Testes do MOD-11 (Dashboard de Escopo) e MOD-12 (Separação de Metarregras)."""

from __future__ import annotations

import json
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
    """Banco com arquivo SPED, registro 0000, e erros fiscais + governance."""
    # Arquivo SPED
    audit_db.execute(
        """INSERT INTO sped_files (id, filename, hash_sha256, status, total_errors)
           VALUES (1, 'test.txt', 'abc123', 'validated', 5)"""
    )

    # Registro 0000 para build_context
    fields_0000 = {
        "REG": "0000",
        "COD_VER": "016",
        "COD_FIN": "0",
        "DT_INI": "01012024",
        "DT_FIN": "31012024",
        "NOME": "Empresa Teste Ltda",
        "CNPJ": "12345678000195",
        "UF": "SP",
        "IND_PERFIL": "A",
    }
    raw_0000 = "|" + "|".join(fields_0000.values()) + "|"
    audit_db.execute(
        """INSERT INTO sped_records (id, file_id, line_number, register, block, fields_json, raw_line)
           VALUES (1, 1, 1, '0000', '0', ?, ?)""",
        (json.dumps(fields_0000, ensure_ascii=False), raw_0000),
    )

    # Erros fiscais
    for i in range(3):
        audit_db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message, categoria)
               VALUES (1, ?, 'C170', 'CALCULO_DIVERGENTE', 'critical', 'Erro fiscal teste', 'fiscal')""",
            (10 + i,),
        )

    # Erros governance (metarregras)
    audit_db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, error_type, severity, message, categoria)
           VALUES (1, 0, 'SPED', 'CHECKLIST_INCOMPLETO', 'info',
                   'Checklist incompleto', 'governance')"""
    )
    audit_db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, error_type, severity, message, categoria)
           VALUES (1, 0, 'SPED', 'CLASSIFICACAO_TIPO_ERRO', 'info',
                   'Classificacao de erros', 'governance')"""
    )
    audit_db.execute(
        """INSERT INTO validation_errors
           (file_id, line_number, register, error_type, severity, message, categoria)
           VALUES (1, 0, 'SPED', 'ACHADO_LIMITADO_AO_SPED', 'info',
                   'Achados baseados apenas no SPED', 'governance')"""
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
    app.dependency_overrides.clear()


# ──────────────────────────────────────────────
# MOD-11: Audit Scope
# ──────────────────────────────────────────────

class TestAuditScope:
    """Testes do endpoint /audit-scope."""

    def test_audit_scope_returns_complete_structure(self, client: TestClient) -> None:
        """Endpoint retorna estrutura completa com todos os campos."""
        resp = client.get("/api/files/1/audit-scope")
        assert resp.status_code == 200
        data = resp.json()

        # Campos obrigatórios
        assert "regime_identificado" in data
        assert "periodo" in data
        assert "checks_executados" in data
        assert "tabelas_externas" in data
        assert "cobertura_estimada_pct" in data

        # Regime e periodo
        assert data["regime_identificado"] == "normal"
        assert data["periodo"] == "01/2024"

        # Checks executados
        assert isinstance(data["checks_executados"], list)
        assert len(data["checks_executados"]) > 0
        check_ids = [c["id"] for c in data["checks_executados"]]
        assert "format_validation" in check_ids
        assert "intra_register" in check_ids
        assert "audit_beneficios" in check_ids
        assert "difal_validation" in check_ids
        assert "st_com_mva" in check_ids
        assert "simples_nacional_cst" in check_ids

        # Cada check tem campos obrigatorios
        for check in data["checks_executados"]:
            assert "id" in check
            assert "status" in check
            assert check["status"] in ("ok", "parcial", "nao_executado", "nao_aplicavel")

        # Tabelas externas
        assert isinstance(data["tabelas_externas"], dict)
        for key in ("aliquotas_internas_uf", "fcp_por_uf", "ncm_tipi", "mva_por_ncm_uf", "codigos_ajuste_uf"):
            assert key in data["tabelas_externas"]
            assert data["tabelas_externas"][key] in ("disponivel", "indisponivel")

        # Cobertura
        assert isinstance(data["cobertura_estimada_pct"], int)
        assert 0 <= data["cobertura_estimada_pct"] <= 100

    def test_simples_nacional_check_not_applicable_for_normal(self, client: TestClient) -> None:
        """Para Regime Normal, simples_nacional_cst deve ser nao_aplicavel."""
        resp = client.get("/api/files/1/audit-scope")
        data = resp.json()
        sn_check = next(c for c in data["checks_executados"] if c["id"] == "simples_nacional_cst")
        assert sn_check["status"] == "nao_aplicavel"


# ──────────────────────────────────────────────
# MOD-12: Separação de Metarregras
# ──────────────────────────────────────────────

class TestMetarregras:
    """Testes de separação de metarregras (governance) do pipeline fiscal."""

    def test_errors_fiscal_default_excludes_governance(self, client: TestClient) -> None:
        """GET /errors (default categoria=fiscal) nao retorna metarregras."""
        resp = client.get("/api/files/1/errors")
        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]

        # Deve retornar apenas erros fiscais
        assert len(data) == 3
        for err in data:
            assert err["categoria"] == "fiscal"
            assert err["error_type"] not in (
                "CHECKLIST_INCOMPLETO",
                "CLASSIFICACAO_TIPO_ERRO",
                "ACHADO_LIMITADO_AO_SPED",
            )

    def test_errors_governance_returns_only_metarregras(self, client: TestClient) -> None:
        """GET /errors?categoria=governance retorna apenas metarregras."""
        resp = client.get("/api/files/1/errors?categoria=governance")
        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]

        assert len(data) == 3
        governance_types = {e["error_type"] for e in data}
        assert governance_types == {
            "CHECKLIST_INCOMPLETO",
            "CLASSIFICACAO_TIPO_ERRO",
            "ACHADO_LIMITADO_AO_SPED",
        }
        for err in data:
            assert err["categoria"] == "governance"

    def test_governance_errors_have_correct_severity(self, client: TestClient) -> None:
        """Metarregras devem ter severity=info."""
        resp = client.get("/api/files/1/errors?categoria=governance")
        data = resp.json()["data"]
        for err in data:
            assert err["severity"] == "info"
