"""Tests for src/validators/beneficio_audit_validator.py.

Covers the main audit rules using synthetic SpedRecord data:
- _E111Agrupado class and properties
- _BeneficioContext pre-processing
- Individual audit rules (debito_integral, e111_sem_rastreabilidade,
  e111_soma_vs_e110, devolucao_sem_reversao, saldo_credor_recorrente,
  sobreposicao_beneficios, beneficio_desproporcional, st_apuracao,
  e111_codigo_generico, checklist_auditoria, inventario_reflexo,
  beneficio_sem_governanca, totalizacao_beneficiada, c190_mistura_cst,
  sped_vs_contribuicoes, codigo_ajuste_incompativel, trilha_beneficio_ausente,
  meta-rules)
"""

from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message='Field name "register".*shadows an attribute',
    category=UserWarning,
)


from src.models import SpedRecord  # noqa: E402
from src.validators.beneficio_audit_validator import validate_beneficio_audit  # noqa: E402

# ──────────────────────────────────────────────
# Helper: build SpedRecord from a dict
# ──────────────────────────────────────────────

def _rec(register: str, fields: dict[str, str], line: int = 1) -> SpedRecord:
    return SpedRecord(
        line_number=line,
        register=register,
        fields={"REG": register, **fields},
        raw_line="|" + "|".join([register] + list(fields.values())) + "|",
    )


def _c170(line: int = 10, cst: str = "000", cfop: str = "5102",
          aliq: str = "18", vl_icms: str = "180", cod_item: str = "ITEM1",
          cst_pis: str = "", cst_cofins: str = "", **extra) -> SpedRecord:
    fields = {
        "NUM_ITEM": "1", "COD_ITEM": cod_item, "DESCR_COMPL": "Produto",
        "QTD": "10", "UNID": "UN", "VL_ITEM": "1000", "VL_DESC": "0",
        "IND_MOV": "0", "CST_ICMS": cst, "CFOP": cfop, "COD_NAT": "001",
        "VL_BC_ICMS": "1000", "ALIQ_ICMS": aliq, "VL_ICMS": vl_icms,
        "VL_BC_ICMS_ST": "0", "ALIQ_ST": "0", "VL_ICMS_ST": "0",
        "IND_APUR": "0", "CST_IPI": "50", "COD_ENQ": "", "VL_BC_IPI": "0",
        "ALIQ_IPI": "0", "VL_IPI": "0", "CST_PIS": cst_pis,
        "VL_BC_PIS": "0", "ALIQ_PIS": "0", "QUANT_BC_PIS": "0",
        "ALIQ_PIS_REAIS": "0", "VL_PIS": "0", "CST_COFINS": cst_cofins,
        "VL_BC_COFINS": "0", "ALIQ_COFINS": "0", "QUANT_BC_COFINS": "0",
        "ALIQ_COFINS_REAIS": "0", "VL_COFINS": "0", "COD_CTA": "",
        "VL_ABAT_NT": "0",
    }
    fields.update(extra)
    return _rec("C170", fields, line)


def _c190(line: int = 20, cst: str = "000", cfop: str = "5102",
          aliq: str = "18", vl_opr: str = "1000", vl_bc: str = "1000",
          vl_icms: str = "180") -> SpedRecord:
    return _rec("C190", {
        "CST_ICMS": cst, "CFOP": cfop, "ALIQ_ICMS": aliq,
        "VL_OPR": vl_opr, "VL_BC_ICMS": vl_bc, "VL_ICMS": vl_icms,
        "VL_BC_ICMS_ST": "0", "VL_ICMS_ST": "0", "VL_RED_BC": "0",
        "VL_IPI": "0", "COD_OBS": "",
    }, line)


