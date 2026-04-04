"""Testes do recálculo tributário (ICMS, ICMS-ST, IPI, PIS/COFINS, totalização E110)."""

from __future__ import annotations

import pytest

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.tax_recalc import (
    E110Totals,
    recalc_e110_totals,
    recalc_icms_item,
    recalc_icms_st_item,
    recalc_ipi_item,
    recalc_pis_cofins_item,
    recalculate_taxes,
)


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields, raw_line=raw)


def c170(
    vl_item: str = "1000,00", vl_desc: str = "0",
    vl_bc: str = "1000,00", aliq: str = "18,00", vl_icms: str = "180,00",
    cst: str = "000", cfop: str = "5101",
    vl_bc_st: str = "", aliq_st: str = "", vl_icms_st: str = "",
    vl_bc_ipi: str = "", aliq_ipi: str = "", vl_ipi: str = "",
    vl_bc_pis: str = "", aliq_pis: str = "", vl_pis: str = "",
    vl_bc_cofins: str = "", aliq_cofins: str = "", vl_cofins: str = "",
    line: int = 1,
) -> SpedRecord:
    """Constrói um C170 com campos nas posições do layout oficial.

    Posições 0-based:
    0:REG, 1:NUM_ITEM, 2:COD_ITEM, 3:DESCR_COMPL, 4:QTD, 5:UNID,
    6:VL_ITEM, 7:VL_DESC, 8:IND_MOV, 9:CST_ICMS, 10:CFOP, 11:COD_NAT,
    12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS,
    15:VL_BC_ICMS_ST, 16:ALIQ_ST, 17:VL_ICMS_ST,
    18:IND_APUR, 19:CST_IPI, 20:COD_ENQ,
    21:VL_BC_IPI, 22:ALIQ_IPI, 23:VL_IPI,
    24:CST_PIS, 25:VL_BC_PIS, 26:ALIQ_PIS_PERC, 27:QUANT_BC_PIS, 28:ALIQ_PIS_R, 29:VL_PIS,
    30:CST_COFINS, 31:VL_BC_COFINS, 32:ALIQ_COFINS_PERC, 33:QUANT_BC_COFINS, 34:ALIQ_COFINS_R, 35:VL_COFINS
    """
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN",       # 0-5
        vl_item, vl_desc, "0", cst, cfop, "001",            # 6-11
        vl_bc, aliq, vl_icms,                                # 12-14
        vl_bc_st, aliq_st, vl_icms_st,                      # 15-17
        "", "", "",                                           # 18-20: IND_APUR, CST_IPI, COD_ENQ
        vl_bc_ipi, aliq_ipi, vl_ipi,                        # 21-23
        "", vl_bc_pis, aliq_pis, "", "", vl_pis,             # 24-29
        "", vl_bc_cofins, aliq_cofins, "", "", vl_cofins,    # 30-35
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# ICMS
# ──────────────────────────────────────────────

class TestRecalcIcmsItem:
    def test_icms_correct(self) -> None:
        r = c170(vl_bc="1000,00", aliq="18,00", vl_icms="180,00")
        assert recalc_icms_item(r) == []

    def test_icms_divergent(self) -> None:
        r = c170(vl_bc="1000,00", aliq="18,00", vl_icms="999,99")
        errors = recalc_icms_item(r)
        assert any(e.field_name == "VL_ICMS" for e in errors)

    def test_bc_divergent(self) -> None:
        # VL_ITEM=1000, VL_DESC=100 -> BC deveria ser 900, mas declarado 1000
        r = c170(vl_item="1000,00", vl_desc="100,00", vl_bc="1000,00",
                 aliq="18,00", vl_icms="180,00")
        errors = recalc_icms_item(r)
        assert any(e.field_name == "VL_BC_ICMS" for e in errors)

    def test_within_tolerance(self) -> None:
        # 1000 * 18% = 180.00, declarado 180.01 -> OK
        r = c170(vl_bc="1000,00", aliq="18,00", vl_icms="180,01")
        assert recalc_icms_item(r) == []

    def test_non_taxed_skipped(self) -> None:
        r = c170(vl_bc="0", aliq="0", vl_icms="0")
        assert recalc_icms_item(r) == []

    def test_missing_fields_skipped(self) -> None:
        r = c170(vl_bc="", aliq="", vl_icms="")
        assert recalc_icms_item(r) == []

    def test_small_values(self) -> None:
        r = c170(vl_item="10,00", vl_desc="0", vl_bc="10,00",
                 aliq="12,00", vl_icms="1,20")
        assert recalc_icms_item(r) == []

    def test_bc_calc_skipped_when_zero(self) -> None:
        """Se VL_ITEM - VL_DESC = 0, não verifica BC."""
        r = c170(vl_item="100,00", vl_desc="100,00", vl_bc="100,00",
                 aliq="18,00", vl_icms="18,00")
        errors = recalc_icms_item(r)
        # bc_calc = 0, não compara com vl_bc
        assert not any(e.field_name == "VL_BC_ICMS" for e in errors)


