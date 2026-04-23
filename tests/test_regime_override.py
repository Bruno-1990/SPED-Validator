"""Testes do regime_override no build_context (bug #10).

O codigo antigo aceitava apenas 'normal' e 'simples_nacional', mas silenciava
qualquer outro valor (inclusive 'lixo', vazio com typo, 'MEI', etc). Agora:
  - Valores validos sao aplicados.
  - Valores invalidos geram context_warning e mantem regime detectado por CST.
"""

from __future__ import annotations

import json
import sqlite3

from src.services.context_builder import TaxRegime, build_context
from src.services.database import init_audit_db


def _in_memory_db() -> sqlite3.Connection:
    return init_audit_db(":memory:")


def _insert_file_with_override(db: sqlite3.Connection, override: str | None) -> int:
    cursor = db.execute(
        "INSERT INTO sped_files (filename, hash_sha256, status, regime_override) "
        "VALUES (?, ?, ?, ?)",
        ("test.txt", "abc123", "parsing", override),
    )
    db.commit()
    return cursor.lastrowid


def _insert_c170(db: sqlite3.Connection, file_id: int, cst: str = "00") -> None:
    """Insere um C170 com CST que indica regime Normal por default."""
    db.execute(
        "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
        "VALUES (?, ?, 'C170', 'C', ?, '')",
        (file_id, 10, json.dumps({"REG": "C170", "CST_ICMS": cst, "CFOP": "5102"})),
    )
    db.commit()


class TestRegimeOverride:
    def test_override_normal_respeitado(self):
        db = _in_memory_db()
        fid = _insert_file_with_override(db, "normal")
        _insert_c170(db, fid, cst="00")
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.NORMAL

    def test_override_simples_nacional_respeitado(self):
        db = _in_memory_db()
        fid = _insert_file_with_override(db, "simples_nacional")
        # CST Normal para confirmar que override sobrescreve CST
        _insert_c170(db, fid, cst="00")
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.SIMPLES_NACIONAL

    def test_override_valor_invalido_nao_altera_regime(self):
        """Bug #10: regime_override='LIXO' nao deve alterar ctx.regime silenciosamente."""
        db = _in_memory_db()
        fid = _insert_file_with_override(db, "LIXO_INVALIDO")
        _insert_c170(db, fid, cst="00")  # Detecta NORMAL via CST
        ctx = build_context(fid, db)
        # Regime deve continuar o detectado por CST (NORMAL), nao UNKNOWN ou outro
        assert ctx.regime == TaxRegime.NORMAL

    def test_override_valor_invalido_gera_warning(self):
        """Bug #10: valores invalidos de regime_override precisam ficar visiveis."""
        db = _in_memory_db()
        fid = _insert_file_with_override(db, "MEI")
        _insert_c170(db, fid, cst="00")
        ctx = build_context(fid, db)
        # Algum warning contendo a string 'regime_override' + o valor rejeitado
        matching = [w for w in ctx.context_warnings if "regime_override" in w.lower() and "MEI" in w]
        assert matching, (
            f"Esperava warning sobre regime_override invalido 'MEI'. "
            f"Warnings atuais: {ctx.context_warnings}"
        )

    def test_override_null_usa_cst(self):
        """Sem regime_override, ctx.regime vem de CST."""
        db = _in_memory_db()
        fid = _insert_file_with_override(db, None)
        _insert_c170(db, fid, cst="00")
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.NORMAL

    def test_override_case_insensitive(self):
        """Valores validos devem ser aceitos case-insensitive (UX)."""
        db = _in_memory_db()
        fid = _insert_file_with_override(db, "  SIMPLES_NACIONAL  ")
        _insert_c170(db, fid, cst="00")
        ctx = build_context(fid, db)
        assert ctx.regime == TaxRegime.SIMPLES_NACIONAL
