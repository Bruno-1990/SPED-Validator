"""Testes das regras de auditoria fiscal (audit_rules.py)."""

from __future__ import annotations

from src.models import SpedRecord
from src.parser import group_by_register
from src.validators.audit_rules import (
    _AuditContext,
    _check_cfop_interestadual_uf,
    _check_credito_uso_consumo,
    _check_cst051_debito,
    _check_inventario_sem_movimento,
    _check_ipi_reflexo_bc,
    _check_parametrizacao_sistemica,
    _check_registros_essenciais,
    _check_remessa_sem_retorno,
    _check_volume_isento,
    validate_audit_rules,
)


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields, raw_line=raw)


def make_0000(uf: str = "ES") -> SpedRecord:
    fields = ["0000", "017", "0", "01012024", "31012024", "EMPRESA", "12345678000190", "", uf]
    return rec("0000", fields)


def make_0150(cod_part: str, uf: str = "SP") -> SpedRecord:
    # 0150: REG|COD_PART|NOME|COD_PAIS|CNPJ|CPF|IE|SUFRAMA|END|NUM|COMPL|BAIRRO|CEP|UF
    fields = ["0150", cod_part, "Nome", "", "11222333000144", "", "", "", "", "", "", "", "", uf]
    return rec("0150", fields)


def make_c100(ind_oper: str = "1", cod_part: str = "CLI001", line: int = 10) -> SpedRecord:
    fields = ["C100", ind_oper, "0", cod_part, "55", "00", "1", "000000001", "01012024", "01012024", "1000,00"]
    return rec("C100", fields, line=line)


def c170(
    cst: str = "000", cfop: str = "5102", aliq: str = "18,00",
    vl_item: str = "1000,00", vl_bc: str = "1000,00", vl_icms: str = "180,00",
    cod_item: str = "PROD001", cst_ipi: str = "", vl_ipi: str = "",
    line: int = 11,
) -> SpedRecord:
    fields = [
        "C170", "1", cod_item, "Desc", "100", "UN",
        vl_item, "0", "0", cst, cfop, "001",
        vl_bc, aliq, vl_icms,
        "", "", "",
        "", cst_ipi, "",
        "", "", vl_ipi,
        "", "", "", "", "", "",
        "", "", "", "", "", "",
    ]
    return rec("C170", fields, line=line)


def make_c190(
    cst: str = "000", cfop: str = "5102", aliq: str = "18,00",
    vl_opr: str = "1000,00", line: int = 20,
) -> SpedRecord:
    fields = ["C190", cst, cfop, aliq, vl_opr, "1000,00", "180,00", "0", "0"]
    return rec("C190", fields, line=line)


def make_h010(cod_item: str = "PROD001", line: int = 30) -> SpedRecord:
    fields = ["H010", cod_item, "UN", "100", "10,00", "1000,00"]
    return rec("H010", fields, line=line)


# ──────────────────────────────────────────────
# AUD_CFOP_INTERESTADUAL_UF_INTERNA
# ───────────���─────────────��────────────────────

