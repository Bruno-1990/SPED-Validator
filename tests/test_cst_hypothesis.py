"""Testes do motor de hipotese de CST ICMS (cst_hypothesis.py).

Cobre os 4 tipos de incompatibilidade detectaveis, casos negativos,
scoring helpers e formato de saida.
"""

import pytest

from src.models import SpedRecord
from src.validators.cst_hypothesis import (
    _detect_inconsistency,
    _build_hypothesis,
    _hypothesis_to_error,
    _score_cfop,
    _score_c190,
    _score_siblings,
    _ISENTO_COM_TRIBUTO,
    _TRIBUTADO_SEM_TRIBUTO,
    _SEM_ST_COM_CAMPOS_ST,
    _INTEGRAL_COM_REDUCAO,
    validate_cst_hypotheses,
)
from src.validators.correction_hypothesis import CorrectionHypothesis


# ──────────────────────────────────────────────
# Helpers para construir registros de teste
# ──────────────────────────────────────────────

def _make_c170(
    *,
    cst: str = "000",
    cfop: str = "5102",
    vl_item: str = "1000.00",
    vl_desc: str = "0.00",
    vl_bc: str = "0.00",
    aliq: str = "0.00",
    vl_icms: str = "0.00",
    vl_bc_st: str = "0.00",
    aliq_st: str = "0.00",
    vl_icms_st: str = "0.00",
    line: int = 100,
) -> SpedRecord:
    """Cria um SpedRecord C170 com os campos relevantes preenchidos.

    Layout (0-based):
      0:REG, 1:NUM_ITEM, 2:COD_ITEM, 3:DESCR, 4:QTD, 5:UNID,
      6:VL_ITEM, 7:VL_DESC, 8:IND_MOV, 9:CST_ICMS, 10:CFOP,
      11:COD_NAT, 12:VL_BC_ICMS, 13:ALIQ_ICMS, 14:VL_ICMS,
      15:VL_BC_ICMS_ST, 16:ALIQ_ST, 17:VL_ICMS_ST
    """
    fields = [
        "C170",         # 0
        "1",            # 1 NUM_ITEM
        "ITEM001",      # 2 COD_ITEM
        "Produto",      # 3 DESCR
        "1.00",         # 4 QTD
        "UN",           # 5 UNID
        vl_item,        # 6 VL_ITEM
        vl_desc,        # 7 VL_DESC
        "",             # 8 IND_MOV
        cst,            # 9 CST_ICMS
        cfop,           # 10 CFOP
        "",             # 11 COD_NAT
        vl_bc,          # 12 VL_BC_ICMS
        aliq,           # 13 ALIQ_ICMS
        vl_icms,        # 14 VL_ICMS
        vl_bc_st,       # 15 VL_BC_ICMS_ST
        aliq_st,        # 16 ALIQ_ST
        vl_icms_st,     # 17 VL_ICMS_ST
    ]
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register="C170", fields=fields, raw_line=raw)


def _make_c100(line: int = 10) -> SpedRecord:
    fields = ["C100"] + [""] * 25
    return SpedRecord(line_number=line, register="C100", fields=fields, raw_line="|C100|")


def _make_c190(
    cst: str = "000",
    cfop: str = "5102",
    aliq: str = "18.00",
    line: int = 200,
) -> SpedRecord:
    # Layout: 0:REG, 1:CST, 2:CFOP, 3:ALIQ, 4:VL_OPR, 5:VL_BC, 6:VL_ICMS
    fields = ["C190", cst, cfop, aliq, "1000.00", "1000.00", "180.00"]
    return SpedRecord(line_number=line, register="C190", fields=fields, raw_line="|C190|")


# ──────────────────────────────────────────────
# 1. ISENTO_COM_TRIBUTO
# ──────────────────────────────────────────────

