"""Extended tests for src/validators/difal_validator.py — covering uncovered branches.

Targets: all 8 DIFAL rules, early exits, table loading, edge cases.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from src.models import SpedRecord
from src.services.reference_loader import ReferenceLoader
from src.validators.difal_validator import (
    _build_parent_map,
    _check_difal_001,
    _check_difal_002,
    _check_difal_003,
    _check_difal_004,
    _check_difal_005,
    _check_difal_006,
    _check_difal_007,
    _check_difal_008,
    validate_difal,
)

def _mock_loader() -> MagicMock:
    """Loader mockado com aliquotas para testes DIFAL."""
    loader = MagicMock(spec=ReferenceLoader)
    _aliq = {"SP": 18.0, "RJ": 20.0, "MG": 18.0, "BA": 20.5, "PR": 19.5}
    loader.get_aliquota_interna = lambda uf, dt=None: _aliq.get(uf.upper(), 0.0)
    loader.get_fcp = lambda uf, dt=None: 2.0 if uf.upper() == "RJ" else 0.0
    loader.get_matriz_aliquota = lambda o, d, dt=None: 12.0
    return loader

_LOADER = _mock_loader()

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_record(register: str, fields: dict[str, str], line_number: int = 1) -> SpedRecord:
    """Create a SpedRecord with named fields."""
    raw_parts = [register] + list(fields.values())
    raw_line = "|" + "|".join(raw_parts) + "|"
    return SpedRecord(
        line_number=line_number,
        register=register,
        fields={"REG": register, **fields},
        raw_line=raw_line,
    )


def _c170(
    cfop: str = "6107",
    cst_icms: str = "000",
    aliq_icms: str = "7.00",
    vl_item: str = "1000.00",
    vl_bc_icms: str = "1000.00",
    vl_icms: str = "70.00",
    line: int = 10,
) -> SpedRecord:
    return _make_record("C170", {
        "NUM_ITEM": "1",
        "COD_ITEM": "ITEM1",
        "DESCR_COMPL": "Descricao",
        "QTD": "10.00000",
        "UNID": "UN",
        "VL_ITEM": vl_item,
        "VL_DESC": "0.00",
        "IND_MOV": "0",
        "CST_ICMS": cst_icms,
        "CFOP": cfop,
        "COD_NAT": "001",
        "VL_BC_ICMS": vl_bc_icms,
        "ALIQ_ICMS": aliq_icms,
        "VL_ICMS": vl_icms,
    }, line_number=line)


def _c100(cod_part: str = "PART1", line: int = 5) -> SpedRecord:
    return _make_record("C100", {
        "IND_OPER": "1",
        "IND_EMIT": "0",
        "COD_PART": cod_part,
        "COD_MOD": "55",
        "COD_SIT": "00",
        "SER": "1",
        "NUM_DOC": "12345",
        "CHV_NFE": "",
        "DT_DOC": "01012024",
        "DT_E_S": "01012024",
        "VL_DOC": "1000.00",
    }, line_number=line)


def _r0000(uf: str = "SP") -> SpedRecord:
    return _make_record("0000", {
        "COD_VER": "016",
        "COD_FIN": "0",
        "DT_INI": "01012024",
        "DT_FIN": "31012024",
        "NOME": "EMPRESA TESTE",
        "CNPJ": "12345678000195",
        "CPF": "",
        "UF": uf,
    }, line_number=1)


def _r0150(cod_part: str = "PART1", uf: str = "RJ", cpf: str = "9") -> SpedRecord:
    """0150 participant record. cpf field here is used as IND_IE proxy."""
    return _make_record("0150", {
        "COD_PART": cod_part,
        "NOME": "DESTINATARIO",
        "COD_PAIS": "01058",
        "CNPJ": "98765432000155",
        "CPF": cpf,
        "IE": "",
        "COD_MUN": "3304557",
        "SUFRAMA": "",
        "END": "Rua X",
        "NUM": "100",
        "COMPL": "",
        "BAIRRO": "Centro",
        "UF": uf,
    }, line_number=2)


# ──────────────────────────────────────────────
# validate_difal — early returns
# ──────────────────────────────────────────────

class TestValidateDifalEarlyReturns:
    def test_pre_2016_returns_empty(self, make_context) -> None:
        """DIFAL only applies from 2016-01-01 onwards (EC 87/2015)."""
        ctx = make_context(periodo_ini=date(2015, 6, 1))
        records = [_r0000(), _c100(), _c170()]
        errors = validate_difal(records, context=ctx)
        assert errors == []

    def test_no_uf_declarante_returns_early(self) -> None:
        """If 0000 record has no UF, returns early (possibly with table warning)."""
        r0000 = _make_record("0000", {"UF": ""}, line_number=1)
        errors = validate_difal([r0000])
        # Should return early — only possible error is the table warning
        for e in errors:
            assert "DIFAL_VERIFICACAO" in e.error_type

    def test_no_c170_records_no_errors(self) -> None:
        """Without C170 records, no item-level errors should be produced."""
        records = [_r0000()]
        errors = validate_difal(records)
        # Only table-level warnings possible
        for e in errors:
            assert "VERIFICACAO" in e.error_type or "INCOMPLETA" in e.error_type


# ──────────────────────────────────────────────
# _build_parent_map
# ──────────────────────────────────────────────

class TestBuildParentMap:
    def test_maps_c170_to_parent_c100(self) -> None:
        c100 = _c100(line=5)
        c170a = _c170(line=10)
        c170b = _c170(line=11)

        groups = {"C100": [c100], "C170": [c170a, c170b]}
        pmap = _build_parent_map(groups)

        assert pmap[10] is c100
        assert pmap[11] is c100

    def test_multiple_c100_parents(self) -> None:
        c100_a = _c100(cod_part="A", line=1)
        c170_a = _c170(line=2)
        c100_b = _c100(cod_part="B", line=3)
        c170_b = _c170(line=4)

        groups = {"C100": [c100_a, c100_b], "C170": [c170_a, c170_b]}
        pmap = _build_parent_map(groups)

        assert pmap[2] is c100_a
        assert pmap[4] is c100_b

    def test_empty_groups(self) -> None:
        pmap = _build_parent_map({})
        assert pmap == {}


# ──────────────────────────────────────────────
# DIFAL_001 — DIFAL missing on final consumer operation
# ──────────────────────────────────────────────

class TestDifal001:
    def test_no_error_same_uf(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", aliq_icms="7.00")
        errors = _check_difal_001(rec, "6107", "SP", "SP", "9")
        assert errors == []

    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6107")
        errors = _check_difal_001(rec, "6107", "SP", "", "9")
        assert errors == []

    def test_no_error_not_consumer(self) -> None:
        """IND_IE=1 (contribuinte) and CFOP not in consumo final."""
        rec = _c170(cfop="6101", cst_icms="000")
        errors = _check_difal_001(rec, "6101", "SP", "RJ", "1")
        assert errors == []

    def test_no_error_cst_not_difal(self) -> None:
        """CST 40 (isento) should not trigger DIFAL check."""
        rec = _c170(cfop="6107", cst_icms="040")
        errors = _check_difal_001(rec, "6107", "SP", "RJ", "9")
        assert errors == []

    def test_no_error_no_cst(self) -> None:
        rec = _c170(cfop="6107", cst_icms="")
        errors = _check_difal_001(rec, "6107", "SP", "RJ", "9")
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_002 — DIFAL indevido em revenda
# ──────────────────────────────────────────────

class TestDifal002:
    def test_no_error_not_contribuinte(self) -> None:
        rec = _c170(cfop="6101", aliq_icms="18.00", cst_icms="000")
        errors = _check_difal_002(rec, "6101", "9")
        assert errors == []

    def test_no_error_cfop_not_revenda(self) -> None:
        rec = _c170(cfop="6107", aliq_icms="18.00", cst_icms="000")
        errors = _check_difal_002(rec, "6107", "1")
        assert errors == []

    def test_no_error_low_aliquota(self) -> None:
        """Aliquota <= 12 is valid for interstate, no error."""
        rec = _c170(cfop="6101", aliq_icms="12.00", cst_icms="000")
        errors = _check_difal_002(rec, "6101", "1")
        assert errors == []

    def test_error_high_aliquota_revenda(self) -> None:
        """Aliquota > 12 and not in {4, 7, 12} for contribuinte revenda -> error."""
        rec = _c170(cfop="6101", aliq_icms="18.00", cst_icms="000")
        errors = _check_difal_002(rec, "6101", "1")
        assert len(errors) == 1
        assert "DIFAL_INDEVIDO_REVENDA" in errors[0].error_type

    def test_no_error_no_cst(self) -> None:
        rec = _c170(cfop="6101", aliq_icms="18.00", cst_icms="")
        errors = _check_difal_002(rec, "6101", "1")
        assert errors == []

    def test_no_error_cst_isento(self) -> None:
        """CST 40 not in _CST_COM_DIFAL."""
        rec = _c170(cfop="6101", aliq_icms="18.00", cst_icms="040")
        errors = _check_difal_002(rec, "6101", "1")
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_003 — UF destino inconsistente
# ──────────────────────────────────────────────

class TestDifal003:
    def test_error_cfop_6xxx_same_uf(self) -> None:
        rec = _c170(cfop="6101")
        errors = _check_difal_003(rec, "6101", "SP", "SP")
        assert len(errors) == 1
        assert "DIFAL_UF_DESTINO_INCONSISTENTE" in errors[0].error_type

    def test_no_error_different_uf(self) -> None:
        rec = _c170(cfop="6101")
        errors = _check_difal_003(rec, "6101", "SP", "RJ")
        assert errors == []

    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6101")
        errors = _check_difal_003(rec, "6101", "SP", "")
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_004 — Aliquota interna destino incorreta
# ──────────────────────────────────────────────

class TestDifal004:
    def test_no_error_same_uf(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", aliq_icms="18.00")
        errors = _check_difal_004(rec, "6107", "SP", "SP")
        assert errors == []

    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", aliq_icms="18.00")
        errors = _check_difal_004(rec, "6107", "", "SP")
        assert errors == []

    def test_no_error_no_cst(self) -> None:
        rec = _c170(cfop="6107", cst_icms="", aliq_icms="18.00")
        errors = _check_difal_004(rec, "6107", "RJ", "SP", _LOADER)
        assert errors == []

    def test_no_error_cst_not_difal(self) -> None:
        rec = _c170(cfop="6107", cst_icms="040", aliq_icms="18.00")
        errors = _check_difal_004(rec, "6107", "RJ", "SP", _LOADER)
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_005 — Base DIFAL inconsistente
# ──────────────────────────────────────────────

class TestDifal005:
    def test_no_error_same_uf(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", vl_item="1000", vl_bc_icms="1000",
                     aliq_icms="12.00", vl_icms="120.00")
        errors = _check_difal_005(rec, "6107", "SP", "SP")
        assert errors == []

    def test_no_error_consistent_values(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", vl_item="1000", vl_bc_icms="1000",
                     aliq_icms="12.00", vl_icms="120.00")
        errors = _check_difal_005(rec, "6107", "RJ", "SP", _LOADER)
        assert errors == []

    def test_error_inconsistent_base(self) -> None:
        """VL_ICMS deviates significantly from BC * ALIQ/100."""
        rec = _c170(cfop="6107", cst_icms="000", vl_item="1000", vl_bc_icms="1000",
                     aliq_icms="12.00", vl_icms="200.00")
        errors = _check_difal_005(rec, "6107", "RJ", "SP", _LOADER)
        assert len(errors) == 1
        assert "DIFAL_BASE_INCONSISTENTE" in errors[0].error_type

    def test_no_error_zero_vl_item(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000", vl_item="0", vl_bc_icms="0")
        errors = _check_difal_005(rec, "6107", "RJ", "SP", _LOADER)
        assert errors == []

    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000")
        errors = _check_difal_005(rec, "6107", "", "SP")
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_006 — FCP ausente
# ──────────────────────────────────────────────

class TestDifal006:
    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6107", cst_icms="000")
        errors = _check_difal_006(rec, "6107", "")
        assert errors == []

    def test_no_error_cfop_not_consumo_final(self) -> None:
        rec = _c170(cfop="6101", cst_icms="000")
        errors = _check_difal_006(rec, "6101", "RJ")
        assert errors == []

    def test_no_error_no_cst(self) -> None:
        rec = _c170(cfop="6107", cst_icms="")
        errors = _check_difal_006(rec, "6107", "RJ", _LOADER)
        assert errors == []

    def test_no_error_cst_not_difal(self) -> None:
        rec = _c170(cfop="6107", cst_icms="040")
        errors = _check_difal_006(rec, "6107", "RJ", _LOADER)
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_007 — Perfil destinatario incompativel
# ──────────────────────────────────────────────

class TestDifal007:
    def test_error_contribuinte_consumo_final(self) -> None:
        """IND_IE=1 (contribuinte) with CFOP consumo final is incompatible."""
        rec = _c170(cfop="6107")
        errors = _check_difal_007(rec, "6107", "1", "RJ")
        assert len(errors) == 1
        assert "DIFAL_PERFIL_INCOMPATIVEL" in errors[0].error_type

    def test_error_nao_contribuinte_revenda(self) -> None:
        """IND_IE=9 (nao-contribuinte) with CFOP revenda is incompatible."""
        rec = _c170(cfop="6101")
        errors = _check_difal_007(rec, "6101", "9", "RJ")
        assert len(errors) == 1
        assert "DIFAL_PERFIL_INCOMPATIVEL" in errors[0].error_type

    def test_no_error_no_ind_ie(self) -> None:
        rec = _c170(cfop="6107")
        errors = _check_difal_007(rec, "6107", "", "RJ")
        assert errors == []

    def test_no_error_no_uf_dest(self) -> None:
        rec = _c170(cfop="6107")
        errors = _check_difal_007(rec, "6107", "1", "")
        assert errors == []

    def test_no_error_consistent_contribuinte_revenda(self) -> None:
        """IND_IE=1 with CFOP revenda is fine."""
        rec = _c170(cfop="6101")
        errors = _check_difal_007(rec, "6101", "1", "RJ")
        assert errors == []

    def test_no_error_consistent_nao_contrib_consumo(self) -> None:
        """IND_IE=9 with CFOP consumo final is fine."""
        rec = _c170(cfop="6107")
        errors = _check_difal_007(rec, "6107", "9", "RJ")
        assert errors == []


# ──────────────────────────────────────────────
# DIFAL_008 — Consumo final sem marcadores
# ──────────────────────────────────────────────

class TestDifal008:
    def test_error_nao_contribuinte_generic_cfop(self) -> None:
        """IND_IE=9 with generic interstate CFOP (not consumo final specific)."""
        rec = _c170(cfop="6101", cst_icms="000")
        errors = _check_difal_008(rec, "6101", "9")
        assert len(errors) == 1
        assert "DIFAL_CONSUMO_FINAL_SEM_MARCADOR" in errors[0].error_type

    def test_no_error_contribuinte(self) -> None:
        rec = _c170(cfop="6101", cst_icms="000")
        errors = _check_difal_008(rec, "6101", "1")
        assert errors == []

    def test_no_error_consumo_final_cfop(self) -> None:
        """IND_IE=9 but already uses specific consumo final CFOP."""
        rec = _c170(cfop="6107", cst_icms="000")
        errors = _check_difal_008(rec, "6107", "9")
        assert errors == []

    def test_no_error_no_cst(self) -> None:
        rec = _c170(cfop="6101", cst_icms="")
        errors = _check_difal_008(rec, "6101", "9")
        assert errors == []

    def test_no_error_cst_not_difal(self) -> None:
        rec = _c170(cfop="6101", cst_icms="040")
        errors = _check_difal_008(rec, "6101", "9")
        assert errors == []


# ──────────────────────────────────────────────
# Integration: validate_difal with full record sets
# ──────────────────────────────────────────────

class TestValidateDifalIntegration:
    def test_full_validation_with_incompatible_profile(self, make_context) -> None:
        """Full pipeline: IND_IE=9 + CFOP revenda should produce DIFAL_PERFIL_INCOMPATIVEL."""
        ctx = make_context(periodo_ini=date(2024, 1, 1))
        records = [
            _r0000(uf="SP"),
            _r0150(cod_part="PART1", uf="RJ", cpf="9"),
            _c100(cod_part="PART1", line=5),
            _c170(cfop="6101", cst_icms="000", aliq_icms="18.00", line=10),
        ]

        errors = validate_difal(records, context=ctx)
        error_types = {e.error_type for e in errors}

        # Should detect profile incompatibility (IND_IE=9 + revenda CFOP)
        assert "DIFAL_PERFIL_INCOMPATIVEL" in error_types or "DIFAL_CONSUMO_FINAL_SEM_MARCADOR" in error_types

    def test_full_validation_cfop_5xxx_skipped(self, make_context) -> None:
        """C170 with CFOP 5xxx (intra-state) should not trigger DIFAL checks."""
        ctx = make_context(periodo_ini=date(2024, 1, 1))
        records = [
            _r0000(uf="SP"),
            _r0150(cod_part="PART1", uf="SP", cpf="9"),
            _c100(cod_part="PART1", line=5),
            _c170(cfop="5102", cst_icms="000", aliq_icms="18.00", line=10),
        ]

        errors = validate_difal(records, context=ctx)
        # No item-level DIFAL errors for CFOP 5xxx
        item_errors = [
            e for e in errors
            if e.line_number > 0 and "DIFAL" in e.error_type and "VERIFICACAO" not in e.error_type
        ]
        assert item_errors == []

    def test_full_validation_uf_same_as_declarante(self, make_context) -> None:
        """When dest UF == declarante UF, DIFAL_003 may fire (CFOP 6xxx same UF)."""
        ctx = make_context(periodo_ini=date(2024, 1, 1))
        records = [
            _r0000(uf="SP"),
            _r0150(cod_part="PART1", uf="SP", cpf="1"),
            _c100(cod_part="PART1", line=5),
            _c170(cfop="6101", cst_icms="000", aliq_icms="12.00", line=10),
        ]

        errors = validate_difal(records, context=ctx)
        error_types = {e.error_type for e in errors}
        assert "DIFAL_UF_DESTINO_INCONSISTENTE" in error_types
