"""Testes da validação semântica fiscal (CST x alíquota zero, CST x CFOP)."""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.fiscal_semantics import (
    _classify_zero_rate_icms,
    _classify_zero_rate_ipi,
    _classify_zero_rate_pis_cofins,
    _ncm_is_monofasico,
    _validate_cst_cfop,
    _validate_monofasico,
    validate_fiscal_semantics,
)
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def c170(
    cst: str = "000",
    cfop: str = "5101",
    vl_bc: str = "1000,00",
    aliq: str = "18,00",
    vl_icms: str = "180,00",
    cst_ipi: str = "",
    vl_bc_ipi: str = "",
    aliq_ipi: str = "",
    vl_ipi: str = "",
    cst_pis: str = "",
    vl_bc_pis: str = "",
    aliq_pis: str = "",
    vl_pis: str = "",
    cst_cofins: str = "",
    vl_bc_cofins: str = "",
    aliq_cofins: str = "",
    vl_cofins: str = "",
    line: int = 1,
) -> SpedRecord:
    """C170 com layout completo para testes de semântica fiscal."""
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN",       # 0-5
        "1000,00", "0", "0", cst, cfop, "001",              # 6-11
        vl_bc, aliq, vl_icms,                                # 12-14
        "", "", "",                                           # 15-17: ST
        "", cst_ipi, "",                                     # 18-20: IND_APUR, CST_IPI, COD_ENQ
        vl_bc_ipi, aliq_ipi, vl_ipi,                        # 21-23
        cst_pis, vl_bc_pis, aliq_pis, "", "", vl_pis,       # 24-29
        cst_cofins, vl_bc_cofins, aliq_cofins, "", "", vl_cofins,  # 30-35
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# Frente 2: Classificador alíquota zero — ICMS
# ──────────────────────────────────────────────

