"""Testes para o MOD-04: Versionamento de Regras por Vigência Fiscal."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from src.services.rule_loader import RuleLoader


@pytest.fixture
def tmp_rules(tmp_path: Path) -> Path:
    """Cria um rules.yaml temporário com regras de vigências variadas."""
    rules = {
        "version": "1.0",
        "tolerance": 0.02,
        "formato": [
            {
                "id": "REGRA_SEMPRE",
                "register": "*",
                "fields": ["CNPJ"],
                "error_type": "FORMATO_INVALIDO",
                "severity": "error",
                "description": "Regra sem vigencia especifica",
                "condition": "test",
                "implemented": True,
                "module": "test.py",
                "vigencia_de": "2000-01-01",
                "vigencia_ate": None,
                "version": "1.0",
                "last_updated": "2026-04-05",
            },
            {
                "id": "REGRA_RS13_2012",
                "register": "C170",
                "fields": ["ALIQ_ICMS"],
                "error_type": "ALIQ_INTERESTADUAL_INVALIDA",
                "severity": "critical",
                "description": "Regra RS 13/2012 vigente desde 2013",
                "condition": "test",
                "implemented": True,
                "module": "test.py",
                "vigencia_de": "2013-01-01",
                "vigencia_ate": None,
                "version": "1.0",
                "last_updated": "2026-04-05",
            },
            {
                "id": "REGRA_EC87_2015",
                "register": "C170",
                "fields": ["CFOP"],
                "error_type": "DIFAL_FALTANTE",
                "severity": "critical",
                "description": "DIFAL EC 87/2015 vigente desde 2016",
                "condition": "test",
                "implemented": True,
                "module": "test.py",
                "vigencia_de": "2016-01-01",
                "vigencia_ate": None,
                "version": "1.0",
                "last_updated": "2026-04-05",
            },
            {
                "id": "REGRA_EXPIRADA",
                "register": "*",
                "fields": ["*"],
                "error_type": "REGRA_VELHA",
                "severity": "warning",
                "description": "Regra que expirou em 2023-06-30",
                "condition": "test",
                "implemented": True,
                "module": "test.py",
                "vigencia_de": "2010-01-01",
                "vigencia_ate": "2023-06-30",
                "version": "1.0",
                "last_updated": "2026-04-05",
            },
            {
                "id": "REGRA_FUTURA",
                "register": "*",
                "fields": ["*"],
                "error_type": "REGRA_NOVA",
                "severity": "error",
                "description": "Regra que so entra em vigor em 2027",
                "condition": "test",
                "implemented": True,
                "module": "test.py",
                "vigencia_de": "2027-01-01",
                "vigencia_ate": None,
                "version": "1.0",
                "last_updated": "2026-04-05",
            },
        ],
    }
    path = tmp_path / "rules.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(rules, f, default_flow_style=False, allow_unicode=True)
    return path


class TestRuleLoader:
    """Testes do RuleLoader."""

    def test_periodo_2021_exclui_regras_futuras(self, tmp_rules: Path) -> None:
        """Período 2021-01: regras com vigencia_de > 2021-12 não carregadas."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2021, 1, 1), date(2021, 1, 31)
        )
        active_ids = {r["id"] for r in active}

        # Regras vigentes em 2021
        assert "REGRA_SEMPRE" in active_ids
        assert "REGRA_RS13_2012" in active_ids
        assert "REGRA_EXPIRADA" in active_ids  # Ainda válida em 2021

        # Regras NÃO vigentes em 2021
        assert "REGRA_EC87_2015" not in active_ids or "REGRA_EC87_2015" in active_ids
        # EC87 vigente desde 2016 -> vigente em 2021
        assert "REGRA_EC87_2015" in active_ids
        assert "REGRA_FUTURA" not in active_ids  # Só em 2027

    def test_periodo_2024_regras_vigentes(self, tmp_rules: Path) -> None:
        """Período 2024-01: regras vigentes retornadas corretamente."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2024, 1, 1), date(2024, 1, 31)
        )
        active_ids = {r["id"] for r in active}

        assert "REGRA_SEMPRE" in active_ids
        assert "REGRA_RS13_2012" in active_ids
        assert "REGRA_EC87_2015" in active_ids
        # Expirada em 2023-06-30 -> NÃO vigente em 2024
        assert "REGRA_EXPIRADA" not in active_ids
        # Futura -> NÃO vigente
        assert "REGRA_FUTURA" not in active_ids

    def test_regra_expirada_nao_carregada(self, tmp_rules: Path) -> None:
        """Regra com vigencia_ate expirada não é carregada para período posterior."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2024, 1, 1), date(2024, 12, 31)
        )
        active_ids = {r["id"] for r in active}
        assert "REGRA_EXPIRADA" not in active_ids

    def test_regra_expirada_carregada_quando_vigente(self, tmp_rules: Path) -> None:
        """Regra com vigencia_ate é carregada quando o período cai dentro da vigência."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2023, 1, 1), date(2023, 1, 31)
        )
        active_ids = {r["id"] for r in active}
        assert "REGRA_EXPIRADA" in active_ids

    def test_load_all_retorna_todas(self, tmp_rules: Path) -> None:
        """load_all_rules retorna todas as regras sem filtro."""
        loader = RuleLoader(tmp_rules)
        all_rules = loader.load_all_rules()
        assert len(all_rules) == 5

    def test_periodo_2012_exclui_rs13(self, tmp_rules: Path) -> None:
        """Período 2012: RS 13/2012 (vigencia_de=2013-01-01) não vigente."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2012, 1, 1), date(2012, 12, 31)
        )
        active_ids = {r["id"] for r in active}
        assert "REGRA_RS13_2012" not in active_ids
        assert "REGRA_EC87_2015" not in active_ids
        assert "REGRA_SEMPRE" in active_ids

    def test_regra_futura_vigente_em_2027(self, tmp_rules: Path) -> None:
        """Regra futura é carregada quando o período é 2027."""
        loader = RuleLoader(tmp_rules)
        active = loader.load_rules_for_period(
            date(2027, 1, 1), date(2027, 1, 31)
        )
        active_ids = {r["id"] for r in active}
        assert "REGRA_FUTURA" in active_ids


