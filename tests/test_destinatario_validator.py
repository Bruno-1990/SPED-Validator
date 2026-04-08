"""Testes do validador de Destinatario (DEST_001, DEST_002, DEST_003)."""

from __future__ import annotations

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.validators.destinatario_validator import (
    _ie_matches_uf,
    _uf_from_cep,
    validate_destinatario,
)
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


def c170(cst: str = "000", cfop: str = "6101", line: int = 2) -> SpedRecord:
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN",
        "1000,00", "0", "0", cst, cfop, "001",
        "1000,00", "18,00", "180,00",
        "", "", "",
        "", "", "",
        "", "", "",
        "", "", "", "", "", "",
        "", "", "", "", "", "",
        "", "",
    ]
    return rec("C170", fields, line=line)


def reg_0150(cod_part: str, uf: str, ie: str = "", cod_mun: str = "", line: int = 10) -> SpedRecord:
    fields = [
        "0150", cod_part, "Nome Participante", "1058", "12345678000100", "",
        ie, cod_mun, "", "Rua X", "100", "", "Centro", uf,
    ]
    return rec("0150", fields, line=line)


def reg_0005(cep: str = "01310100", line: int = 5) -> SpedRecord:
    fields = [
        "0005", "Fantasia", cep, "Av Paulista", "100", "", "Centro",
        "1133334444", "", "email@test.com",
    ]
    return rec("0005", fields, line=line)


def make_ctx(participantes: dict | None = None, uf: str = "SP") -> ValidationContext:
    return ValidationContext(
        file_id=1,
        regime=TaxRegime.NORMAL,
        uf_contribuinte=uf,
        participantes=participantes or {},
    )


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

class TestUfFromCep:
    def test_sp(self) -> None:
        assert _uf_from_cep("01310100") == "SP"

    def test_rj(self) -> None:
        assert _uf_from_cep("20040020") == "RJ"

    def test_mg(self) -> None:
        assert _uf_from_cep("30130000") == "MG"

    def test_rs(self) -> None:
        assert _uf_from_cep("90000000") == "RS"

    def test_invalid(self) -> None:
        assert _uf_from_cep("") is None
        assert _uf_from_cep("12345") is None
        assert _uf_from_cep("abcdefgh") is None


class TestIeMatchesUf:
    def test_sp_match(self) -> None:
        assert _ie_matches_uf("110482180114", "SP") is True

    def test_sp_no_match(self) -> None:
        assert _ie_matches_uf("770482180114", "SP") is False

    def test_rj_match(self) -> None:
        assert _ie_matches_uf("77123456", "RJ") is True

    def test_no_data(self) -> None:
        assert _ie_matches_uf("", "SP") is None

    def test_unknown_uf(self) -> None:
        assert _ie_matches_uf("12345", "XX") is None


# ──────────────────────────────────────────────
# DEST_001 — IE inconsistente com tratamento fiscal
# ──────────────────────────────────────────────

class TestDEST001:
    def test_ie_ativa_cst_isento_interestadual(self) -> None:
        """IE ativa + CST 40 + CFOP 6xxx = inconsistente."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "110123456", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(cst="040", cfop="6101", line=2),
        ]
        errors = validate_destinatario(records, context=ctx)
        assert any(e.error_type == "DEST_IE_INCONSISTENTE" for e in errors)

    def test_ie_ativa_cst_tributado_ok(self) -> None:
        """IE ativa + CST tributado -> OK."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "110123456", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(cst="000", cfop="6101", line=2),
        ]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_IE_INCONSISTENTE" for e in errors)

    def test_sem_ie_nao_gera_erro(self) -> None:
        """Sem IE -> nao valida DEST_001."""
        ctx = make_ctx({"PART01": {"nome": "PF", "cnpj": "", "ie": "", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(cst="040", cfop="6101", line=2),
        ]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_IE_INCONSISTENTE" for e in errors)

    def test_ie_isento_nao_gera_erro(self) -> None:
        """IE = ISENTO -> nao contribuinte, nao valida."""
        ctx = make_ctx({"PART01": {"nome": "PF", "cnpj": "", "ie": "ISENTO", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(cst="040", cfop="6101", line=2),
        ]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_IE_INCONSISTENTE" for e in errors)

    def test_cfop_interno_nao_gera_erro(self) -> None:
        """CST 40 + CFOP 5xxx (interno) -> nao valida DEST_001."""
        ctx = make_ctx({"PART01": {"nome": "Emp", "cnpj": "123", "ie": "110123456", "uf": "SP", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(cst="040", cfop="5101", line=2),
        ]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_IE_INCONSISTENTE" for e in errors)

    def test_sem_contexto(self) -> None:
        records = [c170(cst="040", cfop="6101", line=1)]
        assert validate_destinatario(records, context=None) == []


# ──────────────────────────────────────────────
# DEST_002 — UF incompativel com IE
# ──────────────────────────────────────────────

class TestDEST002:
    def test_ie_uf_incompativel(self) -> None:
        """IE com prefixo SP (1xxx) mas UF = RJ."""
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="RJ", ie="110123456", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert any(e.error_type == "DEST_UF_IE_INCOMPATIVEL" for e in errors)

    def test_ie_uf_compativel(self) -> None:
        """IE com prefixo RJ (77xxx) e UF = RJ."""
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="RJ", ie="77123456", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_IE_INCOMPATIVEL" for e in errors)

    def test_ie_vazia_nao_valida(self) -> None:
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="RJ", ie="", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_IE_INCOMPATIVEL" for e in errors)

    def test_ie_isento_nao_valida(self) -> None:
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="RJ", ie="ISENTO", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_IE_INCOMPATIVEL" for e in errors)


# ──────────────────────────────────────────────
# DEST_003 — UF incompativel com CEP / COD_MUN
# ──────────────────────────────────────────────

class TestDEST003:
    def test_cep_uf_incompativel(self) -> None:
        """CEP de SP mas UF contribuinte (0000) = RJ."""
        ctx = make_ctx(uf="RJ")
        records = [reg_0005(cep="01310100", line=5)]
        errors = validate_destinatario(records, context=ctx)
        assert any(e.error_type == "DEST_UF_CEP_INCOMPATIVEL" for e in errors)

    def test_cep_uf_compativel(self) -> None:
        """CEP de SP e UF contribuinte = SP."""
        ctx = make_ctx(uf="SP")
        records = [reg_0005(cep="01310100", line=5)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_CEP_INCOMPATIVEL" for e in errors)

    def test_cod_mun_uf_incompativel(self) -> None:
        """COD_MUN de SP (35xxxxx) mas UF = RJ."""
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="RJ", cod_mun="3550308", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert any(e.error_type == "DEST_UF_CEP_INCOMPATIVEL" for e in errors)

    def test_cod_mun_uf_compativel(self) -> None:
        """COD_MUN de SP (35xxxxx) e UF = SP."""
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="SP", cod_mun="3550308", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_CEP_INCOMPATIVEL" for e in errors)

    def test_sem_cod_mun_nao_valida(self) -> None:
        ctx = make_ctx()
        records = [reg_0150("PART01", uf="SP", cod_mun="", line=10)]
        errors = validate_destinatario(records, context=ctx)
        assert not any(e.error_type == "DEST_UF_CEP_INCOMPATIVEL" for e in errors)


class TestValidateDestinatarioIntegration:
    def test_empty_records(self) -> None:
        ctx = make_ctx()
        assert validate_destinatario([], context=ctx) == []

    def test_no_context(self) -> None:
        assert validate_destinatario([], context=None) == []
