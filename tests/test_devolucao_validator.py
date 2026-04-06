"""Testes do validador de devolucoes (DEV_001 a DEV_003)."""

from __future__ import annotations

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.devolucao_validator import (
    _check_devolucao_aliq_historica,
    _check_devolucao_sem_difal,
    _check_devolucao_sem_espelhamento,
    validate_devolucao,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(
        line_number=line, register=register,
        fields=fields_to_dict(register, fields), raw_line=raw,
    )


def c100(
    ind_oper: str = "1",
    cod_part: str = "FORN001",
    line: int = 10,
) -> SpedRecord:
    """C100 com campos configuraveis."""
    return rec("C100", [
        "C100", ind_oper, "0", cod_part, "55", "00", "1", "1234",
        "12345678901234567890123456789012345678901234", "01012024",
        "01012024", "1000,00", "0", "0", "0", "1000,00", "0",
        "0", "0", "0", "1000,00", "180,00",
        "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


def c170(
    cst: str = "000",
    cfop: str = "5101",
    aliq: str = "18,00",
    cod_item: str = "PROD001",
    line: int = 20,
) -> SpedRecord:
    fields = [
        "C170", "1", cod_item, "Desc", "100", "UN", "1000,00",
        "0", "0", cst, cfop, "001",
        "1000,00", aliq, "180,00",
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# DEV_001: Devolucao sem espelhamento da NF original
# ──────────────────────────────────────────────

class TestDev001SemEspelhamento:
    def test_devolucao_sem_original_erro(self) -> None:
        """Devolucao (saida) sem NF de entrada correspondente."""
        records = [
            c100(ind_oper="1", cod_part="FORN001", line=10),
            c170(cfop="5201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_espelhamento(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "DEVOLUCAO_SEM_ESPELHAMENTO"

    def test_devolucao_com_original_ok(self) -> None:
        """Devolucao (saida) com NF de entrada do mesmo participante."""
        records = [
            c100(ind_oper="0", cod_part="FORN001", line=5),  # entrada original
            c170(cfop="5101", line=6),
            c100(ind_oper="1", cod_part="FORN001", line=10),  # devolucao
            c170(cfop="5201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_espelhamento(groups)
        assert errors == []

    def test_devolucao_entrada_sem_saida_erro(self) -> None:
        """Devolucao de entrada (1201) sem NF de saida."""
        records = [
            c100(ind_oper="0", cod_part="CLI001", line=10),
            c170(cfop="1201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_espelhamento(groups)
        assert len(errors) == 1

    def test_devolucao_entrada_com_saida_ok(self) -> None:
        """Devolucao de entrada (1201) com NF de saida correspondente."""
        records = [
            c100(ind_oper="1", cod_part="CLI001", line=5),  # saida original
            c170(cfop="5101", line=6),
            c100(ind_oper="0", cod_part="CLI001", line=10),  # devolucao
            c170(cfop="1201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_espelhamento(groups)
        assert errors == []

    def test_sem_c170_devolucao_ok(self) -> None:
        """Sem CFOP de devolucao, nenhum erro."""
        records = [
            c100(ind_oper="1", cod_part="CLI001", line=10),
            c170(cfop="5101", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_espelhamento(groups)
        assert errors == []

    def test_sem_c100_ok(self) -> None:
        """Sem C100 nao gera erro."""
        groups = group_by_register([])
        errors = _check_devolucao_sem_espelhamento(groups)
        assert errors == []


# ──────────────────────────────────────────────
# DEV_002: Devolucao sem tratamento do DIFAL
# ──────────────────────────────────────────────

class TestDev002SemDifal:
    def test_devolucao_interestadual_sem_e300(self) -> None:
        """Devolucao interestadual sem E300 -> erro."""
        records = [
            c100(ind_oper="0", cod_part="FORN001", line=10),
            c170(cfop="2201", line=11),  # devolucao interestadual
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_difal(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "DEVOLUCAO_SEM_DIFAL"

    def test_devolucao_interna_sem_e300_ok(self) -> None:
        """Devolucao interna (1201) nao requer DIFAL."""
        records = [
            c100(ind_oper="0", cod_part="FORN001", line=10),
            c170(cfop="1201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_difal(groups)
        assert errors == []

    def test_sem_devolucao_ok(self) -> None:
        """Sem devolucao interestadual nao gera erro."""
        records = [
            c100(ind_oper="1", cod_part="CLI001", line=10),
            c170(cfop="5101", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_difal(groups)
        assert errors == []

    def test_devolucao_interestadual_saida_sem_e300(self) -> None:
        """Devolucao interestadual de saida (6201) sem E300 -> erro."""
        records = [
            c100(ind_oper="1", cod_part="FORN001", line=10),
            c170(cfop="6201", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_sem_difal(groups)
        assert len(errors) == 1


# ──────────────────────────────────────────────
# DEV_003: Devolucao com aliquota divergente
# ──────────────────────────────────────────────

class TestDev003AliqHistorica:
    def test_devolucao_inter_aliq_atipica(self) -> None:
        """Devolucao interestadual com aliquota 18% (nao e 4/7/12)."""
        records = [
            c170(cst="000", cfop="6201", aliq="18,00", line=11),
        ]
        groups = group_by_register(records)
        errors = _check_devolucao_aliq_historica(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "DEVOLUCAO_ALIQ_DIVERGENTE"

    def test_devolucao_inter_aliq_4_ok(self) -> None:
        records = [c170(cst="000", cfop="6201", aliq="4,00")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []

    def test_devolucao_inter_aliq_7_ok(self) -> None:
        records = [c170(cst="000", cfop="6201", aliq="7,00")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []

    def test_devolucao_inter_aliq_12_ok(self) -> None:
        records = [c170(cst="000", cfop="6201", aliq="12,00")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []

    def test_devolucao_inter_aliq_zero_ok(self) -> None:
        """Aliquota zero nao dispara (item isento)."""
        records = [c170(cst="000", cfop="6201", aliq="0")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []

    def test_devolucao_interna_aliq_atipica_ok(self) -> None:
        """Devolucao interna (1201) nao e verificada."""
        records = [c170(cst="000", cfop="1201", aliq="18,00")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []

    def test_cst_isento_ok(self) -> None:
        """CST isento nao dispara (nao e tributado)."""
        records = [c170(cst="040", cfop="6201", aliq="18,00")]
        groups = group_by_register(records)
        assert _check_devolucao_aliq_historica(groups) == []


# ──────────────────────────────────────────────
# Integracao: validate_devolucao
# ──────────────────────────────────────────────

class TestValidateDevolucaoIntegracao:
    def test_vazio(self) -> None:
        assert validate_devolucao([]) == []

    def test_detecta_dev001(self) -> None:
        records = [
            c100(ind_oper="1", cod_part="FORN001", line=10),
            c170(cfop="5201", line=11),
        ]
        errors = validate_devolucao(records)
        assert any(e.error_type == "DEVOLUCAO_SEM_ESPELHAMENTO" for e in errors)

    def test_detecta_dev003(self) -> None:
        records = [c170(cst="000", cfop="6201", aliq="18,00")]
        errors = validate_devolucao(records)
        assert any(e.error_type == "DEVOLUCAO_ALIQ_DIVERGENTE" for e in errors)

    def test_sem_devolucao_ok(self) -> None:
        records = [
            c100(ind_oper="1", cod_part="CLI001", line=10),
            c170(cfop="5101", line=11),
        ]
        errors = validate_devolucao(records)
        assert errors == []
