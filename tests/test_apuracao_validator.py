"""Testes do apuracao_validator — reconciliação C190→E110→E111→E116 (PRD v2 Fase 1)."""

from __future__ import annotations

from src.models import SpedRecord
from src.services.context_builder import ValidationContext, TaxRegime
from src.validators.apuracao_validator import validate_apuracao


def _rec(register: str, fields: dict[str, str], line: int = 1) -> SpedRecord:
    return SpedRecord(register=register, fields=fields, line_number=line, raw_line="")


def _e110(
    tot_deb="10000", aj_deb="500", est_cred="0",
    tot_cred="8000", aj_cred="300", est_deb="0",
    sld_ant="0", sld_apurado="2200", tot_ded="0",
    icms_recolher="2200", sld_credor="0", deb_esp="0",
) -> SpedRecord:
    return _rec("E110", {
        "VL_TOT_DEBITOS": tot_deb,
        "VL_AJ_DEBITOS": aj_deb,
        "VL_TOT_AJ_DEBITOS": aj_deb,
        "VL_ESTORNOS_CRED": est_cred,
        "VL_TOT_CREDITOS": tot_cred,
        "VL_AJ_CREDITOS": aj_cred,
        "VL_TOT_AJ_CREDITOS": aj_cred,
        "VL_ESTORNOS_DEB": est_deb,
        "VL_SLD_CREDOR_ANT": sld_ant,
        "VL_SLD_APURADO": sld_apurado,
        "VL_TOT_DED": tot_ded,
        "VL_ICMS_RECOLHER": icms_recolher,
        "VL_SLD_CREDOR_TRANSPORTAR": sld_credor,
        "DEB_ESP": deb_esp,
    })


def _c190(cst: str, cfop: str, vl_icms: str) -> SpedRecord:
    return _rec("C190", {"CST_ICMS": cst, "CFOP": cfop, "ALIQ_ICMS": "12", "VL_OPR": "50000", "VL_BC_ICMS": "50000", "VL_ICMS": vl_icms})


def _e111(cod_aj: str, valor: str, line: int = 2) -> SpedRecord:
    return _rec("E111", {"COD_AJ_APUR": cod_aj, "DESCR_COMPL_AJ": "ajuste", "VL_AJ_APUR": valor}, line=line)


def _e116(cod_or: str, vl_or: str, cod_rec: str = "121-0", line: int = 3) -> SpedRecord:
    return _rec("E116", {"COD_OR": cod_or, "VL_OR": vl_or, "DT_VCTO": "15012026", "COD_REC": cod_rec, "NUM_PROC": "", "IND_PROC": ""}, line=line)


def _tipos(errors):
    return {e.error_type for e in errors}


def _ctx(regime=TaxRegime.NORMAL):
    return ValidationContext(file_id=1, regime=regime)


# ── RF001-DEB ──

