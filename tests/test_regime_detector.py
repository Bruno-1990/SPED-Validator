"""Testes para RegimeDetector — deteccao por CSTs reais (BUG-001 fix).

BUG-001: IND_PERFIL NAO e mais usado para determinar regime.
Regime e detectado exclusivamente pelos CSTs encontrados em C170/C190.
"""

import pytest
from src.models import SpedRecord
from src.validators.helpers import fields_to_dict
from src.validators.regime_detector import RegimeDetector, RegimeTributario, DetectionResult


def _make_record(register: str, fields_list: list[str], line: int = 1) -> SpedRecord:
    return SpedRecord(
        line_number=line,
        register=register,
        fields=fields_to_dict(register, fields_list),
        raw_line="|" + "|".join(fields_list) + "|",
    )


def _make_0000(ind_perfil: str = "A") -> SpedRecord:
    fields = ["0000", "017", "0", "01012024", "31012024", "EMPRESA LTDA",
              "12345678000190", "", "SP", "1234567890", "351880", "", "", ind_perfil, "1"]
    return _make_record("0000", fields)


def _make_c170(cst_icms: str = "00") -> SpedRecord:
    fields = ["C170", "1", "ITEM01", "DESC", "10", "UN", "100.00", "0", "0",
              cst_icms, "5101", "", "100.00", "18.00", "18.00",
              "", "", "", "", "", "", "", "", "",
              "", "", "", "", "", "",
              "", "", "", "", "", "", "", ""]
    return _make_record("C170", fields)


class TestRegimeDetector:
    """BUG-001 fix: Regime detectado pelos CSTs, nao por IND_PERFIL."""

    def test_csosn_detecta_simples_nacional(self):
        """CSOSN 400 em C170 → Simples Nacional, independente de IND_PERFIL."""
        records = [_make_0000("A"), _make_c170("400")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL
        assert result.confidence == 1.0

    def test_csosn_101_detecta_simples(self):
        records = [_make_0000("A"), _make_c170("101")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL

    def test_cst_normal_detecta_normal(self):
        """CST 00 (Tabela A) em C170 → Regime Normal."""
        records = [_make_0000("C"), _make_c170("00")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.REGIME_NORMAL
        assert result.confidence == 1.0

    def test_ind_perfil_c_sem_csosn_nao_e_simples(self):
        """IND_PERFIL=C mas CST 00 em C170 → Normal (IND_PERFIL ignorado)."""
        records = [_make_0000("C"), _make_c170("00")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.REGIME_NORMAL

    def test_ind_perfil_a_com_csosn_e_simples(self):
        """IND_PERFIL=A mas CSOSN em C170 → Simples (CST prevalece)."""
        records = [_make_0000("A"), _make_c170("102")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL

    def test_sem_c170_unknown(self):
        """Sem registros C170/C190 → DESCONHECIDO."""
        records = [_make_0000("A")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.DESCONHECIDO
        assert result.needs_confirmation is True

    def test_empty_records(self):
        result = RegimeDetector.detect([])
        assert result.regime == RegimeTributario.DESCONHECIDO

    def test_regime_source_is_cst(self):
        """regime_source deve ser 'CST'."""
        records = [_make_0000("A"), _make_c170("00")]
        result = RegimeDetector.detect(records)
        assert result.regime_source == "CST"

    def test_ind_perfil_logged_but_not_used(self):
        """IND_PERFIL aparece nos signals mas nao determina regime."""
        records = [_make_0000("C"), _make_c170("00")]
        result = RegimeDetector.detect(records)
        assert any("IND_PERFIL" in s for s in result.signals)
        assert any("NAO indica regime" in s for s in result.signals)
        assert result.regime == RegimeTributario.REGIME_NORMAL  # CST prevalece