# ──────────────────────────────────────────────
# ICMS-ST
# ──────────────────────────────────────────────

class TestRecalcIcmsStItem:
    def test_non_st_skipped(self) -> None:
        r = c170(cst="000")
        assert recalc_icms_st_item(r) == []

    def test_st_with_bc_but_no_icms(self) -> None:
        r = c170(cst="10", vl_bc_st="500,00", vl_icms_st="0")
        errors = recalc_icms_st_item(r)
        assert any(e.field_name == "VL_ICMS_ST" for e in errors)

    def test_st_calc_divergent(self) -> None:
        # BC_ST=500, ALIQ_ST=18% -> ST=90, mas declarado 50
        r = c170(cst="30", vl_bc_st="500,00", aliq_st="18,00", vl_icms_st="50,00")
        errors = recalc_icms_st_item(r)
        assert any(e.field_name == "VL_ICMS_ST" for e in errors)

    def test_st_calc_correct(self) -> None:
        r = c170(cst="10", vl_bc_st="500,00", aliq_st="18,00", vl_icms_st="90,00")
        assert recalc_icms_st_item(r) == []

    def test_st_missing_fields_skipped(self) -> None:
        r = c170(cst="60", vl_bc_st="", vl_icms_st="")
        assert recalc_icms_st_item(r) == []

    def test_cst_201_is_st(self) -> None:
        r = c170(cst="201", vl_bc_st="100,00", vl_icms_st="0")
        errors = recalc_icms_st_item(r)
        assert len(errors) > 0

    def test_cst_500_is_st(self) -> None:
        r = c170(cst="500", vl_bc_st="100,00", vl_icms_st="0")
        errors = recalc_icms_st_item(r)
        assert len(errors) > 0


# ──────────────────────────────────────────────
# IPI
# ──────────────────────────────────────────────

