"""Testes do MOD-01: Identificacao de Regime Tributario e ValidationContext."""

from __future__ import annotations

import json
import sqlite3

from src.models import SpedRecord
from src.services.context_builder import (
    TaxRegime,
    ValidationContext,
    _determine_regime,
    build_context,
)
from src.services.database import init_audit_db
from src.validators.cst_validator import validate_cst_and_exemptions
from src.validators.helpers import fields_to_dict

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _in_memory_db() -> sqlite3.Connection:
    """Cria banco de auditoria em memória com schema completo."""
    return init_audit_db(":memory:")


def _insert_file(db: sqlite3.Connection) -> int:
    """Insere um sped_file dummy e retorna o file_id."""
    cursor = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status) VALUES (?, ?, ?)",
        ("test.txt", "abc123", "parsing"),
    )
    db.commit()
    return cursor.lastrowid


def _insert_record(
    db: sqlite3.Connection,
    file_id: int,
    register: str,
    fields: list[str],
    line_number: int = 1,
) -> None:
    """Insere um sped_record no banco."""
    block = register[0] if register else "?"
    raw = "|" + "|".join(fields) + "|"
    db.execute(
        """INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (file_id, line_number, register, block, json.dumps(fields), raw),
    )
    db.commit()


def _make_0000(ind_perfil: str = "A", cod_ver: str = "016") -> list[str]:
    """Gera campos do registro 0000 com IND_PERFIL configurável.

    Layout: REG|COD_VER|COD_FIN|DT_INI|DT_FIN|NOME|CNPJ|CPF|UF|IE|COD_MUN|IM|SUFRAMA|IND_PERFIL|IND_ATIV
    Indices: 0    1       2       3       4      5    6    7  8   9   10     11   12       13         14
    """
    return [
        "0000", cod_ver, "0", "01012024", "31012024", "Empresa Teste LTDA",
        "12345678000190", "", "SP", "123456789", "3550308", "", "",
        ind_perfil, "0",
    ]


def _make_0150(cod_part: str, nome: str, uf: str = "SP") -> list[str]:
    """Gera campos do registro 0150 (participante)."""
    # REG|COD_PART|NOME|COD_PAIS|CNPJ|CPF|IE|COD_MUN|SUFRAMA|END|NUM|COMPL|BAIRRO|UF
    return [
        "0150", cod_part, nome, "01058", "11222333000144", "", "",
        "3550308", "", "Rua Teste", "100", "", "Centro", uf,
    ]


def rec(register: str, fields: list[str], line: int = 1) -> SpedRecord:
    raw = "|" + "|".join(fields) + "|"
    return SpedRecord(line_number=line, register=register, fields=fields_to_dict(register, fields), raw_line=raw)


def c170_simples(cst: str, line: int = 1) -> SpedRecord:
    """C170 com CST Simples Nacional (Tabela B)."""
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN", "1000,00",
        "0", "0", cst, "5102", "001",
        "0", "0", "0",
    ]
    return rec("C170", fields, line=line)


def c170_normal(cst: str, vl_bc: str = "1000,00", vl_icms: str = "180,00", line: int = 1) -> SpedRecord:
    """C170 com CST Regime Normal (Tabela A)."""
    fields = [
        "C170", "1", "PROD001", "Desc", "100", "UN", "1000,00",
        "0", "0", cst, "5101", "001",
        vl_bc, "18,00", vl_icms,
    ]
    return rec("C170", fields, line=line)


# ──────────────────────────────────────────────
# Testes de _determine_regime
# ──────────────────────────────────────────────

class TestDetermineRegime:
    def test_perfil_c_simples_nacional(self) -> None:
        assert _determine_regime("C") == TaxRegime.SIMPLES_NACIONAL

    def test_perfil_a_normal(self) -> None:
        assert _determine_regime("A") == TaxRegime.NORMAL

    def test_perfil_b_normal(self) -> None:
        assert _determine_regime("B") == TaxRegime.NORMAL

    def test_perfil_vazio_unknown(self) -> None:
        assert _determine_regime("") == TaxRegime.UNKNOWN

    def test_perfil_lowercase_c(self) -> None:
        """Deve funcionar mesmo com minúscula."""
        assert _determine_regime("c") == TaxRegime.SIMPLES_NACIONAL


# ──────────────────────────────────────────────
# Testes de build_context
# ──────────────────────────────────────────────

class TestBuildContext:
    def test_perfil_c_regime_simples(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(ind_perfil="C"))
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.SIMPLES_NACIONAL
        assert ctx.ind_perfil == "C"

    def test_perfil_a_regime_normal(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(ind_perfil="A"))
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.NORMAL

    def test_perfil_b_regime_normal(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(ind_perfil="B"))
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.NORMAL

    def test_metadata_populated(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(ind_perfil="A"))
        ctx = build_context(fid, db)
        assert ctx.cnpj == "12345678000190"
        assert ctx.uf_contribuinte == "SP"
        assert ctx.company_name == "Empresa Teste LTDA"
        assert ctx.cod_ver == "016"
        assert ctx.file_id == fid

    def test_participantes_from_0150(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(), line_number=1)
        _insert_record(db, fid, "0150", _make_0150("PART001", "Cliente A", "RJ"), line_number=2)
        _insert_record(db, fid, "0150", _make_0150("PART002", "Fornecedor B", "MG"), line_number=3)
        ctx = build_context(fid, db)
        assert "PART001" in ctx.participantes
        assert ctx.participantes["PART001"]["nome"] == "Cliente A"
        assert ctx.participantes["PART001"]["uf"] == "RJ"
        assert "PART002" in ctx.participantes
        assert ctx.participantes["PART002"]["nome"] == "Fornecedor B"

    def test_produtos_from_0200(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        _insert_record(db, fid, "0000", _make_0000(), line_number=1)
        fields_0200 = [
            "0200", "ITEM001", "Produto Teste", "", "", "", "", "22021000",
        ]
        _insert_record(db, fid, "0200", fields_0200, line_number=2)
        ctx = build_context(fid, db)
        assert "ITEM001" in ctx.produtos
        assert ctx.produtos["ITEM001"]["ncm"] == "22021000"

    def test_no_0000_returns_unknown(self) -> None:
        db = _in_memory_db()
        fid = _insert_file(db)
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.UNKNOWN


# ──────────────────────────────────────────────
# Teste integrado: Simples Nacional com CSTs Tabela B → zero falsos positivos
# ──────────────────────────────────────────────

class TestSimplesNacionalCST:
    """Arquivo Simples Nacional com CSTs 101-900 não deve gerar erros de CST."""

    def _simples_context(self) -> ValidationContext:
        return ValidationContext(
            file_id=1,
            regime=TaxRegime.SIMPLES_NACIONAL,
            ind_perfil="C",
        )

    def test_cst_101_no_errors(self) -> None:
        records = [c170_simples("101")]
        errors = validate_cst_and_exemptions(records, context=self._simples_context())
        cst_errors = [e for e in errors if "CST" in e.error_type and "IPI" not in e.error_type]
        assert cst_errors == []

    def test_cst_102_no_errors(self) -> None:
        records = [c170_simples("102")]
        errors = validate_cst_and_exemptions(records, context=self._simples_context())
        cst_errors = [e for e in errors if "CST" in e.error_type and "IPI" not in e.error_type]
        assert cst_errors == []

    def test_cst_500_no_errors(self) -> None:
        records = [c170_simples("500")]
        errors = validate_cst_and_exemptions(records, context=self._simples_context())
        cst_errors = [e for e in errors if "CST" in e.error_type and "IPI" not in e.error_type]
        assert cst_errors == []

    def test_cst_900_no_errors(self) -> None:
        records = [c170_simples("900")]
        errors = validate_cst_and_exemptions(records, context=self._simples_context())
        cst_errors = [e for e in errors if "CST" in e.error_type and "IPI" not in e.error_type]
        assert cst_errors == []

    def test_all_tabela_b_csts_zero_false_positives(self) -> None:
        """Todos os CSTs válidos do Simples Nacional devem passar sem erro de CST ICMS."""
        csosn_validos = ["101", "102", "103", "201", "202", "203", "300", "400", "500", "900"]
        records = [c170_simples(cst, line=i + 1) for i, cst in enumerate(csosn_validos)]
        errors = validate_cst_and_exemptions(records, context=self._simples_context())
        cst_icms_errors = [
            e for e in errors
            if e.error_type in ("CST_INVALIDO", "ISENCAO_INCONSISTENTE", "CST_020_SEM_REDUCAO")
        ]
        assert cst_icms_errors == [], f"Falsos positivos: {[e.error_type for e in cst_icms_errors]}"

    def test_regime_normal_still_validates_cst(self) -> None:
        """Regime Normal deve continuar validando CSTs Tabela A normalmente."""
        normal_ctx = ValidationContext(file_id=1, regime=TaxRegime.NORMAL, ind_perfil="A")
        # CST 99 é inválido na Tabela A
        records = [c170_normal("99")]
        errors = validate_cst_and_exemptions(records, context=normal_ctx)
        cst_errors = [e for e in errors if e.error_type == "CST_INVALIDO"]
        assert len(cst_errors) > 0

    def test_no_context_still_validates(self) -> None:
        """Sem contexto, deve funcionar como antes (Tabela A ativa)."""
        records = [c170_normal("99")]
        errors = validate_cst_and_exemptions(records)
        cst_errors = [e for e in errors if e.error_type == "CST_INVALIDO"]
        assert len(cst_errors) > 0
