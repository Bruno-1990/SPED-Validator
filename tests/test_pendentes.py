"""Tests for src/validators/pendentes_validator.py.

Covers:
- validate_pendentes main entry
- _check_beneficio_fiscal (CST tributado + aliq zero + no beneficio)
- _check_desoneracao_motivo (desoneracao without MOT_DES_ICMS)
- _check_devolucao_vs_origem (devolucao with isento CST)
- _check_perfil_historico (same item with divergent CSTs)
- _check_ncm_vs_tipi_aliq (same NCM with divergent IPI aliquotas)
"""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)

from src.models import SpedRecord  # noqa: E402
from src.validators.pendentes_validator import validate_pendentes  # noqa: E402


def _rec(register: str, fields: dict[str, str], line: int = 1) -> SpedRecord:
    return SpedRecord(
        line_number=line,
        register=register,
        fields={"REG": register, **fields},
        raw_line="|" + "|".join([register] + list(fields.values())) + "|",
    )


def _c170(line: int = 10, cst: str = "000", cfop: str = "5102",
          aliq: str = "18", cod_item: str = "ITEM1",
          **extra) -> SpedRecord:
    fields = {
        "NUM_ITEM": "1", "COD_ITEM": cod_item, "DESCR_COMPL": "Produto",
        "QTD": "10", "UNID": "UN", "VL_ITEM": "1000", "VL_DESC": "0",
        "IND_MOV": "0", "CST_ICMS": cst, "CFOP": cfop, "COD_NAT": "001",
        "VL_BC_ICMS": "1000", "ALIQ_ICMS": aliq, "VL_ICMS": "180",
        "VL_BC_ICMS_ST": "0", "ALIQ_ST": "0", "VL_ICMS_ST": "0",
        "IND_APUR": "0", "CST_IPI": "50", "COD_ENQ": "", "VL_BC_IPI": "0",
        "ALIQ_IPI": "0", "VL_IPI": "0", "CST_PIS": "01",
        "VL_BC_PIS": "0", "ALIQ_PIS": "0", "QUANT_BC_PIS": "0",
        "ALIQ_PIS_REAIS": "0", "VL_PIS": "0", "CST_COFINS": "01",
        "VL_BC_COFINS": "0", "ALIQ_COFINS": "0", "QUANT_BC_COFINS": "0",
        "ALIQ_COFINS_REAIS": "0", "VL_COFINS": "0", "COD_CTA": "",
        "VL_ABAT_NT": "0",
    }
    fields.update(extra)
    return _rec("C170", fields, line)


def _0200(cod_item: str = "ITEM1", ncm: str = "12345678", line: int = 3) -> SpedRecord:
    return _rec("0200", {
        "COD_ITEM": cod_item, "DESCR_ITEM": "Produto Teste",
        "COD_BARRA": "", "COD_ANT_ITEM": "", "UNID_INV": "UN",
        "TIPO_ITEM": "00", "COD_NCM": ncm, "EX_IPI": "",
        "COD_GEN": "12", "COD_LST": "", "ALIQ_ICMS": "18",
    }, line)


# ──────────────────────────────────────────────
# Tests: validate_pendentes basic
# ──────────────────────────────────────────────

class TestValidatePendentes:
    def test_empty_records(self):
        assert validate_pendentes([]) == []

    def test_returns_list(self):
        records = [_c170()]
        result = validate_pendentes(records)
        assert isinstance(result, list)


# ──────────────────────────────────────────────
# Tests: BENEFICIO_NAO_VINCULADO
# ──────────────────────────────────────────────

class TestBeneficioFiscal:
    def test_cst_tributado_aliq_zero_no_beneficio(self):
        """CST tributado (00) with aliq zero and non-remessa CFOP => error."""
        rec = _c170(cst="000", cfop="5102", aliq="0")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" in types

    def test_cst_isento_no_error(self):
        """CST isento (40) with aliq zero => no error (not tributado)."""
        rec = _c170(cst="040", aliq="0")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types

    def test_cst_tributado_aliq_positive_no_error(self):
        """CST tributado with positive aliq => no error."""
        rec = _c170(cst="000", aliq="18")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types

    def test_remessa_cfop_excluded(self):
        """Remessa/retorno CFOPs are excluded from the check."""
        rec = _c170(cst="000", cfop="5901", aliq="0")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types

    def test_exportacao_cfop_excluded(self):
        """Exportacao CFOPs are excluded from the check."""
        rec = _c170(cst="000", cfop="7101", aliq="0")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types

    def test_no_cst_no_error(self):
        """No CST_ICMS => no error."""
        rec = _c170(cst="")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types

    def test_no_cfop_no_error(self):
        """CST tributado + aliq zero but no CFOP => no error."""
        rec = _c170(cst="000", cfop="", aliq="0")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "BENEFICIO_NAO_VINCULADO" not in types


# ──────────────────────────────────────────────
# Tests: DESONERACAO_SEM_MOTIVO
# ──────────────────────────────────────────────