class TestRF001Debitos:
    def test_debitos_fecham(self):
        records = [
            _c190("000", "5101", "6000"),
            _c190("000", "6101", "4000"),
            _e110(tot_deb="10000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF001_DEBITOS_DIVERGENTE" not in _tipos(errors)

    def test_debitos_divergem(self):
        records = [
            _c190("000", "5101", "6000"),
            _c190("000", "6101", "4000"),
            _e110(tot_deb="8000"),  # deveria ser 10000
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF001_DEBITOS_DIVERGENTE" in _tipos(errors)

    def test_debitos_zerados_com_saidas(self):
        records = [
            _c190("000", "5101", "5000"),
            _e110(tot_deb="0"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF001_DEBITOS_DIVERGENTE" in _tipos(errors)

    def test_diferimento_excluido(self):
        """CST 51 (diferimento) não entra no débito — EX-RF001-01."""
        records = [
            _c190("000", "5101", "5000"),
            _c190("051", "5101", "3000"),  # diferimento — excluir
            _e110(tot_deb="5000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF001_DEBITOS_DIVERGENTE" not in _tipos(errors)

    def test_entradas_nao_contam(self):
        """CFOP 1xxx/2xxx são entradas — não entram no débito."""
        records = [
            _c190("000", "5101", "5000"),
            _c190("000", "1101", "3000"),  # entrada — não conta
            _e110(tot_deb="5000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF001_DEBITOS_DIVERGENTE" not in _tipos(errors)

    def test_simples_nacional_pula(self):
        """Simples Nacional não apura ICMS — EX-RF001-02."""
        records = [_c190("000", "5101", "5000"), _e110(tot_deb="0")]
        errors = validate_apuracao(records, context=_ctx(TaxRegime.SIMPLES_NACIONAL))
        assert len(errors) == 0


# ── RF002-CRE ──

class TestRF002Creditos:
    def test_creditos_fecham(self):
        records = [
            _c190("000", "1101", "8000"),
            _e110(tot_cred="8000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF002_CREDITOS_DIVERGENTE" not in _tipos(errors)

    def test_creditos_divergem(self):
        records = [
            _c190("000", "1101", "8000"),
            _e110(tot_cred="5000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF002_CREDITOS_DIVERGENTE" in _tipos(errors)


# ── RF003-SALDO ──

class TestRF003Saldo:
    def test_saldo_consistente(self):
        # (10000 + 500 + 0) - (8000 + 300 + 0) - 0 = 2200
        records = [_e110()]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_SALDO_INCONSISTENTE" not in _tipos(errors)

    def test_saldo_inconsistente(self):
        records = [_e110(sld_apurado="9999")]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_SALDO_INCONSISTENTE" in _tipos(errors)

    def test_recolher_consistente(self):
        records = [_e110(icms_recolher="2200")]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_RECOLHER_INCONSISTENTE" not in _tipos(errors)

    def test_recolher_inconsistente(self):
        records = [_e110(icms_recolher="1000")]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_RECOLHER_INCONSISTENTE" in _tipos(errors)

    def test_saldo_credor_transportar(self):
        # Saldo negativo: (1000 + 0 + 0) - (5000 + 0 + 0) - 0 = -4000
        records = [_e110(
            tot_deb="1000", aj_deb="0", tot_cred="5000", aj_cred="0",
            sld_apurado="-4000", icms_recolher="0", sld_credor="4000",
        )]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_CREDOR_INCONSISTENTE" not in _tipos(errors)

    def test_saldo_credor_errado(self):
        records = [_e110(
            tot_deb="1000", aj_deb="0", tot_cred="5000", aj_cred="0",
            sld_apurado="-4000", icms_recolher="0", sld_credor="1000",
        )]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF003_CREDOR_INCONSISTENTE" in _tipos(errors)


# ── RF004-AJ-SUM ──

class TestRF004Ajustes:
    def test_ajustes_fecham(self):
        records = [
            _e110(aj_deb="500", aj_cred="300"),
            _e111("ES020002", "500"),   # tipo 2 = outros débitos
            _e111("ES050003", "300", line=3),  # tipo 5 = outros créditos
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF004_AJ_DEBITOS_DIVERGENTE" not in _tipos(errors)
        assert "RF004_AJ_CREDITOS_DIVERGENTE" not in _tipos(errors)

    def test_ajustes_divergem(self):
        records = [
            _e110(aj_deb="500", aj_cred="300"),
            _e111("ES020002", "200"),   # deveria somar 500
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF004_AJ_DEBITOS_DIVERGENTE" in _tipos(errors)


# ── RF008/RF009 ──

class TestRF008RF009Recolhimento:
    def test_e116_presente_quando_recolher(self):
        records = [
            _e110(icms_recolher="2200"),
            _e116("001", "2200"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF008_E116_AUSENTE" not in _tipos(errors)

    def test_e116_ausente_com_saldo_devedor(self):
        records = [_e110(icms_recolher="2200")]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF008_E116_AUSENTE" in _tipos(errors)

    def test_e116_valor_fecha(self):
        records = [
            _e110(icms_recolher="2200", tot_ded="0"),
            _e116("001", "2200"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF009_E116_VALOR_DIVERGENTE" not in _tipos(errors)

    def test_e116_valor_diverge(self):
        records = [
            _e110(icms_recolher="5000"),
            _e116("001", "3000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF009_E116_VALOR_DIVERGENTE" in _tipos(errors)

    def test_saldo_credor_com_e116_recolhimento(self):
        records = [
            _e110(icms_recolher="0", sld_credor="5000"),
            _e116("001", "1000"),
        ]
        errors = validate_apuracao(records, context=_ctx())
        assert "RF014_SALDO_CREDOR_COM_RECOLHIMENTO" in _tipos(errors)

    def test_sem_e110_nao_dispara(self):
        records = [_c190("000", "5101", "5000")]
        errors = validate_apuracao(records, context=_ctx())
        assert len(errors) == 0
