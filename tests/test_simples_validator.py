"""Testes do validador Simples Nacional (simples_validator.py) — MOD-12.

Cobre os criterios de aceitacao:
- SN_003: CSOSN 101/201 com credito — validacao por range (LC 155/2016)
- SN_012: Deteccao de anomalia em aliquotas de credito entre itens
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.validators.simples_validator import validate_simples


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


def _c170(
    csosn: str = "101",
    aliq: str = "1.60",
    vl_bc: str = "1000.00",
    vl_icms: str = "16.00",
    vl_bc_st: str = "0",
    vl_icms_st: str = "0",
    cst_pis: str = "49",
    cod_item: str = "ITEM01",
    line: int = 10,
) -> SpedRecord:
    """Cria um C170 minimo com campos de credito ICMS para Simples Nacional."""
    return _make_record("C170", {
        "REG": "C170",
        "NUM_ITEM": "1",
        "COD_ITEM": cod_item,
        "DESCR_COMPL": "Produto Teste",
        "QTD": "1",
        "UNID": "UN",
        "VL_ITEM": "1000.00",
        "VL_DESC": "0",
        "IND_MOV": "0",
        "CST_ICMS": csosn,
        "CFOP": "5102",
        "COD_NAT": "",
        "VL_BC_ICMS": vl_bc,
        "ALIQ_ICMS": aliq,
        "VL_ICMS": vl_icms,
        "VL_BC_ICMS_ST": vl_bc_st,
        "ALIQ_ST": "0",
        "VL_ICMS_ST": vl_icms_st,
        "CST_PIS": cst_pis,
        "CST_COFINS": cst_pis,
    }, line=line)


def _make_sn_context(ind_perfil: str = "C") -> ValidationContext:
    """Cria um ValidationContext de Simples Nacional."""
    return ValidationContext(
        file_id=1,
        regime=TaxRegime.SIMPLES_NACIONAL,
        uf_contribuinte="SP",
        periodo_ini=date(2024, 1, 1),
        periodo_fim=date(2024, 1, 31),
        ind_perfil=ind_perfil,
    )


# ──────────────────────────────────────────────
# SN_003 — CSOSN 101/201 com credito — range LC 155/2016
# ──────────────────────────────────────────────

class TestSN003CreditoRange:
    """SN_003: CSOSN 101/201 com credito — validacao LC 155/2016."""

    def test_aliq_zero_with_bc_positive(self):
        """ALIQ=0 com VL_BC>0 deve gerar warning SN_CREDITO_ZERADO_OU_FORA_RANGE."""
        records = [_c170(csosn="101", aliq="0", vl_bc="1000.00", vl_icms="0")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 1
        assert "SN_003" in sn003[0].message
        assert "ALIQ_ICMS=0%" in sn003[0].message

    def test_aliq_zero_all_zeros_generates_warning(self):
        """ALIQ=0, BC=0, VL_ICMS=0 — credito nao preenchido."""
        records = [_c170(csosn="101", aliq="0", vl_bc="0", vl_icms="0")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 1
        assert "SN_003" in sn003[0].message
        assert "zerados" in sn003[0].message.lower()

    def test_aliq_above_395_generates_warning(self):
        """ALIQ=5.00% acima do teto 3.95% deve gerar warning."""
        records = [_c170(csosn="101", aliq="5.00", vl_bc="1000.00", vl_icms="50.00")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 1
        assert "SN_003" in sn003[0].message
        assert "3,95%" in sn003[0].message

    def test_aliq_exactly_395_no_error(self):
        """ALIQ=3.95% no teto — nao deve gerar alerta."""
        records = [_c170(csosn="101", aliq="3.95", vl_bc="1000.00", vl_icms="39.50")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 0

    def test_aliq_within_range_no_error(self):
        """ALIQ=1.60% dentro do range — nao deve gerar alerta."""
        records = [_c170(csosn="101", aliq="1.60", vl_bc="1000.00", vl_icms="16.00")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 0

    def test_aliq_18_percent_above_teto(self):
        """ALIQ=18% (aliquota cheia normal) deve gerar warning."""
        records = [_c170(csosn="201", aliq="18.00", vl_bc="1000.00", vl_icms="180.00")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn003 = [e for e in errors if e.error_type == "SN_CREDITO_ZERADO_OU_FORA_RANGE"]
        assert len(sn003) == 1
        assert "SN_003" in sn003[0].message
        assert "18.00" in sn003[0].message


# ──────────────────────────────────────────────
# SN_012 — Deteccao de anomalia em aliquotas de credito
# ──────────────────────────────────────────────

class TestSN012ConsistenciaAliquota:
    """SN_012: Deteccao de anomalia em aliquotas de credito."""

    def test_delta_above_1pp_generates_info(self):
        """Delta > 1.0pp entre itens gera info."""
        records = [
            _c170(csosn="101", aliq="1.60", vl_bc="1000.00", vl_icms="16.00", line=10),
            _c170(csosn="101", aliq="2.78", vl_bc="1000.00", vl_icms="27.80", line=11, cod_item="ITEM02"),
        ]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn012 = [e for e in errors if e.error_type == "SN_CREDITO_INCONSISTENTE"]
        assert len(sn012) == 1
        assert "SN_012" in sn012[0].message
        assert "1.6000" in sn012[0].message or "min=1.6000" in sn012[0].message

    def test_delta_below_1pp_no_alert(self):
        """Delta < 1.0pp nao gera alerta."""
        records = [
            _c170(csosn="101", aliq="1.60", vl_bc="1000.00", vl_icms="16.00", line=10),
            _c170(csosn="101", aliq="1.62", vl_bc="1000.00", vl_icms="16.20", line=11, cod_item="ITEM02"),
        ]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn012 = [e for e in errors if e.error_type == "SN_CREDITO_INCONSISTENTE"]
        assert len(sn012) == 0

    def test_single_item_no_check(self):
        """Com apenas 1 item, nao deve verificar consistencia."""
        records = [_c170(csosn="101", aliq="1.60", vl_bc="1000.00", vl_icms="16.00")]
        ctx = _make_sn_context()
        errors = validate_simples(records, ctx)
        sn012 = [e for e in errors if e.error_type == "SN_CREDITO_INCONSISTENTE"]
        assert len(sn012) == 0
