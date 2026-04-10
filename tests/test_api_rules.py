"""Testes dos endpoints de regras (api/routers/rules.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from api.main import app

# ── Fixtures ──


@pytest.fixture
def rules_yaml(tmp_path: Path) -> Path:
    """Cria um rules.yaml temporario com regras de exemplo."""
    rules_file = tmp_path / "rules.yaml"
    data = {
        "version": "1.0",
        "tolerance": 0.01,
        "semantica_cst_cfop": [
            {
                "id": "CST_CFOP_001",
                "register": "C170",
                "fields": ["CST_ICMS", "CFOP"],
                "error_type": "CST_CFOP_INCONSISTENTE",
                "severity": "error",
                "description": "CST incompativel com CFOP de venda interestadual",
                "condition": "CST != 00 quando CFOP 6xxx",
                "implemented": True,
                "module": "fiscal_semantics.py",
            },
            {
                "id": "CST_CFOP_002",
                "register": "C100",
                "fields": ["CST_ICMS"],
                "error_type": "CST_EXPORT_INVALIDO",
                "severity": "warning",
                "description": "CST invalido para exportacao direta",
                "condition": "CST != 41 quando CFOP 7xxx",
                "implemented": False,
                "module": "fiscal_semantics.py",
            },
        ],
        "monofasicos": [
            {
                "id": "MONO_001",
                "register": "C170",
                "fields": ["CST_PIS", "CST_COFINS"],
                "error_type": "MONOFASICO_ALIQ_ERRADA",
                "severity": "critical",
                "description": "Aliquota monofasica incorreta para produto tributado",
                "condition": "Aliq PIS/COFINS != 0",
                "implemented": False,
                "module": "fiscal_semantics.py",
            },
        ],
    }
    with open(rules_file, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)
    return rules_file


@pytest.fixture
def client(rules_yaml: Path) -> TestClient:
    """TestClient que aponta _get_rules_path para o YAML temporario."""
    with patch("api.routers.rules._get_rules_path", return_value=rules_yaml):
        yield TestClient(app)


@pytest.fixture
def client_no_rules(tmp_path: Path) -> TestClient:
    """TestClient cujo rules.yaml nao existe."""
    missing = tmp_path / "nonexistent" / "rules.yaml"
    with patch("api.routers.rules._get_rules_path", return_value=missing):
        yield TestClient(app)


# ── list_rules ──


class TestListRules:
    def test_list_rules_success(self, client: TestClient) -> None:
        r = client.get("/api/rules")
        assert r.status_code == 200
        rules = r.json()
        assert len(rules) == 3
        ids = {rule["id"] for rule in rules}
        assert "CST_CFOP_001" in ids
        assert "MONO_001" in ids

    def test_list_rules_has_correct_fields(self, client: TestClient) -> None:
        r = client.get("/api/rules")
        rule = r.json()[0]
        for key in ("id", "block", "register", "error_type", "severity", "description", "implemented"):
            assert key in rule

    def test_list_rules_file_not_found(self, client_no_rules: TestClient) -> None:
        r = client_no_rules.get("/api/rules")
        assert r.status_code == 404
        assert "nao encontrado" in r.json()["detail"]


# ── generate_rule ──


class TestGenerateRule:
    def test_generate_rule_empty_description(self, client: TestClient) -> None:
        r = client.post("/api/rules/generate", json={"description": "  "})
        assert r.status_code == 400
        assert "vazia" in r.json()["detail"]

    def test_generate_rule_success_cfop_cst(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Verificar CFOP 5102 com CST 060 para item monofasico"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["id"]
        assert data["block"]
        assert data["register"]
        assert data["fields"]
        assert data["condition"]
        assert data["module"] == "fiscal_semantics.py"

    def test_generate_rule_detects_register_c100(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Validar nota NF-e com valor zerado"},
            )
        assert r.status_code == 200
        assert r.json()["register"] == "C100"

    def test_generate_rule_detects_register_e110(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Validar apuracao debito credito saldo"},
            )
        assert r.status_code == 200
        assert r.json()["register"] == "E110"

    def test_generate_rule_detects_register_h010(self) -> None:
        from api.routers.rules import _detect_register

        assert _detect_register("validar estoque inventario armazem") == "H010"

    def test_generate_rule_detects_register_by_pattern(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Verificar D100 com valor inconsistente"},
            )
        assert r.status_code == 200
        assert r.json()["register"] == "D100"

    def test_generate_rule_duplicate(self, client: TestClient) -> None:
        """Descricao muito semelhante a regra existente gera 409."""
        r = client.post(
            "/api/rules/generate",
            json={"description": "CST incompativel com CFOP de venda interestadual"},
        )
        assert r.status_code == 409
        assert "semelhante" in r.json()["detail"] or "ja existe" in r.json()["detail"]

    def test_generate_rule_detects_fields_cfop(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Validar CFOP NCM aliquota ICMS base calculo ICMS"},
            )
        data = r.json()
        assert r.status_code == 200
        assert "CFOP" in data["fields"]
        assert "NCM" in data["fields"]

    def test_generate_rule_detects_fields_pis_cofins(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Validar CST PIS e CST COFINS com valor PIS e valor COFINS"},
            )
        data = r.json()
        assert r.status_code == 200
        assert "CST_PIS" in data["fields"]
        assert "CST_COFINS" in data["fields"]

    def test_generate_rule_detects_block_monofasicos(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Produto monofasico xablau trebuchet unico"},
            )
        assert r.status_code == 200
        assert r.json()["block"] == "monofasicos"

    def test_generate_rule_detects_block_aliquota_zero(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Campo aliquota zero xablau trebuchet unico"},
            )
        assert r.status_code == 200
        assert r.json()["block"] == "semantica_aliquota_zero"

    def test_generate_rule_detects_block_isencao(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Verificar isencao tributado CST xablau trebuchet"},
            )
        assert r.status_code == 200
        assert r.json()["block"] == "cst_isencoes"

    def test_generate_rule_detects_block_recalculo(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Recalculo BC x aliquota trebuchet xablau unico"},
            )
        assert r.status_code == 200
        assert r.json()["block"] in ("recalculo", "base_calculo")

    def test_generate_rule_detects_block_cruzamento(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Cruzamento E110 vs trebuchet xablau unico"},
            )
        assert r.status_code == 200
        assert r.json()["block"] == "cruzamento"

    def test_generate_rule_detects_block_formato(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Formato CNPJ CPF invalido xablau trebuchet unico"},
            )
        assert r.status_code == 200
        assert r.json()["block"] == "formato"

    def test_generate_rule_severity_error(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Valor invalido xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert r.json()["severity"] == "error"

    def test_generate_rule_severity_critical(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Divergencia critico xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert r.json()["severity"] == "critical"

    def test_generate_rule_severity_info(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Informativo observacao xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert r.json()["severity"] == "info"

    def test_generate_rule_severity_warning_default(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Xablau trebuchet unico special foobar"},
            )
        assert r.status_code == 200
        assert r.json()["severity"] == "warning"

    def test_generate_error_type_monofasico(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Produto monofasico xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert "MONOFASICO" in r.json()["error_type"]

    def test_generate_error_type_cfop_cst(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "CFOP CST xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert "CST_CFOP" in r.json()["error_type"]

    def test_generate_error_type_aliquota(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Aliquota zerada xablau trebuchet unico special"},
            )
        assert r.status_code == 200
        assert any(kw in r.json()["error_type"] for kw in ("ALIQ", "CST_CFOP"))

    def test_generate_error_type_isencao(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Isencao xablau trebuchet unico special foobar"},
            )
        assert r.status_code == 200
        assert "ISENCAO" in r.json()["error_type"] or "CST" in r.json()["error_type"]

    def test_generate_error_type_generic(self, client: TestClient) -> None:
        with patch("api.routers.rules._search_legal_basis", return_value=[]):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Xablau trebuchet unico special foobar bazzz"},
            )
        assert r.status_code == 200
        # Should be significant words joined by underscore
        et = r.json()["error_type"]
        assert et  # non-empty

    def test_generate_rule_with_legal_sources(self, client: TestClient) -> None:
        mock_sources = [
            {
                "fonte": "Lei 12345/2020",
                "heading": "Art. 1",
                "content": "Texto legal...",
                "register": "C170",
                "score": 0.95,
            },
        ]
        with patch("api.routers.rules._search_legal_basis", return_value=mock_sources):
            r = client.post(
                "/api/rules/generate",
                json={"description": "Xablau trebuchet unico special foobar bazzz qux"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data["legal_sources"] is not None
        assert len(data["legal_sources"]) == 1


# ── implement_rule ──


class TestImplementRule:
    def _make_rule(self, **overrides) -> dict:
        base = {
            "id": "NEW_RULE_001",
            "block": "semantica_cst_cfop",
            "register": "C170",
            "fields": ["CST_ICMS"],
            "error_type": "NEW_ERROR_TYPE",
            "severity": "warning",
            "description": "Nova regra completamente diferente e unica xablau",
            "condition": "CST != esperado",
            "module": "fiscal_semantics.py",
            "legislation": None,
        }
        base.update(overrides)
        return base

    def test_implement_rule_success(self, client: TestClient, rules_yaml: Path) -> None:
        rule = self._make_rule()
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 200
        data = r.json()
        assert data["added"] is True
        assert data["rule_id"] == "NEW_RULE_001"

        # Verify it was written to the YAML
        with open(rules_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        ids = [e["id"] for e in saved["semantica_cst_cfop"]]
        assert "NEW_RULE_001" in ids

    def test_implement_rule_new_block(self, client: TestClient, rules_yaml: Path) -> None:
        rule = self._make_rule(
            id="NEWBLOCK_001",
            block="meu_novo_bloco",
            error_type="NOVO_TIPO_UNICO",
            description="Regra para bloco totalmente novo xablau foobar qux",
        )
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 200
        assert r.json()["block"] == "meu_novo_bloco"

        with open(rules_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert "meu_novo_bloco" in saved

    def test_implement_rule_with_legislation(self, client: TestClient, rules_yaml: Path) -> None:
        rule = self._make_rule(
            id="LEGIS_001",
            error_type="LEGIS_TIPO",
            description="Regra com legislacao xablau foobar trebuchet unica",
            legislation="Lei 12345/2020",
        )
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 200

        with open(rules_yaml, encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        entries = saved["semantica_cst_cfop"]
        legis_entry = next(e for e in entries if e["id"] == "LEGIS_001")
        assert legis_entry["legislation"] == "Lei 12345/2020"

    def test_implement_duplicate_id(self, client: TestClient) -> None:
        rule = self._make_rule(id="CST_CFOP_001")
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 409
        assert "ja existe" in r.json()["detail"]

    def test_implement_duplicate_error_type_register(self, client: TestClient) -> None:
        rule = self._make_rule(
            id="UNIQUE_ID_999",
            error_type="CST_CFOP_INCONSISTENTE",
            register="C170",
            description="Regra completamente diferente xablau trebuchet foobar qux",
        )
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 409
        assert "error_type" in r.json()["detail"]

    def test_implement_duplicate_description(self, client: TestClient) -> None:
        rule = self._make_rule(
            id="UNIQUE_ID_888",
            error_type="UNIQUE_TYPE_888",
            description="CST incompativel com CFOP venda interestadual",
        )
        r = client.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 409
        assert "semelhante" in r.json()["detail"]

    def test_implement_rule_no_yaml(self, client_no_rules: TestClient) -> None:
        rule = {
            "id": "X",
            "block": "b",
            "register": "C170",
            "fields": ["CST_ICMS"],
            "error_type": "E",
            "severity": "warning",
            "description": "desc",
            "condition": "cond",
            "module": "m.py",
        }
        r = client_no_rules.post("/api/rules/implement", json={"rule": rule})
        assert r.status_code == 500
        assert "nao encontrado" in r.json()["detail"]


# ── Helper functions (unit-level) ──


class TestHelpers:
    def test_find_duplicate_no_match(self) -> None:
        from api.routers.rules import _find_duplicate

        existing = [
            {"id": "R1", "description": "Verificar aliquota ICMS para produto X"},
        ]
        result = _find_duplicate("Algo completamente diferente xablau", existing)
        assert result is None

    def test_find_duplicate_match(self) -> None:
        from api.routers.rules import _find_duplicate

        existing = [
            {"id": "R1", "description": "Verificar aliquota ICMS para produto exportado"},
        ]
        result = _find_duplicate("Verificar aliquota ICMS produto exportado", existing)
        assert result is not None
        assert result["id"] == "R1"

    def test_find_duplicate_empty_words(self) -> None:
        from api.routers.rules import _find_duplicate

        result = _find_duplicate("o a de", [{"id": "R1", "description": "foo bar"}])
        assert result is None

    def test_find_duplicate_empty_existing_desc(self) -> None:
        from api.routers.rules import _find_duplicate

        result = _find_duplicate("algo valido aqui", [{"id": "R1", "description": ""}])
        assert result is None

    def test_search_legal_basis_no_db(self) -> None:
        from api.routers.rules import _search_legal_basis

        with patch("api.routers.rules.get_doc_db_path", return_value=None):
            result = _search_legal_basis("Verificar ICMS")
        assert result == []

    def test_search_legal_basis_exception(self) -> None:
        from api.routers.rules import _search_legal_basis

        with patch("api.routers.rules.get_doc_db_path", return_value="/fake/path.db"), \
             patch("src.searcher.search", side_effect=Exception("boom")):
            result = _search_legal_basis("Verificar ICMS")
        assert result == []

    def test_search_legal_basis_success(self) -> None:
        from api.routers.rules import _search_legal_basis

        mock_chunk = MagicMock()
        mock_chunk.source_file = "lei_icms.md"
        mock_chunk.heading = "Art. 1"
        mock_chunk.content = "Texto da legislacao"
        mock_chunk.register = "C170"

        mock_result = MagicMock()
        mock_result.chunk = mock_chunk
        mock_result.score = 0.85

        with patch("api.routers.rules.get_doc_db_path", return_value="/fake/path.db"), \
             patch("src.searcher.search", return_value=[mock_result]):
            result = _search_legal_basis("Verificar ICMS")
        assert len(result) == 1
        assert result[0]["fonte"] == "lei icms"
        assert result[0]["score"] == 0.85

    def test_extract_legislation_with_matches(self) -> None:
        from api.routers.rules import _extract_legislation

        sources = [
            {"fonte": "Lei 12345/2020 regulamento", "heading": "Art 1", "content": "x"},
            {"fonte": "decreto 9876/2019 icms", "heading": "", "content": ""},
        ]
        result = _extract_legislation(sources)
        assert result is not None
        assert "Lei" in result or "Decreto" in result

    def test_extract_legislation_no_matches(self) -> None:
        from api.routers.rules import _extract_legislation

        sources = [
            {"fonte": "arquivo qualquer", "heading": "titulo", "content": "x"},
        ]
        result = _extract_legislation(sources)
        assert result is None

    def test_extract_legislation_empty(self) -> None:
        from api.routers.rules import _extract_legislation

        result = _extract_legislation([])
        assert result is None

    def test_extract_legislation_various_patterns(self) -> None:
        from api.routers.rules import _extract_legislation

        sources = [
            {"fonte": "Convênio ICMS 142/2018", "heading": "", "content": ""},
            {"fonte": "Ajuste SINIEF 07/2005", "heading": "", "content": ""},
            {"fonte": "Ato COTEPE 44/2018", "heading": "IN RFB 1234/2020", "content": ""},
        ]
        result = _extract_legislation(sources)
        assert result is not None

    def test_generate_id_with_stopwords(self) -> None:
        from api.routers.rules import _generate_id

        result = _generate_id("Verificar o campo ICMS para exportacao", "formato")
        assert result.startswith("FMT_")
        assert "O" not in result.split("_")[1:]  # stopword removed

    def test_generate_id_empty_significant(self) -> None:
        from api.routers.rules import _generate_id

        result = _generate_id("o a de", "formato")
        assert result == "FMT_NOVA"

    def test_generate_condition(self) -> None:
        from api.routers.rules import _generate_condition

        result = _generate_condition("Minha regra especial", "C170", ["CFOP"])
        assert "minha regra especial" in result.lower()

    def test_detect_fields_default(self) -> None:
        from api.routers.rules import _detect_fields

        result = _detect_fields("algo sem campos conhecidos xablau")
        assert result == ["CST_ICMS"]

    def test_detect_fields_ipi(self) -> None:
        from api.routers.rules import _detect_fields

        result = _detect_fields("verificar cst ipi e vl ipi")
        assert "CST_IPI" in result
        assert "VL_IPI" in result

    def test_detect_fields_doc_item_part(self) -> None:
        from api.routers.rules import _detect_fields

        result = _detect_fields("verificar vl_doc cod_item cod_part ind_oper")
        assert "VL_DOC" in result
        assert "COD_ITEM" in result
        assert "COD_PART" in result
        assert "IND_OPER" in result

    def test_detect_register_0000(self) -> None:
        from api.routers.rules import _detect_register

        assert _detect_register("verificar 0200 participante") == "0200"

    def test_detect_register_default(self) -> None:
        from api.routers.rules import _detect_register

        assert _detect_register("algo sem registro") == "C170"

    def test_load_existing_rules_no_file(self) -> None:
        from api.routers.rules import _load_existing_rules

        with patch("api.routers.rules._get_rules_path", return_value=Path("/no/such/file.yaml")):
            result = _load_existing_rules()
        assert result == []
