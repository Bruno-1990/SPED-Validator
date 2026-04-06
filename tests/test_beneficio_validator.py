"""Testes do validador de beneficios fiscais (BENE_001 a BENE_003)."""

from __future__ import annotations

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.beneficio_validator import (
    _check_base_beneficio_nao_elegivel,
    _check_beneficio_contaminando_aliquota,
    _check_beneficio_contaminando_difal,
    validate_beneficio,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(
        line_number=line, register=register,
        fields=fields_to_dict(register, fields), raw_line=raw,
    )


def e111_beneficio(
    cod_aj: str = "SP020099",
    descr: str = "Credito presumido beneficio fiscal",
    valor: str = "5000,00",
    line: int = 100,
) -> SpedRecord:
    """E111 com ajuste de beneficio fiscal."""
    return rec("E111", ["E111", cod_aj, descr, valor], line=line)


def e111_normal(
    cod_aj: str = "SP000001",
    descr: str = "Outros debitos",
    valor: str = "1000,00",
    line: int = 101,
) -> SpedRecord:
    """E111 sem beneficio."""
    return rec("E111", ["E111", cod_aj, descr, valor], line=line)


def c190(
    cst: str = "000",
    cfop: str = "5101",
    aliq: str = "18,00",
    vl_opr: str = "10000,00",
    vl_bc: str = "10000,00",
    vl_icms: str = "1800,00",
    line: int = 50,
) -> SpedRecord:
    return rec("C190", [
        "C190", cst, cfop, aliq, vl_opr, vl_bc, vl_icms,
        "0", "0", "0", "0", "",
    ], line=line)


def c170(
    cst: str = "000",
    cfop: str = "5101",
    aliq: str = "18,00",
    vl_item: str = "1000,00",
    vl_icms: str = "180,00",
    line: int = 30,
) -> SpedRecord:
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN", vl_item,
        "0", "0", cst, cfop, "001",
        "1000,00", aliq, vl_icms,
    ]
    return rec("C170", fields, line=line)


def reg0000(uf: str = "SP") -> SpedRecord:
    return rec("0000", [
        "0000", "017", "0", "01012024", "31012024", "Empresa",
        "12345678000195", "", uf, "123456789", "3550308", "", "", "A", "0",
    ])


# ──────────────────────────────────────────────
# BENE_001: Beneficio contaminando aliquota
# ──────────────────────────────────────────────

