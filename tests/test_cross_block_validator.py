"""Testes do validador de cruzamento entre blocos."""

from __future__ import annotations

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.cross_block_validator import (
    validate_block9,
    validate_c_vs_e,
    validate_cadastro_refs,
    validate_cross_blocks,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


# ──────────────────────────────────────────────
# Cadastros referenciados (0 vs C/D)
# ──────────────────────────────────────────────

class TestValidateCadastroRefs:
    def test_valid_refs(self) -> None:
        records = [
            rec("0150", ["0150", "FORN001", "Fornecedor"], line=1),
            rec("0200", ["0200", "PROD001", "Produto"], line=2),
            rec("C100", ["C100", "0", "0", "FORN001"], line=3),
            rec("C170", ["C170", "1", "PROD001", "Desc"], line=4),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert len(errors) == 0

    def test_missing_cod_part(self) -> None:
        records = [
            rec("0150", ["0150", "FORN001", "Fornecedor"], line=1),
            rec("C100", ["C100", "0", "0", "FORN_INEXISTENTE"], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert any(e.error_type == "REF_INEXISTENTE" and "COD_PART" in e.field_name for e in errors)

    def test_missing_cod_item(self) -> None:
        records = [
            rec("0200", ["0200", "PROD001", "Produto"], line=1),
            rec("C170", ["C170", "1", "PROD_INEXISTENTE", "Desc"], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert any(e.error_type == "REF_INEXISTENTE" and "COD_ITEM" in e.field_name for e in errors)

    def test_d100_cod_part_not_checked_here(self) -> None:
        """D100 COD_PART desativado aqui — duplica D_001 em bloco_d_validator."""
        records = [
            rec("0150", ["0150", "FORN001", "Forn"], line=1),
            rec("D100", ["D100", "0", "0", "TRANS_INEXISTENTE"], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert not any(e.register == "D100" for e in errors)

    def test_no_cadastros_no_errors(self) -> None:
        """Sem registros 0150/0200, não é possível validar referências."""
        records = [
            rec("C100", ["C100", "0", "0", "FORN001"], line=1),
            rec("C170", ["C170", "1", "PROD001", "Desc"], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert len(errors) == 0

    def test_empty_cod_part_skipped(self) -> None:
        records = [
            rec("0150", ["0150", "FORN001", "Forn"], line=1),
            rec("C100", ["C100", "0", "0", ""], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_cadastro_refs(groups)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# Bloco C vs E
# ──────────────────────────────────────────────

class TestValidateCvsE:
    """Validacao E110 delegada ao tax_recalc.recalc_e110_totals()."""

    def test_delegated_returns_empty(self) -> None:
        """validate_c_vs_e agora delega ao tax_recalc e retorna vazio."""
        records = [
            rec("C190", ["C190", "000", "5102", "18,00", "1000,00", "1000,00", "180,00"], line=1),
            rec("E110", ["E110", "999,00", "0", "0", "0", "0"], line=2),
        ]
        groups = group_by_register(records)
        errors = validate_c_vs_e(groups)
        assert len(errors) == 0  # Delegado ao tax_recalc


# ──────────────────────────────────────────────
# Bloco 9 - Contagem de registros
# ──────────────────────────────────────────────

class TestValidateBlock9:
    def test_valid_counts(self) -> None:
        records = [
            rec("0000", ["0000", "017"], line=1),
            rec("C100", ["C100", "0"], line=2),
            rec("C100", ["C100", "1"], line=3),
            rec("9900", ["9900", "0000", "1"], line=4),
            rec("9900", ["9900", "C100", "2"], line=5),
            rec("9900", ["9900", "9900", "3"], line=6),
            rec("9900", ["9900", "9999", "1"], line=7),
            rec("9999", ["9999", "7"], line=8),  # Errado: total real=8, mas conta 7
        ]
        groups = group_by_register(records)
        errors = validate_block9(records, groups)
        # 9999 declara 7 mas tem 8 registros
        assert any(e.register == "9999" for e in errors)

    def test_wrong_register_count(self) -> None:
        records = [
            rec("C100", ["C100", "0"], line=1),
            rec("9900", ["9900", "C100", "5"], line=2),  # Declara 5, tem 1
            rec("9999", ["9999", "3"], line=3),
        ]
        groups = group_by_register(records)
        errors = validate_block9(records, groups)
        assert any(e.field_name == "QTD_REG" and "C100" in e.message for e in errors)

    def test_correct_total_lines(self) -> None:
        records = [
            rec("0000", ["0000"], line=1),
            rec("9900", ["9900", "0000", "1"], line=2),
            rec("9900", ["9900", "9900", "2"], line=3),
            rec("9900", ["9900", "9999", "1"], line=4),
            rec("9999", ["9999", "5"], line=5),
        ]
        groups = group_by_register(records)
        errors = validate_block9(records, groups)
        assert not any(e.register == "9999" for e in errors)

    def test_empty_records(self) -> None:
        errors = validate_block9([], {})
        assert errors == []


# ──────────────────────────────────────────────
# validate_cross_blocks (integração)
# ──────────────────────────────────────────────

class TestValidateCrossBlocks:
    def test_valid_file(self, valid_records: list[SpedRecord]) -> None:
        errors = validate_cross_blocks(valid_records)
        assert isinstance(errors, list)

    def test_error_file(self, error_records: list[SpedRecord]) -> None:
        errors = validate_cross_blocks(error_records)
        assert isinstance(errors, list)
        # Deve encontrar erros (referências, contagens, etc.)
        assert len(errors) > 0

    def test_empty(self) -> None:
        errors = validate_cross_blocks([])
        assert errors == []
