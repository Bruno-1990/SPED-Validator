"""Testes do validador IPI (IPI_001, IPI_003)."""

from __future__ import annotations

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.validators.helpers import fields_to_dict
from src.validators.ipi_validator import validate_ipi


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


def c170(
    vl_item: str = "1000,00", vl_desc: str = "0",
    vl_bc_icms: str = "1000,00", aliq_icms: str = "18,00", vl_icms: str = "180,00",
    cst: str = "000", cfop: str = "5101",
    vl_bc_ipi: str = "", aliq_ipi: str = "", vl_ipi: str = "",
    cst_ipi: str = "",
    line: int = 2,
) -> SpedRecord:
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN",
        vl_item, vl_desc, "0", cst, cfop, "001",
        vl_bc_icms, aliq_icms, vl_icms,
        "", "", "",
        "", cst_ipi, "",
        vl_bc_ipi, aliq_ipi, vl_ipi,
        "", "", "", "", "", "",
        "", "", "", "", "", "",
        "", "",
    ]
    return rec("C170", fields, line=line)


def make_ctx(participantes: dict | None = None) -> ValidationContext:
    return ValidationContext(
        file_id=1,
        regime=TaxRegime.NORMAL,
        uf_contribuinte="SP",
        participantes=participantes or {},
    )


# ──────────────────────────────────────────────
# IPI_001 — IPI reflexo incorreto na base ICMS
# ──────────────────────────────────────────────

class TestIPI001:
    def test_nao_contribuinte_ipi_fora_bc(self) -> None:
        """Nao-contribuinte: IPI deveria estar na BC ICMS mas nao esta."""
        ctx = make_ctx({"PART01": {"nome": "PF", "cnpj": "", "ie": "", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(vl_item="1000,00", vl_desc="0", vl_bc_icms="1000,00",
                 vl_ipi="100,00", line=2),
        ]
        errors = validate_ipi(records, context=ctx)
        assert any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)

    def test_nao_contribuinte_ipi_na_bc_ok(self) -> None:
        """Nao-contribuinte: IPI corretamente na BC ICMS."""
        ctx = make_ctx({"PART01": {"nome": "PF", "cnpj": "", "ie": "", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(vl_item="1000,00", vl_desc="0", vl_bc_icms="1100,00",
                 vl_ipi="100,00", line=2),
        ]
        errors = validate_ipi(records, context=ctx)
        assert not any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)

    def test_contribuinte_ipi_na_bc_erro(self) -> None:
        """Contribuinte: IPI nao deveria estar na BC ICMS."""
        ctx = make_ctx({"PART01": {
            "nome": "Empresa", "cnpj": "12345678000100",
            "ie": "123456789", "uf": "RJ", "cod_mun": "",
        }})
        records = [
            c100("PART01", line=1),
            c170(vl_item="1000,00", vl_desc="0", vl_bc_icms="1100,00",
                 vl_ipi="100,00", line=2),
        ]
        errors = validate_ipi(records, context=ctx)
        assert any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)

    def test_contribuinte_ipi_fora_bc_ok(self) -> None:
        """Contribuinte: IPI corretamente fora da BC ICMS."""
        ctx = make_ctx({"PART01": {
            "nome": "Empresa", "cnpj": "12345678000100",
            "ie": "123456789", "uf": "RJ", "cod_mun": "",
        }})
        records = [
            c100("PART01", line=1),
            c170(vl_item="1000,00", vl_desc="0", vl_bc_icms="1000,00",
                 vl_ipi="100,00", line=2),
        ]
        errors = validate_ipi(records, context=ctx)
        assert not any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)

    def test_sem_ipi_nao_gera_erro(self) -> None:
        """Sem IPI nao deve gerar erro."""
        ctx = make_ctx({"PART01": {"nome": "PF", "cnpj": "", "ie": "", "uf": "RJ", "cod_mun": ""}})
        records = [
            c100("PART01", line=1),
            c170(vl_item="1000,00", vl_ipi="0", line=2),
        ]
        errors = validate_ipi(records, context=ctx)
        assert not any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)

    def test_sem_contexto_nao_gera_erro(self) -> None:
        records = [c170(vl_ipi="100,00", line=1)]
        errors = validate_ipi(records, context=None)
        assert not any(e.error_type == "IPI_REFLEXO_BC_ICMS" for e in errors)


# ──────────────────────────────────────────────
# IPI_003 — CST IPI incompativel com campos monetarios
# ──────────────────────────────────────────────

class TestIPI003:
    def test_tributado_sem_valor(self) -> None:
        """CST 50 tributado com BC>0 e ALIQ>0 mas VL_IPI=0."""
        records = [c170(cst_ipi="50", vl_bc_ipi="1000,00", aliq_ipi="10,00", vl_ipi="0", line=1)]
        errors = validate_ipi(records)
        assert any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_tributado_com_valor_ok(self) -> None:
        """CST 50 tributado com valor -> OK."""
        records = [c170(cst_ipi="50", vl_bc_ipi="1000,00", aliq_ipi="10,00", vl_ipi="100,00", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_isento_com_valor(self) -> None:
        """CST 02 isento com VL_IPI > 0."""
        records = [c170(cst_ipi="02", vl_ipi="50,00", line=1)]
        errors = validate_ipi(records)
        assert any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_isento_sem_valor_ok(self) -> None:
        """CST 03 isento sem valor -> OK."""
        records = [c170(cst_ipi="03", vl_ipi="0", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_nt_com_valores(self) -> None:
        """CST 99 NT com valores monetarios."""
        records = [c170(cst_ipi="99", vl_bc_ipi="100,00", vl_ipi="10,00", line=1)]
        errors = validate_ipi(records)
        assert any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_nt_sem_valores_ok(self) -> None:
        """CST 99 NT sem valores -> OK."""
        records = [c170(cst_ipi="99", vl_bc_ipi="0", vl_ipi="0", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_sem_cst_ipi_nao_valida(self) -> None:
        """Sem CST IPI -> nao valida."""
        records = [c170(cst_ipi="", vl_ipi="100,00", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_cst_49_residual_nao_exige_valor(self) -> None:
        """CST 49 (Outras Entradas) e residual — nao exige BC/aliq/valor."""
        records = [c170(cst_ipi="49", vl_bc_ipi="500,00", aliq_ipi="5,00", vl_ipi="0", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)

    def test_cst_00_tributado_ok(self) -> None:
        """CST 00 com tudo preenchido corretamente."""
        records = [c170(cst_ipi="00", vl_bc_ipi="200,00", aliq_ipi="10,00", vl_ipi="20,00", line=1)]
        errors = validate_ipi(records)
        assert not any(e.error_type == "IPI_CST_MONETARIO_INCOMPATIVEL" for e in errors)


class TestValidateIpiIntegration:
    def test_empty_records(self) -> None:
        assert validate_ipi([]) == []

    def test_no_c170(self) -> None:
        records = [rec("0000", ["0000", "017", "0", "01012024", "31012024", "Empresa", "12345678000195"])]
        assert validate_ipi(records) == []