def _e110(vl_tot_debitos: str = "180", vl_aj_debitos: str = "0",
          vl_tot_aj_debitos: str = "0", vl_estornos_cred: str = "0",
          vl_tot_creditos: str = "100", vl_aj_creditos: str = "0",
          vl_tot_aj_creditos: str = "0", vl_estornos_deb: str = "0",
          vl_sld_credor: str = "0", vl_tot_ded: str = "0",
          line: int = 50) -> SpedRecord:
    return _rec("E110", {
        "VL_TOT_DEBITOS": vl_tot_debitos,
        "VL_AJ_DEBITOS": vl_aj_debitos,
        "VL_TOT_AJ_DEBITOS": vl_tot_aj_debitos,
        "VL_ESTORNOS_CRED": vl_estornos_cred,
        "VL_TOT_CREDITOS": vl_tot_creditos,
        "VL_AJ_CREDITOS": vl_aj_creditos,
        "VL_TOT_AJ_CREDITOS": vl_tot_aj_creditos,
        "VL_ESTORNOS_DEB": vl_estornos_deb,
        "VL_SLD_CREDOR_ANT": "0",
        "VL_SLD_APURADO": "0",
        "VL_TOT_DED": vl_tot_ded,
        "VL_ICMS_RECOLHER": "80",
        "VL_SLD_CREDOR_TRANSPORTAR": vl_sld_credor,
        "DEB_ESP": "0",
    }, line)


def _e111(cod_aj: str = "SP020001", descr: str = "Ajuste de credito presumido",
          valor: str = "500", line: int = 55) -> SpedRecord:
    return _rec("E111", {
        "COD_AJ_APUR": cod_aj,
        "DESCR_COMPL_AJ": descr,
        "VL_AJ_APUR": valor,
    }, line)


def _e112(line: int = 56) -> SpedRecord:
    return _rec("E112", {
        "NUM_DA": "123", "NUM_PROC": "456", "IND_PROC": "0",
        "PROC": "ABC", "TXT_COMPL": "Complemento",
    }, line)


def _e113(line: int = 57) -> SpedRecord:
    return _rec("E113", {
        "COD_PART": "P001", "COD_MOD": "55", "SER": "1",
        "SUB": "", "NUM_DOC": "100", "DT_DOC": "01012024",
        "COD_ITEM": "ITEM1", "VL_AJ_ITEM": "500",
        "CHV_DOCe": "12345678901234567890123456789012345678901234",
    }, line)


def _c100(line: int = 5, cod_part: str = "P001") -> SpedRecord:
    return _rec("C100", {
        "IND_OPER": "1", "IND_EMIT": "0", "COD_PART": cod_part,
        "COD_MOD": "55", "COD_SIT": "00", "SER": "1",
        "NUM_DOC": "100", "CHV_NFE": "", "DT_DOC": "01012024",
        "DT_E_S": "01012024", "VL_DOC": "1000",
        "IND_PGTO": "0", "VL_DESC": "0", "VL_ABAT_NT": "0",
        "VL_MERC": "1000", "IND_FRT": "0", "VL_FRT": "0",
        "VL_SEG": "0", "VL_OUT_DA": "0", "VL_BC_ICMS": "1000",
        "VL_ICMS": "180", "VL_BC_ICMS_ST": "0", "VL_ICMS_ST": "0",
        "VL_IPI": "0", "VL_PIS": "0", "VL_COFINS": "0",
        "VL_PIS_ST": "0", "VL_COFINS_ST": "0",
    }, line)


def _h010(cod_item: str = "ITEM1", qtd: str = "10", vl_item: str = "100",
          line: int = 80) -> SpedRecord:
    return _rec("H010", {
        "COD_ITEM": cod_item, "UNID": "UN", "QTD": qtd,
        "VL_UNIT": "10", "VL_ITEM": vl_item, "IND_PROP": "0",
        "COD_PART": "", "TXT_COMPL": "", "COD_CTA": "",
        "VL_ITEM_IR": "0",
    }, line)


def _e210(vl_sld: str = "500", line: int = 60) -> SpedRecord:
    return _rec("E210", {
        "IND_MOV_ST": "0", "VL_SLD_CRED_ANT_ST": "0",
        "VL_DEVOL_ST": "0", "VL_RESSARC_ST": "0",
        "VL_OUT_CRED_ST": "0", "VL_AJ_CREDITOS_ST": "0",
        "VL_RETENCAO_ST": "0", "VL_OUT_DEB_ST": "0",
        "VL_AJ_DEBITOS_ST": "0", "VL_SLD_DEV_ANT_ST": vl_sld,
        "VL_DEDUCOES_ST": "0", "VL_ICMS_RECOL_ST": "0",
        "VL_SLD_CRED_ST_TRANSPORTAR": "0", "DEB_ESP_ST": "0",
    }, line)


