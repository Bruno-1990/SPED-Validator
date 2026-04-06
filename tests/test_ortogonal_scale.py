"""MOD-13: Testes da Escala Ortogonal de Achados (certeza x impacto)."""

from __future__ import annotations

import sqlite3

import pytest

from src.models import ValidationError
from src.services.database import init_audit_db
from src.services.rule_loader import RuleLoader
from src.services.validation_service import _load_certeza_impacto, _persist_errors, get_errors


@pytest.fixture
def audit_db(tmp_path) -> sqlite3.Connection:
    """Banco de auditoria com schema completo incluindo migration 6."""
    db_path = tmp_path / "audit.db"
    conn = init_audit_db(db_path)
    conn.row_factory = sqlite3.Row
    # Inserir arquivo de teste
    conn.execute(
        "INSERT INTO sped_files (id, filename, hash_sha256) VALUES (1, 'test.txt', 'abc123')",
    )
    conn.commit()
    return conn


class TestDatabaseColumns:
    """Verifica que as colunas certeza e impacto existem na tabela."""

    def test_certeza_column_exists(self, audit_db: sqlite3.Connection):
        cols = [
            row[1]
            for row in audit_db.execute("PRAGMA table_info(validation_errors)").fetchall()
        ]
        assert "certeza" in cols

    def test_impacto_column_exists(self, audit_db: sqlite3.Connection):
        cols = [
            row[1]
            for row in audit_db.execute("PRAGMA table_info(validation_errors)").fetchall()
        ]
        assert "impacto" in cols

    def test_certeza_default_value(self, audit_db: sqlite3.Connection):
        audit_db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message)
               VALUES (1, 1, 'C170', 'TEST', 'error', 'teste')"""
        )
        row = audit_db.execute(
            "SELECT certeza FROM validation_errors WHERE error_type = 'TEST'"
        ).fetchone()
        assert row[0] == "objetivo"

    def test_impacto_default_value(self, audit_db: sqlite3.Connection):
        audit_db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message)
               VALUES (1, 1, 'C170', 'TEST2', 'error', 'teste')"""
        )
        row = audit_db.execute(
            "SELECT impacto FROM validation_errors WHERE error_type = 'TEST2'"
        ).fetchone()
        assert row[0] == "relevante"


class TestRulesYamlMapping:
    """Verifica que todas as regras no rules.yaml possuem certeza e impacto."""

    def test_all_rules_have_certeza_impacto(self):
        loader = RuleLoader()
        rules = loader.load_all_rules()
        assert len(rules) >= 121, f"Esperado >= 121 regras, encontrado {len(rules)}"
        for rule in rules:
            rule_id = rule.get("id", "?")
            assert "certeza" in rule, f"Regra {rule_id} sem campo certeza"
            assert "impacto" in rule, f"Regra {rule_id} sem campo impacto"
            assert rule["certeza"] in ("objetivo", "provavel", "indicio"), (
                f"Regra {rule_id}: certeza={rule['certeza']} invalida"
            )
            assert rule["impacto"] in ("critico", "relevante", "informativo"), (
                f"Regra {rule_id}: impacto={rule['impacto']} invalido"
            )

    def test_recalculo_rules_are_objetivo_critico(self):
        """Erros matematicos (BC*ALIQ != VL_ICMS) devem ser objetivo + critico."""
        loader = RuleLoader()
        rules = loader.load_all_rules()
        recalc_rules = [r for r in rules if r["id"].startswith("RECALC_")]
        assert len(recalc_rules) >= 7
        for rule in recalc_rules:
            assert rule["certeza"] == "objetivo", f"{rule['id']}: certeza deveria ser objetivo"
            assert rule["impacto"] == "critico", f"{rule['id']}: impacto deveria ser critico"

    def test_metarregras_are_objetivo_informativo(self):
        """Metarregras devem ser objetivo + informativo."""
        loader = RuleLoader()
        rules = loader.load_all_rules()
        meta_rules = [r for r in rules if r.get("tipo_achado") == "metarregra"]
        assert len(meta_rules) >= 4
        for rule in meta_rules:
            assert rule["certeza"] == "objetivo", f"{rule['id']}: certeza deveria ser objetivo"
            assert rule["impacto"] == "informativo", f"{rule['id']}: impacto deveria ser informativo"

    def test_indicios_never_objetivo(self):
        """Regras com tipo_achado=indicio devem ter certeza=indicio."""
        loader = RuleLoader()
        rules = loader.load_all_rules()
        indicio_rules = [r for r in rules if r.get("tipo_achado") == "indicio"]
        for rule in indicio_rules:
            assert rule["certeza"] == "indicio", (
                f"{rule['id']}: tipo_achado=indicio mas certeza={rule['certeza']}"
            )


