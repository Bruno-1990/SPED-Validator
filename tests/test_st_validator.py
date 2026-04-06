"""Testes do validador ICMS-ST (st_validator.py) — MOD-07.

Cobre os criterios de aceitacao do PRD:
- ST_001: ST no item sem reflexo na apuracao (positivo + negativo)
- ST_002: CST 60 com debito indevido (positivo + negativo)
- ST_003: BC_ICMS_ST menor que VL_ITEM (positivo + negativo)
- ST_004: Mistura indevida ST com DIFAL (positivo + negativo)
- CSTs Simples Nacional: 201, 202, 203, 500
"""

from __future__ import annotations

from src.models import SpedRecord
from src.validators.helpers import fields_to_dict
from src.validators.st_validator import validate_st


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def _c170(
    cst: str = "10",
    cfop: str = "5102",
    vl_item: str = "1000.00",
    vl_bc_st: str = "1300.00",
    vl_icms_st: str = "234.00",
    line: int = 10,
) -> SpedRecord:
    """Cria um C170 minimo com campos ST preenchidos.

    Layout posicional (0-based):
    0:REG 1:NUM_ITEM 2:COD_ITEM 3:DESCR 4:QTD 5:UNID
    6:VL_ITEM 7:VL_DESC 8:IND_MOV 9:CST_ICMS 10:CFOP
    11:COD_NAT 12:VL_BC_ICMS 13:ALIQ_ICMS 14:VL_ICMS
    15:VL_BC_ICMS_ST 16:ALIQ_ST 17:VL_ICMS_ST
    """
    fields = [
        "C170", "1", "ITEM01", "Produto Teste", "1", "UN",
        vl_item, "0", "0", cst, cfop,
        "", "1000.00", "18.00", "180.00",
        vl_bc_st, "18.00", vl_icms_st,
    ]
    return rec("C170", fields, line=line)


def _e200(uf: str = "SP") -> SpedRecord:
    """Registro E200 — abertura apuracao ST por UF."""
    return rec("E200", ["E200", uf, "01012024", "31012024"], line=100)


def _e210(vl_st: str = "234.00") -> SpedRecord:
    """Registro E210 — apuracao ST com valor."""
    # Campos simplificados: 0:REG 1:IND_MOV 2:VL_SLD_CRED_ANT ...
    return rec("E210", [
        "E210", "0", vl_st, "0", "0", "0", vl_st, "0", "0",
        "0", "0", vl_st, "0", "0",
    ], line=101)


def _e300() -> SpedRecord:
    """Registro E300 — DIFAL."""
    return rec("E300", ["E300", "RJ", "01012024", "31012024"], line=200)


# ──────────────────────────────────────────────
# ST_001 — ST no item sem reflexo na apuracao
# ──────────────────────────────────────────────

