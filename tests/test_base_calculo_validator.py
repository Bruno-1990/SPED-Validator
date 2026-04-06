"""Testes para base_calculo_validator.py — BASE_001 a BASE_006."""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.base_calculo_validator import validate_base_calculo

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _c100(
    line: int = 1,
    ind_frt: str = "9",
    vl_frt: str = "0",
    vl_out_da: str = "0",
) -> SpedRecord:
    """Cria C100 com campos relevantes para testes de base de calculo."""
    fields = {
        "REG": "C100", "IND_OPER": "0", "IND_EMIT": "0",
        "COD_PART": "FORN01", "COD_MOD": "55", "COD_SIT": "00",
        "SER": "1", "NUM_DOC": "123", "CHV_NFE": "",
        "DT_DOC": "01012024", "DT_E_S": "01012024",
        "VL_DOC": "1000.00", "IND_PGTO": "0", "VL_DESC": "0",
        "VL_ABAT_NT": "0", "VL_MERC": "1000.00",
        "IND_FRT": ind_frt, "VL_FRT": vl_frt,
        "VL_SEG": "0", "VL_OUT_DA": vl_out_da,
        "VL_BC_ICMS": "1000.00", "VL_ICMS": "180.00",
        "VL_BC_ICMS_ST": "0", "VL_ICMS_ST": "0",
        "VL_IPI": "0", "VL_PIS": "0", "VL_COFINS": "0",
        "VL_PIS_ST": "0", "VL_COFINS_ST": "0",
    }
    return SpedRecord(
        line_number=line, register="C100", fields=fields,
        raw_line="|C100|",
    )


def _c170(
    line: int = 2,
    vl_item: str = "1000.00",
    vl_bc_icms: str = "1000.00",
    aliq_icms: str = "18.00",
    vl_icms: str = "180.00",
    cst_icms: str = "000",
) -> SpedRecord:
    """Cria C170 com campos relevantes."""
    fields = {
        "REG": "C170", "NUM_ITEM": "1", "COD_ITEM": "ITEM01",
        "DESCR_COMPL": "", "QTD": "1", "UNID": "UN",
        "VL_ITEM": vl_item, "VL_DESC": "0",
        "IND_MOV": "0", "CST_ICMS": cst_icms, "CFOP": "5102",
        "COD_NAT": "", "VL_BC_ICMS": vl_bc_icms,
        "ALIQ_ICMS": aliq_icms, "VL_ICMS": vl_icms,
        "VL_BC_ICMS_ST": "0", "ALIQ_ST": "0", "VL_ICMS_ST": "0",
        "IND_APUR": "0", "CST_IPI": "99", "COD_ENQ": "",
        "VL_BC_IPI": "0", "ALIQ_IPI": "0", "VL_IPI": "0",
        "CST_PIS": "99", "VL_BC_PIS": "0", "ALIQ_PIS": "0",
        "QUANT_BC_PIS": "0", "ALIQ_PIS_REAIS": "0", "VL_PIS": "0",
        "CST_COFINS": "99", "VL_BC_COFINS": "0", "ALIQ_COFINS": "0",
        "QUANT_BC_COFINS": "0", "ALIQ_COFINS_REAIS": "0",
        "VL_COFINS": "0", "COD_CTA": "", "VL_ABAT_NT": "0",
    }
    return SpedRecord(
        line_number=line, register="C170", fields=fields,
        raw_line="|C170|",
    )


# ──────────────────────────────────────────────
# BASE_001 — Recalculo ICMS divergente
# ──────────────────────────────────────────────

class TestBase001:
    def test_positivo_calculo_correto(self):
        """Calculo correto nao gera erro."""
        records = [_c100(), _c170()]
        errors = validate_base_calculo(records)
        calculo_errs = [e for e in errors if e.error_type == "CALCULO_DIVERGENTE"]
        assert len(calculo_errs) == 0

    def test_negativo_calculo_divergente(self):
        """VL_ICMS diverge do recalculo (BC * ALIQ / 100)."""
        records = [_c100(), _c170(vl_icms="200.00")]
        errors = validate_base_calculo(records)
        calculo_errs = [e for e in errors if e.error_type in ("CALCULO_DIVERGENTE", "CALCULO_ARREDONDAMENTO")]
        assert len(calculo_errs) >= 1
        assert calculo_errs[0].register == "C170"


# ──────────────────────────────────────────────
# BASE_002 — Base menor sem justificativa
# ──────────────────────────────────────────────

