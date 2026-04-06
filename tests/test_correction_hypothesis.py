"""Testes do motor de hipotese de correcao de aliquota (correction_hypothesis.py).

Cobre:
- Deteccao basica de ALIQ_ICMS ausente
- Verificacao de plausibilidade
- Sistema de scoring por evidencia
- Casos negativos (sem erro)
- Niveis de confianca e auto_correctable
- Dataclass CorrectionHypothesis
- Formato do erro de saida
"""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.correction_hypothesis import (
    CorrectionHypothesis,
    _build_hypothesis,
    _find_plausible_rate,
    validate_with_hypotheses,
)
from src.validators.helpers import fields_to_dict

# ──────────────────────────────────────────────
# Helpers para construir registros
# ──────────────────────────────────────────────

def _make_c100(line: int = 1) -> SpedRecord:
    """Cria um registro C100 minimo."""
    fields = ["C100"] + [""] * 25
    return SpedRecord(
        line_number=line,
        register="C100",
        fields=fields_to_dict("C100", fields),
        raw_line="|".join(fields),
    )


def _make_c170(
    line: int,
    vl_bc_icms: str = "0",
    aliq_icms: str = "0",
    vl_icms: str = "0",
    cst_icms: str = "000",
    cfop: str = "5102",
) -> SpedRecord:
    """Cria registro C170 com campos posicionais.

    Layout (0-based):
    0:REG, 1:NUM_ITEM, 2:COD_ITEM, 3:DESCR, 4:QTD, 5:UNID,
    6:VL_ITEM, 7:VL_DESC, 8:IND_MOV, 9:CST_ICMS, 10:CFOP,
    11:COD_NAT, 12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS,
    15:VL_BC_ST, 16:ALIQ_ST, 17:VL_ICMS_ST
    """
    fields = ["C170", "1", "ITEM01", "Produto", "1", "UN",
              "100.00", "0", "", cst_icms, cfop,
              "", vl_bc_icms, aliq_icms, vl_icms,
              "0", "0", "0"]
    return SpedRecord(
        line_number=line,
        register="C170",
        fields=fields_to_dict("C170", fields),
        raw_line="|".join(fields),
    )


def _make_c190(
    line: int,
    cst: str = "000",
    cfop: str = "5102",
    aliq: str = "0",
    vl_opr: str = "0",
    vl_bc: str = "0",
    vl_icms: str = "0",
) -> SpedRecord:
    """Cria registro C190.

    Layout (0-based): 0:REG, 1:CST, 2:CFOP, 3:ALIQ, 4:VL_OPR,
    5:VL_BC, 6:VL_ICMS
    """
    fields = ["C190", cst, cfop, aliq, vl_opr, vl_bc, vl_icms]
    return SpedRecord(
        line_number=line,
        register="C190",
        fields=fields_to_dict("C190", fields),
        raw_line="|".join(fields),
    )


def _build_records(
    c170_items: list[SpedRecord],
    c190_items: list[SpedRecord] | None = None,
) -> list[SpedRecord]:
    """Monta lista de registros com C100 pai, C170 filhos e C190 opcionais."""
    c100 = _make_c100(line=1)
    records = [c100]
    records.extend(c170_items)
    if c190_items:
        records.extend(c190_items)
    return records


# ══════════════════════════════════════════════
# 1. Deteccao basica: ALIQ=0 com VL_ICMS>0 e VL_BC>0
# ══════════════════════════════════════════════

class TestBasicDetection:
    """Aliquota implicita = VL_ICMS / VL_BC_ICMS * 100."""

    def test_implied_rate_18(self):
        """BC=1000, ICMS=180 -> aliq implicita 18%."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert "18.00" in errors[0].message

    def test_implied_rate_12(self):
        """BC=500, ICMS=60 -> aliq implicita 12%."""
        item = _make_c170(line=2, vl_bc_icms="500", aliq_icms="0", vl_icms="60")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert "12.00" in errors[0].message

    def test_implied_rate_7(self):
        """BC=200, ICMS=14 -> aliq implicita 7%."""
        item = _make_c170(line=2, vl_bc_icms="200", aliq_icms="0", vl_icms="14")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert "7.00" in errors[0].message

    def test_implied_rate_4(self):
        """BC=1000, ICMS=40 -> aliq implicita 4%."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="40")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert "4.00" in errors[0].message


