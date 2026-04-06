"""Testes do validador de CSTs, isenções e Bloco H."""

from __future__ import annotations

import pytest

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.cst_validator import (
    _validate_bloco_h,
    _validate_cst_c170,
    _validate_exemptions_c170,
    validate_cst_and_exemptions,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def c170(cst: str = "000", vl_bc: str = "1000,00", vl_icms: str = "180,00", line: int = 1) -> SpedRecord:
    """C170 com layout oficial: 9:CST_ICMS, 10:CFOP, 11:COD_NAT, 12:VL_BC_ICMS, 13:ALIQ, 14:VL_ICMS."""
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN", "1000,00",
        "0", "0", cst, "5101", "001",
        vl_bc, "18,00", vl_icms,
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# Validação CST ICMS
# ──────────────────────────────────────────────

class TestValidateCstC170:
    def test_cst_00_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="00")) == []

    def test_cst_000_valid(self) -> None:
        """3 dígitos: origem 0 + tributação 00."""
        assert _validate_cst_c170(c170(cst="000")) == []

    def test_cst_010_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="010")) == []

    def test_cst_060_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="060")) == []

    def test_cst_090_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="090")) == []

    def test_cst_origem_invalida(self) -> None:
        """Origem 9 com tributação não-CSOSN é inválida."""
        # "900" é CSOSN válido, mas "910" não existe
        errors = _validate_cst_c170(c170(cst="910"))
        assert any(e.error_type == "CST_INVALIDO" for e in errors)

    def test_cst_tributacao_invalida(self) -> None:
        """Tributação 99 não existe (só existe 90)."""
        errors = _validate_cst_c170(c170(cst="099"))
        assert any(e.error_type == "CST_INVALIDO" for e in errors)

    def test_cst_2_digitos_invalido(self) -> None:
        errors = _validate_cst_c170(c170(cst="99"))
        assert any(e.error_type == "CST_INVALIDO" for e in errors)

    def test_csosn_101_valid(self) -> None:
        """CSOSN do Simples Nacional."""
        assert _validate_cst_c170(c170(cst="101")) == []

    def test_csosn_102_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="102")) == []

    def test_csosn_500_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="500")) == []

    def test_csosn_900_valid(self) -> None:
        assert _validate_cst_c170(c170(cst="900")) == []

    def test_empty_cst_skipped(self) -> None:
        assert _validate_cst_c170(c170(cst="")) == []

    def test_cst_1_digito_invalido(self) -> None:
        errors = _validate_cst_c170(c170(cst="5"))
        assert any(e.error_type == "CST_INVALIDO" for e in errors)

    @pytest.mark.parametrize("cst", ["00", "10", "20", "30", "40", "41", "50", "51", "60", "70", "90"])
    def test_all_valid_2digit_csts(self, cst: str) -> None:
        assert _validate_cst_c170(c170(cst=cst)) == []

    @pytest.mark.parametrize("origem", ["0", "1", "2", "3", "4", "5", "6", "7", "8"])
    def test_all_valid_origins(self, origem: str) -> None:
        assert _validate_cst_c170(c170(cst=f"{origem}00")) == []


# ──────────────────────────────────────────────
# Validação de isenções
# ──────────────────────────────────────────────

class TestValidateExemptions:
    def test_isento_com_valores_zero_ok(self) -> None:
        r = c170(cst="040", vl_bc="0", vl_icms="0")
        assert _validate_exemptions_c170(r) == []

    def test_isento_com_bc_positivo(self) -> None:
        r = c170(cst="040", vl_bc="1000,00", vl_icms="0")
        errors = _validate_exemptions_c170(r)
        assert any(e.error_type == "ISENCAO_INCONSISTENTE" for e in errors)

    def test_isento_com_icms_positivo(self) -> None:
        r = c170(cst="041", vl_bc="0", vl_icms="180,00")
        errors = _validate_exemptions_c170(r)
        assert any(e.error_type == "ISENCAO_INCONSISTENTE" for e in errors)

    def test_nao_tributado_com_valores(self) -> None:
        r = c170(cst="50", vl_bc="500,00", vl_icms="90,00")
        errors = _validate_exemptions_c170(r)
        assert any(e.error_type == "ISENCAO_INCONSISTENTE" for e in errors)

    def test_cst_60_com_valores(self) -> None:
        """CST 60 (ICMS cobrado anteriormente por ST) — valores devem ser zero."""
        r = c170(cst="060", vl_bc="500,00", vl_icms="90,00")
        errors = _validate_exemptions_c170(r)
        assert any(e.error_type == "ISENCAO_INCONSISTENTE" for e in errors)

    def test_tributado_com_bc_e_icms_ok(self) -> None:
        r = c170(cst="000", vl_bc="1000,00", vl_icms="180,00")
        assert _validate_exemptions_c170(r) == []

    def test_tributado_com_bc_sem_icms_nao_duplica(self) -> None:
        """TRIBUTACAO_INCONSISTENTE removido daqui (coberto por CST_ALIQ_ZERO_FORTE
        no fiscal_semantics.py). Exemptions so checa CST isento."""
        r = c170(cst="000", vl_bc="1000,00", vl_icms="0")
        errors = _validate_exemptions_c170(r)
        assert not any(e.error_type == "TRIBUTACAO_INCONSISTENTE" for e in errors)

    def test_tributado_sem_bc_ok(self) -> None:
        """Se BC é zero, não reporta erro mesmo com CST tributado."""
        r = c170(cst="000", vl_bc="0", vl_icms="0")
        assert _validate_exemptions_c170(r) == []

    def test_empty_cst_skipped(self) -> None:
        r = c170(cst="", vl_bc="1000,00", vl_icms="180,00")
        assert _validate_exemptions_c170(r) == []


