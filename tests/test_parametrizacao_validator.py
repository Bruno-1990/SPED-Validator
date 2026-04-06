"""Testes das regras de parametrizacao (parametrizacao_validator.py)."""

from __future__ import annotations

from datetime import date

from src.models import SpedRecord
from src.parser import group_by_register
from src.services.context_builder import ValidationContext
from src.validators.helpers import fields_to_dict
from src.validators.parametrizacao_validator import (
    _check_param_001,
    _check_param_002,
    _check_param_003,
    validate_parametrizacao,
)


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def make_0000(uf: str = "ES") -> SpedRecord:
    fields = ["0000", "017", "0", "01012024", "31012024", "EMPRESA", "12345678000190", "", uf]
    return rec("0000", fields)


def make_0150(cod_part: str, uf: str = "SP") -> SpedRecord:
    fields = ["0150", cod_part, "Nome", "", "11222333000144", "", "", "", "", "", "", "", "", uf]
    return rec("0150", fields)


def make_c100(ind_oper: str = "1", cod_part: str = "CLI001", line: int = 10, dt_doc: str = "01012024") -> SpedRecord:
    fields = ["C100", ind_oper, "0", cod_part, "55", "00", "1", "000000001", "", dt_doc, dt_doc, "1000,00"]
    return rec("C100", fields, line=line)