class TestBase002:
    def test_positivo_base_normal(self):
        """Base > 50% do item nao gera erro."""
        records = [_c100(), _c170(vl_item="1000.00", vl_bc_icms="600.00")]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_MENOR_SEM_JUSTIFICATIVA"]
        assert len(errs) == 0

    def test_negativo_base_menor(self):
        """Base < 50% do item sem CST de reducao gera erro."""
        records = [_c100(), _c170(
            vl_item="1000.00", vl_bc_icms="400.00",
            aliq_icms="18.00", vl_icms="72.00",
        )]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_MENOR_SEM_JUSTIFICATIVA"]
        assert len(errs) == 1
        assert "50%" in errs[0].message

    def test_positivo_cst_reducao_020(self):
        """CST 020 (reducao de base) nao gera erro mesmo com base < 50%."""
        records = [_c100(), _c170(
            vl_item="1000.00", vl_bc_icms="400.00",
            aliq_icms="18.00", vl_icms="72.00", cst_icms="020",
        )]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_MENOR_SEM_JUSTIFICATIVA"]
        assert len(errs) == 0

    def test_positivo_cst_reducao_070(self):
        """CST 070 (reducao com ST) nao gera erro."""
        records = [_c100(), _c170(
            vl_item="1000.00", vl_bc_icms="400.00",
            aliq_icms="18.00", vl_icms="72.00", cst_icms="070",
        )]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_MENOR_SEM_JUSTIFICATIVA"]
        assert len(errs) == 0


# ──────────────────────────────────────────────
# BASE_003 — Base superior ao razoavel
# ──────────────────────────────────────────────

class TestBase003:
    def test_positivo_base_normal(self):
        """Base <= 150% do item nao gera erro."""
        records = [_c100(), _c170(vl_item="1000.00", vl_bc_icms="1400.00",
                                   aliq_icms="18.00", vl_icms="252.00")]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_SUPERIOR_RAZOAVEL"]
        assert len(errs) == 0

    def test_negativo_base_superior(self):
        """Base > 150% do item gera warning."""
        records = [_c100(), _c170(vl_item="1000.00", vl_bc_icms="1600.00",
                                   aliq_icms="18.00", vl_icms="288.00")]
        errors = validate_base_calculo(records)
        errs = [e for e in errors if e.error_type == "BASE_SUPERIOR_RAZOAVEL"]
        assert len(errs) == 1
        assert "150%" in errs[0].message


# ──────────────────────────────────────────────
# BASE_004 — Frete CIF nao incluido na base
# ──────────────────────────────────────────────

class TestBase004:
    def test_positivo_cif_com_frete_na_base(self):
        """CIF com frete incluido na base nao gera erro."""
        c100 = _c100(ind_frt="0", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1100.00",
                      aliq_icms="18.00", vl_icms="198.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_CIF_FORA_BASE"]
        assert len(errs) == 0

    def test_negativo_cif_sem_frete_na_base(self):
        """CIF com frete nao incluido na base gera erro."""
        c100 = _c100(ind_frt="0", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_CIF_FORA_BASE"]
        assert len(errs) == 1
        assert "CIF" in errs[0].message

    def test_positivo_fob_nao_dispara(self):
        """FOB nao dispara regra CIF."""
        c100 = _c100(ind_frt="1", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_CIF_FORA_BASE"]
        assert len(errs) == 0


# ──────────────────────────────────────────────
# BASE_005 — Frete FOB incluido indevidamente
# ──────────────────────────────────────────────

class TestBase005:
    def test_positivo_fob_base_normal(self):
        """FOB com base <= valor do item nao gera erro."""
        c100 = _c100(ind_frt="1", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_FOB_NA_BASE"]
        assert len(errs) == 0

    def test_negativo_fob_na_base(self):
        """FOB com base > valor do item gera warning."""
        c100 = _c100(ind_frt="1", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1100.00",
                      aliq_icms="18.00", vl_icms="198.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_FOB_NA_BASE"]
        assert len(errs) == 1
        assert "FOB" in errs[0].message

    def test_positivo_cif_nao_dispara(self):
        """CIF nao dispara regra FOB."""
        c100 = _c100(ind_frt="0", vl_frt="100.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1100.00",
                      aliq_icms="18.00", vl_icms="198.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "FRETE_FOB_NA_BASE"]
        assert len(errs) == 0


# ──────────────────────────────────────────────
# BASE_006 — Despesas acessorias fora da base
# ──────────────────────────────────────────────

class TestBase006:
    def test_positivo_despesas_na_base(self):
        """Despesas acessorias incluidas na base nao gera erro."""
        c100 = _c100(vl_out_da="50.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1050.00",
                      aliq_icms="18.00", vl_icms="189.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "DESPESAS_ACESSORIAS_FORA_BASE"]
        assert len(errs) == 0

    def test_negativo_despesas_fora_base(self):
        """Despesas acessorias nao incluidas na base gera warning."""
        c100 = _c100(vl_out_da="50.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "DESPESAS_ACESSORIAS_FORA_BASE"]
        assert len(errs) == 1
        assert "Art. 13" in errs[0].message
        assert "LC 87/1996" in errs[0].message

    def test_positivo_sem_despesas(self):
        """Sem despesas acessorias nao gera erro."""
        c100 = _c100(vl_out_da="0")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "DESPESAS_ACESSORIAS_FORA_BASE"]
        assert len(errs) == 0

    def test_positivo_cst_nao_tributado(self):
        """CST nao tributado (040) nao gera erro mesmo com despesas fora."""
        c100 = _c100(vl_out_da="50.00")
        c170 = _c170(vl_item="1000.00", vl_bc_icms="1000.00", cst_icms="040")
        errors = validate_base_calculo([c100, c170])
        errs = [e for e in errors if e.error_type == "DESPESAS_ACESSORIAS_FORA_BASE"]
        assert len(errs) == 0