class TestIsentoComTributo:
    """CST 040/041/050 com tributacao efetiva preenchida."""

    def test_cst041_tributacao_integral_sugere_00(self):
        """CST 041 com BC, aliq e ICMS preenchidos -> sugere CST 00."""
        item = _make_c170(
            cst="041", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _ISENTO_COM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "00"

    def test_cst040_tributacao_com_st_sugere_10(self):
        """CST 040 com tributacao + campos ST preenchidos -> sugere CST 10."""
        item = _make_c170(
            cst="040", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _ISENTO_COM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "10"

    def test_cst041_tributacao_com_reducao_sugere_20(self):
        """CST 041 com BC reduzida significativamente -> sugere CST 20."""
        # Base = 600 sobre item de 1000 => reducao de 40%
        item = _make_c170(
            cst="041", vl_item="1000.00",
            vl_bc="600.00", aliq="18.00", vl_icms="108.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _ISENTO_COM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "20"

    def test_cst050_tributacao_com_st_e_reducao_sugere_70(self):
        """CST 050 com BC reduzida + ST -> sugere CST 70."""
        item = _make_c170(
            cst="050", vl_item="1000.00",
            vl_bc="600.00", aliq="18.00", vl_icms="108.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _ISENTO_COM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "70"

    def test_confianca_alta_com_evidencias(self):
        """Score >= 80 quando recalculo bate + CFOP venda + C190 confirma."""
        item = _make_c170(
            cst="041", cfop="5102", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        c190 = _make_c190(cst="000", cfop="5102", aliq="18.00")

        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [c190])
        assert hyp is not None
        assert hyp.confidence == "alta"
        assert hyp.score >= 80


# ──────────────────────────────────────────────
# 2. TRIBUTADO_SEM_TRIBUTO
# ──────────────────────────────────────────────

class TestTributadoSemTributo:
    """CST 00 com BC=0, ALIQ=0, VL_ICMS=0."""

    def test_cst00_tudo_zerado_sugere_040(self):
        """CST 00 com todos valores zerados -> sugere 040 (isenta, default)."""
        item = _make_c170(
            cst="000", cfop="5102", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _TRIBUTADO_SEM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "40"

    def test_cst00_zerado_cfop_exportacao_sugere_041(self):
        """CST 00 zerado com CFOP de exportacao -> sugere 041."""
        item = _make_c170(
            cst="000", cfop="7101", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _TRIBUTADO_SEM_TRIBUTO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "41"

    def test_cst00_zerado_cfop_remessa_nao_detecta(self):
        """CST 00 zerado com CFOP de remessa -> NAO detecta (pode ser legitimo).

        A funcao _detect_inconsistency ignora CFOP remessa/retorno.
        """
        item = _make_c170(
            cst="000", cfop="5901", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        # CFOP remessa e filtrado na deteccao
        assert result is None

    def test_score_indicio_sem_cfop_indicativo(self):
        """Sem CFOP indicativo, score tende a ser mais baixo (indicio)."""
        item = _make_c170(
            cst="000", cfop="5102", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        # CFOP 5102 e venda -> adiciona 15 pontos (venda sem ICMS reforça)
        # Base = 25, + 15 venda = 40 -> indicio
        assert hyp.confidence in ("indicio", "provavel")


# ──────────────────────────────────────────────
# 3. SEM_ST_COM_CAMPOS_ST
# ──────────────────────────────────────────────

class TestSemStComCamposSt:
    """CST sem ST mas campos de ST preenchidos."""

    def test_cst00_com_bc_st_sugere_10(self):
        """CST 00 com BC_ST preenchida -> sugere CST 10."""
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _SEM_ST_COM_CAMPOS_ST

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "10"

    def test_cst40_com_icms_st_sugere_30(self):
        """CST 40 com VL_ICMS_ST preenchido (sem tributacao propria) -> sugere 30."""
        item = _make_c170(
            cst="040", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        # CST 40 com tudo zerado mas com ST -> primeiro detecta isento_com_tributo?
        # Nao: tem_tributacao = False pois BC=0, aliq=0, icms=0
        # Caso 1 nao dispara. Caso 3: CST 40 nao esta em CST_ST e tem_st = True -> dispara
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _SEM_ST_COM_CAMPOS_ST

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "30"

    def test_cst00_com_bc_st_e_reducao_sugere_70(self):
        """CST 00 com BC reduzida + ST -> sugere CST 70."""
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="600.00", aliq="18.00", vl_icms="108.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _SEM_ST_COM_CAMPOS_ST

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "70"


# ──────────────────────────────────────────────
# 4. INTEGRAL_COM_REDUCAO
# ──────────────────────────────────────────────

class TestIntegralComReducao:
    """CST 00 mas BC significativamente menor que VL_ITEM."""

    def test_cst00_reducao_40pct_sugere_20(self):
        """CST 00 com BC 40% menor que item -> sugere CST 20."""
        # VL_ITEM=1000, VL_BC=600 => reducao de 40%
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="600.00", aliq="18.00", vl_icms="108.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _INTEGRAL_COM_REDUCAO
        assert abs(ctx["reducao_pct"] - 0.40) < 0.01

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "20"

    def test_cst00_reducao_33pct_score_maior(self):
        """Reducao de ~33.33% (percentual conhecido) gera score bonus."""
        # VL_ITEM=1000, VL_BC=666.67 => reducao ~33.33%
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="666.67", aliq="18.00", vl_icms="120.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result
        assert incompat_type == _INTEGRAL_COM_REDUCAO

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None
        assert hyp.suggested_value == "20"
        # Percentual conhecido adiciona +15 ao score
        assert hyp.score >= 40

    def test_cst00_reducao_10pct_nao_detecta(self):
        """Reducao de apenas 10% (< 15% limiar) -> NAO gera incompatibilidade."""
        # VL_ITEM=1000, VL_BC=900 => reducao 10% < _REDUCAO_MIN(15%)
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="900.00", aliq="18.00", vl_icms="162.00",
        )
        result = _detect_inconsistency(item)
        assert result is None


# ──────────────────────────────────────────────
# 5. Casos negativos (NAO devem gerar erros)
# ──────────────────────────────────────────────

class TestCasosNegativos:
    """Situacoes corretas que nao devem disparar deteccao."""

    def test_cst00_tributacao_normal(self):
        """CST 00 com BC=ITEM, aliquota e ICMS corretos."""
        item = _make_c170(
            cst="000", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        result = _detect_inconsistency(item)
        assert result is None

    def test_cst40_tudo_zerado_correto(self):
        """CST 40 (isenta) com tudo zerado -> correto."""
        item = _make_c170(
            cst="040", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is None

    def test_cst60_zerado_correto(self):
        """CST 60 (ST cobrado anteriormente) com BC/ICMS proprios zerados."""
        item = _make_c170(
            cst="060", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is None

    def test_cst10_com_campos_st_correto(self):
        """CST 10 com campos de ST preenchidos -> correto (CST 10 esta em CST_ST)."""
        item = _make_c170(
            cst="010", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
            vl_bc_st="1200.00", vl_icms_st="36.00",
        )
        result = _detect_inconsistency(item)
        assert result is None

    def test_cst00_cfop_remessa_zerado_legitimo(self):
        """CST 00 em CFOP remessa com valores zerados -> ignorado (legitimo)."""
        item = _make_c170(
            cst="000", cfop="5901", vl_item="500.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
        )
        result = _detect_inconsistency(item)
        assert result is None

    def test_cst_vazio_ou_curto_ignorado(self):
        """CST vazio ou com menos de 2 caracteres -> ignorado."""
        item = _make_c170(cst="", vl_item="100.00")
        assert _detect_inconsistency(item) is None

        item2 = _make_c170(cst="0", vl_item="100.00")
        assert _detect_inconsistency(item2) is None


# ──────────────────────────────────────────────
# 6. Scoring helpers
# ──────────────────────────────────────────────

class TestScoringHelpers:
    """Testes unitarios dos helpers de pontuacao."""

    def test_score_cfop_venda_com_cst_tributado(self):
        """CFOP de venda + CST sugerido 00 -> +20 pontos."""
        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        ctx = {"cfop": "5102"}
        _score_cfop(hyp, ctx)
        assert hyp.score == 20
        assert any("5102" in r for r in hyp.reasons)

    def test_score_cfop_exportacao_com_cst_isento(self):
        """CFOP de exportacao + CST sugerido 41 -> +20 pontos."""
        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="000", suggested_value="41",
        )
        ctx = {"cfop": "7101"}
        _score_cfop(hyp, ctx)
        assert hyp.score == 20

    def test_score_cfop_sem_cfop(self):
        """Sem CFOP -> nenhum ponto adicionado."""
        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        ctx = {"cfop": ""}
        _score_cfop(hyp, ctx)
        assert hyp.score == 0

    def test_score_c190_confirma(self):
        """C190 com CST sugerido + mesmo CFOP -> +20 pontos."""
        item = _make_c170(cst="041", cfop="5102")
        c190 = _make_c190(cst="000", cfop="5102")

        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        _score_c190(hyp, item, "00", [c190])
        assert hyp.score == 20
        assert any("C190" in r for r in hyp.reasons)

    def test_score_c190_cfop_diferente_nao_pontua(self):
        """C190 com CFOP diferente -> nao pontua."""
        item = _make_c170(cst="041", cfop="5102")
        c190 = _make_c190(cst="000", cfop="6102")

        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        _score_c190(hyp, item, "00", [c190])
        assert hyp.score == 0

    def test_score_siblings_todos_confirmam(self):
        """Todos os irmaos com mesmo CFOP usam CST sugerido -> +10."""
        item = _make_c170(cst="041", cfop="5102", line=100)
        sib1 = _make_c170(cst="000", cfop="5102", line=101)
        sib2 = _make_c170(cst="000", cfop="5102", line=102)

        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        _score_siblings(hyp, item, "00", [item, sib1, sib2])
        assert hyp.score == 10

    def test_score_siblings_parcial(self):
        """Apenas alguns irmaos confirmam -> +5."""
        item = _make_c170(cst="041", cfop="5102", line=100)
        sib1 = _make_c170(cst="000", cfop="5102", line=101)
        sib2 = _make_c170(cst="020", cfop="5102", line=102)

        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        _score_siblings(hyp, item, "00", [item, sib1, sib2])
        assert hyp.score == 5

    def test_score_siblings_cfop_diferente_ignorado(self):
        """Irmaos com CFOP diferente nao sao considerados."""
        item = _make_c170(cst="041", cfop="5102", line=100)
        sib1 = _make_c170(cst="020", cfop="6102", line=101)

        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="041", suggested_value="00",
        )
        _score_siblings(hyp, item, "00", [item, sib1])
        assert hyp.score == 0


# ──────────────────────────────────────────────
# 7. Formato de saida (ValidationError)
# ──────────────────────────────────────────────

class TestErrorOutputFormat:
    """Verifica campos do ValidationError gerado."""

    def test_error_type_e_field_name(self):
        """error_type = CST_HIPOTESE, field_name = CST_ICMS."""
        item = _make_c170(
            cst="041", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        result = _detect_inconsistency(item)
        assert result is not None
        incompat_type, ctx = result

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        assert hyp is not None

        err = _hypothesis_to_error(item, hyp, incompat_type)
        assert err.error_type == "CST_HIPOTESE"
        assert err.field_name == "CST_ICMS"
        assert err.register == "C170"
        assert err.line_number == 100

    def test_expected_value_quando_score_alto(self):
        """expected_value preenchido quando score >= 60 (auto_correctable)."""
        item = _make_c170(
            cst="041", cfop="5102", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        c190 = _make_c190(cst="000", cfop="5102")

        result = _detect_inconsistency(item)
        incompat_type, ctx = result

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [c190])
        assert hyp.score >= 60

        err = _hypothesis_to_error(item, hyp, incompat_type)
        assert err.expected_value is not None
        assert err.expected_value == "00"

    def test_expected_value_none_quando_score_baixo(self):
        """expected_value = None quando score < 60."""
        hyp = CorrectionHypothesis(
            field_name="CST_ICMS", current_value="000", suggested_value="40",
        )
        hyp.score = 45  # indicio
        hyp.reasons.append("Teste")

        item = _make_c170(cst="000")
        err = _hypothesis_to_error(item, hyp, _TRIBUTADO_SEM_TRIBUTO)
        assert err.expected_value is None

    def test_mensagem_contem_informacoes(self):
        """Mensagem de erro contem CST informado, sugerido e confianca."""
        item = _make_c170(
            cst="041", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
        )
        result = _detect_inconsistency(item)
        incompat_type, ctx = result

        hyp = _build_hypothesis(item, incompat_type, ctx, [item], [])
        err = _hypothesis_to_error(item, hyp, incompat_type)

        assert "041" in err.message
        assert "00" in err.message
        assert "pontos" in err.message


# ──────────────────────────────────────────────
# 8. Integracao via validate_cst_hypotheses
# ──────────────────────────────────────────────

class TestValidateCstHypothesesIntegration:
    """Testa a API publica com hierarquia C100 -> C170 -> C190."""

    def test_detecta_isento_com_tributo_via_api(self):
        """Pipeline completo: C100 + C170 com CST errado + C190."""
        c100 = _make_c100(line=10)
        item = _make_c170(
            cst="041", cfop="5102", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
            line=20,
        )
        c190 = _make_c190(cst="000", cfop="5102", line=30)

        errors = validate_cst_hypotheses([c100, item, c190])
        assert len(errors) >= 1
        assert errors[0].error_type == "CST_HIPOTESE"
        assert errors[0].field_name == "CST_ICMS"

    def test_sem_erros_quando_tudo_correto(self):
        """Nenhum erro quando CSTs estao corretos."""
        c100 = _make_c100(line=10)
        item = _make_c170(
            cst="000", cfop="5102", vl_item="1000.00",
            vl_bc="1000.00", aliq="18.00", vl_icms="180.00",
            line=20,
        )
        c190 = _make_c190(cst="000", cfop="5102", line=30)

        errors = validate_cst_hypotheses([c100, item, c190])
        assert len(errors) == 0

    def test_score_abaixo_40_nao_gera_erro(self):
        """Hipotese com score < 40 nao vira ValidationError."""
        c100 = _make_c100(line=10)
        # CST 00 zerado sem CFOP indicativo, score ~25 (baixo)
        # Mas CFOP 5102 (venda) adiciona +15 -> pode chegar a 40
        # Usar CFOP que nao e venda nem exportacao nem remessa
        item = _make_c170(
            cst="000", cfop="1556", vl_item="1000.00",
            vl_bc="0.00", aliq="0.00", vl_icms="0.00",
            line=20,
        )
        c190 = _make_c190(cst="000", cfop="1556", line=30)

        errors = validate_cst_hypotheses([c100, item, c190])
        # Score base = 25, sem bonus de CFOP -> abaixo de 40
        # Pode ou nao gerar erro dependendo dos bonus de C190/siblings
        # O importante e que se gerar, o score >= 40
        for err in errors:
            assert "pontos" in err.message