class TestClassifyZeroRateIcms:
    def test_cst_tributado_bc_positiva_aliq_zero_alerta_forte(self) -> None:
        """TESTE 2: CST 00 + BC>0 + ALIQ=0 → alerta forte."""
        r = c170(cst="000", vl_bc="1000,00", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_ALIQ_ZERO_FORTE"

    def test_cst_tributado_tudo_zero_alerta_moderado(self) -> None:
        """TESTE 1: CST 00 + BC=0 + ALIQ=0 + VL_ICMS=0 → alerta moderado."""
        r = c170(cst="000", vl_bc="0", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_ALIQ_ZERO_MODERADO"

    def test_cst_isento_tudo_zero_ok(self) -> None:
        """TESTE 3: CST 40 + BC=0 + ALIQ=0 + VL_ICMS=0 → OK."""
        r = c170(cst="040", vl_bc="0", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert errors == []

    def test_cst_nt_tudo_zero_ok(self) -> None:
        """CST 41 (não tributado) com tudo zero → OK."""
        r = c170(cst="041", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_suspensao_tudo_zero_ok(self) -> None:
        """CST 50 (suspensão) com tudo zero → OK."""
        r = c170(cst="050", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_diferimento_tudo_zero_ok(self) -> None:
        """CST 51 (diferimento) com tudo zero → OK."""
        r = c170(cst="051", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_60_tudo_zero_ok(self) -> None:
        """CST 60 (ST cobrado anteriormente) com tudo zero → OK."""
        r = c170(cst="060", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_tributado_com_aliquota_positiva_ok(self) -> None:
        """CST 00 com alíquota normal → sem alerta (não entra no classificador)."""
        r = c170(cst="000", vl_bc="1000,00", aliq="18,00", vl_icms="180,00")
        assert _classify_zero_rate_icms(r) == []

    def test_exportacao_aliq_zero_ok(self) -> None:
        """CFOP de exportação + CST tributado + alíquota zero → OK."""
        r = c170(cst="000", cfop="7101", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_remessa_aliq_zero_ok(self) -> None:
        """CFOP de remessa + CST tributado + tudo zero → OK."""
        r = c170(cst="000", cfop="5901", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_vazio_ok(self) -> None:
        """CST vazio → sem validação."""
        r = c170(cst="", vl_bc="0", aliq="0", vl_icms="0")
        assert _classify_zero_rate_icms(r) == []

    def test_cst_20_reducao_tudo_zero_alerta(self) -> None:
        """CST 20 (redução de BC) com tudo zerado → alerta moderado."""
        r = c170(cst="020", vl_bc="0", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_ALIQ_ZERO_MODERADO"

    def test_cst_70_tudo_zero_alerta(self) -> None:
        """CST 70 (redução BC + ST) com tudo zerado → alerta moderado."""
        r = c170(cst="070", vl_bc="0", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_ALIQ_ZERO_MODERADO"

    def test_cst_2digitos_tributado_zero_alerta(self) -> None:
        """CST 00 (2 dígitos) com tudo zerado → alerta moderado."""
        r = c170(cst="00", vl_bc="0", aliq="0", vl_icms="0")
        errors = _classify_zero_rate_icms(r)
        assert len(errors) == 1
        assert errors[0].error_type == "CST_ALIQ_ZERO_MODERADO"


# ──────────────────────────────────────────────
# Frente 2: Classificador alíquota zero — IPI
# ──────────────────────────────────────────────

class TestClassifyZeroRateIpi:
    def test_ipi_tributado_tudo_zero_alerta(self) -> None:
        """TESTE 7: CST_IPI 00 + tudo zero → alerta."""
        r = c170(cst_ipi="00", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        errors = _classify_zero_rate_ipi(r)
        assert len(errors) == 1
        assert errors[0].error_type == "IPI_CST_ALIQ_ZERO"

    def test_ipi_isento_tudo_zero_ok(self) -> None:
        """CST_IPI 02 (isento) com tudo zero → sem alerta."""
        r = c170(cst_ipi="02", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        assert _classify_zero_rate_ipi(r) == []

    def test_ipi_suspenso_tudo_zero_ok(self) -> None:
        """CST_IPI 05 (suspenso) com tudo zero → sem alerta."""
        r = c170(cst_ipi="05", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        assert _classify_zero_rate_ipi(r) == []

    def test_ipi_tributado_com_valores_ok(self) -> None:
        """CST_IPI 50 com valores preenchidos → sem alerta."""
        r = c170(cst_ipi="50", vl_bc_ipi="1000,00", aliq_ipi="10,00", vl_ipi="100,00")
        assert _classify_zero_rate_ipi(r) == []

    def test_ipi_vazio_ok(self) -> None:
        """CST_IPI vazio → sem validação."""
        r = c170(cst_ipi="", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        assert _classify_zero_rate_ipi(r) == []

    def test_ipi_cst_49_residual_zero_ok(self) -> None:
        """CST_IPI 49 (outras entradas, residual) com tudo zero → sem alerta."""
        r = c170(cst_ipi="49", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0")
        assert _classify_zero_rate_ipi(r) == []

    def test_ipi_tributado_aliq_zero_com_bc_ok(self) -> None:
        """CST_IPI 00 com BC preenchida e aliquota 0% (TIPI) → sem alerta."""
        r = c170(cst_ipi="00", vl_bc_ipi="360", aliq_ipi="0", vl_ipi="0")
        assert _classify_zero_rate_ipi(r) == []


# ──────────────────────────────────────────────
# Frente 2: Classificador alíquota zero — PIS/COFINS
# ──────────────────────────────────────────────

class TestClassifyZeroRatePisCofins:
    def test_pis_tributavel_tudo_zero_alerta(self) -> None:
        """TESTE 8: CST_PIS 01 + tudo zero → alerta."""
        r = c170(cst_pis="01", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _classify_zero_rate_pis_cofins(r)
        assert any(e.error_type == "PIS_CST_ALIQ_ZERO" for e in errors)

    def test_cofins_tributavel_tudo_zero_alerta(self) -> None:
        """CST_COFINS 01 + tudo zero → alerta."""
        r = c170(cst_cofins="01", vl_bc_cofins="0", aliq_cofins="0", vl_cofins="0")
        errors = _classify_zero_rate_pis_cofins(r)
        assert any(e.error_type == "COFINS_CST_ALIQ_ZERO" for e in errors)

    def test_pis_nao_tributado_tudo_zero_ok(self) -> None:
        """CST_PIS 04 (não tributado) com tudo zero → sem alerta."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        assert _classify_zero_rate_pis_cofins(r) == []

    def test_pis_cofins_ambos_tributaveis_zero_dois_alertas(self) -> None:
        """PIS e COFINS ambos tributáveis com tudo zero → dois alertas."""
        r = c170(
            cst_pis="01", vl_bc_pis="0", aliq_pis="0", vl_pis="0",
            cst_cofins="01", vl_bc_cofins="0", aliq_cofins="0", vl_cofins="0",
        )
        errors = _classify_zero_rate_pis_cofins(r)
        assert len(errors) == 2
        types = {e.error_type for e in errors}
        assert "PIS_CST_ALIQ_ZERO" in types
        assert "COFINS_CST_ALIQ_ZERO" in types

    def test_pis_com_valores_ok(self) -> None:
        """CST_PIS 01 com valores → sem alerta."""
        r = c170(cst_pis="01", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50")
        assert _classify_zero_rate_pis_cofins(r) == []

    def test_pis_vazio_ok(self) -> None:
        """CST_PIS vazio → sem validação."""
        r = c170(cst_pis="", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        assert _classify_zero_rate_pis_cofins(r) == []

    def test_pis_cst_06_aliquota_zero_ok(self) -> None:
        """CST_PIS 06 (alíquota zero) → não é tributável, sem alerta."""
        r = c170(cst_pis="06", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        assert _classify_zero_rate_pis_cofins(r) == []


# ──────────────────────────────────────────────
# Frente 1: Cruzamento CST x CFOP
# ──────────────────────────────────────────────

class TestValidateCstCfop:
    def test_venda_tributada_cst_isento_alerta(self) -> None:
        """TESTE 5: CFOP de venda normal + CST 41 → alerta."""
        r = c170(cst="041", cfop="5102", vl_bc="0", aliq="0", vl_icms="0")
        errors = _validate_cst_cfop(r)
        assert any(e.error_type == "CST_CFOP_INCOMPATIVEL" for e in errors)

    def test_venda_tributada_cst_tributado_ok(self) -> None:
        """CFOP de venda + CST tributado → OK."""
        r = c170(cst="000", cfop="5102", vl_bc="1000,00", aliq="18,00", vl_icms="180,00")
        assert _validate_cst_cfop(r) == []

    def test_interestadual_cst_tributado_aliq_zero_alerta(self) -> None:
        """TESTE 6: Operação interestadual + alíquota zero + CST tributado → alerta."""
        r = c170(cst="000", cfop="6102", vl_bc="0", aliq="0", vl_icms="0")
        errors = _validate_cst_cfop(r)
        assert any(e.error_type == "CST_CFOP_INCOMPATIVEL" for e in errors)

    def test_interestadual_cst_tributado_aliq_positiva_ok(self) -> None:
        """Operação interestadual com alíquota normal → OK."""
        r = c170(cst="000", cfop="6102", vl_bc="1000,00", aliq="12,00", vl_icms="120,00")
        assert _validate_cst_cfop(r) == []

    def test_exportacao_cst_tributado_aliq_positiva_alerta(self) -> None:
        """Exportação + CST tributado + alíquota > 0 → alerta."""
        r = c170(cst="000", cfop="7101", vl_bc="1000,00", aliq="18,00", vl_icms="180,00")
        errors = _validate_cst_cfop(r)
        assert any(e.error_type == "CST_CFOP_INCOMPATIVEL" for e in errors)

    def test_exportacao_cst_nt_ok(self) -> None:
        """Exportação + CST não tributado → OK."""
        r = c170(cst="041", cfop="7101", vl_bc="0", aliq="0", vl_icms="0")
        # Exportação + isento/NT: o CFOP não está em _CFOP_VENDA, então sem alerta
        errors = _validate_cst_cfop(r)
        assert errors == []

    def test_remessa_cst_isento_ok(self) -> None:
        """Remessa + CST isento → sem alerta (remessa não é venda)."""
        r = c170(cst="040", cfop="5901", vl_bc="0", aliq="0", vl_icms="0")
        assert _validate_cst_cfop(r) == []

    def test_devolucao_interestadual_aliq_zero_ok(self) -> None:
        """Devolução interestadual com alíquota zero → sem alerta (excluída)."""
        r = c170(cst="000", cfop="6201", vl_bc="0", aliq="0", vl_icms="0")
        assert _validate_cst_cfop(r) == []

    def test_cst_vazio_ok(self) -> None:
        """CST vazio → sem validação."""
        r = c170(cst="", cfop="5101", vl_bc="0", aliq="0", vl_icms="0")
        assert _validate_cst_cfop(r) == []

    def test_cfop_vazio_ok(self) -> None:
        """CFOP vazio → sem validação."""
        r = c170(cst="000", cfop="", vl_bc="0", aliq="0", vl_icms="0")
        assert _validate_cst_cfop(r) == []

    def test_venda_cst_40_alerta(self) -> None:
        """CFOP 5101 (venda) + CST 40 (isento) → alerta."""
        r = c170(cst="040", cfop="5101", vl_bc="0", aliq="0", vl_icms="0")
        errors = _validate_cst_cfop(r)
        assert any(e.error_type == "CST_CFOP_INCOMPATIVEL" for e in errors)

    def test_entrada_interestadual_cst_tributado_aliq_zero(self) -> None:
        """Entrada interestadual (CFOP 2102) + CST tributado + aliq zero → alerta."""
        r = c170(cst="000", cfop="2102", vl_bc="0", aliq="0", vl_icms="0")
        errors = _validate_cst_cfop(r)
        assert any(e.error_type == "CST_CFOP_INCOMPATIVEL" for e in errors)

    def test_remessa_interestadual_aliq_zero_ok(self) -> None:
        """Remessa interestadual com alíquota zero → sem alerta."""
        r = c170(cst="000", cfop="6901", vl_bc="0", aliq="0", vl_icms="0")
        assert _validate_cst_cfop(r) == []


# ──────────────────────────────────────────────
# Integração
# ──────────────────────────────────────────────

class TestValidateFiscalSemantics:
    def test_empty(self) -> None:
        assert validate_fiscal_semantics([]) == []

    def test_valid_records_no_semantics_errors(self) -> None:
        """Registros válidos não geram alertas semânticos."""
        records = [
            c170(cst="000", cfop="5101", vl_bc="1000,00", aliq="18,00", vl_icms="180,00"),
        ]
        errors = validate_fiscal_semantics(records)
        assert errors == []

    def test_detects_multiple_issues(self) -> None:
        """Arquivo com múltiplos problemas semânticos."""
        records = [
            # CST tributado com tudo zero em venda → moderado
            c170(cst="000", cfop="5102", vl_bc="0", aliq="0", vl_icms="0", line=1),
            # Venda + CST isento → incompatível
            c170(cst="040", cfop="5101", vl_bc="0", aliq="0", vl_icms="0", line=2),
        ]
        errors = validate_fiscal_semantics(records)
        types = {e.error_type for e in errors}
        assert "CST_ALIQ_ZERO_MODERADO" in types
        assert "CST_CFOP_INCOMPATIVEL" in types

    def test_non_c170_ignored(self) -> None:
        """Registros que não são C170 são ignorados."""
        records = [
            rec("C100", ["C100", "1", "0", "PART001"], line=1),
            rec("C190", ["C190", "000", "5102", "18,00"], line=2),
        ]
        assert validate_fiscal_semantics(records) == []

    def test_ipi_and_pis_cofins_combined(self) -> None:
        """IPI + PIS + COFINS todos tributáveis com zero → 3 alertas."""
        r = c170(
            cst="040", cfop="5949",  # isento ICMS → sem alerta ICMS
            vl_bc="0", aliq="0", vl_icms="0",
            cst_ipi="00", vl_bc_ipi="0", aliq_ipi="0", vl_ipi="0",
            cst_pis="01", vl_bc_pis="0", aliq_pis="0", vl_pis="0",
            cst_cofins="01", vl_bc_cofins="0", aliq_cofins="0", vl_cofins="0",
        )
        errors = validate_fiscal_semantics([r])
        types = {e.error_type for e in errors}
        assert "IPI_CST_ALIQ_ZERO" in types
        assert "PIS_CST_ALIQ_ZERO" in types
        assert "COFINS_CST_ALIQ_ZERO" in types

    def test_monofasico_with_cadastro(self) -> None:
        """Produto monofásico (NCM 3004) com CST 01 na saída → alerta."""
        records = [
            # Cadastro 0200: COD_ITEM=PROD001, NCM na posição 7
            rec("0200", ["0200", "PROD001", "Desc", "UN", "", "", "", "30049099"], line=1),
            c170(
                cst="000", cfop="5102",
                vl_bc="1000,00", aliq="18,00", vl_icms="180,00",
                cst_pis="01", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50",
                cst_cofins="01", vl_bc_cofins="1000,00", aliq_cofins="7,60", vl_cofins="76,00",
                line=2,
            ),
        ]
        errors = validate_fiscal_semantics(records)
        types = {e.error_type for e in errors}
        assert "MONOFASICO_CST_INCORRETO" in types


# ──────────────────────────────────────────────
# NCM Monofásico — lookup
# ──────────────────────────────────────────────

class TestNcmIsMonofasico:
    def test_combustivel(self) -> None:
        assert _ncm_is_monofasico("27101259") is not None
        assert "Combustivel" in (_ncm_is_monofasico("27101259") or "")

    def test_farmaceutico(self) -> None:
        assert _ncm_is_monofasico("30049099") is not None
        assert "Farmaceutico" in (_ncm_is_monofasico("30049099") or "")

    def test_higiene(self) -> None:
        assert _ncm_is_monofasico("33049900") is not None
        assert "Higiene" in (_ncm_is_monofasico("33049900") or "")

    def test_bebida(self) -> None:
        assert _ncm_is_monofasico("22021000") is not None
        assert "Bebida" in (_ncm_is_monofasico("22021000") or "")

    def test_veiculo(self) -> None:
        assert _ncm_is_monofasico("87032100") is not None
        assert "Veiculo" in (_ncm_is_monofasico("87032100") or "")

    def test_autopeca(self) -> None:
        assert _ncm_is_monofasico("87089990") is not None
        assert "Autopeca" in (_ncm_is_monofasico("87089990") or "")

    def test_pneu(self) -> None:
        assert _ncm_is_monofasico("40111000") is not None
        assert "Autopeca" in (_ncm_is_monofasico("40111000") or "")

    def test_papel(self) -> None:
        assert _ncm_is_monofasico("48010000") is not None
        assert "Papel" in (_ncm_is_monofasico("48010000") or "")

    def test_nao_monofasico(self) -> None:
        assert _ncm_is_monofasico("94036000") is None  # Móveis

    def test_ncm_vazio(self) -> None:
        assert _ncm_is_monofasico("") is None

    def test_ncm_curto(self) -> None:
        assert _ncm_is_monofasico("27") is None


# ──────────────────────────────────────────────
# Monofásico — Regras de validação
# ──────────────────────────────────────────────

class TestValidateMonofasico:
    """Testes das 5 regras monofásicas PIS/COFINS."""

    # Mapa COD_ITEM → NCM para testes
    NCM_FARMA = {"PROD001": "30049099"}     # Farmacêutico
    NCM_MOVEL = {"PROD001": "94036000"}     # Móvel (não monofásico)
    NCM_VAZIO: dict[str, str] = {}

    def test_regra1_cst04_aliq_positiva_erro(self) -> None:
        """CST 04 (monofásico) com alíquota > 0 → erro."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="1,65", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert any(e.error_type == "MONOFASICO_ALIQ_INVALIDA" for e in errors)

    def test_regra1_cst04_aliq_zero_ok(self) -> None:
        """CST 04 com alíquota zero → sem erro de alíquota."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert not any(e.error_type == "MONOFASICO_ALIQ_INVALIDA" for e in errors)

    def test_regra2_cst04_valor_positivo_erro(self) -> None:
        """CST 04 com valor de PIS > 0 → erro."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="16,50")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert any(e.error_type == "MONOFASICO_VALOR_INDEVIDO" for e in errors)

    def test_regra2_cst04_valor_zero_ok(self) -> None:
        """CST 04 com valor zero → sem erro de valor."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert not any(e.error_type == "MONOFASICO_VALOR_INDEVIDO" for e in errors)

    def test_regra3_cst04_ncm_nao_monofasico_alerta(self) -> None:
        """CST 04 com NCM de móvel (não monofásico) → alerta."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_MOVEL)
        assert any(e.error_type == "MONOFASICO_NCM_INCOMPATIVEL" for e in errors)

    def test_regra3_cst04_ncm_monofasico_ok(self) -> None:
        """CST 04 com NCM farmacêutico → sem alerta de NCM."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert not any(e.error_type == "MONOFASICO_NCM_INCOMPATIVEL" for e in errors)

    def test_regra3_cst04_sem_cadastro_sem_alerta_ncm(self) -> None:
        """CST 04 sem cadastro 0200 → sem alerta de NCM (não tem como validar)."""
        r = c170(cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0")
        errors = _validate_monofasico(r, self.NCM_VAZIO)
        assert not any(e.error_type == "MONOFASICO_NCM_INCOMPATIVEL" for e in errors)

    def test_regra4_ncm_monofasico_cst_tributavel_saida_alerta(self) -> None:
        """NCM farmacêutico + CST 01 (tributável) em saída → alerta."""
        r = c170(
            cfop="5102",
            cst_pis="01", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert any(e.error_type == "MONOFASICO_CST_INCORRETO" for e in errors)

    def test_regra4_ncm_monofasico_cst_tributavel_entrada_ok(self) -> None:
        """NCM farmacêutico + CST 01 em entrada → sem alerta (regra 4 só saída)."""
        r = c170(
            cfop="1102",
            cst_pis="01", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert not any(e.error_type == "MONOFASICO_CST_INCORRETO" for e in errors)

    def test_regra4_ncm_nao_monofasico_cst_tributavel_ok(self) -> None:
        """NCM não monofásico + CST 01 → sem alerta."""
        r = c170(
            cfop="5102",
            cst_pis="01", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50",
        )
        errors = _validate_monofasico(r, self.NCM_MOVEL)
        assert not any(e.error_type == "MONOFASICO_CST_INCORRETO" for e in errors)

    def test_regra5_cst04_entrada_alerta(self) -> None:
        """CST 04 em entrada → alerta informativo."""
        r = c170(
            cfop="1102",
            cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert any(e.error_type == "MONOFASICO_ENTRADA_CST04" for e in errors)

    def test_regra5_cst04_saida_sem_alerta_entrada(self) -> None:
        """CST 04 em saída → sem alerta de entrada."""
        r = c170(
            cfop="5102",
            cst_pis="04", vl_bc_pis="0", aliq_pis="0", vl_pis="0",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert not any(e.error_type == "MONOFASICO_ENTRADA_CST04" for e in errors)

    def test_cofins_mesmas_regras(self) -> None:
        """COFINS aplica mesmas regras monofásicas que PIS."""
        r = c170(
            cfop="5102",
            cst_cofins="04", vl_bc_cofins="0", aliq_cofins="1,00", vl_cofins="10,00",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        cofins_types = {e.error_type for e in errors if "COFINS" in (e.field_name or "")}
        assert "MONOFASICO_ALIQ_INVALIDA" in cofins_types
        assert "MONOFASICO_VALOR_INDEVIDO" in cofins_types

    def test_cst_vazio_sem_erros(self) -> None:
        """CST PIS/COFINS vazios → sem validação monofásica."""
        r = c170(cst_pis="", cst_cofins="")
        errors = _validate_monofasico(r, self.NCM_FARMA)
        assert errors == []

    def test_cst06_nao_e_monofasico(self) -> None:
        """CST 06 (alíquota zero) não é monofásico — sem alertas monofásicos."""
        r = c170(
            cfop="5102",
            cst_pis="06", vl_bc_pis="0", aliq_pis="0", vl_pis="0",
        )
        errors = _validate_monofasico(r, self.NCM_FARMA)
        # CST 06 não é monofásico nem tributável → nenhuma regra se aplica
        assert errors == []

    def test_multiplos_erros_combinados(self) -> None:
        """CST 04 + alíq > 0 + valor > 0 + NCM não monofásico → múltiplos erros."""
        r = c170(
            cfop="5102",
            cst_pis="04", vl_bc_pis="1000,00", aliq_pis="1,65", vl_pis="16,50",
        )
        errors = _validate_monofasico(r, self.NCM_MOVEL)
        types = {e.error_type for e in errors}
        assert "MONOFASICO_ALIQ_INVALIDA" in types
        assert "MONOFASICO_VALOR_INDEVIDO" in types
        assert "MONOFASICO_NCM_INCOMPATIVEL" in types
