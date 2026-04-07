"""Testes para o lint de índices hardcoded."""

import pytest
from pathlib import Path

# Adicionar scripts ao path para importação
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from check_hardcoded_indices import check_file


def test_detects_hardcoded_index(tmp_path):
    f = tmp_path / "bad_validator.py"
    f.write_text("def validate(fields):\n    return fields[5]\n")
    violations = check_file(f)
    assert len(violations) == 1
    assert "fields[5]" in violations[0][2]


def test_allows_index_zero(tmp_path):
    f = tmp_path / "validator.py"
    f.write_text("def validate(fields):\n    reg = fields[0]\n")
    violations = check_file(f)
    assert violations == []


def test_allows_index_one(tmp_path):
    f = tmp_path / "validator.py"
    f.write_text("def validate(fields):\n    x = fields[1]\n")
    violations = check_file(f)
    assert violations == []


def test_allows_variable_index(tmp_path):
    f = tmp_path / "validator.py"
    f.write_text("def validate(fields):\n    i = get_index()\n    return fields[i]\n")
    violations = check_file(f)
    assert violations == []


def test_ignores_non_fields_variable(tmp_path):
    f = tmp_path / "validator.py"
    f.write_text("def validate(row):\n    return row[5]\n")
    violations = check_file(f)
    assert violations == []


def test_detects_multiple_violations(tmp_path):
    f = tmp_path / "validator.py"
    f.write_text("def v(fields):\n    a = fields[3]\n    b = fields[7]\n")
    violations = check_file(f)
    assert len(violations) == 2


def test_ignores_ignored_files(tmp_path):
    f = tmp_path / "__init__.py"
    f.write_text("def v(fields):\n    a = fields[5]\n")
    violations = check_file(f)
    assert violations == []