class TestDesoneracaoMotivo:
    def test_desoneracao_without_motivo(self):
        """Record with IND_APUR > 0, > 18 fields, no mot_des after pos 30 => error."""
        # Build a record with > 30 fields where IND_APUR > 0 and no digit 1-9 after pos 30
        rec = _c170(line=10)
        # IND_APUR is at position 18 in C170, set to a positive value
        rec.fields["IND_APUR"] = "100"
        # Ensure fields beyond position 30 do not contain digits 1-9
        # The default _c170 has ~37 fields which is > 30
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DESONERACAO_SEM_MOTIVO" in types

    def test_desoneracao_with_motivo(self):
        """If a digit 1-9 is found after position 30 => no error."""
        rec = _c170(line=10)
        rec.fields["IND_APUR"] = "100"
        # Add a field that will be after position 30 with a valid motivo digit
        # fields_to_dict produces dict keys in order; add extra field
        rec.fields["F40"] = "3"  # motivo code at position > 30
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DESONERACAO_SEM_MOTIVO" not in types

    def test_few_fields_no_error(self):
        """Record with <= 18 fields => no error (skipped)."""
        rec = _rec("C170", {"NUM_ITEM": "1", "COD_ITEM": "X"}, line=10)
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DESONERACAO_SEM_MOTIVO" not in types


# ──────────────────────────────────────────────
# Tests: DEVOLUCAO_INCONSISTENTE
# ──────────────────────────────────────────────

class TestDevolucaoVsOrigem:
    def test_devolucao_with_isento_cst(self):
        """Devolucao CFOP + CST isento => DEVOLUCAO_INCONSISTENTE."""
        rec = _c170(cfop="1201", cst="040")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_INCONSISTENTE" in types

    def test_devolucao_with_tributado_cst_no_error(self):
        """Devolucao CFOP + CST tributado => no error."""
        rec = _c170(cfop="1201", cst="000")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_INCONSISTENTE" not in types

    def test_non_devolucao_cfop_no_error(self):
        """Non-devolucao CFOP => no error regardless of CST."""
        rec = _c170(cfop="5102", cst="040")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_INCONSISTENTE" not in types

    def test_devolucao_no_cst_no_error(self):
        rec = _c170(cfop="1201", cst="")
        errors = validate_pendentes([rec])
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_INCONSISTENTE" not in types


# ──────────────────────────────────────────────
# Tests: ANOMALIA_HISTORICA (perfil historico)
# ──────────────────────────────────────────────

class TestPerfilHistorico:
    def test_item_with_divergent_csts(self):
        """Same item with >80% tributado and some isento => ANOMALIA_HISTORICA."""
        records = []
        # 9 tributado (00)
        for i in range(9):
            records.append(_c170(cod_item="ITEM1", cst="000", line=10 + i))
        # 1 isento (40)
        records.append(_c170(cod_item="ITEM1", cst="040", line=20))
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "ANOMALIA_HISTORICA" in types

    def test_item_all_tributado_no_error(self):
        """Same item all tributado => no anomaly."""
        records = [_c170(cod_item="ITEM1", cst="000", line=10 + i) for i in range(5)]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "ANOMALIA_HISTORICA" not in types

    def test_item_balanced_no_error(self):
        """50/50 split => ratio < 80%, no error."""
        records = []
        for i in range(5):
            records.append(_c170(cod_item="ITEM1", cst="000", line=10 + i))
        for i in range(5):
            records.append(_c170(cod_item="ITEM1", cst="040", line=20 + i))
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "ANOMALIA_HISTORICA" not in types

    def test_item_no_cst_skipped(self):
        """Items without CST are skipped."""
        records = [_c170(cod_item="ITEM1", cst="", line=10 + i) for i in range(5)]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "ANOMALIA_HISTORICA" not in types


# ──────────────────────────────────────────────
# Tests: IPI_ALIQ_NCM_DIVERGENTE
# ──────────────────────────────────────────────

class TestNcmVsTipiAliq:
    def test_same_ncm_different_ipi_aliquotas(self):
        """Same NCM with different non-zero IPI aliquotas => error."""
        records = [
            _0200(cod_item="ITEM1", ncm="12345678"),
            _0200(cod_item="ITEM2", ncm="12345678", line=4),
            _c170(cod_item="ITEM1", line=10, ALIQ_IPI="5"),
            _c170(cod_item="ITEM2", line=11, ALIQ_IPI="10"),
        ]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "IPI_ALIQ_NCM_DIVERGENTE" in types

    def test_same_ncm_same_ipi_no_error(self):
        records = [
            _0200(cod_item="ITEM1", ncm="12345678"),
            _0200(cod_item="ITEM2", ncm="12345678", line=4),
            _c170(cod_item="ITEM1", line=10, ALIQ_IPI="5"),
            _c170(cod_item="ITEM2", line=11, ALIQ_IPI="5"),
        ]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "IPI_ALIQ_NCM_DIVERGENTE" not in types

    def test_zero_ipi_ignored(self):
        """Zero IPI aliquotas are excluded from comparison."""
        records = [
            _0200(cod_item="ITEM1", ncm="12345678"),
            _0200(cod_item="ITEM2", ncm="12345678", line=4),
            _c170(cod_item="ITEM1", line=10, ALIQ_IPI="0"),
            _c170(cod_item="ITEM2", line=11, ALIQ_IPI="5"),
        ]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "IPI_ALIQ_NCM_DIVERGENTE" not in types

    def test_different_ncm_no_error(self):
        """Different NCMs with different aliquotas => no error."""
        records = [
            _0200(cod_item="ITEM1", ncm="11111111"),
            _0200(cod_item="ITEM2", ncm="22222222", line=4),
            _c170(cod_item="ITEM1", line=10, ALIQ_IPI="5"),
            _c170(cod_item="ITEM2", line=11, ALIQ_IPI="10"),
        ]
        errors = validate_pendentes(records)
        types = {e.error_type for e in errors}
        assert "IPI_ALIQ_NCM_DIVERGENTE" not in types
