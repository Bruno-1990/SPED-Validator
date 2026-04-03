"""Testes dos dataclasses de modelos."""

from __future__ import annotations

import json

from src.models import Chunk, RegisterField, SearchResult, SpedRecord, ValidationError


class TestSpedRecord:
    def test_creation(self) -> None:
        rec = SpedRecord(line_number=1, register="C100", fields=["C100", "0"], raw_line="|C100|0|")
        assert rec.register == "C100"
        assert rec.line_number == 1
        assert rec.fields == ["C100", "0"]

    def test_raw_line_preserved(self) -> None:
        raw = "|0000|017|0|01012024|"
        rec = SpedRecord(line_number=1, register="0000", fields=["0000", "017", "0", "01012024"], raw_line=raw)
        assert rec.raw_line == raw


class TestRegisterField:
    def test_valid_values_json_serialization(self) -> None:
        rf = RegisterField(register="C100", field_no=2, field_name="IND_OPER",
                           valid_values=["0", "1"])
        serialized = rf.valid_values_json()
        assert serialized is not None
        assert json.loads(serialized) == ["0", "1"]

    def test_valid_values_json_none(self) -> None:
        rf = RegisterField(register="C100", field_no=2, field_name="NOME",
                           valid_values=None)
        assert rf.valid_values_json() is None

    def test_valid_values_from_json(self) -> None:
        result = RegisterField.valid_values_from_json('["0", "1"]')
        assert result == ["0", "1"]

    def test_valid_values_from_json_none(self) -> None:
        assert RegisterField.valid_values_from_json(None) is None

    def test_default_values(self) -> None:
        rf = RegisterField(register="C100", field_no=1, field_name="REG")
        assert rf.field_type is None
        assert rf.field_size is None
        assert rf.decimals is None
        assert rf.required is None
        assert rf.valid_values is None
        assert rf.description is None


class TestValidationError:
    def test_creation(self) -> None:
        err = ValidationError(
            line_number=10, register="C100", field_no=2,
            field_name="IND_OPER", value="X",
            error_type="INVALID_VALUE", message="Valor inválido",
        )
        assert err.error_type == "INVALID_VALUE"
        assert err.line_number == 10


class TestChunk:
    def test_defaults(self) -> None:
        chunk = Chunk()
        assert chunk.id is None
        assert chunk.source_file == ""
        assert chunk.category == "guia"
        assert chunk.register is None
        assert chunk.embedding is None

    def test_with_values(self) -> None:
        chunk = Chunk(id=1, source_file="test.md", register="C100",
                      heading="Reg C100", content="Conteúdo")
        assert chunk.id == 1
        assert chunk.register == "C100"


class TestSearchResult:
    def test_creation(self) -> None:
        chunk = Chunk(id=1, source_file="t.md", content="test")
        result = SearchResult(chunk=chunk, score=0.95, source="fts")
        assert result.score == 0.95
        assert result.source == "fts"

    def test_default_source(self) -> None:
        chunk = Chunk(id=1, source_file="t.md", content="test")
        result = SearchResult(chunk=chunk, score=0.5)
        assert result.source == ""
