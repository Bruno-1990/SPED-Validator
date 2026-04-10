"""Testes do beneficio_cross_validator — cruzamento beneficios x JSON x SPED."""

from __future__ import annotations

import pytest

from src.models import SpedRecord
from src.services.context_builder import ValidationContext, TaxRegime
from src.services.reference_loader import ReferenceLoader
from src.validators.beneficio_cross_validator import validate_beneficio_cross


# ── Helpers ──

_loader = ReferenceLoader()


def _rec(register: str, fields: dict[str, str], line: int = 1) -> SpedRecord:
    return SpedRecord(register=register, fields=fields, line_number=line, raw_line="")


def _ctx(*codigos: str) -> ValidationContext:
    ctx = ValidationContext(file_id=1)
    ctx.beneficios_ativos = _loader.get_beneficios_do_cliente(list(codigos))
    return ctx


def _e110(debitos: str = "100000", creditos: str = "80000", saldo_credor: str = "0") -> SpedRecord:
    return _rec("E110", {
        "VL_TOT_DEBITOS": debitos,
        "VL_AJ_DEBITOS": "0",
        "VL_TOT_CREDITOS": creditos,
        "VL_AJ_CREDITOS": "0",
        "VL_SLD_CREDOR_TRANSPORTAR": saldo_credor,
    })


def _e111(cod_aj: str, descr: str, valor: str, line: int = 2) -> SpedRecord:
    return _rec("E111", {
        "COD_AJ_APUR": cod_aj,
        "DESCR_COMPL_AJ": descr,
        "VL_AJ_APUR": valor,
    }, line=line)


def _e116(cod_rec: str, valor: str = "1000", line: int = 3) -> SpedRecord:
    return _rec("E116", {
        "COD_OR": "000",
        "VL_OR": valor,
        "DT_VCTO": "15012024",
        "COD_REC": cod_rec,
        "NUM_PROC": "",
        "IND_PROC": "",
    }, line=line)


def _c190(cst: str, cfop: str, aliq: str = "12", vl_opr: str = "50000") -> SpedRecord:
    return _rec("C190", {
        "CST_ICMS": cst,
        "CFOP": cfop,
        "ALIQ_ICMS": aliq,
        "VL_OPR": vl_opr,
    })


def _c170(cfop: str, cst: str, vl_icms: str = "0", cod_item: str = "", line: int = 10) -> SpedRecord:
    return _rec("C170", {
        "CFOP": cfop,
        "CST_ICMS": cst,
        "VL_ICMS": vl_icms,
        "COD_ITEM": cod_item,
    }, line=line)


def _tipos(errors):
    return {e.error_type for e in errors}


# ── Testes: sem beneficio = sem erro ──

class TestShortCircuit:
    def test_sem_contexto(self):
        assert validate_beneficio_cross([_e110()], context=None) == []

    def test_sem_beneficios_ativos(self):
        ctx = ValidationContext(file_id=1)
        assert validate_beneficio_cross([_e110()], context=ctx) == []


# ── CROSS_004a: apuracao nao segregada ──

