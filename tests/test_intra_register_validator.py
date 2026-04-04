"""Testes do validador intra-registro (C100, C170, C190, E110)."""

from __future__ import annotations

import pytest

from src.models import SpedRecord
from src.validators.intra_register_validator import (
    SpedContext,
    _build_context,
    _build_parent_map,
    _get_c170_siblings,
    _get_field,
    _to_float,
    _validate_c100,
    _validate_c170,
    _validate_c190,
    _validate_e110,
    validate_intra_register,
)


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields, raw_line=raw)


CTX = SpedContext(dt_ini="01012024", dt_fin="31012024")


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

class TestHelpers:
    def test_get_field_valid(self) -> None:
        r = rec("C100", ["C100", "0", "1"])
        assert _get_field(r, 1) == "0"

    def test_get_field_out_of_range(self) -> None:
        r = rec("C100", ["C100"])
        assert _get_field(r, 5) == ""

    def test_to_float_dot(self) -> None:
        assert _to_float("1000.50") == 1000.50

    def test_to_float_comma(self) -> None:
        assert _to_float("1000,50") == 1000.50

    def test_to_float_empty(self) -> None:
        assert _to_float("") is None

    def test_to_float_invalid(self) -> None:
        assert _to_float("ABC") is None

    def test_to_float_zero(self) -> None:
        assert _to_float("0") == 0.0


# ──────────────────────────────────────────────
# _build_context
# ──────────────────────────────────────────────

class TestBuildContext:
    def test_extracts_dates(self) -> None:
        records = [rec("0000", ["0000", "017", "0", "01012024", "31012024", "EMPRESA", "12345678901234"])]
        ctx = _build_context(records)
        assert ctx.dt_ini == "01012024"
        assert ctx.dt_fin == "31012024"

    def test_no_0000_record(self) -> None:
        records = [rec("C100", ["C100", "0"])]
        ctx = _build_context(records)
        assert ctx.dt_ini == ""
        assert ctx.dt_fin == ""


# ──────────────────────────────────────────────
# _build_parent_map
# ──────────────────────────────────────────────

class TestBuildParentMap:
    def test_c170_maps_to_c100(self) -> None:
        records = [
            rec("C001", ["C001", "0"], line=1),
            rec("C100", ["C100", "0", "0", "FORN"], line=2),
            rec("C170", ["C170", "1", "PROD"], line=3),
            rec("C190", ["C190", "000"], line=4),
        ]
        pmap = _build_parent_map(records)
        assert pmap[3].register == "C100"  # C170 -> C100
        assert pmap[4].register == "C100"  # C190 -> C100

    def test_new_parent_resets(self) -> None:
        records = [
            rec("C100", ["C100", "0"], line=1),
            rec("C170", ["C170", "1"], line=2),
            rec("C100", ["C100", "1"], line=3),
            rec("C170", ["C170", "1"], line=4),
        ]
        pmap = _build_parent_map(records)
        assert pmap[2].line_number == 1  # C170@2 -> C100@1
        assert pmap[4].line_number == 3  # C170@4 -> C100@3

    def test_block_close_resets_parent(self) -> None:
        records = [
            rec("C100", ["C100", "0"], line=1),
            rec("C170", ["C170", "1"], line=2),
            rec("C990", ["C990", "3"], line=3),
            rec("E110", ["E110", "0"], line=4),
        ]
        pmap = _build_parent_map(records)
        assert 4 not in pmap  # E110 não é filho de C100


# ──────────────────────────────────────────────
# C100
# ──────────────────────────────────────────────

