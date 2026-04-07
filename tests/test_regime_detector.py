"""Testes para RegimeDetector — detecção multi-sinal de regime tributário."""

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
    # 0000 tem 15 campos: REG, COD_VER, COD_FIN, DT_INI, DT_FIN, NOME, CNPJ, CPF,
    # UF, IE, COD_MUN, IM, SUFRAMA, IND_PERFIL, IND_ATIV
    fields = ["0000", "017", "0", "01012024", "31012024", "EMPRESA LTDA",
              "12345678000190", "", "SP", "1234567890", "351880", "", "", ind_perfil, "1"]
    return _make_record("0000", fields)


def _make_c170(cst_icms: str = "00") -> SpedRecord:
    # Campos mínimos do C170 com CST_ICMS na posição correta
    fields = ["C170", "1", "ITEM01", "DESC", "10", "UN", "100.00", "0", "0",
              cst_icms, "5101", "", "100.00", "18.00", "18.00",
              "", "", "", "", "", "", "", "", "",
              "", "", "", "", "", "",
              "", "", "", "", "", "", "", ""]
    return _make_record("C170", fields)


class TestRegimeDetector:
    def test_perfil_c_simples_nacional(self):
        records = [_make_0000("C")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL
        assert result.confidence >= 0.7

    def test_perfil_a_regime_normal(self):
        records = [_make_0000("A")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.REGIME_NORMAL
        assert result.confidence >= 0.7

    def test_perfil_b_regime_normal(self):
        records = [_make_0000("B")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.REGIME_NORMAL

    def test_csosn_in_c170_indicates_sn(self):
        records = [_make_0000("C"), _make_c170("400")]
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL
        assert result.confidence >= 0.7

    def test_no_signals_unknown(self):
        records = [_make_0000("")]  # IND_PERFIL vazio
        result = RegimeDetector.detect(records)
        assert result.regime == RegimeTributario.DESCONHECIDO
        assert result.needs_confirmation is True

    def test_mixed_signals(self):
        # Perfil C + CST normal (ambíguo mas SN domina)
        records = [_make_0000("C"), _make_c170("00")]
        result = RegimeDetector.detect(records)
        # IND_PERFIL=C gives sn_score=0.7, CST normal without CSOSN gives normal_score=0.5
        # SN score >= 0.6 so should be SIMPLES_NACIONAL
        assert result.regime == RegimeTributario.SIMPLES_NACIONAL

    def test_empty_records(self):
        result = RegimeDetector.detect([])
        assert result.regime == RegimeTributario.DESCONHECIDO
        assert result.needs_confirmation is True

    def test_high_confidence_no_confirmation(self):
        # IND_PERFIL=C + CSOSN gives score 0.7 + 0.6 = 1.3 capped at 1.0
        records = [_make_0000("C"), _make_c170("400")]
        result = RegimeDetector.detect(records)
        assert result.confidence >= 0.8
        assert result.needs_confirmation is False