# ──────────────────────────────────────────────
# Bloco H (Estoque)
# ──────────────────────────────────────────────

class TestValidateBlocoH:
    def test_h010_valid(self) -> None:
        records = [
            rec("0200", ["0200", "PROD001", "Produto A"], line=1),
            rec("H010", ["H010", "PROD001", "UN", "100", "10,00", "1000,00"], line=2),
        ]
        groups = group_by_register(records)
        errors = _validate_bloco_h(groups)
        assert len(errors) == 0

    def test_h010_item_inexistente(self) -> None:
        records = [
            rec("0200", ["0200", "PROD001", "Produto A"], line=1),
            rec("H010", ["H010", "PROD_INEXISTENTE", "UN", "100", "10,00", "1000,00"], line=2),
        ]
        groups = group_by_register(records)
        errors = _validate_bloco_h(groups)
        assert any(e.error_type == "REF_INEXISTENTE" for e in errors)

    def test_h010_qtd_negativa(self) -> None:
        records = [
            rec("H010", ["H010", "PROD001", "UN", "-100", "10,00", "-1000,00"], line=1),
        ]
        groups = group_by_register(records)
        errors = _validate_bloco_h(groups)
        assert any(e.field_name == "QTD" for e in errors)

    def test_h010_valor_negativo(self) -> None:
        records = [
            rec("H010", ["H010", "PROD001", "UN", "100", "10,00", "-1000,00"], line=1),
        ]
        groups = group_by_register(records)
        errors = _validate_bloco_h(groups)
        assert any(e.field_name == "VL_ITEM" for e in errors)

    def test_no_h010_no_errors(self) -> None:
        records = [rec("0200", ["0200", "PROD001", "Produto A"])]
        groups = group_by_register(records)
        assert _validate_bloco_h(groups) == []

    def test_no_cadastro_no_ref_check(self) -> None:
        """Sem 0200, não verifica referência."""
        records = [
            rec("H010", ["H010", "PROD001", "UN", "100", "10,00", "1000,00"], line=1),
        ]
        groups = group_by_register(records)
        errors = _validate_bloco_h(groups)
        # Sem cadastro 0200, não reporta REF_INEXISTENTE
        assert not any(e.error_type == "REF_INEXISTENTE" for e in errors)


# ──────────────────────────────────────────────
# Integração
# ──────────────────────────────────────────────

class TestValidateCstAndExemptions:
    def test_valid_file(self, valid_records: list[SpedRecord]) -> None:
        errors = validate_cst_and_exemptions(valid_records)
        assert isinstance(errors, list)

    def test_empty(self) -> None:
        assert validate_cst_and_exemptions([]) == []

    def test_detects_mixed_errors(self) -> None:
        records = [
            rec("0200", ["0200", "PROD001", "Produto A"], line=1),
            c170(cst="99", vl_bc="1000,00", vl_icms="180,00", line=2),  # CST inválido
            c170(cst="040", vl_bc="500,00", vl_icms="90,00", line=3),  # Isento com valor
            rec("H010", ["H010", "INEXISTENTE", "UN", "100", "10,00", "1000,00"], line=4),
        ]
        errors = validate_cst_and_exemptions(records)
        assert any(e.error_type == "CST_INVALIDO" for e in errors)
        assert any(e.error_type == "ISENCAO_INCONSISTENTE" for e in errors)
        assert any(e.error_type == "REF_INEXISTENTE" for e in errors)