class TestRuleLoaderWithRealFile:
    """Testes com o rules.yaml real do projeto."""

    def test_rules_yaml_tem_vigencia_em_todas_regras(self) -> None:
        """Todas as regras no rules.yaml real devem ter campos de vigência."""
        loader = RuleLoader()
        all_rules = loader.load_all_rules()
        assert len(all_rules) >= 121  # Mínimo especificado no PRD

        for rule in all_rules:
            assert "vigencia_de" in rule, f"Regra {rule['id']} sem vigencia_de"
            assert "vigencia_ate" in rule, f"Regra {rule['id']} sem vigencia_ate"
            assert "version" in rule, f"Regra {rule['id']} sem version"
            assert "last_updated" in rule, f"Regra {rule['id']} sem last_updated"

    def test_difal_nao_vigente_antes_2016(self) -> None:
        """Regras DIFAL (EC 87/2015) não devem ser vigentes antes de 2016."""
        loader = RuleLoader()
        active = loader.load_rules_for_period(
            date(2015, 1, 1), date(2015, 12, 31)
        )
        active_ids = {r["id"] for r in active}

        difal_ids = {"DIFAL_001", "DIFAL_002", "DIFAL_003", "DIFAL_004",
                     "DIFAL_005", "DIFAL_006", "DIFAL_007", "DIFAL_008"}
        for did in difal_ids:
            assert did not in active_ids, f"{did} não deveria estar vigente em 2015"

    def test_difal_vigente_em_2024(self) -> None:
        """Regras DIFAL devem estar vigentes em 2024."""
        loader = RuleLoader()
        active = loader.load_rules_for_period(
            date(2024, 1, 1), date(2024, 1, 31)
        )
        active_ids = {r["id"] for r in active}

        assert "DIFAL_001" in active_ids
        assert "DIFAL_008" in active_ids

    def test_rs13_nao_vigente_antes_2013(self) -> None:
        """Regra ALIQ_001 (RS 13/2012) não vigente antes de 2013."""
        loader = RuleLoader()
        active = loader.load_rules_for_period(
            date(2012, 6, 1), date(2012, 6, 30)
        )
        active_ids = {r["id"] for r in active}
        assert "ALIQ_001" not in active_ids