class TestPersistErrors:
    """Verifica que _persist_errors salva certeza/impacto corretos."""

    def test_recalculo_error_saved_with_objetivo_critico(self, audit_db: sqlite3.Connection):
        """Regra de recalculo deve persistir com certeza=objetivo, impacto=critico."""
        errors = [
            ValidationError(
                line_number=10,
                register="C170",
                field_no=7,
                field_name="VL_ICMS",
                value="100.00",
                error_type="CALCULO_DIVERGENTE",
                message="VL_ICMS diverge do recalculo",
            ),
        ]
        _persist_errors(audit_db, 1, errors)

        row = audit_db.execute(
            "SELECT certeza, impacto FROM validation_errors WHERE error_type = 'CALCULO_DIVERGENTE'"
        ).fetchone()
        assert row is not None
        assert row["certeza"] == "objetivo"
        assert row["impacto"] == "critico"

    def test_indicio_error_saved(self, audit_db: sqlite3.Connection):
        """Erro de indicio fiscal deve ser salvo com certeza correta."""
        errors = [
            ValidationError(
                line_number=20,
                register="C190",
                field_no=1,
                field_name="CST_ICMS",
                value="040",
                error_type="VOLUME_ISENTO_ATIPICO",
                message="Volume excessivo de CST isento",
            ),
        ]
        _persist_errors(audit_db, 1, errors)

        row = audit_db.execute(
            "SELECT certeza, impacto FROM validation_errors WHERE error_type = 'VOLUME_ISENTO_ATIPICO'"
        ).fetchone()
        assert row is not None
        assert row["certeza"] == "indicio"
        assert row["impacto"] == "relevante"


class TestGetErrorsFilters:
    """Verifica filtros ?certeza= e ?impacto= no get_errors."""

    def _seed_errors(self, db: sqlite3.Connection):
        """Insere erros de teste com diferentes combinacoes."""
        db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message, categoria, certeza, impacto)
               VALUES (1, 10, 'C170', 'CALCULO_DIVERGENTE', 'critical', 'erro math', 'fiscal', 'objetivo', 'critico')"""
        )
        db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message, categoria, certeza, impacto)
               VALUES (1, 20, 'C190', 'VOLUME_ISENTO_ATIPICO', 'warning',
                       'indicio', 'fiscal', 'indicio', 'relevante')"""
        )
        db.execute(
            """INSERT INTO validation_errors
               (file_id, line_number, register, error_type, severity, message, categoria, certeza, impacto)
               VALUES (1, 30, 'E110', 'CHECKLIST_INCOMPLETO', 'info', 'meta', 'fiscal', 'objetivo', 'informativo')"""
        )
        db.commit()

    def test_filter_certeza_objetivo(self, audit_db: sqlite3.Connection):
        self._seed_errors(audit_db)
        rows = get_errors(audit_db, 1, certeza="objetivo", categoria="fiscal")
        assert len(rows) == 2
        assert all(r["certeza"] == "objetivo" for r in rows)

    def test_filter_certeza_indicio(self, audit_db: sqlite3.Connection):
        self._seed_errors(audit_db)
        rows = get_errors(audit_db, 1, certeza="indicio", categoria="fiscal")
        assert len(rows) == 1
        assert rows[0]["error_type"] == "VOLUME_ISENTO_ATIPICO"

    def test_filter_impacto_critico(self, audit_db: sqlite3.Connection):
        self._seed_errors(audit_db)
        rows = get_errors(audit_db, 1, impacto="critico", categoria="fiscal")
        assert len(rows) == 1
        assert rows[0]["error_type"] == "CALCULO_DIVERGENTE"

    def test_filter_combined(self, audit_db: sqlite3.Connection):
        self._seed_errors(audit_db)
        rows = get_errors(audit_db, 1, certeza="objetivo", impacto="informativo", categoria="fiscal")
        assert len(rows) == 1
        assert rows[0]["error_type"] == "CHECKLIST_INCOMPLETO"


class TestCertezaImpactoCache:
    """Verifica que o cache de certeza/impacto carrega do rules.yaml."""

    def test_load_certeza_impacto_returns_dict(self):
        mapping = _load_certeza_impacto()
        assert isinstance(mapping, dict)
        assert len(mapping) > 0

    def test_calculo_divergente_is_objetivo_critico(self):
        mapping = _load_certeza_impacto()
        assert "CALCULO_DIVERGENTE" in mapping
        certeza, impacto = mapping["CALCULO_DIVERGENTE"]
        assert certeza == "objetivo"
        assert impacto == "critico"
