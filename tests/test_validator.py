"""Testes do validador de campos SPED EFD."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from src.indexer import init_db
from src.models import RegisterField, SpedRecord, ValidationError
from src.validator import (
    _is_numeric,
    _validate_record,
    generate_report,
    load_field_definitions,
    validate_records,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def make_record(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields, raw_line=raw)


# ──────────────────────────────────────────────
# _is_numeric
# ──────────────────────────────────────────────

class TestIsNumeric:
    def test_integer(self) -> None:
        assert _is_numeric("123") is True

    def test_decimal_dot(self) -> None:
        assert _is_numeric("123.45") is True

    def test_negative(self) -> None:
        assert _is_numeric("-10") is True

    def test_zero(self) -> None:
        assert _is_numeric("0") is True

    def test_text(self) -> None:
        assert _is_numeric("abc") is False

    def test_empty(self) -> None:
        assert _is_numeric("") is False

    def test_mixed(self) -> None:
        assert _is_numeric("12a3") is False


# ──────────────────────────────────────────────
# Validação de tipo (WRONG_TYPE)
# ──────────────────────────────────────────────

class TestFieldType:
    def test_numeric_field_with_text_raises_error(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="VL_DOC",
                              field_type="N", required="O")]
        record = make_record("C100", ["C100", "ABC"])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "WRONG_TYPE" for e in errors)

    def test_numeric_field_with_number_ok(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="VL_DOC",
                              field_type="N", required="O")]
        record = make_record("C100", ["C100", "1000"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_TYPE" for e in errors)

    def test_numeric_field_with_comma_decimal(self) -> None:
        """Valores com vírgula devem ser aceitos (padrão brasileiro)."""
        defs = [RegisterField(register="C100", field_no=2, field_name="VL_DOC",
                              field_type="N", required="O")]
        record = make_record("C100", ["C100", "1000,50"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_TYPE" for e in errors)

    def test_char_field_accepts_anything(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="DESCR",
                              field_type="C", required="O")]
        record = make_record("C100", ["C100", "Qualquer texto 123!@#"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_TYPE" for e in errors)


# ──────────────────────────────────────────────
# Validação de tamanho (WRONG_SIZE)
# ──────────────────────────────────────────────

class TestFieldSize:
    def test_value_exceeds_max_size(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="SER",
                              field_type="C", field_size=3, required="O")]
        record = make_record("C100", ["C100", "ABCDE"])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "WRONG_SIZE" for e in errors)

    def test_value_within_size(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="SER",
                              field_type="C", field_size=3, required="O")]
        record = make_record("C100", ["C100", "AB"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_SIZE" for e in errors)

    def test_value_exact_size(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="SER",
                              field_type="C", field_size=3, required="O")]
        record = make_record("C100", ["C100", "ABC"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_SIZE" for e in errors)

    def test_no_size_defined_skips_check(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="DESCR",
                              field_type="C", field_size=None, required="O")]
        record = make_record("C100", ["C100", "X" * 1000])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "WRONG_SIZE" for e in errors)


# ──────────────────────────────────────────────
# Validação de obrigatoriedade (MISSING_REQUIRED)
# ──────────────────────────────────────────────

class TestRequired:
    def test_required_field_empty_raises_error(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="IND_OPER",
                              field_type="C", required="O")]
        record = make_record("C100", ["C100", ""])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "MISSING_REQUIRED" for e in errors)

    def test_required_field_present_ok(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="IND_OPER",
                              field_type="C", required="O")]
        record = make_record("C100", ["C100", "0"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "MISSING_REQUIRED" for e in errors)

    def test_required_field_missing_from_record(self) -> None:
        defs = [
            RegisterField(register="C100", field_no=1, field_name="REG", field_type="C", required="O"),
            RegisterField(register="C100", field_no=2, field_name="IND_OPER", field_type="C", required="O"),
            RegisterField(register="C100", field_no=3, field_name="COD_PART", field_type="C", required="O"),
        ]
        # Registro com apenas 2 campos (faltando o terceiro)
        record = make_record("C100", ["C100", "0"])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "MISSING_REQUIRED" and e.field_name == "COD_PART" for e in errors)

    def test_optional_field_empty_ok(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="SER",
                              field_type="C", required="N")]
        record = make_record("C100", ["C100", ""])
        errors = _validate_record(record, defs)
        assert len(errors) == 0

    def test_conditional_field_empty_ok(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="DT_E_S",
                              field_type="N", required="OC")]
        record = make_record("C100", ["C100", ""])
        errors = _validate_record(record, defs)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# Validação de valores válidos (INVALID_VALUE)
# ──────────────────────────────────────────────

class TestValidValues:
    def test_invalid_value_raises_error(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="IND_OPER",
                              field_type="C", required="O", valid_values=["0", "1"])]
        record = make_record("C100", ["C100", "X"])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "INVALID_VALUE" for e in errors)

    def test_valid_value_ok(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="IND_OPER",
                              field_type="C", required="O", valid_values=["0", "1"])]
        record = make_record("C100", ["C100", "0"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "INVALID_VALUE" for e in errors)

    def test_cod_sit_valid(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="COD_SIT",
                              field_type="N", required="O",
                              valid_values=["00", "01", "02", "03", "04", "05", "06", "07", "08"])]
        record = make_record("C100", ["C100", "00"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "INVALID_VALUE" for e in errors)

    def test_cod_sit_invalid(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="COD_SIT",
                              field_type="N", required="O",
                              valid_values=["00", "01", "02", "03", "04", "05", "06", "07", "08"])]
        record = make_record("C100", ["C100", "09"])
        errors = _validate_record(record, defs)
        assert any(e.error_type == "INVALID_VALUE" for e in errors)

    def test_no_valid_values_skips_check(self) -> None:
        defs = [RegisterField(register="C100", field_no=2, field_name="NOME",
                              field_type="C", required="O", valid_values=None)]
        record = make_record("C100", ["C100", "qualquer coisa"])
        errors = _validate_record(record, defs)
        assert not any(e.error_type == "INVALID_VALUE" for e in errors)


# ──────────────────────────────────────────────
# validate_records (múltiplos registros)
# ──────────────────────────────────────────────

class TestValidateRecords:
    def test_records_without_defs_skipped(self) -> None:
        records = [make_record("XXXX", ["XXXX", "1", "2"])]
        errors = validate_records(records, {})
        assert len(errors) == 0

    def test_multiple_records(self, sample_field_defs: dict) -> None:
        records = [
            make_record("C100", ["C100", "0", "0", "FORN01", "55", "00", "001", "123",
                                 "10012024", "15012024", "1000"], line=10),
            make_record("C100", ["C100", "X", "0", "FORN01", "55", "00", "001", "456",
                                 "20012024", "20012024", "ABC"], line=20),
        ]
        errors = validate_records(records, sample_field_defs)
        # Segundo C100: IND_OPER="X" (INVALID_VALUE) + VL_DOC="ABC" (WRONG_TYPE)
        assert len(errors) >= 2

    def test_valid_records_no_errors(self, sample_field_defs: dict) -> None:
        records = [
            make_record("0000", ["0000", "017", "0", "01012024", "31012024",
                                 "EMPRESA TESTE", "11222333000181"], line=1),
        ]
        errors = validate_records(records, sample_field_defs)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# generate_report
# ──────────────────────────────────────────────

class TestGenerateReport:
    def test_no_errors_report(self) -> None:
        report = generate_report([])
        assert "Nenhum erro encontrado" in report

    def test_report_contains_error_details(self) -> None:
        errors = [
            ValidationError(
                line_number=10, register="C100", field_no=2,
                field_name="IND_OPER", value="X",
                error_type="INVALID_VALUE",
                message="Valor inválido",
            ),
        ]
        report = generate_report(errors)
        assert "INVALID_VALUE" in report
        assert "Linha 10" in report
        assert "IND_OPER" in report
        assert "Total de erros" in report

    def test_report_with_docs(self) -> None:
        errors = [
            ValidationError(
                line_number=5, register="C100", field_no=2,
                field_name="IND_OPER", value="X",
                error_type="INVALID_VALUE",
                message="Valor inválido",
            ),
        ]
        docs = {0: ["Documentação: IND_OPER aceita 0 ou 1"]}
        report = generate_report(errors, docs)
        assert "Documentação relevante" in report
        assert "IND_OPER aceita 0 ou 1" in report

    def test_report_groups_by_type(self) -> None:
        errors = [
            ValidationError(line_number=1, register="C100", field_no=2,
                            field_name="F1", value="X", error_type="INVALID_VALUE", message="m1"),
            ValidationError(line_number=2, register="C100", field_no=3,
                            field_name="F2", value="", error_type="MISSING_REQUIRED", message="m2"),
            ValidationError(line_number=3, register="C100", field_no=4,
                            field_name="F3", value="Y", error_type="INVALID_VALUE", message="m3"),
        ]
        report = generate_report(errors)
        assert "INVALID_VALUE (2 ocorrências)" in report
        assert "MISSING_REQUIRED (1 ocorrências)" in report


# ──────────────────────────────────────────────
# load_field_definitions
# ──────────────────────────────────────────────

class TestLoadFieldDefinitions:
    def test_loads_from_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))
        conn.execute(
            """INSERT INTO register_fields
               (register, field_no, field_name, field_type, field_size, decimals, required, valid_values, description)
               VALUES ('C100', 1, 'REG', 'C', 4, NULL, 'O', NULL, 'Registro')""",
        )
        conn.execute(
            """INSERT INTO register_fields
               (register, field_no, field_name, field_type, field_size, decimals, required, valid_values, description)
               VALUES ('C100', 2, 'IND_OPER', 'C', 1, NULL, 'O', ?, 'Indicador')""",
            (json.dumps(["0", "1"]),),
        )
        conn.execute(
            """INSERT INTO register_fields
               (register, field_no, field_name, field_type, field_size, decimals, required, valid_values, description)
               VALUES ('E110', 1, 'REG', 'C', 4, NULL, 'O', NULL, 'Registro')""",
        )
        conn.commit()
        conn.close()

        defs = load_field_definitions(db_path)
        assert "C100" in defs
        assert "E110" in defs
        assert len(defs["C100"]) == 2
        assert defs["C100"][0].field_name == "REG"
        assert defs["C100"][1].valid_values == ["0", "1"]

    def test_empty_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "empty.db"
        conn = init_db(str(db_path))
        conn.close()
        defs = load_field_definitions(db_path)
        assert defs == {}

    def test_ordered_by_field_no(self, tmp_path: Path) -> None:
        db_path = tmp_path / "test.db"
        conn = init_db(str(db_path))
        # Inserir fora de ordem
        conn.execute(
            """INSERT INTO register_fields (register, field_no, field_name) VALUES ('C100', 3, 'THIRD')""",
        )
        conn.execute(
            """INSERT INTO register_fields (register, field_no, field_name) VALUES ('C100', 1, 'FIRST')""",
        )
        conn.execute(
            """INSERT INTO register_fields (register, field_no, field_name) VALUES ('C100', 2, 'SECOND')""",
        )
        conn.commit()
        conn.close()

        defs = load_field_definitions(db_path)
        names = [f.field_name for f in defs["C100"]]
        assert names == ["FIRST", "SECOND", "THIRD"]


# ──────────────────────────────────────────────
# Validação com registros sem definição
# ──────────────────────────────────────────────

class TestValidateNoDefinition:
    def test_skips_unknown_registers(self) -> None:
        records = [
            make_record("ZZZZ", ["ZZZZ", "val1", "val2"], line=1),
            make_record("XXXX", ["XXXX", "val1"], line=2),
        ]
        defs: dict[str, list[RegisterField]] = {}
        errors = validate_records(records, defs)
        assert len(errors) == 0
