"""Testes do validador de Bloco C Servicos (MOD-17)."""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.bloco_c_servicos_validator import validate_bloco_c_servicos
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(
        line_number=line,
        register=register,
        fields=fields_to_dict(register, fields),
        raw_line=raw,
    )


# ──────────────────────────────────────────────
# C500/C590 validos — sem erros
# ──────────────────────────────────────────────

class TestC500C590Valid:
    def test_valid_c500_c590(self) -> None:
        """C500/C510/C590 com valores consistentes nao gera erros."""
        records = [
            rec("0000", [
                "0000", "017", "0", "01042026", "30042026", "EMPRESA",
                "12345678000199", "", "SP", "123456789", "3550308",
                "", "", "A", "0",
            ], line=1),
            rec("0150", [
                "0150", "ENER001", "Cia Eletrica",
            ], line=2),
            rec("C500", [
                "C500", "0", "1", "ENER001", "06", "00",
                "", "", "1001", "15042026", "15042026", "1000,00", "180,00",
                "", "0,00", "0,00", "",
            ], line=3),
            rec("C510", [
                "C510", "1", "ITEM001", "01", "100", "KWH",
                "1000,00", "0,00", "000", "1252", "1000,00",
                "18,00", "180,00", "0,00", "0,00", "0,00",
                "0", "ENER001", "0,00", "0,00", "",
            ], line=4),
            rec("C590", [
                "C590", "000", "1252", "18,00", "1000,00", "1000,00",
                "180,00", "0,00", "0,00", "0,00", "",
            ], line=5),
        ]
        errors = validate_bloco_c_servicos(records)
        # Nenhum erro de divergencia C590 vs C510
        cs_errors = [e for e in errors if e.error_type in (
            "CS_C590_DIVERGE_C510", "CS_C490_SOMA_DIVERGENTE",
            "REF_INEXISTENTE",
        )]
        assert len(cs_errors) == 0


# ──────────────────────────────────────────────
# C590 com soma errada → erro detectado
# ──────────────────────────────────────────────

class TestC590SomaDivergente:
    def test_c590_diverge_c510(self) -> None:
        """C590 com VL_ICMS diferente da soma dos C510 deve gerar erro."""
        records = [
            rec("0000", [
                "0000", "017", "0", "01042026", "30042026", "EMPRESA",
                "12345678000199", "", "SP", "123456789", "3550308",
                "", "", "A", "0",
            ], line=1),
            rec("0150", ["0150", "ENER001", "Cia Eletrica"], line=2),
            rec("C500", [
                "C500", "0", "1", "ENER001", "06", "00",
                "", "", "1001", "15042026", "15042026", "1000,00", "180,00",
                "", "0,00", "0,00", "",
            ], line=3),
            rec("C510", [
                "C510", "1", "ITEM001", "01", "100", "KWH",
                "1000,00", "0,00", "000", "1252", "1000,00",
                "18,00", "180,00", "0,00", "0,00", "0,00",
                "0", "ENER001", "0,00", "0,00", "",
            ], line=4),
            # C590 declara VL_ICMS=200,00 mas C510 soma 180,00
            rec("C590", [
                "C590", "000", "1252", "18,00", "1000,00", "1000,00",
                "200,00", "0,00", "0,00", "0,00", "",
            ], line=5),
        ]
        errors = validate_bloco_c_servicos(records)
        diverge_errors = [e for e in errors if e.error_type == "CS_C590_DIVERGE_C510"]
        assert len(diverge_errors) == 1
        assert "200.00" in diverge_errors[0].message
        assert "180.00" in diverge_errors[0].message


# ──────────────────────────────────────────────
# C490 consistencia interna
# ──────────────────────────────────────────────

class TestC490Consistencia:
    def test_c490_valid(self) -> None:
        """C490 com BC*ALIQ = VL_ICMS nao gera erro."""
        records = [
            rec("C490", [
                "C490", "000", "5102", "18,00", "500,00", "500,00", "90,00",
            ], line=1),
        ]
        errors = validate_bloco_c_servicos(records)
        c490_errors = [e for e in errors if e.error_type == "CS_C490_SOMA_DIVERGENTE"]
        assert len(c490_errors) == 0

    def test_c490_divergente(self) -> None:
        """C490 com BC*ALIQ divergindo de VL_ICMS gera erro."""
        records = [
            # 500 * 18% = 90, mas declara 100
            rec("C490", [
                "C490", "000", "5102", "18,00", "500,00", "500,00", "100,00",
            ], line=1),
        ]
        errors = validate_bloco_c_servicos(records)
        c490_errors = [e for e in errors if e.error_type == "CS_C490_SOMA_DIVERGENTE"]
        assert len(c490_errors) == 1


# ──────────────────────────────────────────────
# C500 referencia inexistente
# ──────────────────────────────────────────────

class TestC500RefInexistente:
    def test_c500_cod_part_inexistente(self) -> None:
        """C500 com COD_PART que nao existe no 0150 gera erro."""
        records = [
            rec("0150", ["0150", "ENER001", "Cia Eletrica"], line=1),
            rec("C500", [
                "C500", "0", "1", "INEXISTENTE", "06", "00",
                "", "", "1001", "15042026", "15042026", "1000,00", "180,00",
                "", "0,00", "0,00", "",
            ], line=2),
        ]
        errors = validate_bloco_c_servicos(records)
        ref_errors = [e for e in errors if e.error_type == "REF_INEXISTENTE"]
        assert len(ref_errors) == 1
        assert "INEXISTENTE" in ref_errors[0].message


# ──────────────────────────────────────────────
# C405 data fora do periodo
# ──────────────────────────────────────────────

class TestC405DateOutOfPeriod:
    def test_c405_date_in_period(self) -> None:
        """C405 com DT_DOC dentro do periodo nao gera erro."""
        records = [
            rec("0000", [
                "0000", "017", "0", "01042026", "30042026", "EMPRESA",
                "12345678000199", "", "SP", "123456789", "3550308",
                "", "", "A", "0",
            ], line=1),
            rec("C405", [
                "C405", "15042026", "1", "1", "100", "5000,00", "3000,00",
            ], line=2),
        ]
        errors = validate_bloco_c_servicos(records)
        date_errors = [e for e in errors if e.error_type == "DATE_OUT_OF_PERIOD"]
        assert len(date_errors) == 0

    def test_c405_date_out_of_period(self) -> None:
        """C405 com DT_DOC fora do periodo gera erro."""
        records = [
            rec("0000", [
                "0000", "017", "0", "01042026", "30042026", "EMPRESA",
                "12345678000199", "", "SP", "123456789", "3550308",
                "", "", "A", "0",
            ], line=1),
            rec("C405", [
                "C405", "15032026", "1", "1", "100", "5000,00", "3000,00",
            ], line=2),
        ]
        errors = validate_bloco_c_servicos(records)
        date_errors = [e for e in errors if e.error_type == "DATE_OUT_OF_PERIOD"]
        assert len(date_errors) == 1


# ──────────────────────────────────────────────
# Empty records
# ──────────────────────────────────────────────

class TestEmpty:
    def test_empty_records(self) -> None:
        errors = validate_bloco_c_servicos([])
        assert errors == []
