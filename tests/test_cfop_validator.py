"""Testes do validador CFOP (CFOP_001, CFOP_002, CFOP_003)."""

from __future__ import annotations

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.validators.cfop_validator import validate_cfop
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def c100(cod_part: str = "PART01", line: int = 1) -> SpedRecord:
    fields = [
        "C100", "1", "0", cod_part, "55", "00",
        "", "", "", "", "", "1000,00",
        "", "", "", "", "",
        "", "", "", "", "",
        "", "", "", "", "",
        "", "",
    ]
    return rec("C100", fields, line=line)


def c170(cfop: str = "5101", line: int = 2) -> SpedRecord:
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN",
        "1000,00", "0", "0", "000", cfop, "001",
        "1000,00", "18,00", "180,00",
        "", "", "",
        "", "", "",
        "", "", "",
        "", "", "", "", "", "",
        "", "", "", "", "", "",
        "", "",
    ]
    return rec("C170", fields, line=line)


def e300(uf: str = "RJ", line: int = 100) -> SpedRecord:
    return rec("E300", ["E300", uf, "01012024", "31012024"], line=line)


def make_ctx(participantes: dict | None = None, uf: str = "SP") -> ValidationContext:
    return ValidationContext(
        file_id=1,
        regime=TaxRegime.NORMAL,
        uf_contribuinte=uf,
        participantes=participantes or {},
    )


# ──────────────────────────────────────────────
# CFOP_001 — CFOP interestadual com destino mesma UF
# ──────────────────────────────────────────────

class TestCFOP001:
    def test_cfop_6xxx_mesma_uf(self) -> None:
        """CFOP 6101 + destino SP (mesma UF) = erro."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "110", "uf": "SP", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="6101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert any(e.error_type == "CFOP_INTERESTADUAL_MESMA_UF" for e in errors)
        err = [e for e in errors if e.error_type == "CFOP_INTERESTADUAL_MESMA_UF"][0]
        assert err.expected_value == "5101"

    def test_cfop_6xxx_outra_uf_ok(self) -> None:
        """CFOP 6101 + destino RJ (outra UF) = OK."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="6101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_INTERESTADUAL_MESMA_UF" for e in errors)


# ──────────────────────────────────────────────
# CFOP_002 — CFOP interno com destino outra UF
# ──────────────────────────────────────────────

class TestCFOP002:
    def test_cfop_5xxx_outra_uf(self) -> None:
        """CFOP 5101 + destino RJ (outra UF) = erro."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="5101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert any(e.error_type == "CFOP_INTERNO_OUTRA_UF" for e in errors)
        err = [e for e in errors if e.error_type == "CFOP_INTERNO_OUTRA_UF"][0]
        assert err.expected_value == "6101"

    def test_cfop_5xxx_mesma_uf_ok(self) -> None:
        """CFOP 5101 + destino SP (mesma UF) = OK."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "110", "uf": "SP", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="5101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_INTERNO_OUTRA_UF" for e in errors)


# ──────────────────────────────────────────────
# CFOP_003 — CFOP incompativel com DIFAL
# ──────────────────────────────────────────────

class TestCFOP003:
    def test_remessa_com_e300(self) -> None:
        """CFOP 6901 (remessa) + E300 presente = aviso."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [
            c100("PART01", line=1),
            c170(cfop="6901", line=2),
            e300(line=100),
        ]
        errors = validate_cfop(records, context=ctx)
        assert any(e.error_type == "CFOP_DIFAL_INCOMPATIVEL" for e in errors)

    def test_remessa_sem_e300_ok(self) -> None:
        """CFOP 6901 sem E300 = OK."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [
            c100("PART01", line=1),
            c170(cfop="6901", line=2),
        ]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_DIFAL_INCOMPATIVEL" for e in errors)

    def test_venda_com_e300_ok(self) -> None:
        """CFOP 6101 (venda) com E300 = OK (venda pode gerar DIFAL)."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [
            c100("PART01", line=1),
            c170(cfop="6101", line=2),
            e300(line=100),
        ]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_DIFAL_INCOMPATIVEL" for e in errors)


# ──────────────────────────────────────────────
# Edge cases
# ──────────────────────────────────────────────

class TestCFOPEdgeCases:
    def test_sem_contexto(self) -> None:
        records = [c170(cfop="6101", line=1)]
        assert validate_cfop(records, context=None) == []

    def test_sem_uf_contribuinte(self) -> None:
        ctx = ValidationContext(file_id=1, regime=TaxRegime.NORMAL, uf_contribuinte="")
        records = [c170(cfop="6101", line=1)]
        assert validate_cfop(records, context=ctx) == []

    def test_sem_uf_destino_nao_valida(self) -> None:
        """Participante sem UF -> nao gera erro."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "", "uf": "", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="6101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_INTERESTADUAL_MESMA_UF" for e in errors)
        assert not any(e.error_type == "CFOP_INTERNO_OUTRA_UF" for e in errors)

    def test_cfop_7xxx_nao_valida(self) -> None:
        """CFOP 7xxx (exportacao) -> nao valida CFOP_001/002."""
        ctx = make_ctx({"PART01": {"nome": "Ext", "cnpj": "", "ie": "", "uf": "EX", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="7101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert not any(e.error_type == "CFOP_INTERESTADUAL_MESMA_UF" for e in errors)
        assert not any(e.error_type == "CFOP_INTERNO_OUTRA_UF" for e in errors)

    def test_cfop_entrada_nao_valida(self) -> None:
        """CFOP 1xxx/2xxx (entrada) -> nao valida CFOP_001/002."""
        ctx = make_ctx({"PART01": {"nome": "Forn", "cnpj": "123", "ie": "77123", "uf": "RJ", "cod_mun": ""}}, uf="SP")
        records = [c100("PART01", line=1), c170(cfop="1101", line=2)]
        errors = validate_cfop(records, context=ctx)
        assert len(errors) == 0

    def test_empty_records(self) -> None:
        ctx = make_ctx()
        assert validate_cfop([], context=ctx) == []

    def test_multiple_items(self) -> None:
        """Multiplos C170 com problemas diferentes."""
        ctx = make_ctx({
            "PART_SP": {"nome": "SP", "cnpj": "1", "ie": "110", "uf": "SP", "cod_mun": ""},
            "PART_RJ": {"nome": "RJ", "cnpj": "2", "ie": "77123", "uf": "RJ", "cod_mun": ""},
        }, uf="SP")
        records = [
            c100("PART_SP", line=1),
            c170(cfop="6101", line=2),  # CFOP_001: interestadual mesma UF
            c100("PART_RJ", line=3),
            c170(cfop="5101", line=4),  # CFOP_002: interno outra UF
        ]
        errors = validate_cfop(records, context=ctx)
        assert any(e.error_type == "CFOP_INTERESTADUAL_MESMA_UF" and e.line_number == 2 for e in errors)
        assert any(e.error_type == "CFOP_INTERNO_OUTRA_UF" and e.line_number == 4 for e in errors)
