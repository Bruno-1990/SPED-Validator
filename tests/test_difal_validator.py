"""Testes do validador DIFAL (difal_validator.py) — MOD-06.

Cobre os criterios de aceitacao do PRD:
- NF interestadual PF sem IE + sem E300 -> DIFAL_001 critical
- NF interestadual B2B com IE ativa -> DIFAL_001 nao dispara
- E300 com UF diferente do 0150 -> DIFAL_003 error
- Arquivo de 2015 -> regras DIFAL nao executadas (vigencia)
- Sem tabela de aliquotas -> warning de verificacao incompleta
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.services.reference_loader import ReferenceLoader
from src.validators.difal_validator import validate_difal
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def _make_loader() -> MagicMock:
    """Cria ReferenceLoader mockado com aliquotas e FCP."""
    loader = MagicMock(spec=ReferenceLoader)
    _aliq = {"SP": 18.0, "RJ": 20.0, "MG": 18.0, "BA": 20.5, "PR": 19.5}
    loader.get_aliquota_interna = lambda uf, dt=None: _aliq.get(uf.upper())
    loader.get_fcp = lambda uf, dt=None: 2.0 if uf.upper() == "RJ" else 0.0
    loader.get_matriz_aliquota = lambda o, d, dt=None: 7.0 if o in ("SP", "RJ", "MG", "ES", "PR", "SC", "RS") and d not in ("SP", "RJ", "MG", "ES", "PR", "SC", "RS") else 12.0
    loader.has_difal_vigente_table.return_value = False
    return loader


def _ctx(
    periodo_ini: date | None = None,
    periodo_fim: date | None = None,
    with_loader: bool = True,
) -> ValidationContext:
    ctx = ValidationContext(
        file_id=1,
        regime=TaxRegime.NORMAL,
        uf_contribuinte="SP",
        periodo_ini=periodo_ini or date(2024, 1, 1),
        periodo_fim=periodo_fim or date(2024, 1, 31),
        ind_perfil="A",
        cnpj="12345678000195",
        company_name="Empresa Teste Ltda",
    )
    if with_loader:
        ctx.reference_loader = _make_loader()
    return ctx


def _make_0000(uf: str = "SP") -> SpedRecord:
    """Registro 0000 minimo."""
    # 0:REG 1:COD_VER 2:COD_FIN 3:DT_INI 4:DT_FIN 5:NOME 6:CNPJ 7:CPF 8:UF
    return rec("0000", [
        "0000", "017", "0", "01012024", "31012024", "EMPRESA TESTE",
        "12345678000195", "", uf, "110042490114", "3550308", "",
        "", "A", "1",
    ], line=1)


def _make_0150(
    cod_part: str = "PART01",
    uf: str = "RJ",
    ind_ie: str = "9",
) -> SpedRecord:
    """Registro 0150 — participante.

    Campo 5 = IND_IE (1=contribuinte, 2=isento, 9=nao contribuinte)
    Campo 13 = UF
    """
    # 0:REG 1:COD_PART 2:NOME 3:COD_PAIS 4:CNPJ 5:IND_IE 6:IE 7:COD_MUN
    # 8:SUFRAMA 9:END 10:NUM 11:COMPL 12:BAIRRO 13:UF
    ie = "" if ind_ie == "9" else "123456789"
    return rec("0150", [
        "0150", cod_part, "DESTINATARIO TESTE", "01058", "98765432000199",
        ind_ie, ie, "3304557", "", "Rua Teste", "100", "", "Centro", uf,
    ], line=2)


def _make_c100(
    cod_part: str = "PART01",
    line: int = 10,
) -> SpedRecord:
    """C100 minimo para saida interestadual."""
    return rec("C100", [
        "C100", "1", "0", cod_part, "55", "00", "001", "123", "",
        "15012024", "15012024", "1000,00", "0", "0", "0", "1000,00",
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


def _make_c170_interestadual(
    cfop: str = "6107",
    cst: str = "00",
    aliq: str = "12,00",
    vl_item: str = "1000,00",
    vl_bc: str = "1000,00",
    vl_icms: str = "120,00",
    line: int = 11,
) -> SpedRecord:
    """C170 com CFOP interestadual."""
    # 0:REG 1:NUM_ITEM 2:COD_ITEM 3:DESCR 4:QTD 5:UNID 6:VL_ITEM
    # 7:VL_DESC 8:IND_MOV 9:CST_ICMS 10:CFOP 11:COD_NAT
    # 12:VL_BC_ICMS 13:ALIQ_ICMS 14:VL_ICMS
    return rec("C170", [
        "C170", "1", "PROD01", "", "10", "UN", vl_item,
        "0", "0", cst, cfop, "001", vl_bc, aliq, vl_icms,
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
        "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


class TestDifal001ConsumidorFinalSemDifal:
    """NF interestadual PF sem IE + sem E300 -> DIFAL_001 critical."""

    def test_nf_interestadual_pf_sem_ie_gera_difal_001(self) -> None:
        records = [
            _make_0000(uf="SP"),
            _make_0150(cod_part="PART01", uf="RJ", ind_ie="9"),
            _make_c100(cod_part="PART01", line=10),
            _make_c170_interestadual(
                cfop="6107", cst="00", aliq="12,00",
                vl_item="1000,00", vl_bc="1000,00", vl_icms="120,00",
                line=11,
            ),
        ]
        ctx = _ctx()
        errors = validate_difal(records, context=ctx)

        difal_001 = [e for e in errors if e.error_type == "DIFAL_FALTANTE_CONSUMO_FINAL"]
        assert len(difal_001) >= 1, (
            f"Esperado DIFAL_FALTANTE_CONSUMO_FINAL para PF sem IE interestadual. "
            f"Erros encontrados: {[e.error_type for e in errors]}"
        )


class TestDifal001NaoDisparaB2B:
    """NF interestadual B2B com IE ativa -> DIFAL_001 nao dispara."""

    def test_nf_interestadual_b2b_com_ie_nao_gera_difal_001(self) -> None:
        records = [
            _make_0000(uf="SP"),
            _make_0150(cod_part="PART01", uf="RJ", ind_ie="1"),
            _make_c100(cod_part="PART01", line=10),
            _make_c170_interestadual(
                cfop="6101", cst="00", aliq="12,00",
                vl_item="1000,00", vl_bc="1000,00", vl_icms="120,00",
                line=11,
            ),
        ]
        ctx = _ctx()
        errors = validate_difal(records, context=ctx)

        difal_001 = [e for e in errors if e.error_type == "DIFAL_FALTANTE_CONSUMO_FINAL"]
        assert len(difal_001) == 0, (
            f"DIFAL_001 nao deveria disparar para B2B com IE ativa. "
            f"Erros: {[e.error_type for e in errors]}"
        )


class TestDifal003UfInconsistente:
    """E300 com UF diferente do 0150 -> DIFAL_003 error."""

    def test_cfop_6xxx_mesma_uf_gera_difal_003(self) -> None:
        """CFOP interestadual mas destinatario na mesma UF -> inconsistencia."""
        records = [
            _make_0000(uf="SP"),
            _make_0150(cod_part="PART01", uf="SP", ind_ie="9"),
            _make_c100(cod_part="PART01", line=10),
            _make_c170_interestadual(
                cfop="6107", cst="00", aliq="12,00",
                vl_item="1000,00", vl_bc="1000,00", vl_icms="120,00",
                line=11,
            ),
        ]
        ctx = _ctx()
        errors = validate_difal(records, context=ctx)

        difal_003 = [e for e in errors if e.error_type == "DIFAL_UF_DESTINO_INCONSISTENTE"]
        assert len(difal_003) >= 1, (
            f"Esperado DIFAL_UF_DESTINO_INCONSISTENTE para CFOP 6xxx na mesma UF. "
            f"Erros: {[e.error_type for e in errors]}"
        )


class TestDifalVigencia:
    """Arquivo de 2015 -> regras DIFAL nao executadas (vigencia)."""

    def test_arquivo_2015_nao_executa_difal(self) -> None:
        records = [
            _make_0000(uf="SP"),
            _make_0150(cod_part="PART01", uf="RJ", ind_ie="9"),
            _make_c100(cod_part="PART01", line=10),
            _make_c170_interestadual(
                cfop="6107", cst="00", aliq="12,00",
                line=11,
            ),
        ]
        ctx = _ctx(
            periodo_ini=date(2015, 1, 1),
            periodo_fim=date(2015, 12, 31),
        )
        errors = validate_difal(records, context=ctx)

        assert len(errors) == 0, (
            f"Nenhuma regra DIFAL deveria executar para periodo 2015. "
            f"Erros encontrados: {[e.error_type for e in errors]}"
        )


class TestDifalTabelaIndisponivel:
    """Sem tabela de aliquotas -> warning de verificacao incompleta."""

    def test_sem_tabela_aliquotas_emite_warning(self) -> None:
        records = [
            _make_0000(uf="SP"),
            _make_0150(cod_part="PART01", uf="RJ", ind_ie="9"),
            _make_c100(cod_part="PART01", line=10),
            _make_c170_interestadual(
                cfop="6107", cst="00", aliq="12,00",
                line=11,
            ),
        ]
        ctx = _ctx(with_loader=False)
        errors = validate_difal(records, context=ctx)

        incompleta = [e for e in errors if e.error_type == "DIFAL_VERIFICACAO_INCOMPLETA"]
        assert len(incompleta) >= 1, (
            f"Esperado warning DIFAL_VERIFICACAO_INCOMPLETA sem tabela de aliquotas. "
            f"Erros: {[e.error_type for e in errors]}"
        )