class TestRecalcIpiItem:
    def test_ipi_correct(self) -> None:
        r = c170(vl_bc_ipi="1000,00", aliq_ipi="10,00", vl_ipi="100,00")
        assert recalc_ipi_item(r) == []

    def test_ipi_divergent(self) -> None:
        r = c170(vl_bc_ipi="1000,00", aliq_ipi="10,00", vl_ipi="50,00")
        errors = recalc_ipi_item(r)
        assert any(e.field_name == "VL_IPI" for e in errors)

    def test_ipi_non_taxed_skipped(self) -> None:
        r = c170(vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        assert recalc_ipi_item(r) == []

    def test_ipi_missing_skipped(self) -> None:
        r = c170(vl_bc_ipi="", aliq_ipi="", vl_ipi="")
        assert recalc_ipi_item(r) == []

    def test_ipi_within_tolerance(self) -> None:
        r = c170(vl_bc_ipi="100,00", aliq_ipi="5,00", vl_ipi="5,01")
        assert recalc_ipi_item(r) == []


# ──────────────────────────────────────────────
# PIS/COFINS
# ──────────────────────────────────────────────

class TestRecalcPisCofinsItem:
    def test_pis_correct(self) -> None:
        r = c170(vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50")
        assert recalc_pis_cofins_item(r) == []

    def test_pis_divergent(self) -> None:
        r = c170(vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="99,00")
        errors = recalc_pis_cofins_item(r)
        assert any(e.field_name == "VL_PIS" for e in errors)

    def test_cofins_correct(self) -> None:
        r = c170(vl_bc_cofins="1000,00", aliq_cofins="7,60", vl_cofins="76,00")
        assert recalc_pis_cofins_item(r) == []

    def test_cofins_divergent(self) -> None:
        r = c170(vl_bc_cofins="1000,00", aliq_cofins="7,60", vl_cofins="99,00")
        errors = recalc_pis_cofins_item(r)
        assert any(e.field_name == "VL_COFINS" for e in errors)

    def test_pis_missing_skipped(self) -> None:
        r = c170(vl_bc_pis="", aliq_pis="", vl_pis="")
        assert recalc_pis_cofins_item(r) == []

    def test_cofins_missing_skipped(self) -> None:
        r = c170(vl_bc_cofins="", aliq_cofins="", vl_cofins="")
        assert recalc_pis_cofins_item(r) == []

    def test_pis_zero_skipped(self) -> None:
        r = c170(vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        assert recalc_pis_cofins_item(r) == []

    def test_both_pis_and_cofins_errors(self) -> None:
        r = c170(
            vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="99,00",
            vl_bc_cofins="1000,00", aliq_cofins="7,60", vl_cofins="99,00",
        )
        errors = recalc_pis_cofins_item(r)
        assert any(e.field_name == "VL_PIS" for e in errors)
        assert any(e.field_name == "VL_COFINS" for e in errors)


# ──────────────────────────────────────────────
# E110Totals
# ──────────────────────────────────────────────

class TestE110Totals:
    def test_totals(self) -> None:
        t = E110Totals(debitos_c190=300, creditos_c190=100, debitos_d=60, creditos_d=40)
        assert t.total_debitos == 360
        assert t.total_creditos == 140

    def test_defaults(self) -> None:
        t = E110Totals()
        assert t.total_debitos == 0.0
        assert t.total_creditos == 0.0


# ──────────────────────────────────────────────
# Totalização E110
# ──────────────────────────────────────────────

class TestRecalcE110Totals:
    def test_correct_totals(self) -> None:
        records = [
            rec("C190", ["C190", "000", "5102", "18,00", "1000,00", "1000,00", "180,00"], line=1),
            rec("C190", ["C190", "000", "5102", "18,00", "1000,00", "1000,00", "180,00"], line=2),
            rec("C190", ["C190", "000", "1019", "18,00", "500,00", "500,00", "90,00"], line=3),
            rec("E110", ["E110", "360,00", "0", "0", "0", "90,00"], line=4),
        ]
        groups = group_by_register(records)
        errors = recalc_e110_totals(groups)
        assert len(errors) == 0

    def test_debitos_divergent(self) -> None:
        records = [
            rec("C190", ["C190", "000", "5102", "18,00", "1000,00", "1000,00", "180,00"], line=1),
            rec("E110", ["E110", "999,00", "0", "0", "0", "0"], line=2),
        ]
        groups = group_by_register(records)
        errors = recalc_e110_totals(groups)
        assert any("VL_TOT_DEBITOS" in e.field_name for e in errors)

    def test_creditos_divergent(self) -> None:
        records = [
            rec("C190", ["C190", "000", "1019", "18,00", "500,00", "500,00", "90,00"], line=1),
            rec("E110", ["E110", "0", "0", "0", "0", "999,00"], line=2),
        ]
        groups = group_by_register(records)
        errors = recalc_e110_totals(groups)
        assert any("VL_TOT_CREDITOS" in e.field_name for e in errors)

    def test_no_e110_no_errors(self) -> None:
        records = [rec("C190", ["C190", "000", "5102", "18", "1000", "1000", "180"])]
        groups = group_by_register(records)
        assert recalc_e110_totals(groups) == []

    def test_with_d690(self) -> None:
        """Inclui D690 nos totais."""
        records = [
            rec("C190", ["C190", "000", "5102", "18,00", "1000,00", "1000,00", "100,00"], line=1),
            rec("D690", ["D690", "000", "5352", "0", "50,00"], line=2),
            rec("E110", ["E110", "150,00", "0", "0", "0", "0"], line=3),
        ]
        groups = group_by_register(records)
        errors = recalc_e110_totals(groups)
        assert len(errors) == 0


# ──────────────────────────────────────────────
# recalculate_taxes (integração)
# ──────────────────────────────────────────────

class TestRecalculateTaxes:
    def test_valid_file(self, valid_records: list[SpedRecord]) -> None:
        errors = recalculate_taxes(valid_records)
        assert isinstance(errors, list)

    def test_empty(self) -> None:
        assert recalculate_taxes([]) == []

    def test_detects_icms_error(self) -> None:
        records = [
            c170(vl_bc="1000,00", aliq="18,00", vl_icms="999,99", line=1),
        ]
        errors = recalculate_taxes(records)
        assert any(e.field_name == "VL_ICMS" for e in errors)