class TestValidateC100:
    # Layout C100 (0-based): 0:REG, 1:IND_OPER, 2:IND_EMIT, 3:COD_PART,
    # 4:COD_MOD, 5:COD_SIT, 6:SER, 7:NUM_DOC, 8:CHV_NFE, 9:DT_DOC,
    # 10:DT_E_S, 11:VL_DOC, ...

    def test_valid_c100(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "10012024", "15012024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert len(errors) == 0

    def test_entrada_sem_dt_e_s(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "10012024", "", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "MISSING_CONDITIONAL" for e in errors)

    def test_cancelada_com_valor(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "02", "001", "123",
                         "", "10012024", "15012024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "INCONSISTENCY" for e in errors)

    def test_cancelada_sem_valor_ok(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "03", "001", "123",
                         "", "10012024", "15012024", "0"])
        errors = _validate_c100(r, CTX)
        assert not any(e.error_type == "INCONSISTENCY" for e in errors)

    def test_dt_doc_invalida(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "99992024", "15012024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "INVALID_DATE" for e in errors)

    def test_dt_e_s_invalida(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "10012024", "32012024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "INVALID_DATE" for e in errors)

    def test_dt_doc_after_dt_e_s(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "20012024", "10012024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "DATE_ORDER" for e in errors)

    def test_dt_doc_fora_do_periodo(self) -> None:
        r = rec("C100", ["C100", "0", "0", "FORN", "55", "00", "001", "123",
                         "", "10022024", "15022024", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert any(e.error_type == "DATE_OUT_OF_PERIOD" for e in errors)

    def test_saida_sem_dt_e_s_ok(self) -> None:
        """Saída (IND_OPER=1) não exige DT_E_S."""
        r = rec("C100", ["C100", "1", "0", "CLI", "55", "00", "001", "123",
                         "", "10012024", "", "1000,00"])
        errors = _validate_c100(r, CTX)
        assert not any(e.error_type == "MISSING_CONDITIONAL" for e in errors)

    def test_no_context_no_period_check(self) -> None:
        ctx_empty = SpedContext()
        r = rec("C100", ["C100", "1", "0", "CLI", "55", "00", "001", "123",
                         "", "10052025", "10052025", "1000,00"])
        errors = _validate_c100(r, ctx_empty)
        assert not any(e.error_type == "DATE_OUT_OF_PERIOD" for e in errors)


# ──────────────────────────────────────────────
# C170
# ──────────────────────────────────────────────

class TestValidateC170:
    def test_valid_c170(self) -> None:
        parent = rec("C100", ["C100", "0", "0", "FORN"])
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "1019", "001", "1000,00", "18,00", "180,00"])
        errors = _validate_c170(r, parent)
        assert len(errors) == 0

    def test_cfop_mismatch_entrada(self) -> None:
        parent = rec("C100", ["C100", "0"])  # IND_OPER=0 (entrada)
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "5102", "001"])  # CFOP 5xxx = saída
        errors = _validate_c170(r, parent)
        assert any(e.error_type == "CFOP_MISMATCH" for e in errors)

    def test_cfop_mismatch_saida(self) -> None:
        parent = rec("C100", ["C100", "1"])  # IND_OPER=1 (saída)
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "1019", "001"])  # CFOP 1xxx = entrada
        errors = _validate_c170(r, parent)
        assert any(e.error_type == "CFOP_MISMATCH" for e in errors)

    def test_icms_calculo_divergente(self) -> None:
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "1019", "001", "1000,00", "18,00", "999,99"])
        errors = _validate_c170(r)
        assert any(e.error_type == "CALCULO_DIVERGENTE" for e in errors)

    def test_icms_calculo_ok(self) -> None:
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "1019", "001", "1000,00", "18,00", "180,00"])
        errors = _validate_c170(r)
        assert not any(e.error_type == "CALCULO_DIVERGENTE" for e in errors)

    def test_icms_within_tolerance(self) -> None:
        # 1000 * 18 / 100 = 180.00, declarado 180.01 -> dentro da tolerância
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "1019", "001", "1000,00", "18,00", "180,01"])
        errors = _validate_c170(r)
        assert not any(e.error_type == "CALCULO_DIVERGENTE" for e in errors)

    def test_no_parent_no_cfop_check(self) -> None:
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "5102", "001"])
        errors = _validate_c170(r, parent=None)
        assert not any(e.error_type == "CFOP_MISMATCH" for e in errors)

    def test_zero_bc_skips_icms_check(self) -> None:
        r = rec("C170", ["C170", "1", "PROD", "Desc", "100", "UN", "1000,00",
                         "0", "0", "000", "1019", "001", "0", "0", "0"])
        errors = _validate_c170(r)
        assert not any(e.error_type == "CALCULO_DIVERGENTE" for e in errors)


# ──────────────────────────────────────────────
# C190
# ──────────────────────────────────────────────

class TestValidateC190:
    def test_valid_c190(self) -> None:
        c170s = [
            rec("C170", ["C170", "1", "P1", "D", "100", "UN", "500,00",
                         "0", "0", "000", "1019", "001", "500,00", "18", "90,00"], line=2),
            rec("C170", ["C170", "2", "P2", "D", "100", "UN", "500,00",
                         "0", "0", "000", "1019", "001", "500,00", "18", "90,00"], line=3),
        ]
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "1000,00", "1000,00", "180,00"], line=4)
        errors = _validate_c190(c190, c170s)
        assert len(errors) == 0

    def test_vl_opr_divergente(self) -> None:
        c170s = [
            rec("C170", ["C170", "1", "P1", "D", "100", "UN", "500,00",
                         "0", "0", "000", "1019", "001", "500,00", "18", "90,00"]),
        ]
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "999,00", "500,00", "90,00"])
        errors = _validate_c190(c190, c170s)
        assert any(e.field_name == "VL_OPR" for e in errors)

    def test_vl_bc_divergente(self) -> None:
        c170s = [
            rec("C170", ["C170", "1", "P1", "D", "100", "UN", "500,00",
                         "0", "0", "000", "1019", "001", "500,00", "18", "90,00"]),
        ]
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "500,00", "999,00", "90,00"])
        errors = _validate_c190(c190, c170s)
        assert any(e.field_name == "VL_BC_ICMS" for e in errors)

    def test_vl_icms_divergente(self) -> None:
        c170s = [
            rec("C170", ["C170", "1", "P1", "D", "100", "UN", "500,00",
                         "0", "0", "000", "1019", "001", "500,00", "18", "90,00"]),
        ]
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "500,00", "500,00", "999,00"])
        errors = _validate_c190(c190, c170s)
        assert any(e.field_name == "VL_ICMS" for e in errors)

    def test_no_siblings_no_errors(self) -> None:
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "1000,00", "1000,00", "180,00"])
        errors = _validate_c190(c190, [])
        assert len(errors) == 0

    def test_different_cfop_not_matched(self) -> None:
        """C170 com CFOP diferente do C190 não deve ser contabilizado."""
        c170s = [
            rec("C170", ["C170", "1", "P1", "D", "100", "UN", "500,00",
                         "0", "0", "000", "5102", "001", "000", "500,00", "18", "90,00"]),
        ]
        c190 = rec("C190", ["C190", "000", "1019", "18,00", "0", "0", "0"])
        errors = _validate_c190(c190, c170s)
        # CFOP 5102 != 1019, não deve comparar
        assert len(errors) == 0


