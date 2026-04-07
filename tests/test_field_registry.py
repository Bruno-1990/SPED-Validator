"""Testes para FieldRegistry e helpers_registry."""

import pytest
from unittest.mock import patch, MagicMock
from src.validators.field_registry import FieldRegistry, FieldNotFoundError, get_registry


@pytest.fixture(autouse=True)
def reset_registry():
    FieldRegistry.reset()
    yield
    FieldRegistry.reset()


def make_registry_with_data(rows):
    """Cria FieldRegistry com dados de teste sem acessar o banco."""
    reg = FieldRegistry.__new__(FieldRegistry)
    reg._registry = {}
    for register, field_name, field_no in rows:
        reg._registry[(register.upper(), field_name.upper())] = field_no
    return reg


def test_get_index_returns_correct_position():
    reg = make_registry_with_data([("C170", "CST_ICMS", 9), ("C170", "ALIQ_ICMS", 10)])
    assert reg.get_index("C170", "CST_ICMS") == 9
    assert reg.get_index("C170", "ALIQ_ICMS") == 10


def test_get_index_case_insensitive():
    reg = make_registry_with_data([("c170", "cst_icms", 9)])
    assert reg.get_index("C170", "CST_ICMS") == 9
    assert reg.get_index("c170", "cst_icms") == 9


def test_get_index_raises_field_not_found():
    reg = make_registry_with_data([("C170", "CST_ICMS", 9)])
    with pytest.raises(FieldNotFoundError):
        reg.get_index("C170", "CAMPO_INEXISTENTE")


def test_get_field_safe_within_range():
    reg = make_registry_with_data([("C170", "CST_ICMS", 2)])
    fields = ["C170", "item1", "400"]
    assert reg.get_field_safe(fields, "C170", "CST_ICMS") == "400"


def test_get_field_safe_out_of_range_returns_default():
    reg = make_registry_with_data([("C170", "CAMPO", 99)])
    fields = ["C170", "only_two_fields"]
    assert reg.get_field_safe(fields, "C170", "CAMPO", "FALLBACK") == "FALLBACK"


def test_get_field_safe_not_found_returns_default():
    reg = make_registry_with_data([])
    assert reg.get_field_safe(["C170", "x"], "C170", "NAO_EXISTE", "DEFAULT") == "DEFAULT"


def test_has_field_true_and_false():
    reg = make_registry_with_data([("E110", "VL_TOT_DEBITOS", 3)])
    assert reg.has_field("E110", "VL_TOT_DEBITOS") is True
    assert reg.has_field("E110", "CAMPO_FALSO") is False


def test_list_fields_returns_only_register_fields():
    reg = make_registry_with_data([
        ("C170", "CST_ICMS", 9),
        ("C170", "ALIQ_ICMS", 10),
        ("C100", "VL_DOC", 11),
    ])
    c170_fields = reg.list_fields("C170")
    names = [name for name, _ in c170_fields]
    assert "CST_ICMS" in names
    assert "ALIQ_ICMS" in names
    assert "VL_DOC" not in names


def test_singleton_pattern():
    FieldRegistry.reset()
    with patch.object(FieldRegistry, "_load", return_value=None):
        r1 = FieldRegistry.get_instance()
        r2 = FieldRegistry.get_instance()
        assert r1 is r2