def c170(
    cst: str = "000", cfop: str = "5102", aliq: str = "18,00",
    vl_item: str = "1000,00", vl_bc: str = "1000,00", vl_icms: str = "180,00",
    cod_item: str = "PROD001", line: int = 11,
) -> SpedRecord:
    fields = [
        "C170", "1", cod_item, "Desc", "100", "UN",
        vl_item, "0", "0", cst, cfop, "001",
        vl_bc, aliq, vl_icms,
        "", "", "",
        "", "", "",
        "", "", "",
        "", "", "", "", "", "",
        "", "", "", "", "", "",
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# PARAM_001: Erro sistematico por item
# ──────────────────────────────────────────────

class TestParam001:
    def test_item_com_erro_repetitivo_alerta(self) -> None:
        # 4 vendas com CST isento = 100% incompatível -> alerta
        records = [
            c170(cst="040", cfop="5102", cod_item="X", line=1),
            c170(cst="040", cfop="5102", cod_item="X", line=2),
            c170(cst="040", cfop="5102", cod_item="X", line=3),
            c170(cst="040", cfop="5102", cod_item="X", line=4),
        ]
        groups = group_by_register(records)
        errors = _check_param_001(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "PARAM_ERRO_SISTEMATICO_ITEM"
        assert "X" in errors[0].message

    def test_item_sem_erro_ok(self) -> None:
        records = [
            c170(cst="000", cfop="5102", cod_item="X", line=1),
            c170(cst="000", cfop="5102", cod_item="X", line=2),
            c170(cst="000", cfop="5102", cod_item="X", line=3),
        ]
        groups = group_by_register(records)
        assert _check_param_001(groups) == []

    def test_poucos_registros_nao_aplica(self) -> None:
        records = [
            c170(cst="040", cfop="5102", cod_item="X", line=1),
            c170(cst="040", cfop="5102", cod_item="X", line=2),
        ]
        groups = group_by_register(records)
        assert _check_param_001(groups) == []

    def test_erro_abaixo_threshold_nao_aplica(self) -> None:
        # 2 erros em 4 registros = 50% < 80%
        records = [
            c170(cst="040", cfop="5102", cod_item="Y", line=1),
            c170(cst="040", cfop="5102", cod_item="Y", line=2),
            c170(cst="000", cfop="5102", cod_item="Y", line=3),
            c170(cst="000", cfop="5102", cod_item="Y", line=4),
        ]
        groups = group_by_register(records)
        assert _check_param_001(groups) == []


# ──────────────────────────────────────────────
# PARAM_002: Erro sistematico por UF destino
# ──────────────────────────────────────────────

class TestParam002:
    def test_erro_concentrado_por_uf_alerta(self) -> None:
        records = [
            make_0150("CLI001", uf="RJ"),
            make_c100(cod_part="CLI001", line=10),
            c170(cst="040", cfop="5102", cod_item="A", line=11),
            make_c100(cod_part="CLI001", line=20),
            c170(cst="040", cfop="5102", cod_item="B", line=21),
            make_c100(cod_part="CLI001", line=30),
            c170(cst="040", cfop="5102", cod_item="C", line=31),
        ]
        groups = group_by_register(records)
        from src.validators.parametrizacao_validator import _build_maps
        parent_map, part_uf = _build_maps(groups)
        errors = _check_param_002(groups, parent_map, part_uf)
        assert len(errors) == 1
        assert errors[0].error_type == "PARAM_ERRO_SISTEMATICO_UF"
        assert "RJ" in errors[0].message

    def test_sem_erro_por_uf_ok(self) -> None:
        records = [
            make_0150("CLI001", uf="RJ"),
            make_c100(cod_part="CLI001", line=10),
            c170(cst="000", cfop="5102", cod_item="A", line=11),
            make_c100(cod_part="CLI001", line=20),
            c170(cst="000", cfop="5102", cod_item="B", line=21),
            make_c100(cod_part="CLI001", line=30),
            c170(cst="000", cfop="5102", cod_item="C", line=31),
        ]
        groups = group_by_register(records)
        from src.validators.parametrizacao_validator import _build_maps
        parent_map, part_uf = _build_maps(groups)
        assert _check_param_002(groups, parent_map, part_uf) == []

    def test_sem_participante_nao_aplica(self) -> None:
        records = [
            c170(cst="040", cfop="5102", cod_item="A", line=1),
            c170(cst="040", cfop="5102", cod_item="B", line=2),
            c170(cst="040", cfop="5102", cod_item="C", line=3),
        ]
        groups = group_by_register(records)
        from src.validators.parametrizacao_validator import _build_maps
        parent_map, part_uf = _build_maps(groups)
        assert _check_param_002(groups, parent_map, part_uf) == []


# ──────────────────────────────────────────────
# PARAM_003: Erro sistematico iniciado em data
# ──────────────────────────────────────────────

class TestParam003:
    def test_erro_concentrado_na_segunda_metade_alerta(self) -> None:
        # Primeira metade: sem erro. Segunda metade: todos com erro
        records = [
            make_c100(line=10, dt_doc="01012024"),
            c170(cst="000", cfop="5102", cod_item="A", line=11),
            make_c100(line=20, dt_doc="05012024"),
            c170(cst="000", cfop="5102", cod_item="B", line=21),
            make_c100(line=30, dt_doc="10012024"),
            c170(cst="000", cfop="5102", cod_item="C", line=31),
            # Mudanca de parametrizacao em 15/01
            make_c100(line=40, dt_doc="15012024"),
            c170(cst="040", cfop="5102", cod_item="D", line=41),
            make_c100(line=50, dt_doc="20012024"),
            c170(cst="040", cfop="5102", cod_item="E", line=51),
            make_c100(line=60, dt_doc="25012024"),
            c170(cst="040", cfop="5102", cod_item="F", line=61),
        ]
        groups = group_by_register(records)
        ctx = ValidationContext(file_id=1, periodo_ini=date(2024, 1, 1), periodo_fim=date(2024, 1, 31))
        errors = _check_param_003(groups, ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "PARAM_ERRO_INICIADO_EM_DATA"

    def test_erro_distribuido_uniformemente_nao_aplica(self) -> None:
        # Erros distribuidos em ambas metades
        records = [
            make_c100(line=10, dt_doc="01012024"),
            c170(cst="040", cfop="5102", cod_item="A", line=11),
            make_c100(line=20, dt_doc="05012024"),
            c170(cst="040", cfop="5102", cod_item="B", line=21),
            make_c100(line=30, dt_doc="15012024"),
            c170(cst="040", cfop="5102", cod_item="C", line=31),
            make_c100(line=40, dt_doc="20012024"),
            c170(cst="040", cfop="5102", cod_item="D", line=41),
        ]
        groups = group_by_register(records)
        ctx = ValidationContext(file_id=1, periodo_ini=date(2024, 1, 1), periodo_fim=date(2024, 1, 31))
        errors = _check_param_003(groups, ctx)
        assert errors == []

    def test_sem_contexto_nao_aplica(self) -> None:
        records = [
            make_c100(line=10, dt_doc="01012024"),
            c170(cst="040", cfop="5102", cod_item="A", line=11),
        ]
        groups = group_by_register(records)
        assert _check_param_003(groups, None) == []

    def test_poucos_registros_nao_aplica(self) -> None:
        records = [
            make_c100(line=10, dt_doc="01012024"),
            c170(cst="040", cfop="5102", cod_item="A", line=11),
        ]
        groups = group_by_register(records)
        ctx = ValidationContext(file_id=1, periodo_ini=date(2024, 1, 1), periodo_fim=date(2024, 1, 31))
        assert _check_param_003(groups, ctx) == []


# ──────────────────────────────────────────────
# Integracao
# ──────────────────────────────────────────────

class TestValidateParametrizacao:
    def test_empty(self) -> None:
        assert validate_parametrizacao([]) == []

    def test_detecta_erro_sistematico_item(self) -> None:
        records = [
            c170(cst="040", cfop="5102", cod_item="X", line=1),
            c170(cst="040", cfop="5102", cod_item="X", line=2),
            c170(cst="040", cfop="5102", cod_item="X", line=3),
            c170(cst="040", cfop="5102", cod_item="X", line=4),
        ]
        errors = validate_parametrizacao(records)
        types = {e.error_type for e in errors}
        assert "PARAM_ERRO_SISTEMATICO_ITEM" in types