class TestST001:
    def test_st001_positivo_sem_e200(self):
        """CST 10 com VL_ICMS_ST > 0 e sem E200 -> erro."""
        records = [_c170(cst="10")]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 1
        assert "ST_001" in st001[0].message

    def test_st001_positivo_e210_zerado(self):
        """CST 30 com VL_ICMS_ST > 0 e E210 zerado -> erro."""
        records = [
            _c170(cst="30"),
            _e200(),
            rec("E210", ["E210", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0", "0"], line=101),
        ]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 1

    def test_st001_negativo_com_e200_e210(self):
        """CST 10 com VL_ICMS_ST > 0 e E200+E210 preenchidos -> sem erro."""
        records = [_c170(cst="10"), _e200(), _e210()]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 0

    def test_st001_cst70_dispara(self):
        """CST 70 tambem indica ST com debito."""
        records = [_c170(cst="70")]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 1


# ──────────────────────────────────────────────
# ST_002 — CST 60 com debito indevido
# ──────────────────────────────────────────────

class TestST002:
    def test_st002_positivo_cst60_com_st(self):
        """CST 60 com VL_ICMS_ST > 0 -> erro (nao deveria ter debito)."""
        records = [_c170(cst="60", vl_icms_st="100.00")]
        errors = validate_st(records)
        st002 = [e for e in errors if e.error_type == "ST_CST60_DEBITO_INDEVIDO"]
        assert len(st002) == 1
        assert "ST_002" in st002[0].message

    def test_st002_negativo_cst60_sem_st(self):
        """CST 60 com VL_ICMS_ST = 0 -> sem erro."""
        records = [_c170(cst="60", vl_icms_st="0", vl_bc_st="0")]
        errors = validate_st(records)
        st002 = [e for e in errors if e.error_type == "ST_CST60_DEBITO_INDEVIDO"]
        assert len(st002) == 0

    def test_st002_negativo_cst10_com_st(self):
        """CST 10 com VL_ICMS_ST > 0 -> NAO e debito indevido (10 e substituto)."""
        records = [_c170(cst="10"), _e200(), _e210()]
        errors = validate_st(records)
        st002 = [e for e in errors if e.error_type == "ST_CST60_DEBITO_INDEVIDO"]
        assert len(st002) == 0


# ──────────────────────────────────────────────
# ST_003 — BC_ICMS_ST menor que VL_ITEM
# ──────────────────────────────────────────────

class TestST003:
    def test_st003_positivo_bc_menor(self):
        """BC_ICMS_ST < VL_ITEM para CST 10 -> warning."""
        records = [
            _c170(cst="10", vl_item="1000.00", vl_bc_st="800.00"),
            _e200(), _e210(),
        ]
        errors = validate_st(records)
        st003 = [e for e in errors if e.error_type == "ST_BC_MENOR_QUE_ITEM"]
        assert len(st003) == 1
        assert "ST_003" in st003[0].message

    def test_st003_negativo_bc_maior(self):
        """BC_ICMS_ST > VL_ITEM para CST 10 -> sem warning."""
        records = [
            _c170(cst="10", vl_item="1000.00", vl_bc_st="1300.00"),
            _e200(), _e210(),
        ]
        errors = validate_st(records)
        st003 = [e for e in errors if e.error_type == "ST_BC_MENOR_QUE_ITEM"]
        assert len(st003) == 0

    def test_st003_cst30_bc_menor(self):
        """BC_ICMS_ST < VL_ITEM para CST 30 -> warning."""
        records = [
            _c170(cst="30", vl_item="500.00", vl_bc_st="400.00"),
            _e200(), _e210(),
        ]
        errors = validate_st(records)
        st003 = [e for e in errors if e.error_type == "ST_BC_MENOR_QUE_ITEM"]
        assert len(st003) == 1


# ──────────────────────────────────────────────
# ST_004 — Mistura indevida ST com DIFAL
# ──────────────────────────────────────────────

class TestST004:
    def test_st004_positivo_st_com_difal(self):
        """CST 10 + CFOP 6102 + E300 -> warning mistura."""
        records = [_c170(cst="10", cfop="6102"), _e200(), _e210(), _e300()]
        errors = validate_st(records)
        st004 = [e for e in errors if e.error_type == "ST_MISTURA_DIFAL"]
        assert len(st004) == 1
        assert "ST_004" in st004[0].message

    def test_st004_negativo_sem_e300(self):
        """CST 10 + CFOP 6102 sem E300 -> sem warning."""
        records = [_c170(cst="10", cfop="6102"), _e200(), _e210()]
        errors = validate_st(records)
        st004 = [e for e in errors if e.error_type == "ST_MISTURA_DIFAL"]
        assert len(st004) == 0

    def test_st004_negativo_cfop_interno(self):
        """CST 10 + CFOP 5102 (interno) + E300 -> sem warning."""
        records = [_c170(cst="10", cfop="5102"), _e200(), _e210(), _e300()]
        errors = validate_st(records)
        st004 = [e for e in errors if e.error_type == "ST_MISTURA_DIFAL"]
        assert len(st004) == 0


# ──────────────────────────────────────────────
# Simples Nacional — CSTs 201, 202, 203, 500
# ──────────────────────────────────────────────

class TestSimplesNacionalST:
    def test_cst201_st001_dispara(self):
        """CST 201 (SN com ST) sem E200 -> ST_001."""
        records = [_c170(cst="201")]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 1

    def test_cst202_st001_dispara(self):
        """CST 202 (SN com ST) sem E200 -> ST_001."""
        records = [_c170(cst="202")]
        errors = validate_st(records)
        st001 = [e for e in errors if e.error_type == "ST_APURACAO_INCONSISTENTE"]
        assert len(st001) == 1

    def test_cst203_st003_bc_menor(self):
        """CST 203 com BC < VL_ITEM -> ST_003."""
        records = [
            _c170(cst="203", vl_item="1000.00", vl_bc_st="500.00"),
            _e200(), _e210(),
        ]
        errors = validate_st(records)
        st003 = [e for e in errors if e.error_type == "ST_BC_MENOR_QUE_ITEM"]
        assert len(st003) == 1

    def test_cst500_st002_debito_indevido(self):
        """CST 500 (SN ST retido) com VL_ICMS_ST > 0 -> ST_002."""
        records = [_c170(cst="500", vl_icms_st="50.00")]
        errors = validate_st(records)
        st002 = [e for e in errors if e.error_type == "ST_CST60_DEBITO_INDEVIDO"]
        assert len(st002) == 1

    def test_cst500_sem_debito_ok(self):
        """CST 500 (SN ST retido) com VL_ICMS_ST = 0 -> sem erro."""
        records = [_c170(cst="500", vl_icms_st="0", vl_bc_st="0")]
        errors = validate_st(records)
        st002 = [e for e in errors if e.error_type == "ST_CST60_DEBITO_INDEVIDO"]
        assert len(st002) == 0

    def test_cst201_st004_mistura_difal(self):
        """CST 201 + CFOP 6xxx + E300 -> ST_004."""
        records = [
            _c170(cst="201", cfop="6101"),
            _e200(), _e210(), _e300(),
        ]
        errors = validate_st(records)
        st004 = [e for e in errors if e.error_type == "ST_MISTURA_DIFAL"]
        assert len(st004) == 1


# ──────────────────────────────────────────────
# Sem C170 -> sem erros
# ──────────────────────────────────────────────

class TestEdgeCases:
    def test_sem_c170_sem_erros(self):
        """Sem registros C170 -> nenhum erro ST."""
        records = [_e200(), _e210()]
        errors = validate_st(records)
        assert len(errors) == 0

    def test_cst00_ignorado(self):
        """CST 00 (tributacao normal) -> nenhuma regra ST dispara."""
        c170 = _c170(cst="00", vl_icms_st="0", vl_bc_st="0")
        errors = validate_st([c170])
        assert len(errors) == 0