class TestCfopInterestadualUf:
    def _make_ctx(self, uf_decl: str, uf_part: str) -> _AuditContext:
        records = [
            make_0000(uf=uf_decl),
            make_0150("CLI001", uf=uf_part),
            make_c100(cod_part="CLI001", line=10),
            c170(cfop="6102", line=11),
        ]
        return _AuditContext(group_by_register(records))

    def test_cfop_6xxx_mesma_uf_alerta(self) -> None:
        ctx = self._make_ctx("ES", "ES")
        r = c170(cfop="6102", line=11)
        errors = _check_cfop_interestadual_uf(r, ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "CFOP_INTERESTADUAL_DESTINO_INTERNO"

    def test_cfop_6xxx_uf_diferente_ok(self) -> None:
        ctx = self._make_ctx("ES", "SP")
        r = c170(cfop="6102", line=11)
        assert _check_cfop_interestadual_uf(r, ctx) == []

    def test_cfop_5xxx_nao_aplica(self) -> None:
        ctx = self._make_ctx("ES", "ES")
        r = c170(cfop="5102", line=11)
        assert _check_cfop_interestadual_uf(r, ctx) == []

    def test_cfop_remessa_excluida(self) -> None:
        ctx = self._make_ctx("ES", "ES")
        r = c170(cfop="6901", line=11)
        assert _check_cfop_interestadual_uf(r, ctx) == []


# ──────────────────────────────────────��───────
# AUD_CST051_DEBITO_INDEVIDO
# ────��─────────────────────────────────────────

class TestCst051Debito:
    def test_cst051_com_debito_alerta(self) -> None:
        r = c170(cst="051", vl_icms="100,00")
        errors = _check_cst051_debito(r)
        assert len(errors) == 1
        assert errors[0].error_type == "DIFERIMENTO_COM_DEBITO"

    def test_cst051_sem_debito_ok(self) -> None:
        r = c170(cst="051", vl_icms="0")
        assert _check_cst051_debito(r) == []

    def test_cst000_nao_aplica(self) -> None:
        r = c170(cst="000", vl_icms="180,00")
        assert _check_cst051_debito(r) == []

    def test_cst_3digitos_051(self) -> None:
        r = c170(cst="051", vl_icms="50,00")
        errors = _check_cst051_debito(r)
        assert len(errors) == 1


# ─────────────���────────────────────────────────
# AUD_IPI_REFLEXO_CUSTO_BC
# ─────────────────────────────────────���────────

class TestIpiReflexoBc:
    def test_ipi_nao_recuperavel_fora_da_bc_alerta(self) -> None:
        r = c170(cst_ipi="02", vl_ipi="100,00", vl_item="1000,00", vl_bc="1000,00")
        errors = _check_ipi_reflexo_bc(r)
        assert len(errors) == 1
        assert errors[0].error_type == "IPI_REFLEXO_INCORRETO"

    def test_ipi_recuperavel_nao_aplica(self) -> None:
        r = c170(cst_ipi="50", vl_ipi="100,00", vl_item="1000,00", vl_bc="1000,00")
        assert _check_ipi_reflexo_bc(r) == []

    def test_ipi_zero_nao_aplica(self) -> None:
        r = c170(cst_ipi="02", vl_ipi="0")
        assert _check_ipi_reflexo_bc(r) == []

    def test_sem_cst_ipi_nao_aplica(self) -> None:
        r = c170(cst_ipi="", vl_ipi="100,00")
        assert _check_ipi_reflexo_bc(r) == []


# ───────────────────────────────���──────────────
# AUD_BENEFICIO_REDUZIDO_NA_NOTA
# ───────────────────���──────────────────────────

# TestBeneficioReduzidoNota removido: regra era duplicata de ALIQ_001
# (aliquota_validator.py). Cobertura agora via validate_aliquotas().


# ────────���─────────────────────────────────────
# AUD_CST_VOLUME_ISENTO_ATIPICO
# ─────────────────────���────────────────────────

class TestVolumeIsento:
    def test_mais_de_50pct_alerta(self) -> None:
        groups = group_by_register([
            make_c190(cst="040", vl_opr="6000,00", line=1),
            make_c190(cst="000", vl_opr="4000,00", line=2),
        ])
        errors = _check_volume_isento(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "VOLUME_ISENTO_ATIPICO"

    def test_menos_de_50pct_ok(self) -> None:
        groups = group_by_register([
            make_c190(cst="040", vl_opr="3000,00", line=1),
            make_c190(cst="000", vl_opr="7000,00", line=2),
        ])
        assert _check_volume_isento(groups) == []

    def test_sem_c190_ok(self) -> None:
        assert _check_volume_isento({}) == []


# ────────────��─────────────────────────────────
# AUD_REMESSA_SEM_RETORNO
# ─────────────────────────────────���────────────

class TestRemessaSemRetorno:
    def test_remessa_sem_retorno_alerta(self) -> None:
        records = [
            c170(cfop="5901", cod_item="PROD001", line=1),
        ]
        ctx = _AuditContext(group_by_register(records))
        errors = _check_remessa_sem_retorno(ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "REMESSA_SEM_RETORNO"

    def test_remessa_com_retorno_ok(self) -> None:
        records = [
            c170(cfop="5901", cod_item="PROD001", line=1),
            c170(cfop="1902", cod_item="PROD001", line=2),
        ]
        ctx = _AuditContext(group_by_register(records))
        assert _check_remessa_sem_retorno(ctx) == []

    def test_sem_remessa_ok(self) -> None:
        records = [c170(cfop="5102", cod_item="PROD001")]
        ctx = _AuditContext(group_by_register(records))
        assert _check_remessa_sem_retorno(ctx) == []


# ──────────────────────────────────────────────
# AUD_INVENTARIO_ITEM_SEM_MOVIMENTO
# ─────────────��────────────────────────────────

class TestInventarioSemMovimento:
    def test_item_inventario_sem_c170_alerta(self) -> None:
        records = [make_h010("PROD_PARADO")]
        ctx = _AuditContext(group_by_register(records))
        errors = _check_inventario_sem_movimento(ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "INVENTARIO_ITEM_PARADO"

    def test_item_inventario_com_c170_ok(self) -> None:
        records = [
            make_h010("PROD001"),
            c170(cod_item="PROD001"),
        ]
        ctx = _AuditContext(group_by_register(records))
        assert _check_inventario_sem_movimento(ctx) == []

    def test_sem_inventario_ok(self) -> None:
        records = [c170(cod_item="PROD001")]
        ctx = _AuditContext(group_by_register(records))
        assert _check_inventario_sem_movimento(ctx) == []


# ───────────��──────────────────────────────────
# AUD_PARAMETRIZACAO_SISTEMICA
# ─────────��──────────────────────���─────────────

class TestParametrizacaoSistemica:
    def test_item_com_cst_incompativel_repetitivo_alerta(self) -> None:
        # 4 vendas com CST isento = 80%+ incompatível
        records = [
            c170(cst="040", cfop="5102", cod_item="X", line=1),
            c170(cst="040", cfop="5102", cod_item="X", line=2),
            c170(cst="040", cfop="5102", cod_item="X", line=3),
            c170(cst="040", cfop="5102", cod_item="X", line=4),
        ]
        groups = group_by_register(records)
        errors = _check_parametrizacao_sistemica(groups)
        assert len(errors) == 1
        assert errors[0].error_type == "PARAMETRIZACAO_SISTEMICA_INCORRETA"

    def test_item_com_cst_correto_ok(self) -> None:
        records = [
            c170(cst="000", cfop="5102", cod_item="X", line=1),
            c170(cst="000", cfop="5102", cod_item="X", line=2),
            c170(cst="000", cfop="5102", cod_item="X", line=3),
        ]
        groups = group_by_register(records)
        assert _check_parametrizacao_sistemica(groups) == []

    def test_poucos_registros_nao_aplica(self) -> None:
        records = [
            c170(cst="040", cfop="5102", cod_item="X", line=1),
            c170(cst="040", cfop="5102", cod_item="X", line=2),
        ]
        groups = group_by_register(records)
        assert _check_parametrizacao_sistemica(groups) == []


# ─────────���──────────────────────��─────────────
# AUD_CREDITO_ENTRADA_USO_CONSUMO
# ──────────────────────────────────────────────

class TestCreditoUsoConsumo:
    def test_entrada_sem_saida_sem_inventario_alerta(self) -> None:
        records = [
            c170(cfop="1102", cod_item="LIMPEZA", line=1),
        ]
        ctx = _AuditContext(group_by_register(records))
        groups = group_by_register(records)
        errors = _check_credito_uso_consumo(ctx, groups)
        assert len(errors) == 1
        assert errors[0].error_type == "CREDITO_USO_CONSUMO_INDEVIDO"

    def test_entrada_com_saida_ok(self) -> None:
        records = [
            c170(cfop="1102", cod_item="PROD001", line=1),
            c170(cfop="5102", cod_item="PROD001", line=2),
        ]
        ctx = _AuditContext(group_by_register(records))
        groups = group_by_register(records)
        assert _check_credito_uso_consumo(ctx, groups) == []

    def test_entrada_com_inventario_ok(self) -> None:
        records = [
            c170(cfop="1102", cod_item="PROD001", line=1),
            make_h010("PROD001"),
        ]
        ctx = _AuditContext(group_by_register(records))
        groups = group_by_register(records)
        assert _check_credito_uso_consumo(ctx, groups) == []

    def test_cfop_nao_credito_nao_aplica(self) -> None:
        records = [c170(cfop="1556", cod_item="USO")]
        ctx = _AuditContext(group_by_register(records))
        groups = group_by_register(records)
        assert _check_credito_uso_consumo(ctx, groups) == []


# ────────────���────────────────────���────────────
# AUD_REGISTROS_ESSENCIAIS_AUSENTES
# ──────��────────────────��──────────────────────

class TestRegistrosEssenciais:
    def test_tudo_presente_ok(self) -> None:
        records = [
            make_0150("CLI001"),
            rec("0200", ["0200", "PROD001"]),
            make_c100(),
            c170(),
            make_c190(),
            rec("E110", ["E110", "0", "0", "0", "0", "0"]),
            make_h010(),
        ]
        ctx = _AuditContext(group_by_register(records))
        assert _check_registros_essenciais(ctx) == []

    def test_faltando_registros_alerta(self) -> None:
        records = [c170()]
        ctx = _AuditContext(group_by_register(records))
        errors = _check_registros_essenciais(ctx)
        assert len(errors) == 1
        assert errors[0].error_type == "REGISTROS_ESSENCIAIS_AUSENTES"
        assert "0150" in errors[0].value


# ───���──────────────────────────────────────────
# Integração
# ──────────���─────────────────────���─────────────

class TestValidateAuditRules:
    def test_empty(self) -> None:
        assert validate_audit_rules([]) == []

    def test_valid_file_no_audit_issues(self) -> None:
        records = [
            make_0000("ES"),
            make_0150("CLI001", "SP"),
            rec("0200", ["0200", "PROD001", "Desc", "UN", "", "", "", "94036000"]),
            make_c100(cod_part="CLI001", line=10),
            c170(cst="000", cfop="6102", aliq="12,00", cod_item="PROD001", line=11),
            make_c190(cst="000", cfop="6102", aliq="12,00", line=20),
            rec("E110", ["E110", "120,00", "0", "0", "0", "0"], line=30),
            make_h010("PROD001"),
        ]
        errors = validate_audit_rules(records)
        # Deve ter poucos ou nenhum erro
        critical = [e for e in errors if e.error_type in (
            "CFOP_INTERESTADUAL_DESTINO_INTERNO",
            "PARAMETRIZACAO_SISTEMICA_INCORRETA",
            "BENEFICIO_CARGA_REDUZIDA_DOCUMENTO",
        )]
        assert critical == []

    def test_detects_cfop_uf_issue(self) -> None:
        records = [
            make_0000("ES"),
            make_0150("CLI001", "ES"),  # mesmo estado!
            make_c100(cod_part="CLI001", line=10),
            c170(cst="000", cfop="6102", aliq="12,00", line=11),
        ]
        errors = validate_audit_rules(records)
        types = {e.error_type for e in errors}
        assert "CFOP_INTERESTADUAL_DESTINO_INTERNO" in types