# ══════════════════════════════════════════════
# 2. Verificacao de plausibilidade
# ══════════════════════════════════════════════

class TestPlausibility:

    def test_within_tolerance_matches(self):
        """Taxa implicita 18.02% deve corresponder a 18.00% (tolerancia 0.05)."""
        # BC=1000, ICMS=180.20 -> 18.02% -> proximo de 18.00
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180.20")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert "18.00" in errors[0].message

    def test_implausible_rate_no_match(self):
        """Taxa implicita 15.5% nao e uma aliquota conhecida -> sem erro."""
        # BC=1000, ICMS=155 -> 15.5% -> nao plausivel
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="155")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0

    def test_vl_icms_zero_no_error(self):
        """Se VL_ICMS=0 nao ha erro mesmo com ALIQ=0."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="0")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0


# ══════════════════════════════════════════════
# 3. Sistema de scoring
# ══════════════════════════════════════════════

class TestScoring:

    def test_exact_recalculation_40_points(self):
        """Recalculo exato: BC * aliq / 100 == VL_ICMS -> +40."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        hyp = _build_hypothesis(item, [item], [])
        assert hyp is not None
        # Deve ter pelo menos 40 (recalculo exato) + 10 (campo zerado)
        assert hyp.score >= 50
        assert any("reproduz exatamente" in r for r in hyp.reasons)

    def test_approximate_match_20_points(self):
        """Recalculo aproximado (arredondamento) -> +20."""
        # BC=999.99, ICMS=180.04 -> impl=18.0041... -> plausivel=18.0
        # Recalculo: 999.99 * 18 / 100 = 179.9982 -> arredondado=180.00
        # |180.00 - 180.04| = 0.04 > TOLERANCE(0.02) -> aproximado
        item = _make_c170(line=2, vl_bc_icms="999.99", aliq_icms="0", vl_icms="180.04")
        hyp = _build_hypothesis(item, [item], [])
        assert hyp is not None
        assert any("aproxima-se" in r for r in hyp.reasons)

    def test_field_zerado_10_points(self):
        """Campo ALIQ_ICMS zerado sempre soma +10."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        hyp = _build_hypothesis(item, [item], [])
        assert hyp is not None
        assert any("zerado" in r for r in hyp.reasons)

    def test_all_siblings_confirm_20_points(self):
        """Todos os irmaos com mesmo CST/CFOP confirmam mesma aliquota -> +20."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180",
                          cst_icms="000", cfop="5102")
        sib1 = _make_c170(line=3, vl_bc_icms="500", aliq_icms="18", vl_icms="90",
                          cst_icms="000", cfop="5102")
        sib2 = _make_c170(line=4, vl_bc_icms="200", aliq_icms="18", vl_icms="36",
                          cst_icms="000", cfop="5102")
        hyp = _build_hypothesis(item, [item, sib1, sib2], [])
        assert hyp is not None
        assert any("Todos" in r for r in hyp.reasons)
        # Score: 40 (exato) + 10 (zerado) + 20 (irmaos) = 70 minimo
        assert hyp.score >= 70

    def test_some_siblings_confirm_10_points(self):
        """Apenas parte dos irmaos confirma -> +10."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180",
                          cst_icms="000", cfop="5102")
        sib1 = _make_c170(line=3, vl_bc_icms="500", aliq_icms="18", vl_icms="90",
                          cst_icms="000", cfop="5102")
        # Irmao com aliquota diferente (12%)
        sib2 = _make_c170(line=4, vl_bc_icms="200", aliq_icms="12", vl_icms="24",
                          cst_icms="000", cfop="5102")
        hyp = _build_hypothesis(item, [item, sib1, sib2], [])
        assert hyp is not None
        assert any("de" in r and "itens irmaos" in r for r in hyp.reasons
                    if "Todos" not in r)

    def test_c190_confirms_rate_20_points(self):
        """C190 com mesma aliquota confirma -> +20."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180",
                          cst_icms="000", cfop="5102")
        c190 = _make_c190(line=5, cst="000", cfop="5102", aliq="18",
                          vl_bc="1000", vl_icms="180")
        hyp = _build_hypothesis(item, [item], [c190])
        assert hyp is not None
        assert any("C190" in r and "confirma" in r for r in hyp.reasons)

    def test_cst_tributado_10_points(self):
        """CST tributado (ex: 000 -> trib='00') -> +10."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180",
                          cst_icms="000", cfop="5102")
        hyp = _build_hypothesis(item, [item], [])
        assert hyp is not None
        assert any("CST" in r and "tributacao" in r for r in hyp.reasons)


# ══════════════════════════════════════════════
# 4. Casos negativos (sem erro)
# ══════════════════════════════════════════════

class TestNegativeCases:

    def test_aliq_greater_than_zero_no_error(self):
        """Se ALIQ_ICMS > 0, nao ha erro."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="18", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0

    def test_vl_icms_zero_no_error(self):
        """Se VL_ICMS = 0, nao ha erro."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="0")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0

    def test_vl_bc_zero_no_error(self):
        """Se VL_BC_ICMS = 0, nao ha erro."""
        item = _make_c170(line=2, vl_bc_icms="0", aliq_icms="0", vl_icms="100")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0

    def test_implausible_rate_no_error(self):
        """Se a taxa implicita nao bate com nenhuma aliquota conhecida -> sem erro."""
        # 155 / 1000 * 100 = 15.5% (nao plausivel)
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="155")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 0


# ══════════════════════════════════════════════
# 5. Niveis de confianca
# ══════════════════════════════════════════════

class TestConfidenceLevels:

    def test_score_80_alta_auto_correctable(self):
        """Score >= 80 -> confianca 'alta', auto_correctable True."""
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=80,
        )
        assert hyp.confidence == "alta"
        assert hyp.auto_correctable is True

    def test_score_90_alta(self):
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=90,
        )
        assert hyp.confidence == "alta"
        assert hyp.auto_correctable is True

    def test_score_60_provavel_auto_correctable(self):
        """Score 60-79 -> confianca 'provavel', auto_correctable True."""
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=60,
        )
        assert hyp.confidence == "provavel"
        assert hyp.auto_correctable is True

    def test_score_79_provavel(self):
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=79,
        )
        assert hyp.confidence == "provavel"
        assert hyp.auto_correctable is True

    def test_score_40_indicio_not_auto_correctable(self):
        """Score 40-59 -> confianca 'indicio', auto_correctable False."""
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=40,
        )
        assert hyp.confidence == "indicio"
        assert hyp.auto_correctable is False

    def test_score_59_indicio(self):
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=59,
        )
        assert hyp.confidence == "indicio"
        assert hyp.auto_correctable is False

    def test_score_below_40_baixa_not_auto_correctable(self):
        """Score < 40 -> confianca 'baixa', auto_correctable False."""
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=39,
        )
        assert hyp.confidence == "baixa"
        assert hyp.auto_correctable is False

    def test_score_zero_baixa(self):
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00", score=0,
        )
        assert hyp.confidence == "baixa"
        assert hyp.auto_correctable is False


# ══════════════════════════════════════════════
# 6. CorrectionHypothesis dataclass
# ══════════════════════════════════════════════

class TestCorrectionHypothesisDataclass:

    def test_default_score_zero(self):
        hyp = CorrectionHypothesis(
            field_name="ALIQ_ICMS", current_value="0",
            suggested_value="18.00",
        )
        assert hyp.score == 0
        assert hyp.reasons == []

    def test_confidence_property_boundary_values(self):
        """Testa os limites exatos de cada faixa."""
        for score, expected in [(80, "alta"), (79, "provavel"),
                                (60, "provavel"), (59, "indicio"),
                                (40, "indicio"), (39, "baixa"),
                                (0, "baixa"), (100, "alta")]:
            hyp = CorrectionHypothesis(
                field_name="X", current_value="0",
                suggested_value="1", score=score,
            )
            assert hyp.confidence == expected, f"score={score}"

    def test_auto_correctable_boundary(self):
        """auto_correctable True a partir de score 60."""
        assert CorrectionHypothesis(
            field_name="X", current_value="0",
            suggested_value="1", score=60,
        ).auto_correctable is True
        assert CorrectionHypothesis(
            field_name="X", current_value="0",
            suggested_value="1", score=59,
        ).auto_correctable is False


# ══════════════════════════════════════════════
# 7. Formato do erro de saida
# ══════════════════════════════════════════════

class TestErrorOutput:

    def test_error_type(self):
        """error_type deve ser 'ALIQ_ICMS_AUSENTE'."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert errors[0].error_type == "ALIQ_ICMS_AUSENTE"

    def test_field_name(self):
        """field_name deve ser 'ALIQ_ICMS'."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert errors[0].field_name == "ALIQ_ICMS"

    def test_expected_value_set_when_auto_correctable(self):
        """Quando score >= 60 (auto_correctable), expected_value e preenchido."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180",
                          cst_icms="000", cfop="5102")
        # Adicionar C190 que confirma a aliquota para elevar o score
        c190 = _make_c190(line=5, cst="000", cfop="5102", aliq="18",
                          vl_bc="1000", vl_icms="180")
        sib = _make_c170(line=3, vl_bc_icms="500", aliq_icms="18", vl_icms="90",
                         cst_icms="000", cfop="5102")
        records = _build_records([item, sib], [c190])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        # Score: 40(exato) + 10(zerado) + 20(irmao) + 20(c190) + 10(CST) = 100
        assert errors[0].expected_value is not None
        assert errors[0].expected_value == "18.00"

    def test_expected_value_none_when_not_auto_correctable(self):
        """Quando score < 60 (nao auto_correctable), expected_value e None.

        Para obter score baixo: item sem irmaos confirmando, sem C190,
        CST nao tributado, e recalculo apenas aproximado.
        """
        # BC=999.99, ICMS=180.04 -> aproximado (+20) + zerado (+10) = 30 < 60
        # CST '040' -> trib='40' esta em CST_ISENTO_NT, nao CST_TRIBUTADO
        item = _make_c170(line=2, vl_bc_icms="999.99", aliq_icms="0", vl_icms="180.04",
                          cst_icms="040", cfop="5102")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert errors[0].expected_value is None

    def test_error_line_number_matches_record(self):
        """O line_number do erro deve coincidir com o do registro C170."""
        item = _make_c170(line=42, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert errors[0].line_number == 42

    def test_error_register_is_c170(self):
        """O register do erro deve ser C170."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert errors[0].register == "C170"

    def test_error_value_is_zero(self):
        """O value do erro deve ser '0' (aliquota atual)."""
        item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        records = _build_records([item])
        errors = validate_with_hypotheses(records)
        assert errors[0].value == "0"


# ══════════════════════════════════════════════
# Testes auxiliares: _find_plausible_rate
# ══════════════════════════════════════════════

class TestFindPlausibleRate:

    def test_exact_known_rates(self):
        for rate in [0.0, 4.0, 7.0, 12.0, 17.0, 18.0, 25.0]:
            assert _find_plausible_rate(rate) == rate

    def test_within_tolerance(self):
        assert _find_plausible_rate(18.03) == 18.0
        assert _find_plausible_rate(11.97) == 12.0
        assert _find_plausible_rate(7.04) == 7.0

    def test_outside_tolerance(self):
        assert _find_plausible_rate(15.5) is None
        assert _find_plausible_rate(10.0) is None
        assert _find_plausible_rate(18.1) is None

    def test_zero_is_plausible(self):
        assert _find_plausible_rate(0.0) == 0.0


# ══════════════════════════════════════════════
# Teste de integracao: multiplos itens no mesmo documento
# ══════════════════════════════════════════════

class TestMultipleItems:

    def test_only_items_with_aliq_zero_generate_errors(self):
        """Apenas itens com ALIQ=0 e VL_ICMS>0 geram erros."""
        ok_item = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="18", vl_icms="180")
        bad_item = _make_c170(line=3, vl_bc_icms="500", aliq_icms="0", vl_icms="60")
        no_icms = _make_c170(line=4, vl_bc_icms="200", aliq_icms="0", vl_icms="0")
        records = _build_records([ok_item, bad_item, no_icms])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 1
        assert errors[0].line_number == 3

    def test_multiple_errors_for_multiple_bad_items(self):
        """Cada item com problema gera seu proprio erro."""
        bad1 = _make_c170(line=2, vl_bc_icms="1000", aliq_icms="0", vl_icms="180")
        bad2 = _make_c170(line=3, vl_bc_icms="500", aliq_icms="0", vl_icms="60")
        records = _build_records([bad1, bad2])
        errors = validate_with_hypotheses(records)
        assert len(errors) == 2
        error_lines = {e.line_number for e in errors}
        assert error_lines == {2, 3}
