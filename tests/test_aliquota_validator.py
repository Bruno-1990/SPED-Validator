"""Testes para o validador de aliquotas (ALIQ_001 a ALIQ_007)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from src.models import SpedRecord
from src.services.context_builder import ValidationContext
from src.validators.aliquota_validator import validate_aliquotas

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_record(register: str, fields: dict[str, str], line: int = 1) -> SpedRecord:
    return SpedRecord(
        line_number=line,
        register=register,
        fields=fields,
        raw_line="",
    )


def _c170(cfop: str, aliq: str, cst: str = "000", cod_item: str = "ITEM01", line: int = 10) -> SpedRecord:
    return _make_record("C170", {
        "REG": "C170",
        "NUM_ITEM": "1",
        "COD_ITEM": cod_item,
        "CFOP": cfop,
        "CST_ICMS": cst,
        "ALIQ_ICMS": aliq,
        "VL_BC_ICMS": "1000",
        "VL_ICMS": "120",
    }, line=line)


def _c100(cod_part: str = "PART01", line: int = 5) -> SpedRecord:
    return _make_record("C100", {
        "REG": "C100",
        "IND_OPER": "1",
        "COD_PART": cod_part,
        "COD_SIT": "00",
        "NUM_DOC": "1",
        "DT_DOC": "01012024",
    }, line=line)


def _c190(cfop: str, aliq: str, cst: str = "000", line: int = 20) -> SpedRecord:
    return _make_record("C190", {
        "REG": "C190",
        "CST_ICMS": cst,
        "CFOP": cfop,
        "ALIQ_ICMS": aliq,
        "VL_OPR": "1000",
        "VL_BC_ICMS": "1000",
        "VL_ICMS": "120",
    }, line=line)


def _reg0000(uf: str = "SP") -> SpedRecord:
    return _make_record("0000", {
        "REG": "0000", "COD_VER": "017", "COD_FIN": "0",
        "DT_INI": "01012024", "DT_FIN": "31012024",
        "NOME": "Empresa", "CNPJ": "12345678000195",
        "UF": uf, "IE": "123456789",
    }, line=1)


def _reg0150(cod_part: str, uf: str) -> SpedRecord:
    return _make_record("0150", {
        "REG": "0150", "COD_PART": cod_part, "NOME": "Parceiro",
        "UF": uf,
    }, line=2)


def _make_context(
    uf: str = "SP",
    produtos: dict | None = None,
    ref_loader: object | None = None,
) -> ValidationContext:
    return ValidationContext(
        file_id=1,
        uf_contribuinte=uf,
        periodo_ini=date(2024, 1, 1),
        periodo_fim=date(2024, 1, 31),
        produtos=produtos or {},
        reference_loader=ref_loader,
    )


# ──────────────────────────────────────────────
# ALIQ_001: Aliquota interestadual invalida
# ──────────────────────────────────────────────

class TestAliq001:
    def test_cfop_6xxx_aliq_fora_padrao(self):
        records = [_reg0000(), _c100(), _c170("6102", "18", cst="000")]
        errors = validate_aliquotas(records)
        assert any(e.error_type == "ALIQ_INTERESTADUAL_INVALIDA" for e in errors)

    def test_cfop_6xxx_aliq_valida_sem_erro(self):
        records = [_reg0000(), _c100(), _c170("6102", "12", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_INTERESTADUAL_INVALIDA" for e in errors)

    def test_cfop_5xxx_ignorado(self):
        records = [_reg0000(), _c100(), _c170("5102", "18", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_INTERESTADUAL_INVALIDA" for e in errors)

    def test_remessa_retorno_ignorado(self):
        records = [_reg0000(), _c100(), _c170("6901", "18", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_INTERESTADUAL_INVALIDA" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_002: Aliquota interna em interestadual
# ──────────────────────────────────────────────

class TestAliq002:
    def test_cfop_6xxx_aliq_alta(self):
        records = [_reg0000(), _c100(), _c170("6102", "18", cst="000")]
        errors = validate_aliquotas(records)
        errs002 = [e for e in errors if e.error_type == "ALIQ_INTERNA_EM_INTERESTADUAL"]
        assert len(errs002) == 1
        assert errs002[0].certeza == "provavel"

    def test_cfop_6xxx_aliq_12_sem_erro(self):
        records = [_reg0000(), _c100(), _c170("6102", "12", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_INTERNA_EM_INTERESTADUAL" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_003: Aliquota interestadual em interna
# ──────────────────────────────────────────────

class TestAliq003:
    def test_cfop_5xxx_aliq_interestadual_mesma_uf(self):
        records = [
            _reg0000("SP"),
            _reg0150("PART01", "SP"),
            _c100("PART01"),
            _c170("5102", "12", cst="000"),
        ]
        errors = validate_aliquotas(records)
        assert any(e.error_type == "ALIQ_INTERESTADUAL_EM_INTERNA" for e in errors)

    def test_cfop_5xxx_aliq_18_sem_erro(self):
        records = [_reg0000("SP"), _c100(), _c170("5102", "18", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_INTERESTADUAL_EM_INTERNA" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_004: Aliquota incompativel com par UF
# ──────────────────────────────────────────────

class TestAliq004:
    def test_aliq_incompativel_com_par_uf(self):
        """SP->RS deveria ser 12%, mas arquivo usa 7%."""
        loader = MagicMock()
        loader.get_matriz_aliquota.return_value = 12.0
        ctx = _make_context(uf="SP", ref_loader=loader)

        records = [
            _reg0000("SP"),
            _reg0150("PART01", "RS"),
            _c100("PART01"),
            _c170("6102", "7", cst="000"),
        ]
        errors = validate_aliquotas(records, context=ctx)
        errs004 = [e for e in errors if e.error_type == "ALIQ_UF_INCOMPATIVEL"]
        assert len(errs004) == 1
        assert "SP" in errs004[0].message
        assert "RS" in errs004[0].message

    def test_aliq_compativel_sem_erro(self):
        """SP->RS = 12%, arquivo usa 12% — ok."""
        loader = MagicMock()
        loader.get_matriz_aliquota.return_value = 12.0
        ctx = _make_context(uf="SP", ref_loader=loader)

        records = [
            _reg0000("SP"),
            _reg0150("PART01", "RS"),
            _c100("PART01"),
            _c170("6102", "12", cst="000"),
        ]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_UF_INCOMPATIVEL" for e in errors)

    def test_sem_ref_loader_sem_erro(self):
        """Sem reference_loader, ALIQ_004 nao emite erro."""
        ctx = _make_context(uf="SP")
        records = [
            _reg0000("SP"),
            _reg0150("PART01", "RS"),
            _c100("PART01"),
            _c170("6102", "7", cst="000"),
        ]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_UF_INCOMPATIVEL" for e in errors)

    def test_cfop_5xxx_ignorado(self):
        """Operacao interna nao deve disparar ALIQ_004."""
        loader = MagicMock()
        loader.get_matriz_aliquota.return_value = 12.0
        ctx = _make_context(uf="SP", ref_loader=loader)

        records = [_reg0000("SP"), _c100(), _c170("5102", "7", cst="000")]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_UF_INCOMPATIVEL" for e in errors)

    def test_remessa_ignorada(self):
        """Remessa/retorno nao deve disparar ALIQ_004."""
        loader = MagicMock()
        loader.get_matriz_aliquota.return_value = 12.0
        ctx = _make_context(uf="SP", ref_loader=loader)

        records = [
            _reg0000("SP"),
            _reg0150("PART01", "RS"),
            _c100("PART01"),
            _c170("6901", "7", cst="000"),
        ]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_UF_INCOMPATIVEL" for e in errors)

    def test_exportacao_ignorada(self):
        """Exportacao nao deve disparar ALIQ_004."""
        loader = MagicMock()
        loader.get_matriz_aliquota.return_value = 12.0
        ctx = _make_context(uf="SP", ref_loader=loader)

        records = [
            _reg0000("SP"),
            _reg0150("PART01", "RS"),
            _c100("PART01"),
            _c170("7101", "7", cst="000"),
        ]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_UF_INCOMPATIVEL" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_005: Aliquota 4% sem suporte de importacao
# ──────────────────────────────────────────────

class TestAliq005:
    def test_aliq_4_ncm_nao_importado(self):
        """NCM 3923 (plasticos) com 4% — warning."""
        ctx = _make_context(produtos={
            "ITEM01": {"ncm": "39231090", "descr": "Caixa plastica"},
        })
        records = [_reg0000(), _c100(), _c170("6102", "4", cst="000", cod_item="ITEM01")]
        errors = validate_aliquotas(records, context=ctx)
        errs005 = [e for e in errors if e.error_type == "ALIQ_4_SEM_IMPORTACAO"]
        assert len(errs005) == 1
        assert errs005[0].certeza == "provavel"

    def test_aliq_4_ncm_importado_sem_erro(self):
        """NCM 8471 (computadores) com 4% — ok, tipico de importado."""
        ctx = _make_context(produtos={
            "ITEM01": {"ncm": "84714900", "descr": "Computador"},
        })
        records = [_reg0000(), _c100(), _c170("6102", "4", cst="000", cod_item="ITEM01")]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_4_SEM_IMPORTACAO" for e in errors)

    def test_aliq_7_sem_erro(self):
        """Aliquota 7% nao dispara ALIQ_005."""
        ctx = _make_context(produtos={
            "ITEM01": {"ncm": "39231090", "descr": "Caixa plastica"},
        })
        records = [_reg0000(), _c100(), _c170("6102", "7", cst="000", cod_item="ITEM01")]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_4_SEM_IMPORTACAO" for e in errors)

    def test_sem_contexto_sem_erro(self):
        """Sem context.produtos, ALIQ_005 nao emite."""
        records = [_reg0000(), _c100(), _c170("6102", "4", cst="000")]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_4_SEM_IMPORTACAO" for e in errors)

    def test_cfop_5xxx_ignorado(self):
        """Operacao interna nao dispara ALIQ_005."""
        ctx = _make_context(produtos={
            "ITEM01": {"ncm": "39231090", "descr": "Caixa"},
        })
        records = [_reg0000(), _c100(), _c170("5102", "4", cst="000", cod_item="ITEM01")]
        errors = validate_aliquotas(records, context=ctx)
        assert not any(e.error_type == "ALIQ_4_SEM_IMPORTACAO" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_006: Mesmo item com aliquotas divergentes
# ──────────────────────────────────────────────

class TestAliq006:
    def test_item_com_aliquotas_divergentes(self):
        """Mesmo COD_ITEM com 12% e 18% — warning."""
        ctx = _make_context(produtos={
            "ITEM01": {"ncm": "39231090", "descr": "Caixa"},
        })
        records = [
            _reg0000(),
            _c100(line=5),
            _c170("6102", "12", cst="000", cod_item="ITEM01", line=10),
            _c170("5102", "18", cst="000", cod_item="ITEM01", line=11),
        ]
        errors = validate_aliquotas(records, context=ctx)
        errs006 = [e for e in errors if e.error_type == "ALIQ_DIVERGENTE_MESMO_ITEM"]
        assert len(errs006) == 1
        assert errs006[0].certeza == "indicio"
        assert "12.00%" in errs006[0].message
        assert "18.00%" in errs006[0].message

    def test_item_com_mesma_aliquota_sem_erro(self):
        """Mesmo COD_ITEM com mesma aliquota — ok."""
        records = [
            _reg0000(),
            _c100(line=5),
            _c170("6102", "12", cst="000", cod_item="ITEM01", line=10),
            _c170("6103", "12", cst="000", cod_item="ITEM01", line=11),
        ]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_DIVERGENTE_MESMO_ITEM" for e in errors)

    def test_itens_diferentes_aliquotas_diferentes_sem_erro(self):
        """Itens diferentes podem ter aliquotas diferentes — ok."""
        records = [
            _reg0000(),
            _c100(line=5),
            _c170("6102", "12", cst="000", cod_item="ITEM01", line=10),
            _c170("6102", "7", cst="000", cod_item="ITEM02", line=11),
        ]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_DIVERGENTE_MESMO_ITEM" for e in errors)


# ──────────────────────────────────────────────
# ALIQ_007: Aliquota media indevida no C190
# ──────────────────────────────────────────────

class TestAliq007:
    def test_c190_com_aliquota_media(self):
        """C190 com aliquota 10% entre itens de 7% e 12% — erro."""
        records = [
            _reg0000(),
            _c100(line=5),
            _c170("6102", "7", cst="000", cod_item="A", line=10),
            _c170("6102", "12", cst="000", cod_item="B", line=11),
            _c190("6102", "10", cst="000", line=20),
        ]
        errors = validate_aliquotas(records)
        assert any(e.error_type == "ALIQ_MEDIA_INDEVIDA" for e in errors)

    def test_c190_aliquota_presente_nos_itens_sem_erro(self):
        """C190 com aliquota que existe nos itens — ok."""
        records = [
            _reg0000(),
            _c100(line=5),
            _c170("6102", "12", cst="000", cod_item="A", line=10),
            _c170("6102", "7", cst="000", cod_item="B", line=11),
            _c190("6102", "12", cst="000", line=20),
        ]
        errors = validate_aliquotas(records)
        assert not any(e.error_type == "ALIQ_MEDIA_INDEVIDA" for e in errors)