def _e210_st(vl_retencao: str = "500", line: int = 60) -> SpedRecord:
    """E210 com VL_RETENCAO_ST preenchido (cenario real de ST nos docs)."""
    return _rec("E210", {
        "IND_MOV_ST": "0", "VL_SLD_CRED_ANT_ST": "0",
        "VL_DEVOL_ST": "0", "VL_RESSARC_ST": "0",
        "VL_OUT_CRED_ST": "0", "VL_AJ_CREDITOS_ST": "0",
        "VL_RETENCAO_ST": vl_retencao, "VL_OUT_DEB_ST": "0",
        "VL_AJ_DEBITOS_ST": "0", "VL_SLD_DEV_ANT_ST": vl_retencao,
        "VL_DEDUCOES_ST": "0", "VL_ICMS_RECOL_ST": vl_retencao,
        "VL_SLD_CRED_ST_TRANSPORTAR": "0", "DEB_ESP_ST": "0",
    }, line)


def _0000(uf: str = "SP", line: int = 1) -> SpedRecord:
    return _rec("0000", {
        "COD_VER": "017", "COD_FIN": "0", "DT_INI": "01012024",
        "DT_FIN": "31012024", "NOME": "Empresa Teste",
        "CNPJ": "12345678000195", "CPF": "", "UF": uf,
        "IE": "123456789", "COD_MUN": "3550308", "IM": "",
        "SUFRAMA": "", "IND_PERFIL": "A", "IND_ATIV": "0",
    }, line)


def _0150(cod_part: str = "P001", uf: str = "MG", line: int = 2) -> SpedRecord:
    return _rec("0150", {
        "COD_PART": cod_part, "NOME": "Participante",
        "COD_PAIS": "1058", "CNPJ": "98765432000100",
        "CPF": "", "IE": "111222333", "COD_MUN": "3106200",
        "SUFRAMA": "", "END": "Rua Teste", "NUM": "100",
        "COMPL": "", "BAIRRO": "Centro", "UF": uf,
    }, line)


def _0200(cod_item: str = "ITEM1", line: int = 3) -> SpedRecord:
    return _rec("0200", {
        "COD_ITEM": cod_item, "DESCR_ITEM": "Produto Teste",
        "COD_BARRA": "", "COD_ANT_ITEM": "", "UNID_INV": "UN",
        "TIPO_ITEM": "00", "COD_NCM": "12345678", "EX_IPI": "",
        "COD_GEN": "12", "COD_LST": "", "ALIQ_ICMS": "18",
    }, line)


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

class TestEmptyRecords:
    def test_no_records(self):
        assert validate_beneficio_audit([]) == []

    def test_minimal_records(self):
        """Only 0000 — should not crash, may produce checklist error."""
        errors = validate_beneficio_audit([_0000()])
        types = {e.error_type for e in errors}
        # Should at least produce CHECKLIST_INCOMPLETO (missing many registers)
        assert "CHECKLIST_INCOMPLETO" in types


