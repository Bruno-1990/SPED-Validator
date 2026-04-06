"""Testes das regras de validacao NCM (ncm_validator.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.models import SpedRecord
from src.parser import group_by_register
from src.services.context_builder import ValidationContext
from src.services.reference_loader import ReferenceLoader
from src.validators.helpers import fields_to_dict
from src.validators.ncm_validator import (
    _check_ncm_001,
    _check_ncm_002,
    validate_ncm,
)


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def make_0200(cod_item: str, ncm: str = "94036000", line: int = 5) -> SpedRecord:
    fields = ["0200", cod_item, "Descricao", "", "", "UN", "00", ncm]
    return rec("0200", fields, line=line)


def c170(
    cst: str = "000", cfop: str = "5102",
    vl_item: str = "1000,00", cod_item: str = "PROD001", line: int = 11,
) -> SpedRecord:
    fields = [
        "C170", "1", cod_item, "Desc", "100", "UN",
        vl_item, "0", "0", cst, cfop, "001",
        "1000,00", "18,00", "180,00",
        "", "", "",
        "", "", "",
        "", "", "",
        "", "", "", "", "", "",
        "", "", "", "", "", "",
    ]
    return rec("C170", fields, line=line)


def _make_context_with_loader(tributacao_map: dict[str, str]) -> ValidationContext:
    """Cria contexto com ReferenceLoader mockado."""
    loader = MagicMock(spec=ReferenceLoader)
    loader.get_ncm_tributacao = lambda ncm: tributacao_map.get(ncm.strip())
    ctx = ValidationContext(file_id=1, reference_loader=loader)
    return ctx


# ──────────────────────────────────────────────
# NCM_001: NCM com tratamento tributario incompativel
# ──────────────────────────────────────────────

class TestNcm001:
    def test_ncm_isento_cst_tributado_alerta(self) -> None:
        records = [
            make_0200("PROD001", ncm="12345678"),
            c170(cst="000", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "12345678"}
        ctx = _make_context_with_loader({"12345678": "isento"})
        errors = _check_ncm_001(groups, item_ncm, ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "NCM_TRIBUTACAO_INCOMPATIVEL"
        assert "isento" in errors[0].message

    def test_ncm_monofasico_cst_normal_alerta(self) -> None:
        records = [
            make_0200("PROD001", ncm="22021000"),
            c170(cst="000", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "22021000"}
        ctx = _make_context_with_loader({"22021000": "monofasico"})
        errors = _check_ncm_001(groups, item_ncm, ctx)
        assert len(errors) == 1
        assert "monofasico" in errors[0].message

    def test_ncm_monofasico_cst60_ok(self) -> None:
        records = [
            c170(cst="060", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "22021000"}
        ctx = _make_context_with_loader({"22021000": "monofasico"})
        errors = _check_ncm_001(groups, item_ncm, ctx)
        assert errors == []

    def test_ncm_normal_cst_tributado_ok(self) -> None:
        records = [
            c170(cst="000", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "94036000"}
        ctx = _make_context_with_loader({"94036000": "normal"})
        errors = _check_ncm_001(groups, item_ncm, ctx)
        assert errors == []

    def test_ncm_nao_catalogado_ignora(self) -> None:
        records = [
            c170(cst="000", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "99999999"}
        ctx = _make_context_with_loader({})  # sem NCM catalogado
        errors = _check_ncm_001(groups, item_ncm, ctx)
        assert errors == []

    def test_sem_reference_loader_emite_info(self) -> None:
        records = [
            c170(cst="000", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "12345678"}
        errors = _check_ncm_001(groups, item_ncm, None)
        assert len(errors) == 1
        assert errors[0].error_type == "NCM_REFERENCIA_INDISPONIVEL"


# ──────────────────────────────────────────────
# NCM_002: NCM generico com reflexo fiscal
# ──────────────────────────────────────────────

class TestNcm002:
    def test_ncm_generico_valor_alto_alerta(self) -> None:
        records = [
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "84710000"}
        errors = _check_ncm_002(groups, item_ncm)
        assert len(errors) == 1
        assert errors[0].error_type == "NCM_GENERICO_RELEVANTE"
        assert "84710000" in errors[0].message

    def test_ncm_generico_valor_baixo_ok(self) -> None:
        records = [
            c170(vl_item="500,00", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "84710000"}
        errors = _check_ncm_002(groups, item_ncm)
        assert errors == []

    def test_ncm_especifico_nao_aplica(self) -> None:
        records = [
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "84713012"}  # NCM especifico
        errors = _check_ncm_002(groups, item_ncm)
        assert errors == []

    def test_ncm_curto_nao_aplica(self) -> None:
        records = [
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "8471"}  # NCM curto
        errors = _check_ncm_002(groups, item_ncm)
        assert errors == []

    def test_mesmo_ncm_generico_alerta_uma_vez(self) -> None:
        records = [
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
            c170(vl_item="3000,00", cod_item="PROD002", line=12),
        ]
        groups = group_by_register(records)
        item_ncm = {"PROD001": "84710000", "PROD002": "84710000"}
        errors = _check_ncm_002(groups, item_ncm)
        assert len(errors) == 1  # Apenas 1 alerta por NCM


# ──────────────────────────────────────────────
# Integracao
# ──────────────────────────────────────────────

class TestValidateNcm:
    def test_empty(self) -> None:
        assert validate_ncm([]) == []

    def test_detecta_ncm_generico(self) -> None:
        records = [
            make_0200("PROD001", ncm="84710000"),
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
        ]
        errors = validate_ncm(records)
        types = {e.error_type for e in errors}
        assert "NCM_GENERICO_RELEVANTE" in types

    def test_sem_0200_sem_erros_ncm(self) -> None:
        records = [
            c170(vl_item="5000,00", cod_item="PROD001", line=11),
        ]
        # Sem context = emite NCM_REFERENCIA_INDISPONIVEL
        errors = validate_ncm(records)
        ncm_errors = [e for e in errors if e.error_type not in ("NCM_REFERENCIA_INDISPONIVEL",)]
        assert ncm_errors == []
