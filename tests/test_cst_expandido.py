"""Testes das regras CST expandidas (CST_001, CST_004, CST_005)."""

from __future__ import annotations

import pytest

from src.models import SpedRecord
from src.validators.cst_validator import (
    _validate_cst020_aliq_reduzida,
    _validate_cst_tributado_aliq_zero,
    _validate_diferimento_debito,
    validate_cst_and_exemptions,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(
        line_number=line, register=register,
        fields=fields_to_dict(register, fields), raw_line=raw,
    )


def c170(
    cst: str = "000",
    cfop: str = "5101",
    aliq: str = "18,00",
    vl_item: str = "1000,00",
    vl_bc: str = "1000,00",
    vl_icms: str = "180,00",
    vl_desc: str = "0",
    line: int = 1,
) -> SpedRecord:
    """C170 com campos configuraveis para testes CST expandido."""
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN", vl_item,
        vl_desc, "0", cst, cfop, "001",
        vl_bc, aliq, vl_icms,
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# CST_001: CST tributado com aliquota zero
# ──────────────────────────────────────────────

class TestCst001TributadoAliqZero:
    def test_cst00_aliq_zero_erro(self) -> None:
        r = c170(cst="000", aliq="0", vl_item="1000,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_TRIBUTADO_ALIQ_ZERO"

    def test_cst20_aliq_zero_ok(self) -> None:
        """CST 20 (reducao de base) admite ALIQ=0 conforme Guia Pratico."""
        r = c170(cst="020", aliq="0", vl_item="500,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 0

    def test_cst70_aliq_zero_erro(self) -> None:
        r = c170(cst="070", aliq="0", vl_item="1000,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 1

    def test_cst90_aliq_zero_ok(self) -> None:
        """CST 90 (Outras) admite ALIQ=0 conforme Guia Pratico EFD."""
        r = c170(cst="090", aliq="0", vl_item="1000,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 0

    def test_cst00_aliq_positiva_ok(self) -> None:
        r = c170(cst="000", aliq="18,00", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_cst_isento_aliq_zero_ok(self) -> None:
        """CST 40 (isento) com aliquota zero e esperado."""
        r = c170(cst="040", aliq="0", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_cst_diferimento_aliq_zero_ok(self) -> None:
        """CST 51 (diferimento) nao e CST tributado."""
        r = c170(cst="051", aliq="0", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_exportacao_aliq_zero_ok(self) -> None:
        """CFOP 7101 (exportacao) com aliquota zero e esperado."""
        r = c170(cst="000", cfop="7101", aliq="0", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_remessa_aliq_zero_ok(self) -> None:
        """CFOP 5901 (remessa) com aliquota zero e esperado."""
        r = c170(cst="000", cfop="5901", aliq="0", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_vl_item_zero_ok(self) -> None:
        """VL_ITEM = 0 nao dispara erro."""
        r = c170(cst="000", aliq="0", vl_item="0")
        assert _validate_cst_tributado_aliq_zero(r) == []

    def test_cst_vazio_ok(self) -> None:
        r = c170(cst="", aliq="0", vl_item="1000,00")
        assert _validate_cst_tributado_aliq_zero(r) == []

    @pytest.mark.parametrize("cst", ["00", "10", "70"])
    def test_cst_tributados_aliq_zero_erro(self, cst: str) -> None:
        """CSTs tributados estritos (00,10,70) com aliquota zero geram erro."""
        r = c170(cst=cst, aliq="0", vl_item="100,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 1

    @pytest.mark.parametrize("cst", ["20", "90"])
    def test_cst_admite_zero_nao_gera_erro(self, cst: str) -> None:
        """CSTs 20 (reducao) e 90 (outras) admitem ALIQ=0 conforme Guia Pratico."""
        r = c170(cst=cst, aliq="0", vl_item="100,00")
        errors = _validate_cst_tributado_aliq_zero(r)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# CST_004: CST 020 com aliquota reduzida sem decreto
# ──────────────────────────────────────────────

class TestCst004AliqReduzida:
    def test_cst020_aliq_7_interno_erro(self) -> None:
        """CST 020 com aliquota 7% em operacao interna (5xxx)."""
        r = c170(cst="020", cfop="5101", aliq="7,00")
        errors = _validate_cst020_aliq_reduzida(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_020_ALIQ_REDUZIDA"

    def test_cst020_aliq_12_interno_erro(self) -> None:
        r = c170(cst="020", cfop="5101", aliq="12,00")
        errors = _validate_cst020_aliq_reduzida(r)
        assert len(errors) == 1

    def test_cst020_aliq_18_ok(self) -> None:
        """Aliquota >= 17% nao dispara."""
        r = c170(cst="020", cfop="5101", aliq="18,00")
        assert _validate_cst020_aliq_reduzida(r) == []

    def test_cst020_aliq_17_ok(self) -> None:
        r = c170(cst="020", cfop="5101", aliq="17,00")
        assert _validate_cst020_aliq_reduzida(r) == []

    def test_cst020_aliq_12_interestadual_ok(self) -> None:
        """CFOP 6xxx (interestadual) — aliquota 12% e normal."""
        r = c170(cst="020", cfop="6101", aliq="12,00")
        assert _validate_cst020_aliq_reduzida(r) == []

    def test_cst00_aliq_baixa_ok(self) -> None:
        """Apenas CST 020 dispara."""
        r = c170(cst="000", cfop="5101", aliq="7,00")
        assert _validate_cst020_aliq_reduzida(r) == []

    def test_cst020_aliq_zero_ok(self) -> None:
        """Aliquota zero e tratada por CST_001, nao CST_004."""
        r = c170(cst="020", cfop="5101", aliq="0")
        assert _validate_cst020_aliq_reduzida(r) == []


# ──────────────────────────────────────────────
# CST_005: Diferimento com debito indevido
# ──────────────────────────────────────────────

class TestCst005DiferimentoDebito:
    def test_cst051_com_icms_erro(self) -> None:
        r = c170(cst="051", vl_icms="180,00")
        errors = _validate_diferimento_debito(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_051_DIFERIMENTO_DEBITO"

    def test_cst051_icms_zero_ok(self) -> None:
        r = c170(cst="051", vl_icms="0")
        assert _validate_diferimento_debito(r) == []

    def test_cst051_3digitos_com_icms_erro(self) -> None:
        """CST 051 com 3 digitos (origem 0 + diferimento)."""
        r = c170(cst="051", vl_icms="50,00")
        errors = _validate_diferimento_debito(r)
        assert len(errors) == 1

    def test_cst00_com_icms_ok(self) -> None:
        """CST 00 nao e diferimento."""
        r = c170(cst="000", vl_icms="180,00")
        assert _validate_diferimento_debito(r) == []

    def test_cst_vazio_ok(self) -> None:
        r = c170(cst="", vl_icms="180,00")
        assert _validate_diferimento_debito(r) == []

    def test_cst40_com_icms_ok(self) -> None:
        """CST 40 nao e diferimento."""
        r = c170(cst="040", vl_icms="180,00")
        assert _validate_diferimento_debito(r) == []


# ──────────────────────────────────────────────
# Integracao: validate_cst_and_exemptions
# ──────────────────────────────────────────────

class TestCstExpandidoIntegracao:
    def test_detecta_cst001(self) -> None:
        """CST_001 detectado via funcao publica."""
        records = [c170(cst="000", aliq="0", vl_item="1000,00")]
        errors = validate_cst_and_exemptions(records)
        assert any(e.error_type == "CST_TRIBUTADO_ALIQ_ZERO" for e in errors)

    def test_detecta_cst004(self) -> None:
        records = [c170(cst="020", cfop="5101", aliq="7,00")]
        errors = validate_cst_and_exemptions(records)
        assert any(e.error_type == "CST_020_ALIQ_REDUZIDA" for e in errors)

    def test_detecta_cst005(self) -> None:
        records = [c170(cst="051", vl_icms="180,00")]
        errors = validate_cst_and_exemptions(records)
        assert any(e.error_type == "CST_051_DIFERIMENTO_DEBITO" for e in errors)