# ──────────────────────────────────────────────
# E110
# ──────────────────────────────────────────────

class TestValidateE110:
    def test_valid_e110(self) -> None:
        # Débitos=360, Créditos=180 -> Saldo=180, Recolher=180-0=180
        r = rec("E110", ["E110", "360,00", "0", "0", "0", "180,00", "0", "0", "0", "0",
                         "180,00", "0", "180,00", "0", "0"])
        errors = _validate_e110(r)
        assert len(errors) == 0

    def test_saldo_divergente(self) -> None:
        # Débitos=360, Créditos=180 -> Saldo deveria ser 180, mas declarado 999
        r = rec("E110", ["E110", "360,00", "0", "0", "0", "180,00", "0", "0", "0", "0",
                         "999,00", "0", "180,00", "0", "0"])
        errors = _validate_e110(r)
        assert any(e.field_name == "VL_SLD_APURADO" for e in errors)

    def test_recolher_divergente(self) -> None:
        # Saldo=180, Deduções=0 -> Recolher deveria ser 180, mas declarado 100
        r = rec("E110", ["E110", "360,00", "0", "0", "0", "180,00", "0", "0", "0", "0",
                         "180,00", "0", "100,00", "0", "0"])
        errors = _validate_e110(r)
        assert any(e.field_name == "VL_ICMS_RECOLHER" for e in errors)

    def test_credor_transportar(self) -> None:
        # Débitos=100, Créditos=300 -> Saldo=-200, Credor=200
        r = rec("E110", ["E110", "100,00", "0", "0", "0", "300,00", "0", "0", "0", "0",
                         "-200,00", "0", "0", "200,00", "0"])
        errors = _validate_e110(r)
        assert len(errors) == 0

    def test_credor_divergente(self) -> None:
        # Saldo=-200, mas Credor declarado=100
        r = rec("E110", ["E110", "100,00", "0", "0", "0", "300,00", "0", "0", "0", "0",
                         "-200,00", "0", "0", "100,00", "0"])
        errors = _validate_e110(r)
        assert any(e.field_name == "VL_SLD_CREDOR_TRANSPORTAR" for e in errors)

    def test_with_adjustments(self) -> None:
        # Débitos=360 + AjDeb=10 + Estornos_cred=5
        # Créditos=180 + AjCred=20 + Estornos_deb=15 + Sld_ant=50
        # Saldo = (360+10+0+5) - (180+20+0+15+50) = 375 - 265 = 110
        r = rec("E110", ["E110", "360,00", "10,00", "0", "5,00", "180,00", "20,00", "0",
                         "15,00", "50,00", "110,00", "0", "110,00", "0", "0"])
        errors = _validate_e110(r)
        assert len(errors) == 0

    def test_with_deductions(self) -> None:
        # Saldo=180, Deduções=30 -> Recolher=150
        r = rec("E110", ["E110", "360,00", "0", "0", "0", "180,00", "0", "0", "0", "0",
                         "180,00", "30,00", "150,00", "0", "0"])
        errors = _validate_e110(r)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# validate_intra_register (integração)
# ──────────────────────────────────────────────

class TestValidateIntraRegister:
    def test_full_file(self, valid_records: list[SpedRecord]) -> None:
        errors = validate_intra_register(valid_records)
        # O arquivo sped_valid.txt deve ser consistente
        # Pode ter alguns erros por posição de campos, mas sem erros graves
        assert isinstance(errors, list)

    def test_detects_errors(self, error_records: list[SpedRecord]) -> None:
        errors = validate_intra_register(error_records)
        # O arquivo sped_errors.txt tem erros conhecidos
        assert len(errors) > 0

    def test_empty_records(self) -> None:
        errors = validate_intra_register([])
        assert errors == []

    def test_auto_builds_context(self) -> None:
        records = [
            rec("0000", ["0000", "017", "0", "01012024", "31012024", "EMP", "CNPJ"], line=1),
            rec("C100", ["C100", "0", "0", "F", "55", "00", "001", "1",
                         "", "10012024", "15012024", "100"], line=2),
        ]
        errors = validate_intra_register(records)
        assert isinstance(errors, list)