class TestCross004a:
    def test_sem_e111_dispara(self):
        errors = validate_beneficio_cross([_e110()], context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_APURACAO_NAO_SEGREGADA" in _tipos(errors)

    def test_com_e111_relacionado_nao_dispara(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA credito presumido", "5000"),
            _e116("380-8"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_APURACAO_NAO_SEGREGADA" not in _tipos(errors)

    def test_e111_nao_relacionado_ainda_dispara(self):
        records = [
            _e110(),
            _e111("ES010001", "ajuste generico qualquer", "1000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_APURACAO_NAO_SEGREGADA" in _tipos(errors)

    def test_fundap_sem_e111_dispara(self):
        errors = validate_beneficio_cross([_e110()], context=_ctx("FUNDAP"))
        assert "BENE_CROSS_APURACAO_NAO_SEGREGADA" in _tipos(errors)

    def test_invest_industria_sem_e111_dispara(self):
        errors = validate_beneficio_cross([_e110()], context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_APURACAO_NAO_SEGREGADA" in _tipos(errors)


# ── CROSS_004b: codigo receita incorreto ──

class TestCross004b:
    def test_compete_atk_sem_e116_nao_dispara(self):
        """Sem E116 nenhum, a verificacao nao se aplica (ausencia total e outro problema)."""
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA presumido", "5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CODIGO_RECEITA_INCORRETO" not in _tipos(errors)

    def test_compete_atk_e116_codigo_errado_dispara(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA presumido", "5000"),
            _e116("999-9"),  # codigo errado, deveria ser 380-8
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CODIGO_RECEITA_INCORRETO" in _tipos(errors)

    def test_compete_atk_e116_codigo_correto_nao_dispara(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA presumido", "5000"),
            _e116("380-8"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CODIGO_RECEITA_INCORRETO" not in _tipos(errors)

    def test_compete_ecommerce_codigo_385_9(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ecommerce credito presumido", "5000"),
            _e116("385-9"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_VAREJISTA_ECOMMERCE"))
        assert "BENE_CROSS_CODIGO_RECEITA_INCORRETO" not in _tipos(errors)

    def test_beneficio_sem_codigo_receita_nao_verifica(self):
        """FUNDAP nao tem codigo receita proprio — nao deve disparar."""
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime especial", "5000"),
            _e116("121-0"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP"))
        assert "BENE_CROSS_CODIGO_RECEITA_INCORRETO" not in _tipos(errors)


# ── CROSS_005: estorno ausente ──

class TestCross005:
    def test_invest_importacao_saldo_credor_sem_exportacao(self):
        records = [
            _e110(debitos="50000", creditos="80000", saldo_credor="30000"),
            _e111("ES020002", "INVEST importacao credito", "10000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_IMPORTACAO"))
        assert "BENE_CROSS_ESTORNO_AUSENTE" in _tipos(errors)

    def test_invest_importacao_saldo_credor_com_exportacao_ok(self):
        records = [
            _e110(debitos="50000", creditos="80000", saldo_credor="30000"),
            _e111("ES020002", "INVEST importacao credito", "10000"),
            _c190("020", "7101"),  # exportacao
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_IMPORTACAO"))
        assert "BENE_CROSS_ESTORNO_AUSENTE" not in _tipos(errors)

    def test_invest_importacao_sem_saldo_credor_ok(self):
        records = [
            _e110(debitos="100000", creditos="80000", saldo_credor="0"),
            _e111("ES020002", "INVEST importacao credito", "10000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_IMPORTACAO"))
        assert "BENE_CROSS_ESTORNO_AUSENTE" not in _tipos(errors)

    def test_compete_graficas_sem_estorno(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE grafica credito presumido", "5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_GRAFICAS"))
        assert "BENE_CROSS_ESTORNO_AUSENTE" in _tipos(errors)

    def test_compete_graficas_com_estorno_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE grafica credito presumido", "5000"),
            _e111("ES010001", "estorno proporcional credito grafica", "1000", line=3),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_GRAFICAS"))
        assert "BENE_CROSS_ESTORNO_AUSENTE" not in _tipos(errors)


# ── CROSS_006: cumulacao vedada ──

class TestCross006:
    def test_fundap_compete_atk_ambos_e111_periodo(self):
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime especial", "5000"),
            _e111("ES020004", "COMPETE ATACADISTA credito presumido 380-8", "3000", line=3),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP", "COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CUMULACAO_VEDADA_PERIODO" in _tipos(errors)

    def test_fundap_compete_atk_c190_mistura_documento(self):
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime", "5000"),
            _e111("ES020004", "COMPETE ATACADISTA 380-8", "3000", line=3),
            _c190("020", "3101"),  # FUNDAP: importacao + CST 20
            _c190("020", "6101"),  # COMPETE ATK: interestadual + CST 20
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP", "COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CUMULACAO_VEDADA_DOCUMENTO" in _tipos(errors)

    def test_sem_par_vedado_nao_dispara(self):
        """FUNDAP + INVEST_ES_INDUSTRIA nao estao nos pares vedados diretos."""
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime", "5000"),
            _e111("ES020004", "INVEST industria credito", "3000", line=3),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP", "INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_CUMULACAO_VEDADA_PERIODO" not in _tipos(errors)

    def test_invest_compete_cumulacao_periodo(self):
        records = [
            _e110(),
            _e111("ES020002", "INVEST industria credito presumido", "5000"),
            _e111("ES020004", "COMPETE ATACADISTA presumido 380-8", "3000", line=3),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA", "COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CUMULACAO_VEDADA_PERIODO" in _tipos(errors)


# ── CROSS_007: limite credito entrada (alerta) ──

class TestCross007:
    def test_compete_atk_sem_estorno_alerta(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA credito presumido", "5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CREDITO_ENTRADA_ALERTA" in _tipos(errors)

    def test_compete_atk_com_estorno_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE ATACADISTA credito presumido", "5000"),
            _e111("ES010001", "estorno credito limite 7%", "500", line=3),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CREDITO_ENTRADA_ALERTA" not in _tipos(errors)

    def test_fundap_sem_limite_nao_alerta(self):
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime especial", "5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP"))
        assert "BENE_CROSS_CREDITO_ENTRADA_ALERTA" not in _tipos(errors)


# ── CROSS_008: credito presumido base incorreta (INVEST-ES Industria) ──

class TestCross008:
    def test_credito_presumido_acima_70pct(self):
        # ICMS apurado = 100000 - 20000 = 80000; 60000 / 80000 = 75%
        records = [
            _e110(debitos="100000", creditos="20000"),
            _e111("ES020002", "INVEST-ES credito presumido industria", "60000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA" in _tipos(errors)

    def test_credito_presumido_dentro_70pct_ok(self):
        # ICMS apurado = 100000 - 20000 = 80000; 50000 / 80000 = 62.5%
        records = [
            _e110(debitos="100000", creditos="20000"),
            _e111("ES020002", "INVEST-ES credito presumido industria", "50000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA" not in _tipos(errors)

    def test_sem_icms_a_pagar_nao_dispara(self):
        # ICMS apurado = 50000 - 80000 = -30000 (negativo)
        records = [
            _e110(debitos="50000", creditos="80000"),
            _e111("ES020002", "INVEST-ES credito presumido industria", "60000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA" not in _tipos(errors)

    def test_nao_aplica_compete(self):
        """CROSS_008 e exclusivo do INVEST-ES Industria."""
        records = [
            _e110(debitos="100000", creditos="20000"),
            _e111("ES020002", "COMPETE ATACADISTA presumido", "60000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_ATACADISTA"))
        assert "BENE_CROSS_CREDITO_PRESUMIDO_BASE_INCORRETA" not in _tipos(errors)


# ── CROSS_009: diferimento creditado (INVEST-ES Industria) ──

class TestCross009:
    def test_compra_interna_diferida_com_credito(self):
        records = [
            _e110(),
            _e111("ES020002", "INVEST industria presumido", "5000"),
            _c170("1101", "051", vl_icms="5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_DIFERIMENTO_CREDITADO" in _tipos(errors)

    def test_compra_interna_diferida_sem_credito_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "INVEST industria presumido", "5000"),
            _c170("1101", "051", vl_icms="0"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_DIFERIMENTO_CREDITADO" not in _tipos(errors)

    def test_compra_interna_tributada_com_credito_ok(self):
        """CST 00 (tributado normal) com credito nao e erro."""
        records = [
            _e110(),
            _e111("ES020002", "INVEST industria presumido", "5000"),
            _c170("1101", "000", vl_icms="5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("INVEST_ES_INDUSTRIA"))
        assert "BENE_CROSS_DIFERIMENTO_CREDITADO" not in _tipos(errors)

    def test_nao_aplica_fundap(self):
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime especial", "5000"),
            _c170("1101", "051", vl_icms="5000"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP"))
        assert "BENE_CROSS_DIFERIMENTO_CREDITADO" not in _tipos(errors)


# ── CROSS_010: NCM nao autorizada diferimento (COMPETE Papelao) ──

class TestCross010:
    def test_ncm_fora_3901_3903_dispara(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE papelao credito", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39041000"}),
            _c170("3101", "051", cod_item="ITEM01"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_PAPELAO_MAT_PLAST"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" in _tipos(errors)

    def test_ncm_3901_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE papelao credito", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39011000"}),
            _c170("3101", "051", cod_item="ITEM01"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_PAPELAO_MAT_PLAST"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" not in _tipos(errors)

    def test_ncm_3902_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE papelao credito", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39021010"}),
            _c170("3101", "051", cod_item="ITEM01"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_PAPELAO_MAT_PLAST"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" not in _tipos(errors)

    def test_ncm_3903_ok(self):
        records = [
            _e110(),
            _e111("ES020002", "COMPETE papelao credito", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39031900"}),
            _c170("3101", "051", cod_item="ITEM01"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_PAPELAO_MAT_PLAST"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" not in _tipos(errors)

    def test_cfop_nao_importacao_nao_dispara(self):
        """Apenas CFOP 3101 com CST 51 dispara."""
        records = [
            _e110(),
            _e111("ES020002", "COMPETE papelao credito", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39041000"}),
            _c170("5101", "051", cod_item="ITEM01"),  # saida interna, nao importacao
        ]
        errors = validate_beneficio_cross(records, context=_ctx("COMPETE_IND_PAPELAO_MAT_PLAST"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" not in _tipos(errors)

    def test_nao_aplica_fundap(self):
        records = [
            _e110(),
            _e111("ES020002", "FUNDAP regime", "5000"),
            _rec("0200", {"COD_ITEM": "ITEM01", "COD_NCM": "39041000"}),
            _c170("3101", "051", cod_item="ITEM01"),
        ]
        errors = validate_beneficio_cross(records, context=_ctx("FUNDAP"))
        assert "BENE_CROSS_NCM_NAO_AUTORIZADA_DIFERIMENTO" not in _tipos(errors)


# ── BeneficioProfile: carregamento ──

class TestBeneficioProfileLoader:
    def test_todos_beneficios_carregam(self):
        codigos = [
            "FUNDAP", "COMPETE_ATACADISTA", "COMPETE_VAREJISTA_ECOMMERCE",
            "COMPETE_IND_GRAFICAS", "COMPETE_IND_PAPELAO_MAT_PLAST",
            "INVEST_ES_INDUSTRIA", "INVEST_ES_IMPORTACAO",
            "SUBSTITUICAO_TRIBUTARIA_ES",
        ]
        for cod in codigos:
            perfil = _loader.get_beneficio(cod)
            assert perfil is not None, f"{cod} nao carregou"
            assert perfil.codigo == cod
            assert len(perfil.cfops) > 0
            assert len(perfil.csts) > 0

    def test_inexistente_retorna_none(self):
        assert _loader.get_beneficio("NAO_EXISTE") is None

    def test_cfops_normalizados(self):
        """CFOPs de ST como '1403 -- compra...' devem virar '1403'."""
        st = _loader.get_beneficio("SUBSTITUICAO_TRIBUTARIA_ES")
        assert st is not None
        assert "1403" in st.cfops
        assert "2403" in st.cfops
        assert "5401" in st.cfops

    def test_codigos_receita_compete_atk(self):
        atk = _loader.get_beneficio("COMPETE_ATACADISTA")
        assert atk is not None
        assert "380-8" in atk.codigos_receita.values()

    def test_codigos_receita_graficas_dual(self):
        grf = _loader.get_beneficio("COMPETE_IND_GRAFICAS")
        assert grf is not None
        assert "938-5" in grf.codigos_receita.values()
        assert "937-7" in grf.codigos_receita.values()

    def test_apto_producao_cbenef_false(self):
        """Todos os beneficios ainda tem cbenef pendente."""
        for cod in ["FUNDAP", "COMPETE_ATACADISTA", "INVEST_ES_INDUSTRIA"]:
            perfil = _loader.get_beneficio(cod)
            assert perfil is not None
            assert perfil.apto_producao_cbenef is False

    def test_exige_estorno_correto(self):
        assert _loader.get_beneficio("COMPETE_IND_GRAFICAS").exige_estorno is True
        assert _loader.get_beneficio("INVEST_ES_IMPORTACAO").exige_estorno is True
        assert _loader.get_beneficio("COMPETE_ATACADISTA").exige_estorno is False
        assert _loader.get_beneficio("FUNDAP").exige_estorno is False

    def test_get_beneficios_do_cliente_filtra(self):
        result = _loader.get_beneficios_do_cliente(["FUNDAP", "NAO_EXISTE", "COMPETE_ATACADISTA"])
        assert len(result) == 2
        codigos = {b.codigo for b in result}
        assert codigos == {"FUNDAP", "COMPETE_ATACADISTA"}
