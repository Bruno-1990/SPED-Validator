"""Tests for src/rules.py — loader and validator for rules.yaml."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.rules import (
    _KNOWN_ERROR_TYPES,
    RULES_PATH,
    Rule,
    _count_by_block,
    _count_by_severity,
    check_rules,
    load_rules,
    print_block,
    print_pending,
    print_summary,
    print_vigentes,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rule(**overrides) -> Rule:
    """Create a Rule with sensible defaults, overridden as needed."""
    defaults = dict(
        id="TST_001",
        block="formato",
        register="C100",
        fields=["VL_MERC"],
        error_type="FORMATO_INVALIDO",
        severity="error",
        description="Regra de teste",
        condition="campo vazio",
        implemented=True,
        module="test_module.py",
        legislation=None,
        vigencia_de=None,
        vigencia_ate=None,
        version=None,
        last_updated=None,
        corrigivel="proposta",
    )
    defaults.update(overrides)
    return Rule(**defaults)


def _write_yaml(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "rules.yaml"
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Rule dataclass
# ---------------------------------------------------------------------------

class TestRuleDataclass:
    def test_defaults(self):
        r = Rule(
            id="X", block="b", register="r", fields=[], error_type="E",
            severity="error", description="d", condition="c",
            implemented=False, module="m",
        )
        assert r.legislation is None
        assert r.vigencia_de is None
        assert r.vigencia_ate is None
        assert r.version is None
        assert r.last_updated is None

    def test_all_fields(self):
        r = _make_rule(legislation="Art. 1", vigencia_de="2024-01-01",
                       vigencia_ate="2025-12-31", version="1.1",
                       last_updated="2025-06-01")
        assert r.legislation == "Art. 1"
        assert r.vigencia_de == "2024-01-01"
        assert r.vigencia_ate == "2025-12-31"
        assert r.version == "1.1"
        assert r.last_updated == "2025-06-01"


# ---------------------------------------------------------------------------
# load_rules
# ---------------------------------------------------------------------------

class TestLoadRules:
    def test_load_from_real_file(self):
        """Smoke test: real rules.yaml loads without error."""
        rules = load_rules()
        assert len(rules) > 0
        assert all(isinstance(r, Rule) for r in rules)

    def test_load_simple_yaml(self, tmp_path):
        data = {
            "version": "1.0",
            "tolerance": 0.02,
            "bloco_teste": [
                {
                    "id": "BT_001",
                    "register": "C100",
                    "fields": ["VL_MERC"],
                    "error_type": "FORMATO_INVALIDO",
                    "severity": "error",
                    "description": "desc",
                    "condition": "cond",
                    "implemented": True,
                    "module": "mod.py",
                },
                {
                    "id": "BT_002",
                    "register": "C170",
                    "fields": ["VL_ITEM", "VL_DESC"],
                    "error_type": "SOMA_DIVERGENTE",
                    "severity": "warning",
                    "description": "desc2",
                    "condition": "cond2",
                    "implemented": False,
                    "module": "mod2.py",
                    "legislation": "Art 5",
                    "vigencia_de": "2024-01-01",
                    "vigencia_ate": "2025-12-31",
                    "version": "1.0",
                    "last_updated": "2024-06-01",
                },
            ],
        }
        path = _write_yaml(tmp_path, data)
        rules = load_rules(path)
        assert len(rules) == 2
        assert rules[0].id == "BT_001"
        assert rules[0].block == "bloco_teste"
        assert rules[1].fields == ["VL_ITEM", "VL_DESC"]
        assert rules[1].legislation == "Art 5"
        assert rules[1].vigencia_de == "2024-01-01"

    def test_skip_version_and_tolerance_keys(self, tmp_path):
        data = {"version": "2.0", "tolerance": 0.05}
        path = _write_yaml(tmp_path, data)
        rules = load_rules(path)
        assert rules == []

    def test_skip_non_list_blocks(self, tmp_path):
        data = {
            "version": "1.0",
            "metadata": {"author": "test"},  # dict, not list
            "bloco_a": [
                {"id": "A1", "implemented": True, "module": "x.py"},
            ],
        }
        path = _write_yaml(tmp_path, data)
        rules = load_rules(path)
        assert len(rules) == 1
        assert rules[0].id == "A1"

    def test_defaults_for_missing_keys(self, tmp_path):
        """Entries with minimal keys should get sensible defaults."""
        data = {
            "blk": [{"id": "MIN_001"}]
        }
        path = _write_yaml(tmp_path, data)
        rules = load_rules(path)
        assert len(rules) == 1
        r = rules[0]
        assert r.register == "*"
        assert r.fields == []
        assert r.error_type == ""
        assert r.severity == "error"
        assert r.description == ""
        assert r.condition == ""
        assert r.implemented is False
        assert r.module == ""

    def test_multiple_blocks(self, tmp_path):
        data = {
            "bloco_a": [{"id": "A1"}],
            "bloco_b": [{"id": "B1"}, {"id": "B2"}],
        }
        path = _write_yaml(tmp_path, data)
        rules = load_rules(path)
        assert len(rules) == 3
        blocks = {r.block for r in rules}
        assert blocks == {"bloco_a", "bloco_b"}


# ---------------------------------------------------------------------------
# check_rules
# ---------------------------------------------------------------------------

class TestCheckRules:
    def test_all_implemented(self):
        rules = [_make_rule(id="R1", implemented=True),
                 _make_rule(id="R2", implemented=True)]
        report = check_rules(rules)
        assert report["total"] == 2
        assert report["implemented"] == 2
        assert report["pending"] == 0
        assert report["missing_error_types"] == []
        assert report["pending_rules"] == []

    def test_pending_rules(self):
        rules = [
            _make_rule(id="R1", implemented=True),
            _make_rule(id="R2", implemented=False),
            _make_rule(id="R3", implemented=False),
        ]
        report = check_rules(rules)
        assert report["implemented"] == 1
        assert report["pending"] == 2
        assert len(report["pending_rules"]) == 2

    def test_missing_error_type(self):
        rules = [
            _make_rule(id="R1", implemented=True, error_type="TOTALLY_UNKNOWN_TYPE"),
        ]
        report = check_rules(rules)
        assert len(report["missing_error_types"]) == 1
        assert report["missing_error_types"][0].id == "R1"

    def test_known_error_type_not_flagged(self):
        rules = [
            _make_rule(id="R1", implemented=True, error_type="FORMATO_INVALIDO"),
        ]
        report = check_rules(rules)
        assert report["missing_error_types"] == []

    def test_empty_error_type_not_flagged(self):
        """Rules with empty error_type should not trigger missing_error_types."""
        rules = [_make_rule(id="R1", implemented=True, error_type="")]
        report = check_rules(rules)
        assert report["missing_error_types"] == []

    def test_pending_rule_unknown_type_not_flagged(self):
        """Only implemented rules are checked for missing error types."""
        rules = [_make_rule(id="R1", implemented=False, error_type="UNKNOWN_XYZ")]
        report = check_rules(rules)
        assert report["missing_error_types"] == []

    def test_by_block_and_severity(self):
        rules = [
            _make_rule(id="R1", block="A", severity="error", implemented=True),
            _make_rule(id="R2", block="A", severity="warning", implemented=False),
            _make_rule(id="R3", block="B", severity="error", implemented=True),
        ]
        report = check_rules(rules)
        assert report["by_block"]["A"]["total"] == 2
        assert report["by_block"]["A"]["implemented"] == 1
        assert report["by_block"]["A"]["pending"] == 1
        assert report["by_block"]["B"]["total"] == 1
        assert report["by_severity"]["error"] == 2
        assert report["by_severity"]["warning"] == 1

    def test_empty_rules(self):
        report = check_rules([])
        assert report["total"] == 0
        assert report["implemented"] == 0
        assert report["pending"] == 0


# ---------------------------------------------------------------------------
# _count_by_block / _count_by_severity helpers
# ---------------------------------------------------------------------------

class TestCountHelpers:
    def test_count_by_block_empty(self):
        assert _count_by_block([]) == {}

    def test_count_by_block(self):
        rules = [
            _make_rule(block="X", implemented=True),
            _make_rule(block="X", implemented=False),
            _make_rule(block="Y", implemented=True),
        ]
        result = _count_by_block(rules)
        assert result["X"] == {"total": 2, "implemented": 1, "pending": 1}
        assert result["Y"] == {"total": 1, "implemented": 1, "pending": 0}

    def test_count_by_severity_empty(self):
        assert _count_by_severity([]) == {}

    def test_count_by_severity(self):
        rules = [
            _make_rule(severity="error"),
            _make_rule(severity="error"),
            _make_rule(severity="warning"),
            _make_rule(severity="info"),
        ]
        result = _count_by_severity(rules)
        assert result == {"error": 2, "warning": 1, "info": 1}


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------

class TestPrintSummary:
    def test_print_summary_runs(self, capsys):
        rules = [
            _make_rule(id="R1", block="blk", severity="error", implemented=True),
            _make_rule(id="R2", block="blk", severity="warning", implemented=False),
        ]
        print_summary(rules)
        out = capsys.readouterr().out
        assert "Total: 2 regras" in out
        assert "Implementadas: 1" in out
        assert "Pendentes: 1" in out
        assert "blk" in out
        assert "error" in out
        assert "warning" in out

    def test_print_summary_with_missing_types(self, capsys):
        rules = [
            _make_rule(id="R1", implemented=True, error_type="DOES_NOT_EXIST_XYZ"),
        ]
        print_summary(rules)
        out = capsys.readouterr().out
        assert "ATENCAO" in out
        assert "R1" in out
        assert "DOES_NOT_EXIST_XYZ" in out

    def test_print_summary_no_missing_types(self, capsys):
        rules = [_make_rule(id="R1", implemented=True, error_type="FORMATO_INVALIDO")]
        print_summary(rules)
        out = capsys.readouterr().out
        assert "ATENCAO" not in out

    def test_print_summary_all_implemented(self, capsys):
        rules = [_make_rule(id="R1", block="b", implemented=True)]
        print_summary(rules)
        out = capsys.readouterr().out
        assert "OK" in out


# ---------------------------------------------------------------------------
# print_pending
# ---------------------------------------------------------------------------

class TestPrintPending:
    def test_no_pending(self, capsys):
        rules = [_make_rule(implemented=True)]
        print_pending(rules)
        out = capsys.readouterr().out
        assert "Nenhuma regra pendente" in out

    def test_with_pending(self, capsys):
        rules = [
            _make_rule(id="P1", implemented=False, block="blk",
                       register="C100", fields=["F1", "F2"],
                       error_type="FORMATO_INVALIDO", severity="error",
                       condition="x > 0", module="m.py",
                       legislation="Art 99"),
        ]
        print_pending(rules)
        out = capsys.readouterr().out
        assert "REGRAS PENDENTES" in out
        assert "P1" in out
        assert "blk" in out
        assert "C100" in out
        assert "F1, F2" in out
        assert "FORMATO_INVALIDO" in out
        assert "Art 99" in out

    def test_pending_without_legislation(self, capsys):
        rules = [_make_rule(id="P1", implemented=False, legislation=None)]
        print_pending(rules)
        out = capsys.readouterr().out
        assert "Legislacao" not in out


# ---------------------------------------------------------------------------
# print_block
# ---------------------------------------------------------------------------

class TestPrintBlock:
    def test_existing_block(self, capsys):
        rules = [
            _make_rule(id="R1", block="bloco_c", implemented=True,
                       register="C100", fields=["VL_MERC"],
                       error_type="TIPO", severity="error",
                       condition="cond", legislation="Lei X"),
            _make_rule(id="R2", block="bloco_c", implemented=False),
            _make_rule(id="R3", block="bloco_d"),
        ]
        print_block(rules, "bloco_c")
        out = capsys.readouterr().out
        assert "BLOCO: bloco_c" in out
        assert "2 regras" in out
        assert "[R1]" in out
        assert "[OK]" in out
        assert "[PENDENTE]" in out
        assert "Lei X" in out

    def test_nonexistent_block(self, capsys):
        rules = [
            _make_rule(block="bloco_a"),
            _make_rule(block="bloco_b"),
        ]
        print_block(rules, "bloco_z")
        out = capsys.readouterr().out
        assert "nao encontrado" in out
        assert "bloco_a" in out
        assert "bloco_b" in out

    def test_block_rule_without_legislation(self, capsys):
        rules = [_make_rule(id="R1", block="blk", legislation=None)]
        print_block(rules, "blk")
        out = capsys.readouterr().out
        assert "Legislacao" not in out


# ---------------------------------------------------------------------------
# _KNOWN_ERROR_TYPES sanity checks
# ---------------------------------------------------------------------------

class TestKnownErrorTypes:
    def test_is_non_empty_set(self):
        assert isinstance(_KNOWN_ERROR_TYPES, set)
        assert len(_KNOWN_ERROR_TYPES) > 50

    def test_sample_types_present(self):
        expected = {
            "FORMATO_INVALIDO", "INVALID_DATE", "MISSING_REQUIRED",
            "SOMA_DIVERGENTE", "CST_INVALIDO", "REF_INEXISTENTE",
            "ALIQ_INTERESTADUAL_INVALIDA", "C190_DIVERGE_C170",
            "DIFAL_FALTANTE_CONSUMO_FINAL",
        }
        assert expected.issubset(_KNOWN_ERROR_TYPES)


# ---------------------------------------------------------------------------
# RULES_PATH
# ---------------------------------------------------------------------------

class TestRulesPath:
    def test_points_to_yaml(self):
        assert RULES_PATH.name == "rules.yaml"
        assert RULES_PATH.exists()


# ---------------------------------------------------------------------------
# print_vigentes (mocked)
# ---------------------------------------------------------------------------

class TestPrintVigentes:
    def test_print_vigentes(self, capsys, monkeypatch):
        """Test print_vigentes with mocked RuleLoader."""
        rules = [
            _make_rule(id="V1", implemented=True, vigencia_de="2024-01-01",
                       vigencia_ate=None),
            _make_rule(id="V2", implemented=True, vigencia_de="2020-01-01",
                       vigencia_ate="2023-12-31"),
        ]

        class FakeLoader:
            def load_rules_for_period(self, start, end):
                # Only V1 is active
                return [{"id": "V1"}]

        # Patch the import inside the function
        monkeypatch.setattr(
            "src.services.rule_loader.RuleLoader", FakeLoader
        )
        print_vigentes(rules, "2024-06")
        out = capsys.readouterr().out
        assert "REGRAS VIGENTES PARA 2024-06" in out
        assert "Vigentes: 1" in out
        assert "Excluidas por vigencia: 1" in out
        assert "V2" in out  # listed as excluded

    def test_print_vigentes_december(self, capsys, monkeypatch):
        """Edge case: December period."""
        rules = [_make_rule(id="D1", vigencia_de="2024-01-01")]

        class FakeLoader:
            def load_rules_for_period(self, start, end):
                return [{"id": "D1"}]

        monkeypatch.setattr(
            "src.services.rule_loader.RuleLoader", FakeLoader
        )
        print_vigentes(rules, "2024-12")
        out = capsys.readouterr().out
        assert "2024-12" in out
        assert "Vigentes: 1" in out


# ---------------------------------------------------------------------------
# main (CLI dispatch)
# ---------------------------------------------------------------------------

class TestMain:
    def test_main_default_summary(self, capsys, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": True, "module": "x"}]}
        path = _write_yaml(tmp_path, data)
        monkeypatch.setattr("sys.argv", ["rules", "--rules-file", str(path)])
        from src.rules import main
        main()
        out = capsys.readouterr().out
        assert "Total: 1 regras" in out

    def test_main_pending(self, capsys, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": False, "module": "x"}]}
        path = _write_yaml(tmp_path, data)
        monkeypatch.setattr("sys.argv", ["rules", "--rules-file", str(path), "--pending"])
        from src.rules import main
        main()
        out = capsys.readouterr().out
        assert "REGRAS PENDENTES" in out

    def test_main_block(self, capsys, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": True, "module": "x"}]}
        path = _write_yaml(tmp_path, data)
        monkeypatch.setattr("sys.argv", ["rules", "--rules-file", str(path), "--block", "blk"])
        from src.rules import main
        main()
        out = capsys.readouterr().out
        assert "BLOCO: blk" in out

    def test_main_check_no_missing(self, capsys, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": True, "module": "x",
                         "error_type": "FORMATO_INVALIDO", "corrigivel": "proposta"}]}
        path = _write_yaml(tmp_path, data)
        monkeypatch.setattr("sys.argv", ["rules", "--rules-file", str(path), "--check"])
        from src.rules import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0

    def test_main_check_with_missing_exits_1(self, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": True, "module": "x",
                         "error_type": "BOGUS_UNKNOWN_TYPE"}]}
        path = _write_yaml(tmp_path, data)
        monkeypatch.setattr("sys.argv", ["rules", "--rules-file", str(path), "--check"])
        from src.rules import main
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 1

    def test_main_vigentes(self, capsys, monkeypatch, tmp_path):
        data = {"blk": [{"id": "M1", "implemented": True, "module": "x",
                         "vigencia_de": "2024-01-01"}]}
        path = _write_yaml(tmp_path, data)

        class FakeLoader:
            def load_rules_for_period(self, start, end):
                return [{"id": "M1"}]

        monkeypatch.setattr("src.services.rule_loader.RuleLoader", FakeLoader)
        monkeypatch.setattr("sys.argv", [
            "rules", "--rules-file", str(path), "--vigentes-para", "2024-06"
        ])
        from src.rules import main
        main()
        out = capsys.readouterr().out
        assert "REGRAS VIGENTES PARA 2024-06" in out
