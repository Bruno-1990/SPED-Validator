"""Testes do validador do Bloco D (bloco_d_validator.py — MOD-08).

Testes para as 6 regras: D_001 a D_006.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.models import SpedRecord
from src.services.context_builder import TaxRegime, ValidationContext
from src.validators.bloco_d_validator import validate_bloco_d
from src.validators.helpers import fields_to_dict


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(
        line_number=line, register=register,
        fields=fields_to_dict(register, fields), raw_line=raw,
    )


def _compute_valid_chave(base43: str) -> str:
    """Calcula DV modulo 11 e retorna chave de 44 digitos."""
    digits = [int(c) for c in base43]
    weights = [2, 3, 4, 5, 6, 7, 8, 9]
    total = sum(d * weights[i % 8] for i, d in enumerate(reversed(digits)))
    remainder = total % 11
    dv = 0 if remainder < 2 else 11 - remainder
    return base43 + str(dv)


VALID_CHV = _compute_valid_chave("3524011234567800019557001000000001100000000")


def _make_0150(cod_part: str = "TRANSP", line: int = 1) -> SpedRecord:
    return rec("0150", [
        "0150", cod_part, "Transportadora Teste", "1058", "12345678000195",
        "", "123456789", "3550308", "", "Rua Teste", "100", "", "Centro", "SP",
    ], line=line)


def _make_d100(
    line: int = 10,
    ind_oper: str = "1",
    cod_part: str = "TRANSP",
    chv_cte: str = "",
    vl_doc: str = "1000,00",
    vl_icms: str = "120,00",
) -> SpedRecord:
    if not chv_cte:
        chv_cte = VALID_CHV
    return rec("D100", [
        "D100", ind_oper, "0", cod_part, "57", "00", "001", "",
        "12345", chv_cte, "10012024", "10012024", "0", "",
        vl_doc, "0", "0", vl_doc, vl_doc, vl_icms, "0", "", "",
    ], line=line)


def _make_d190(
    line: int = 11,
    cst: str = "00",
    cfop: str = "5353",
    aliq: str = "12,00",
    vl_opr: str = "1000,00",
    vl_bc: str = "1000,00",
    vl_icms: str = "120,00",
) -> SpedRecord:
    return rec("D190", [
        "D190", cst, cfop, aliq, vl_opr, vl_bc, vl_icms, "0", "",
    ], line=line)


def _make_d690(
    line: int = 20,
    cst: str = "00",
    cfop: str = "5353",
    aliq: str = "12,00",
    vl_opr: str = "500,00",
    vl_bc: str = "500,00",
    vl_icms: str = "60,00",
) -> SpedRecord:
    return rec("D690", [
        "D690", cst, cfop, aliq, vl_opr, vl_bc, vl_icms, "0", "0", "0", "",
    ], line=line)


def _make_e110(
    line: int = 30,
    vl_tot_debitos: str = "1000,00",
    vl_tot_creditos: str = "500,00",
) -> SpedRecord:
    return rec("E110", [
        "E110", vl_tot_debitos, "0", "0", "0", vl_tot_creditos,
        "0", "0", "0", "0", "0", "0", "0", "0", "0",
    ], line=line)


def _make_context(regime: TaxRegime = TaxRegime.NORMAL) -> ValidationContext:
    return ValidationContext(
        file_id=1,
        regime=regime,
        uf_contribuinte="SP",
        periodo_ini=date(2024, 1, 1),
        periodo_fim=date(2024, 1, 31),
    )


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def valid_bloco_d_records() -> list[SpedRecord]:
    """Arquivo SPED com Bloco D valido — nenhum erro esperado."""
    return [
        _make_0150("TRANSP", line=1),
        _make_d100(line=10, ind_oper="1", cod_part="TRANSP",
                   vl_doc="1000,00", vl_icms="120,00"),
        _make_d190(line=11, cst="00", cfop="5353", aliq="12,00",
                   vl_opr="1000,00", vl_icms="120,00"),
        _make_e110(line=30, vl_tot_debitos="1000,00"),
    ]


@pytest.fixture
def invalid_bloco_d_records() -> list[SpedRecord]:
    """Arquivo SPED com erros no Bloco D — multiplos erros esperados."""
    invalid_chv = VALID_CHV[:-1] + str((int(VALID_CHV[-1]) + 1) % 10)
    return [
        _make_0150("TRANSP", line=1),
        # D100 com COD_PART inexistente e chave invalida
        _make_d100(line=10, ind_oper="1", cod_part="INEXISTENTE",
                   chv_cte=invalid_chv,
                   vl_doc="1000,00", vl_icms="120,00"),
        # D190 com CFOP entrada em doc de saida + VL_OPR divergente
        _make_d190(line=11, cst="00", cfop="1353", aliq="12,00",
                   vl_opr="500,00", vl_icms="60,00"),
        _make_e110(line=30, vl_tot_debitos="50,00"),
    ]


# ──────────────────────────────────────────────
# D_001: COD_PART do D100 deve existir no 0150
# ──────────────────────────────────────────────

class TestD001CodPart:
    """D_001: COD_PART do D100 deve existir no 0150."""

    def test_cod_part_valido(self, valid_bloco_d_records: list[SpedRecord]) -> None:
        errors = validate_bloco_d(valid_bloco_d_records)
        ref_errors = [e for e in errors if e.error_type == "D_REF_INEXISTENTE"]
        assert len(ref_errors) == 0

    def test_cod_part_inexistente(self) -> None:
        records = [
            _make_0150("TRANSP", line=1),
            _make_d100(line=10, cod_part="FANTASMA"),
        ]
        errors = validate_bloco_d(records)
        ref_errors = [e for e in errors if e.error_type == "D_REF_INEXISTENTE"]
        assert len(ref_errors) == 1
        assert "FANTASMA" in ref_errors[0].message


# ──────────────────────────────────────────────
# D_002: CFOP compativel com direcao da operacao
# ──────────────────────────────────────────────

class TestD002CfopDirecao:
    """D_002: CFOP do D190 compativel com direcao da operacao."""

    def test_cfop_saida_em_saida_ok(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="1", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="5353", vl_opr="1000,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        cfop_errors = [e for e in errors if e.error_type == "D_CFOP_DIRECAO_INCOMPATIVEL"]
        assert len(cfop_errors) == 0

    def test_cfop_entrada_em_saida_erro(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="1", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="1353", vl_opr="1000,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        cfop_errors = [e for e in errors if e.error_type == "D_CFOP_DIRECAO_INCOMPATIVEL"]
        assert len(cfop_errors) == 1
        assert "1353" in cfop_errors[0].message

    def test_cfop_entrada_em_entrada_ok(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="0", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="1353", vl_opr="1000,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        cfop_errors = [e for e in errors if e.error_type == "D_CFOP_DIRECAO_INCOMPATIVEL"]
        assert len(cfop_errors) == 0

    def test_cfop_saida_em_entrada_erro(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="0", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="5353", vl_opr="1000,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        cfop_errors = [e for e in errors if e.error_type == "D_CFOP_DIRECAO_INCOMPATIVEL"]
        assert len(cfop_errors) == 1


# ──────────────────────────────────────────────
# D_003: D190 deve fechar com soma dos D100
# ──────────────────────────────────────────────

class TestD003D190FechaComD100:
    """D_003: D190 deve fechar com soma dos D100 correspondentes."""

    def test_soma_correta(self) -> None:
        records = [
            _make_d100(line=10, vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, vl_opr="1000,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        div_errors = [e for e in errors if e.error_type == "D190_DIVERGE_D100"]
        assert len(div_errors) == 0

    def test_soma_divergente_vl_opr(self) -> None:
        records = [
            _make_d100(line=10, vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, vl_opr="500,00", vl_icms="120,00"),
        ]
        errors = validate_bloco_d(records)
        opr_errors = [e for e in errors
                      if e.error_type == "D190_DIVERGE_D100" and e.field_name == "VL_OPR"]
        assert len(opr_errors) == 1

    def test_soma_divergente_vl_icms(self) -> None:
        records = [
            _make_d100(line=10, vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, vl_opr="1000,00", vl_icms="60,00"),
        ]
        errors = validate_bloco_d(records)
        icms_errors = [e for e in errors
                       if e.error_type == "D190_DIVERGE_D100" and e.field_name == "VL_ICMS"]
        assert len(icms_errors) == 1

    def test_multiplos_d190_soma_correta(self) -> None:
        records = [
            _make_d100(line=10, vl_doc="1500,00", vl_icms="180,00"),
            _make_d190(line=11, cst="00", cfop="5353", vl_opr="1000,00", vl_icms="120,00"),
            _make_d190(line=12, cst="40", cfop="5353", aliq="0",
                       vl_opr="500,00", vl_bc="0", vl_icms="60,00"),
        ]
        errors = validate_bloco_d(records)
        div_errors = [e for e in errors if e.error_type == "D190_DIVERGE_D100"]
        assert len(div_errors) == 0


# ──────────────────────────────────────────────
# D_004: D190/D690 deve compor VL_TOT_DEBITOS do E110
# ──────────────────────────────────────────────

class TestD004D690E110:
    """D_004: D190/D690 deve compor VL_TOT_DEBITOS do E110."""

    def test_debitos_incluidos_ok(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="1", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="5353", vl_icms="120,00"),
            _make_e110(line=30, vl_tot_debitos="1000,00"),
        ]
        errors = validate_bloco_d(records)
        e110_errors = [e for e in errors if e.error_type == "D_DEBITOS_EXCEDE_E110"]
        assert len(e110_errors) == 0

    def test_debitos_excedem_e110(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="1", vl_doc="1000,00", vl_icms="500,00"),
            _make_d190(line=11, cfop="5353", vl_icms="500,00"),
            _make_e110(line=30, vl_tot_debitos="100,00"),
        ]
        errors = validate_bloco_d(records)
        e110_errors = [e for e in errors if e.error_type == "D_DEBITOS_EXCEDE_E110"]
        assert len(e110_errors) == 1

    def test_d690_saida_incluido(self) -> None:
        records = [
            _make_d690(line=20, cfop="5353", vl_icms="200,00"),
            _make_e110(line=30, vl_tot_debitos="1000,00"),
        ]
        errors = validate_bloco_d(records)
        e110_errors = [e for e in errors if e.error_type == "D_DEBITOS_EXCEDE_E110"]
        assert len(e110_errors) == 0

    def test_d690_excede_e110(self) -> None:
        records = [
            _make_d690(line=20, cfop="5353", vl_icms="500,00"),
            _make_e110(line=30, vl_tot_debitos="100,00"),
        ]
        errors = validate_bloco_d(records)
        e110_errors = [e for e in errors if e.error_type == "D_DEBITOS_EXCEDE_E110"]
        assert len(e110_errors) == 1

    def test_entrada_nao_gera_debito(self) -> None:
        records = [
            _make_d100(line=10, ind_oper="0", vl_doc="1000,00", vl_icms="120,00"),
            _make_d190(line=11, cfop="1353", vl_icms="120,00"),
            _make_e110(line=30, vl_tot_debitos="0"),
        ]
        errors = validate_bloco_d(records)
        e110_errors = [e for e in errors if e.error_type == "D_DEBITOS_EXCEDE_E110"]
        assert len(e110_errors) == 0


# ──────────────────────────────────────────────
# D_005: CST_ICMS compativel com regime tributario
# ──────────────────────────────────────────────

class TestD005CstRegime:
    """D_005: CST_ICMS do D190 compativel com regime."""

    def test_cst_normal_regime_normal_ok(self) -> None:
        ctx = _make_context(TaxRegime.NORMAL)
        records = [
            _make_d100(line=10),
            _make_d190(line=11, cst="00"),
        ]
        errors = validate_bloco_d(records, context=ctx)
        regime_errors = [e for e in errors if e.error_type == "D_CST_REGIME_INCOMPATIVEL"]
        assert len(regime_errors) == 0

    def test_csosn_em_regime_normal_erro(self) -> None:
        ctx = _make_context(TaxRegime.NORMAL)
        records = [
            _make_d100(line=10),
            _make_d190(line=11, cst="101"),
        ]
        errors = validate_bloco_d(records, context=ctx)
        regime_errors = [e for e in errors if e.error_type == "D_CST_REGIME_INCOMPATIVEL"]
        assert len(regime_errors) == 1
        assert "101" in regime_errors[0].message

    def test_cst_tabela_a_em_simples_erro(self) -> None:
        ctx = _make_context(TaxRegime.SIMPLES_NACIONAL)
        records = [
            _make_d100(line=10),
            _make_d190(line=11, cst="00"),
        ]
        errors = validate_bloco_d(records, context=ctx)
        regime_errors = [e for e in errors if e.error_type == "D_CST_REGIME_INCOMPATIVEL"]
        assert len(regime_errors) == 1

    def test_csosn_em_simples_ok(self) -> None:
        ctx = _make_context(TaxRegime.SIMPLES_NACIONAL)
        records = [
            _make_d100(line=10),
            _make_d190(line=11, cst="101"),
        ]
        errors = validate_bloco_d(records, context=ctx)
        regime_errors = [e for e in errors if e.error_type == "D_CST_REGIME_INCOMPATIVEL"]
        assert len(regime_errors) == 0

    def test_regime_desconhecido_ignora(self) -> None:
        ctx = _make_context(TaxRegime.UNKNOWN)
        records = [
            _make_d100(line=10),
            _make_d190(line=11, cst="00"),
        ]
        errors = validate_bloco_d(records, context=ctx)
        regime_errors = [e for e in errors if e.error_type == "D_CST_REGIME_INCOMPATIVEL"]
        assert len(regime_errors) == 0


# ──────────────────────────────────────────────
# D_006: CHV_CTE deve ter 44 digitos com DV valido
# ──────────────────────────────────────────────

class TestD006ChaveCte:
    """D_006: CHV_CTE deve ter 44 digitos com DV valido."""

    def test_chave_valida(self) -> None:
        records = [_make_d100(line=10, chv_cte=VALID_CHV)]
        errors = validate_bloco_d(records)
        chv_errors = [e for e in errors if e.error_type == "D_CHAVE_CTE_INVALIDA"]
        assert len(chv_errors) == 0

    def test_chave_invalida_dv_errado(self) -> None:
        invalid = VALID_CHV[:-1] + str((int(VALID_CHV[-1]) + 1) % 10)
        records = [_make_d100(line=10, chv_cte=invalid)]
        errors = validate_bloco_d(records)
        chv_errors = [e for e in errors if e.error_type == "D_CHAVE_CTE_INVALIDA"]
        assert len(chv_errors) == 1

    def test_chave_curta(self) -> None:
        records = [_make_d100(line=10, chv_cte="123456")]
        errors = validate_bloco_d(records)
        chv_errors = [e for e in errors if e.error_type == "D_CHAVE_CTE_INVALIDA"]
        assert len(chv_errors) == 1

    def test_chave_com_letras(self) -> None:
        records = [_make_d100(line=10, chv_cte="3524011234567800019557001000000001100000000A")]
        errors = validate_bloco_d(records)
        chv_errors = [e for e in errors if e.error_type == "D_CHAVE_CTE_INVALIDA"]
        assert len(chv_errors) == 1

    def test_chave_vazia_ignorada(self) -> None:
        records = [_make_d100(line=10, chv_cte="")]
        errors = validate_bloco_d(records)
        chv_errors = [e for e in errors if e.error_type == "D_CHAVE_CTE_INVALIDA"]
        assert len(chv_errors) == 0


# ──────────────────────────────────────────────
# Testes integrados com fixtures completas
# ──────────────────────────────────────────────

class TestBlocoDCompleto:
    """Testes integrados com fixtures de arquivo valido e invalido."""

    def test_arquivo_valido_sem_erros(
        self, valid_bloco_d_records: list[SpedRecord],
    ) -> None:
        ctx = _make_context(TaxRegime.NORMAL)
        errors = validate_bloco_d(valid_bloco_d_records, context=ctx)
        assert len(errors) == 0, \
            f"Erros inesperados: {[(e.error_type, e.message) for e in errors]}"

    def test_arquivo_invalido_com_erros(
        self, invalid_bloco_d_records: list[SpedRecord],
    ) -> None:
        errors = validate_bloco_d(invalid_bloco_d_records)
        error_types = {e.error_type for e in errors}
        assert "D_REF_INEXISTENTE" in error_types
        assert "D_CFOP_DIRECAO_INCOMPATIVEL" in error_types
        assert "D190_DIVERGE_D100" in error_types
        assert "D_CHAVE_CTE_INVALIDA" in error_types