class TestChecklistAuditoria:
    def test_complete_checklist_no_error(self):
        """With all essential registers present, no CHECKLIST_INCOMPLETO."""
        records = [
            _0000(), _0150(), _0200(),
            _c100(), _c170(), _c190(),
            _e110(), _e111(), _h010(),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CHECKLIST_INCOMPLETO" not in types

    def test_incomplete_checklist(self):
        records = [_0000(), _c170()]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CHECKLIST_INCOMPLETO" in types


class TestDebitoIntegral:
    def test_debito_matches_no_error(self):
        """C190 ICMS == E110 VL_TOT_DEBITOS => no BENEFICIO_DEBITO_NAO_INTEGRAL."""
        records = [
            _0000(), _c190(vl_icms="180"), _e110(vl_tot_debitos="180"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_DEBITO_NAO_INTEGRAL" not in types

    def test_debito_diverge_with_e111_no_error(self):
        """Divergence present but E111 exists => no error (justified)."""
        records = [
            _0000(), _c190(vl_icms="180"), _e110(vl_tot_debitos="100"),
            _e111(),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_DEBITO_NAO_INTEGRAL" not in types

    def test_debito_diverge_without_e111(self):
        """Divergence without E111 => BENEFICIO_DEBITO_NAO_INTEGRAL."""
        records = [
            _0000(), _c190(vl_icms="180"), _e110(vl_tot_debitos="50"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_DEBITO_NAO_INTEGRAL" in types


class TestE111SemRastreabilidade:
    def test_e111_with_lastro_no_error(self):
        """E111 with E112 child => has lastro, no error."""
        records = [
            _0000(), _e110(), _e111(valor="5000", line=55), _e112(line=56),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_SEM_LASTRO_DOCUMENTAL" not in types

    def test_e111_without_lastro(self):
        """E111 with valor > 1000 and no E112/E113 => error."""
        records = [
            _0000(), _e110(), _e111(valor="5000", line=55),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_SEM_LASTRO_DOCUMENTAL" in types

    def test_e111_small_value_no_error(self):
        """E111 with valor <= 1000 => no error even without lastro."""
        records = [
            _0000(), _e110(), _e111(valor="500", line=55),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_SEM_LASTRO_DOCUMENTAL" not in types


class TestE111SomaVsE110:
    def test_soma_matches(self):
        """E111 sum matches E110 fields => no AJUSTE_SOMA_DIVERGENTE."""
        records = [
            _0000(),
            _e110(vl_tot_aj_creditos="500"),
            _e111(cod_aj="SP020001", valor="500"),  # natureza 2 = creditos
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_SOMA_DIVERGENTE" not in types

    def test_soma_diverges(self):
        """E111 sum != E110 field => AJUSTE_SOMA_DIVERGENTE."""
        records = [
            _0000(),
            _e110(vl_tot_aj_creditos="100"),
            _e111(cod_aj="SP020001", valor="500"),  # natureza 2 = creditos
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_SOMA_DIVERGENTE" in types


class TestDevolucaoSemReversao:
    def test_devolucao_above_5pct(self):
        """Devolucoes > 5% with E111 => DEVOLUCAO_BENEFICIO_NAO_REVERTIDO."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_opr="800", vl_icms="144"),
            _c190(cfop="1201", vl_opr="200", vl_icms="0", line=21),  # devolucao
            _e110(),
            _e111(valor="100"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO" in types

    def test_devolucao_below_5pct_no_error(self):
        """Devolucoes < 5% => no error."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_opr="9800", vl_icms="1764"),
            _c190(cfop="1201", vl_opr="10", vl_icms="0", line=21),
            _e110(),
            _e111(valor="100"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "DEVOLUCAO_BENEFICIO_NAO_REVERTIDO" not in types


class TestSaldoCredorRecorrente:
    def test_saldo_credor_with_saidas(self):
        """Saldo credor > 0 with saidas tributadas => warning."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_icms="180"),
            _e110(vl_sld_credor="5000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SALDO_CREDOR_RECORRENTE" in types

    def test_no_saldo_credor(self):
        records = [
            _0000(),
            _c190(cfop="5102", vl_icms="180"),
            _e110(vl_sld_credor="0"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SALDO_CREDOR_RECORRENTE" not in types


class TestSobreposicaoBeneficios:
    def test_cst020_with_credito_presumido(self):
        """CST 020 items + credito presumido in E111 => SOBREPOSICAO_BENEFICIOS."""
        records = [
            _0000(),
            _c170(cst="020", cfop="6102", aliq="7", line=10, vl_icms="70"),
            _e110(),
            _e111(cod_aj="SP020001", descr="Credito presumido outorgado", valor="500"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SOBREPOSICAO_BENEFICIOS" in types
        assert "MISTURA_INSTITUTOS_TRIBUTARIOS" in types

    def test_no_cst020(self):
        records = [
            _0000(),
            _c170(cst="000", cfop="5102", line=10),
            _e110(),
            _e111(cod_aj="SP020001", descr="Credito presumido", valor="500"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SOBREPOSICAO_BENEFICIOS" not in types


class TestBeneficioDesproporcional:
    def test_creditos_exceed_interestadual(self):
        """E111 creditos > ICMS interestadual => BENEFICIO_VALOR_DESPROPORCIONAL."""
        records = [
            _0000(),
            _c190(cfop="6102", vl_icms="100", vl_opr="1000", line=20),
            _e110(),
            _e111(cod_aj="SP020001", valor="500"),  # natureza 2 = credito
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_VALOR_DESPROPORCIONAL" in types

    def test_creditos_within_limit(self):
        records = [
            _0000(),
            _c190(cfop="6102", vl_icms="1000", vl_opr="10000", line=20),
            _e110(),
            _e111(cod_aj="SP020001", valor="500"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_VALOR_DESPROPORCIONAL" not in types


class TestStApuracao:
    def test_st_inconsistente_c170_com_st(self):
        """C170 with VL_ICMS_ST > 0 and E210 divergent => ST_APURACAO_INCONSISTENTE."""
        records = [
            _0000(),
            _rec("E200", {"UF": "SP", "DT_INI": "01012024", "DT_FIN": "31012024"}, line=55),
            _c170(cst="010", cfop="5102", VL_ICMS_ST="300", line=10),
            _e210_st(vl_retencao="100"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "ST_APURACAO_INCONSISTENTE" in types

    def test_st_inconsistente_sem_c170_fallback_c100(self):
        """Sem C170, usa C100.VL_ICMS_ST como fallback."""
        records = [
            _0000(),
            _rec("E200", {"UF": "MG", "DT_INI": "01012024", "DT_FIN": "31012024"}, line=55),
            _rec("C100", {
                "IND_OPER": "1", "IND_EMIT": "0", "COD_PART": "P1",
                "COD_MOD": "55", "COD_SIT": "00", "NUM_DOC": "123",
                "VL_DOC": "500", "VL_ICMS_ST": "200", "VL_MERC": "500",
            }, line=10),
            _e210_st(vl_retencao="100"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "ST_APURACAO_INCONSISTENTE" in types

    def test_st_valores_batem_sem_erro(self):
        """C100 VL_ICMS_ST == E210 VL_RETENCAO_ST => sem erro."""
        records = [
            _0000(),
            _rec("E200", {"UF": "MG", "DT_INI": "01012024", "DT_FIN": "31012024"}, line=55),
            _rec("C100", {
                "IND_OPER": "1", "IND_EMIT": "0", "COD_PART": "P1",
                "COD_MOD": "55", "COD_SIT": "00", "NUM_DOC": "123",
                "VL_DOC": "500", "VL_ICMS_ST": "137.81", "VL_MERC": "500",
            }, line=10),
            _e210_st(vl_retencao="137.81"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "ST_APURACAO_INCONSISTENTE" not in types

    def test_no_e210_no_error(self):
        records = [
            _0000(),
            _c170(cst="010", cfop="5102", vl_icms="300", line=10),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "ST_APURACAO_INCONSISTENTE" not in types

    def test_st_e220_ajuste_explica_diferenca(self):
        """Se nao ha ST nos docs mas E210 tem retencao com ajustes E220, sem erro."""
        records = [
            _0000(),
            _rec("E200", {"UF": "SP", "DT_INI": "01012024", "DT_FIN": "31012024"}, line=55),
            _e210_st(vl_retencao="100"),
            _rec("E220", {"COD_AJ_APUR": "SP100001", "DESCR_COMPL_AJ": "Ajuste ST", "VL_AJ_APUR": "100"}, line=62),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "ST_APURACAO_INCONSISTENTE" not in types


class TestE111CodigoGenerico:
    def test_cod_generico_999(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020999", valor="1000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_CODIGO_GENERICO" in types
        assert "AJUSTE_NUMERICO_SEM_VALIDADE_JURIDICA" in types

    def test_cod_especifico_no_error(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001", valor="1000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "AJUSTE_CODIGO_GENERICO" not in types


class TestInventarioReflexo:
    def test_h010_vl_zero(self):
        records = [_0000(), _0200(), _h010(vl_item="0")]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "INVENTARIO_INCONSISTENTE_TRIBUTARIO" in types

    def test_h010_qtd_huge(self):
        records = [_0000(), _0200(), _h010(qtd="200000")]
        errors = validate_beneficio_audit(records)
        msgs = [e.message for e in errors if e.error_type == "INVENTARIO_INCONSISTENTE_TRIBUTARIO"]
        assert any("quantidade" in m.lower() for m in msgs)

    def test_h010_item_not_in_0200(self):
        records = [_0000(), _h010(cod_item="MISSING")]
        errors = validate_beneficio_audit(records)
        msgs = [e.message for e in errors if e.error_type == "INVENTARIO_INCONSISTENTE_TRIBUTARIO"]
        assert any("cadastrado" in m.lower() for m in msgs)


class TestBeneficioSemGovernanca:
    def test_e111_no_e112_short_descr(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001", descr="", valor="5000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_SEM_GOVERNANCA" in types

    def test_e111_with_e112_no_error(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001", descr="", valor="5000", line=55),
            _e112(line=56),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_SEM_GOVERNANCA" not in types


class TestC190MisturaCst:
    def test_aliq_efetiva_diverge(self):
        """C190 with declared ALIQ != effective (VL_ICMS/VL_BC) => error."""
        records = [
            _0000(),
            _c190(aliq="18", vl_bc="1000", vl_icms="120"),  # efetiva = 12%
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "C190_CONSOLIDACAO_INDEVIDA" in types

    def test_aliq_matches_no_error(self):
        records = [
            _0000(),
            _c190(aliq="18", vl_bc="1000", vl_icms="180"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "C190_CONSOLIDACAO_INDEVIDA" not in types


class TestSpedVsContribuicoes:
    def test_pis_cofins_divergente(self):
        """CST_PIS tributado + CST_COFINS isento => SPED_CONTRIBUICOES_DIVERGENTE."""
        records = [
            _0000(),
            _c170(cst_pis="01", cst_cofins="06", line=10),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SPED_CONTRIBUICOES_DIVERGENTE" in types

    def test_pis_cofins_consistent(self):
        records = [
            _0000(),
            _c170(cst_pis="01", cst_cofins="01", line=10),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "SPED_CONTRIBUICOES_DIVERGENTE" not in types


class TestCodigoAjusteIncompativel:
    def test_invalid_uf(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="XX020001"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CODIGO_AJUSTE_INCOMPATIVEL" in types

    def test_wrong_length(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP02"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CODIGO_AJUSTE_INCOMPATIVEL" in types

    def test_valid_cod(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CODIGO_AJUSTE_INCOMPATIVEL" not in types


class TestTrilhaBeneficioAusente:
    def test_high_value_without_lastro(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001", valor="10000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "TRILHA_BENEFICIO_AUSENTE" in types

    def test_low_value_no_error(self):
        records = [
            _0000(), _e110(),
            _e111(cod_aj="SP020001", valor="1000"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "TRILHA_BENEFICIO_AUSENTE" not in types


class TestMetaRules:
    def test_classificacao_erro_produced(self):
        """When errors exist, meta-rules should produce governance outputs."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_icms="180"),
            _e110(vl_tot_debitos="50"),  # will trigger debito integral
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "CLASSIFICACAO_TIPO_ERRO" in types
        assert "ACHADO_LIMITADO_AO_SPED" in types
        assert "GRAU_CONFIANCA_ACHADOS" in types
        assert "AMOSTRAGEM_MATERIALIDADE" in types

    def test_no_errors_no_meta(self):
        """When no fiscal errors, meta-rules should not produce output."""
        # An empty records list produces no errors at all
        errors = validate_beneficio_audit([])
        types = {e.error_type for e in errors}
        assert "CLASSIFICACAO_TIPO_ERRO" not in types


class TestTotalizacaoBeneficiada:
    def test_interestadual_high_but_icms_low(self):
        """Interestadual > 30% ops but ICMS inter < 10% => error."""
        records = [
            _0000(),
            # 70% interestadual ops
            _c190(cfop="6102", vl_opr="7000", vl_icms="10", vl_bc="140", line=20),
            _c190(cfop="5102", vl_opr="3000", vl_icms="540", vl_bc="3000", line=21),
            _e110(vl_tot_debitos="550"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "TOTALIZACAO_BENEFICIO_DIVERGENTE" in types


class TestBeneficioForaEscopo:
    def test_predominantemente_interno_com_credito(self):
        """>70% interno com E111 credito => BENEFICIO_FORA_ESCOPO."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_opr="8000", vl_icms="1440", line=20),
            _c190(cfop="6102", vl_opr="2000", vl_icms="240", line=21),
            _e110(),
            _e111(cod_aj="SP020001", valor="500"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BENEFICIO_FORA_ESCOPO" in types


class TestBaseBeneficioInflada:
    def test_ajuste_exceeds_icms_elegivel(self):
        """E111 total > ICMS elegivel => BASE_BENEFICIO_INFLADA."""
        records = [
            _0000(),
            _c190(cfop="5102", vl_opr="1000", vl_icms="100", line=20),
            _e110(),
            _e111(cod_aj="SP020001", valor="200"),
        ]
        errors = validate_beneficio_audit(records)
        types = {e.error_type for e in errors}
        assert "BASE_BENEFICIO_INFLADA" in types
