"""Testes para ErrorDeduplicator."""

import pytest
from src.models import ValidationError
from src.validators.error_deduplicator import ErrorDeduplicator


def _err(line: int, field: str, error_type: str, impacto: str = "relevante") -> ValidationError:
    return ValidationError(
        line_number=line,
        register="C170",
        field_no=0,
        field_name=field,
        value="",
        error_type=error_type,
        message=f"Erro {error_type}",
        impacto=impacto,
    )


def test_empty_list():
    assert ErrorDeduplicator.deduplicate([]) == []


def test_single_error_returned():
    errors = [_err(10, "CST_ICMS", "TRIBUTACAO_INCONSISTENTE")]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 1
    assert result[0].error_type == "TRIBUTACAO_INCONSISTENTE"


def test_different_lines_not_deduplicated():
    errors = [
        _err(10, "CST_ICMS", "TRIBUTACAO_INCONSISTENTE"),
        _err(20, "CST_ICMS", "ISENCAO_INCONSISTENTE"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 2


def test_same_line_same_group_deduplicated():
    errors = [
        _err(10, "CST_ICMS", "TRIBUTACAO_INCONSISTENTE", "relevante"),
        _err(10, "CST_ICMS", "ISENCAO_INCONSISTENTE", "critico"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 1
    assert result[0].error_type == "ISENCAO_INCONSISTENTE"  # critico ganha
    assert "TRIBUTACAO_INCONSISTENTE" in result[0].message


def test_same_line_different_groups_not_deduplicated():
    errors = [
        _err(10, "CST_ICMS", "TRIBUTACAO_INCONSISTENTE"),
        _err(10, "CST_ICMS", "CONTAGEM_DIVERGENTE"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 2


def test_winner_has_duplicate_reference():
    errors = [
        _err(10, "CFOP", "CST_CFOP_INCOMPATIVEL", "critico"),
        _err(10, "CFOP", "CFOP_MISMATCH", "relevante"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 1
    assert "também detectado como" in result[0].message
    assert "CFOP_MISMATCH" in result[0].message


def test_three_errors_same_cluster():
    errors = [
        _err(10, "VL_ICMS", "SOMA_DIVERGENTE", "informativo"),
        _err(10, "VL_ICMS", "CALCULO_DIVERGENTE", "critico"),
        _err(10, "VL_ICMS", "CRUZAMENTO_DIVERGENTE", "relevante"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    assert len(result) == 1
    assert result[0].error_type == "CALCULO_DIVERGENTE"  # critico ganha
    assert result[0].impacto == "critico"


def test_output_sorted_by_line():
    errors = [
        _err(30, "A", "CONTAGEM_DIVERGENTE"),
        _err(10, "B", "TRIBUTACAO_INCONSISTENTE"),
        _err(20, "C", "CFOP_MISMATCH"),
    ]
    result = ErrorDeduplicator.deduplicate(errors)
    lines = [e.line_number for e in result]
    assert lines == sorted(lines)
