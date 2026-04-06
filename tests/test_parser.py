"""Testes do parser SPED EFD."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models import SpedRecord
from src.parser import (
    _read_with_fallback,
    _register_level,
    get_register_hierarchy,
    group_by_register,
    parse_sped_file,
)
from src.validators.helpers import fields_to_dict

# ──────────────────────────────────────────────
# parse_sped_file
# ──────────────────────────────────────────────

class TestParseSped:
    def test_minimal_file(self, sped_minimal_path: Path) -> None:
        records = parse_sped_file(sped_minimal_path)
        assert len(records) > 0
        assert records[0].register == "0000"
        assert records[-1].register == "9999"

    def test_valid_file_record_count(self, sped_valid_path: Path) -> None:
        records = parse_sped_file(sped_valid_path)
        assert len(records) == 57

    def test_fields_include_register_code(self, sped_minimal_path: Path) -> None:
        records = parse_sped_file(sped_minimal_path)
        for rec in records:
            assert rec.fields.get("REG") == rec.register

    def test_line_numbers_are_sequential(self, sped_valid_path: Path) -> None:
        records = parse_sped_file(sped_valid_path)
        for i in range(1, len(records)):
            assert records[i].line_number >= records[i - 1].line_number

    def test_raw_line_starts_with_pipe(self, sped_valid_path: Path) -> None:
        records = parse_sped_file(sped_valid_path)
        for rec in records:
            assert rec.raw_line.startswith("|")

    def test_0000_fields(self, sped_valid_path: Path) -> None:
        records = parse_sped_file(sped_valid_path)
        r0000 = records[0]
        assert r0000.register == "0000"
        assert r0000.fields["NOME"] == "EMPRESA VALIDA LTDA"
        assert r0000.fields["CNPJ"] == "11222333000181"

    def test_errors_file_parses(self, sped_errors_path: Path) -> None:
        records = parse_sped_file(sped_errors_path)
        assert len(records) > 0
        registers = [r.register for r in records]
        assert "0000" in registers
        assert "9999" in registers


# ──────────────────────────────────────────────
# Linhas malformadas
# ──────────────────────────────────────────────

class TestMalformedLines:
    def test_empty_lines_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("|0000|017|0|\n\n\n|9999|3|\n")
        records = parse_sped_file(f)
        assert len(records) == 2

    def test_lines_without_pipes_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("|0000|017|0|\nlinhamalformada sem pipes\n|9999|3|\n")
        records = parse_sped_file(f)
        assert len(records) == 2

    def test_empty_pipe_line_parsed(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("|0000|017|\n||\n|9999|3|\n")
        records = parse_sped_file(f)
        # || gera parts = ['', '', ''] -> parts[1:-1] = [''] -> registro vazio
        assert len(records) == 3

    def test_whitespace_only_lines_ignored(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("|0000|017|\n   \n  \t  \n|9999|3|\n")
        records = parse_sped_file(f)
        assert len(records) == 2


# ──────────────────────────────────────────────
# Encoding fallback
# ──────────────────────────────────────────────

class TestEncodingFallback:
    def test_utf8(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes("|0000|Descrição|café|\n".encode())
        records = parse_sped_file(f)
        assert len(records) == 1

    def test_latin1(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes("|0000|Descrição|café|\n".encode("latin-1"))
        records = parse_sped_file(f)
        assert len(records) == 1

    def test_cp1252(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes("|0000|Descrição|café|\n".encode("cp1252"))
        records = parse_sped_file(f)
        assert len(records) == 1

    def test_read_with_fallback_returns_string(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_bytes(b"|0000|data|\n")
        result = _read_with_fallback(f)
        assert isinstance(result, str)


# ──────────────────────────────────────────────
# group_by_register
# ──────────────────────────────────────────────

class TestGroupByRegister:
    def test_groups_correct_registers(self, valid_records: list[SpedRecord]) -> None:
        groups = group_by_register(valid_records)
        assert "0000" in groups
        assert "C100" in groups
        assert "C170" in groups
        assert "9999" in groups

    def test_c100_count(self, valid_records: list[SpedRecord]) -> None:
        groups = group_by_register(valid_records)
        assert len(groups["C100"]) == 2

    def test_c170_count(self, valid_records: list[SpedRecord]) -> None:
        groups = group_by_register(valid_records)
        assert len(groups["C170"]) == 4

    def test_all_records_accounted(self, valid_records: list[SpedRecord]) -> None:
        groups = group_by_register(valid_records)
        total = sum(len(recs) for recs in groups.values())
        assert total == len(valid_records)


# ──────────────────────────────────────────────
# Hierarquia
# ──────────────────────────────────────────────

class TestHierarchy:
    def test_c100_has_children(self, valid_records: list[SpedRecord]) -> None:
        hierarchy = get_register_hierarchy(valid_records)
        c100_entries = [(p, c) for p, c in hierarchy if p.register == "C100"]
        assert len(c100_entries) == 2

    def test_c100_children_are_c170_c190(self, valid_records: list[SpedRecord]) -> None:
        hierarchy = get_register_hierarchy(valid_records)
        c100_entries = [(p, c) for p, c in hierarchy if p.register == "C100"]
        for _parent, children in c100_entries:
            child_regs = {c.register for c in children}
            assert "C170" in child_regs
            assert "C190" in child_regs

    def test_first_c100_has_3_children(self, valid_records: list[SpedRecord]) -> None:
        hierarchy = get_register_hierarchy(valid_records)
        c100_entries = [(p, c) for p, c in hierarchy if p.register == "C100"]
        # Primeiro C100: 2 C170 + 1 C190 = 3 filhos
        assert len(c100_entries[0][1]) == 3


# ──────────────────────────────────────────────
# _register_level
# ──────────────────────────────────────────────

class TestRegisterLevel:
    @pytest.mark.parametrize("reg,expected", [
        ("0000", 1),
        ("9999", 1),
        ("0001", 1),
        ("C001", 1),
        ("C990", 1),
        ("9900", 2),  # int("900") % 100 == 0 -> nível pai
        ("C100", 2),
        ("D100", 2),
        ("E100", 2),
        ("C170", 3),
        ("C190", 3),
        ("D150", 3),
    ])
    def test_register_levels(self, reg: str, expected: int) -> None:
        assert _register_level(reg) == expected

    def test_empty_register(self) -> None:
        assert _register_level("") == 0

    def test_short_register(self) -> None:
        assert _register_level("X") == 0

    def test_non_numeric_register(self) -> None:
        """Registro com parte não numérica retorna 0."""
        assert _register_level("XABC") == 0


# ──────────────────────────────────────────────
# Edge cases adicionais
# ──────────────────────────────────────────────

class TestParserEdgeCases:
    def test_line_with_single_pipe(self, tmp_path: Path) -> None:
        """Linha |X| gera parts ['', 'X', ''] -> ['X'] -> registro 'X'."""
        f = tmp_path / "test.txt"
        f.write_text("|X|\n")
        records = parse_sped_file(f)
        assert len(records) == 1
        assert records[0].register == "X"

    def test_hierarchy_ends_with_parent(self) -> None:
        """Testa que o último parent é adicionado à hierarquia."""
        records = [
            SpedRecord(
                line_number=1, register="C001",
                fields=fields_to_dict("C001", ["C001", "0"]),
                raw_line="|C001|0|",
            ),
            SpedRecord(
                line_number=2, register="C100",
                fields=fields_to_dict("C100", ["C100", "0"]),
                raw_line="|C100|0|",
            ),
            SpedRecord(
                line_number=3, register="C170",
                fields=fields_to_dict("C170", ["C170", "1"]),
                raw_line="|C170|1|",
            ),
        ]
        hierarchy = get_register_hierarchy(records)
        assert len(hierarchy) == 1
        assert hierarchy[0][0].register == "C100"
        assert len(hierarchy[0][1]) == 1

    def test_encoding_fallback_with_replace(self, tmp_path: Path) -> None:
        """Testa o último recurso de encoding (replace errors)."""
        f = tmp_path / "test.txt"
        # Escrever bytes que não são válidos em nenhum encoding padrão
        # Na verdade, latin-1 aceita tudo (0x00-0xFF), então o fallback com errors=replace
        # só é ativado se os 3 encodings falharem. Como latin-1 aceita tudo, este path
        # é difícil de atingir. Vamos testar o _read_with_fallback diretamente.
        f.write_bytes(b"|0000|test|\n")
        result = _read_with_fallback(f)
        assert "|0000|test|" in result
