"""Testes do validador de consolidacao C190 (c190_validator.py).

Testes focados no agrupamento correto por (CST_ICMS, CFOP, ALIQ_ICMS)
conforme Guia Pratico EFD v3.2.2.
"""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.c190_validator import validate_c190
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def _make_c100(line: int = 1, vl_doc: str = "1500,00", vl_merc: str = "1500,00") -> SpedRecord:
    """Cria C100 minimo com campos posicionais corretos.

    C100: 0:REG, 1:IND_OPER, 2:IND_EMIT, 3:COD_PART, 4:COD_MOD, 5:COD_SIT,
    6:SER, 7:NUM_DOC, 8:CHV_NFE, 9:DT_DOC, 10:DT_E_S, 11:VL_DOC,
    12:IND_PGTO, 13:VL_DESC, 14:VL_ABAT_NT, 15:VL_MERC, 16:IND_FRT,
    17:VL_FRT, 18:VL_SEG, 19:VL_OUT_DA, 20:VL_BC_ICMS, 21:VL_ICMS,
    22:VL_BC_ICMS_ST, 23:VL_ICMS_ST, 24:VL_IPI
    """
    return rec("C100", [
        "C100", "1", "0", "FORN", "55", "00", "001", "123", "",
        "10012024", "10012024", vl_doc, "0", "0", "0", vl_merc,
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


class TestC190TwoCSTs:
    """Documento com CST 00 + CST 40 no mesmo CFOP → dois C190 validados separadamente."""

    def test_two_csts_same_cfop_no_errors(self) -> None:
        c100 = _make_c100(line=1, vl_doc="1500,00", vl_merc="1500,00")
        c170_cst00 = rec("C170", [
            "C170", "1", "P1", "D", "10", "UN", "1000,00",
            "0", "0", "00", "5102", "001", "1000,00", "18", "180,00",
            "0", "0", "0", "0", "0", "0", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ], line=2)
        c170_cst40 = rec("C170", [
            "C170", "2", "P2", "D", "5", "UN", "500,00",
            "0", "0", "40", "5102", "001", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ], line=3)
        # C190 para CST=00 CFOP=5102 ALIQ=18
        c190_cst00 = rec("C190", [
            "C190", "00", "5102", "18,00", "1000,00", "1000,00", "180,00",
            "0", "0", "0", "0",
        ], line=4)
        # C190 para CST=40 CFOP=5102 ALIQ=0
        c190_cst40 = rec("C190", [
            "C190", "40", "5102", "0", "500,00", "0", "0",
            "0", "0", "0", "0",
        ], line=5)

        records = [c100, c170_cst00, c170_cst40, c190_cst00, c190_cst40]
        errors = validate_c190(records)

        # Nenhum erro de divergencia C190_DIVERGE_C170
        diverge_errors = [e for e in errors if e.error_type == "C190_DIVERGE_C170"]
        assert len(diverge_errors) == 0, \
            f"Nao deveria ter divergencia com agrupamento correto: {diverge_errors}"


class TestC190Cst40Aliq0:
    """C190 com CST 40 (isento) e ALIQ 0 → aceito sem erro."""

    def test_cst40_aliq0_accepted(self) -> None:
        c100 = _make_c100(line=1, vl_doc="800,00", vl_merc="800,00")
        c170 = rec("C170", [
            "C170", "1", "P1", "D", "10", "UN", "800,00",
            "0", "0", "40", "5102", "001", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ], line=2)
        c190 = rec("C190", [
            "C190", "40", "5102", "0", "800,00", "0", "0",
            "0", "0", "0", "0",
        ], line=3)

        records = [c100, c170, c190]
        errors = validate_c190(records)

        diverge_errors = [e for e in errors if e.error_type == "C190_DIVERGE_C170"]
        assert len(diverge_errors) == 0, \
            f"CST 40 com ALIQ 0 deveria ser aceito: {diverge_errors}"


class TestC190WrongSumByCstCfopAliq:
    """C190 com soma errada por CFOP+CST+ALIQ → erro detectado."""

    def test_wrong_sum_detected(self) -> None:
        c100 = _make_c100(line=1, vl_doc="1500,00", vl_merc="1500,00")
        c170_1 = rec("C170", [
            "C170", "1", "P1", "D", "10", "UN", "1000,00",
            "0", "0", "00", "5102", "001", "1000,00", "18", "180,00",
            "0", "0", "0", "0", "0", "0", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ], line=2)
        c170_2 = rec("C170", [
            "C170", "2", "P2", "D", "5", "UN", "500,00",
            "0", "0", "00", "5102", "001", "500,00", "18", "90,00",
            "0", "0", "0", "0", "0", "0", "0", "0", "0",
            "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
        ], line=3)
        # C190 declara VL_ICMS=180 mas soma C170 CST=00 CFOP=5102 ALIQ=18 é 270
        c190 = rec("C190", [
            "C190", "00", "5102", "18,00", "1500,00", "1500,00", "180,00",
            "0", "0", "0", "0",
        ], line=4)

        records = [c100, c170_1, c170_2, c190]
        errors = validate_c190(records)

        icms_errors = [e for e in errors
                       if e.error_type == "C190_DIVERGE_C170" and e.field_name == "VL_ICMS"]
        assert len(icms_errors) > 0, \
            f"Deveria detectar divergencia em VL_ICMS: {[e.error_type for e in errors]}"