class TestBene001ContaminandoAliquota:
    def test_aliq_atipica_com_beneficio(self) -> None:
        """C190 interno com aliquota < 17% + E111 beneficio -> erro."""
        records = [
            reg0000(),
            c190(cst="000", cfop="5101", aliq="12,00"),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_aliquota(groups, e111_ben)
        assert len(errors) == 1
        assert errors[0].error_type == "BENEFICIO_CONTAMINANDO_ALIQUOTA"

    def test_aliq_normal_ok(self) -> None:
        """C190 com aliquota >= 17% nao dispara."""
        records = [
            reg0000(),
            c190(cst="000", cfop="5101", aliq="18,00"),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_aliquota(groups, e111_ben)
        assert errors == []

    def test_interestadual_aliq_baixa_ok(self) -> None:
        """C190 interestadual com aliquota 12% e normal."""
        records = [
            reg0000(),
            c190(cst="000", cfop="6101", aliq="12,00"),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_aliquota(groups, e111_ben)
        assert errors == []

    def test_sem_cst_tributado_ok(self) -> None:
        """C190 com CST isento nao dispara."""
        records = [
            reg0000(),
            c190(cst="040", cfop="5101", aliq="0"),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_aliquota(groups, e111_ben)
        assert errors == []


# ─────────────────────────��────────────────────
# BENE_002: Beneficio contaminando DIFAL
# ───────────────���───────────────────────────���──

class TestBene002ContaminandoDifal:
    def test_aliq_interestadual_muito_baixa(self) -> None:
        """C170 interestadual com aliquota < 4% + E111 beneficio -> erro."""
        records = [
            c170(cst="000", cfop="6101", aliq="2,00"),
            rec("E300", ["E300", "MG", "01012024", "31012024"], line=200),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_difal(groups, e111_ben)
        assert len(errors) == 1
        assert errors[0].error_type == "BENEFICIO_CONTAMINANDO_DIFAL"

    def test_aliq_interestadual_normal_ok(self) -> None:
        """C170 com aliquota 7% nao dispara."""
        records = [
            c170(cst="000", cfop="6101", aliq="7,00"),
            rec("E300", ["E300", "MG", "01012024", "31012024"], line=200),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_difal(groups, e111_ben)
        assert errors == []

    def test_interno_aliq_baixa_ok(self) -> None:
        """C170 interno (5xxx) nao e verificado."""
        records = [
            c170(cst="000", cfop="5101", aliq="2,00"),
            rec("E300", ["E300", "MG", "01012024", "31012024"], line=200),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_beneficio_contaminando_difal(groups, e111_ben)
        assert errors == []


# ��──────────────────────���──────────────────────
# BENE_003: Base do beneficio com operacoes nao elegiveis
# ──────────────────────────────────────────────

class TestBene003BaseNaoElegivel:
    def test_devolucao_significativa_erro(self) -> None:
        """C190 com >5% em devolucoes + E111 beneficio -> erro."""
        records = [
            c190(cfop="5101", vl_opr="90000,00", line=50),
            c190(cfop="1201", vl_opr="10000,00", line=51),  # devolucao = 10%
            e111_beneficio(valor="5000,00"),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio(valor="5000,00")]
        errors = _check_base_beneficio_nao_elegivel(groups, e111_ben)
        assert len(errors) == 1
        assert errors[0].error_type == "BENEFICIO_BASE_NAO_ELEGIVEL"

    def test_devolucao_minima_ok(self) -> None:
        """C190 com <5% em devolucoes nao dispara."""
        records = [
            c190(cfop="5101", vl_opr="98000,00", line=50),
            c190(cfop="1201", vl_opr="2000,00", line=51),  # 2%
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_base_beneficio_nao_elegivel(groups, e111_ben)
        assert errors == []

    def test_sem_devolucao_ok(self) -> None:
        """Sem CFOPs de devolucao nao dispara."""
        records = [
            c190(cfop="5101", vl_opr="100000,00"),
            e111_beneficio(),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio()]
        errors = _check_base_beneficio_nao_elegivel(groups, e111_ben)
        assert errors == []

    def test_beneficio_zero_ok(self) -> None:
        """Beneficio com valor zero nao dispara."""
        records = [
            c190(cfop="5101", vl_opr="90000,00"),
            c190(cfop="1201", vl_opr="10000,00"),
            e111_beneficio(valor="0"),
        ]
        groups = group_by_register(records)
        e111_ben = [e111_beneficio(valor="0")]
        errors = _check_base_beneficio_nao_elegivel(groups, e111_ben)
        assert errors == []


# ────────────��─────────────────────────────────
# Integracao: validate_beneficio
# ──────���───────────────────────────────────────

class TestValidateBeneficioIntegracao:
    def test_sem_e111_beneficio_retorna_vazio(self) -> None:
        """Sem E111 de beneficio, nenhuma regra e executada."""
        records = [
            reg0000(),
            c190(cfop="5101", aliq="12,00"),
            e111_normal(),
        ]
        assert validate_beneficio(records) == []

    def test_detecta_bene001(self) -> None:
        records = [
            reg0000(),
            c190(cst="000", cfop="5101", aliq="12,00"),
            e111_beneficio(),
        ]
        errors = validate_beneficio(records)
        assert any(e.error_type == "BENEFICIO_CONTAMINANDO_ALIQUOTA" for e in errors)

    def test_vazio(self) -> None:
        assert validate_beneficio([]) == []
