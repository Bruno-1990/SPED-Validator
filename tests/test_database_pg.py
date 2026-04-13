"""Testes do wrapper PostgreSQL — valida compatibilidade com interface sqlite3.

Requer PostgreSQL rodando em localhost:25434 (container aap-db).
Usa banco sped_audit (schema ja deve existir via scripts/pg_schema.sql).

Pula automaticamente se o PostgreSQL nao estiver disponivel.
"""

from __future__ import annotations

import json

import pytest

# Skip se psycopg2 nao estiver instalado
psycopg2 = pytest.importorskip("psycopg2")

DSN = "postgresql://root:root@localhost:25434/sped_audit"


def _pg_available() -> bool:
    try:
        conn = psycopg2.connect(DSN)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_available(),
    reason="PostgreSQL nao disponivel em localhost:25434",
)


@pytest.fixture
def conn():
    """Conexao PgConnection com cleanup automatico."""
    from src.services.database_pg import get_pg_connection
    c = get_pg_connection(DSN)
    yield c
    # Limpar dados de teste
    try:
        c.execute("DELETE FROM nfe_itens WHERE nfe_id IN (SELECT id FROM nfe_xmls WHERE chave_nfe LIKE 'TEST_%')")
        c.execute("DELETE FROM nfe_cruzamento WHERE chave_nfe LIKE 'TEST_%'")
        c.execute("DELETE FROM nfe_xmls WHERE chave_nfe LIKE 'TEST_%'")
        c.execute("DELETE FROM validation_errors WHERE file_id IN (SELECT id FROM sped_files WHERE filename LIKE 'test_%')")
        c.execute("DELETE FROM sped_records WHERE file_id IN (SELECT id FROM sped_files WHERE filename LIKE 'test_%')")
        c.execute("DELETE FROM sped_files WHERE filename LIKE 'test_%'")
        c.commit()
    except Exception:
        c.rollback()
    c.close()


# ── Teste de conexao e placeholder ──

class TestPlaceholderConversion:
    def test_question_marks_converted(self, conn):
        """Placeholders ? devem ser convertidos para %s."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_ph.txt", "abc123"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT filename FROM sped_files WHERE hash_sha256 = ?",
            ("abc123",),
        ).fetchone()
        assert row is not None
        assert row["filename"] == "test_ph.txt"
        assert row[0] == "test_ph.txt"

    def test_question_mark_inside_string_not_converted(self, conn):
        """? dentro de string literal nao deve ser convertido."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256, company_name) VALUES (?, ?, 'What?')",
            ("test_qm.txt", "qm123"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT company_name FROM sped_files WHERE hash_sha256 = ?",
            ("qm123",),
        ).fetchone()
        assert row["company_name"] == "What?"


# ── DictRow — acesso dict-like e tuple-like ──

class TestDictRow:
    def test_access_by_name(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256, cnpj) VALUES (?, ?, ?)",
            ("test_dr.txt", "dr123", "12345678000199"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT filename, cnpj FROM sped_files WHERE hash_sha256 = ?",
            ("dr123",),
        ).fetchone()
        assert row["filename"] == "test_dr.txt"
        assert row["cnpj"] == "12345678000199"

    def test_access_by_index(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_idx.txt", "idx123"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT filename, hash_sha256 FROM sped_files WHERE hash_sha256 = ?",
            ("idx123",),
        ).fetchone()
        assert row[0] == "test_idx.txt"
        assert row[1] == "idx123"

    def test_keys_method(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_keys.txt", "keys123"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT filename, hash_sha256 FROM sped_files WHERE hash_sha256 = ?",
            ("keys123",),
        ).fetchone()
        assert "filename" in row.keys()
        assert "hash_sha256" in row.keys()

    def test_dict_conversion(self, conn):
        """dict(row) deve funcionar como sqlite3.Row."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_dict.txt", "dict123"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT filename, hash_sha256 FROM sped_files WHERE hash_sha256 = ?",
            ("dict123",),
        ).fetchone()
        d = dict(row.items())
        assert d["filename"] == "test_dict.txt"

    def test_fetchone_none(self, conn):
        row = conn.execute(
            "SELECT * FROM sped_files WHERE hash_sha256 = ?",
            ("inexistente_xyz",),
        ).fetchone()
        assert row is None


# ── JSONB — fields_json como string (compatibilidade json.loads) ──

class TestJsonbCompatibility:
    def test_insert_json_string_read_as_string(self, conn):
        """JSONB inserido como json.dumps() deve retornar como string (nao dict)."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_jsonb.txt", "jsonb123"),
        )
        conn.commit()
        file_row = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("jsonb123",),
        ).fetchone()
        file_id = file_row[0]

        fields = {"REG": "C100", "VL_DOC": "1931,49", "CHV_NFE": "12345678901234567890123456789012345678901234"}
        conn.execute(
            "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, 1, "C100", "C", json.dumps(fields, ensure_ascii=False), "|C100|...|"),
        )
        conn.commit()

        row = conn.execute(
            "SELECT fields_json FROM sped_records WHERE file_id = ? AND register = ?",
            (file_id, "C100"),
        ).fetchone()
        raw = row[0]
        # Deve ser string (compativel com json.loads existente no codigo)
        assert isinstance(raw, str), f"Esperado str, recebeu {type(raw)}"
        parsed = json.loads(raw)
        assert parsed["VL_DOC"] == "1931,49"
        assert parsed["CHV_NFE"] == "12345678901234567890123456789012345678901234"

    def test_jsonb_gin_index_query(self, conn):
        """Consulta JSONB via operador ->> deve funcionar."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_gin.txt", "gin123"),
        )
        conn.commit()
        file_row = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("gin123",),
        ).fetchone()
        file_id = file_row[0]

        fields = {"REG": "C100", "CHV_NFE": "CHAVE_TESTE_GIN_12345"}
        conn.execute(
            "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (file_id, 1, "C100", "C", json.dumps(fields), "|C100|"),
        )
        conn.commit()

        # Busca via JSONB ->> (PostgreSQL nativo)
        row = conn.execute(
            "SELECT id FROM sped_records WHERE file_id = %s AND fields_json->>'CHV_NFE' = %s",
            (file_id, "CHAVE_TESTE_GIN_12345"),
        )
        result = row.fetchone()
        assert result is not None


# ── Fetchall e multiplas rows ──

class TestFetchall:
    def test_fetchall_multiple_rows(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_multi.txt", "multi123"),
        )
        conn.commit()
        file_row = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("multi123",),
        ).fetchone()
        file_id = file_row[0]

        for i in range(5):
            conn.execute(
                "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (file_id, i + 1, "C100", "C", json.dumps({"REG": "C100", "N": i}), f"|C100|{i}|"),
            )
        conn.commit()

        rows = conn.execute(
            "SELECT * FROM sped_records WHERE file_id = ? ORDER BY line_number",
            (file_id,),
        ).fetchall()
        assert len(rows) == 5
        assert rows[0]["line_number"] == 1
        assert rows[4]["line_number"] == 5

    def test_fetchall_empty(self, conn):
        rows = conn.execute(
            "SELECT * FROM sped_files WHERE hash_sha256 = ?",
            ("nao_existe_xyz",),
        ).fetchall()
        assert rows == []


# ── Executemany (batch insert) ──

class TestExecutemany:
    def test_batch_insert(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_batch.txt", "batch123"),
        )
        conn.commit()
        file_row = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("batch123",),
        ).fetchone()
        file_id = file_row[0]

        batch = [
            (file_id, i, "C170", "C", json.dumps({"REG": "C170", "NUM_ITEM": str(i)}), f"|C170|{i}|")
            for i in range(1, 11)
        ]
        conn.executemany(
            "INSERT INTO sped_records (file_id, line_number, register, block, fields_json, raw_line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            batch,
        )
        conn.commit()

        count = conn.execute(
            "SELECT COUNT(*) FROM sped_records WHERE file_id = ? AND register = ?",
            (file_id, "C170"),
        ).fetchone()
        assert count[0] == 10


# ── Commit / Rollback ──

class TestTransaction:
    def test_rollback(self, conn):
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_rollback.txt", "rb123"),
        )
        conn.rollback()
        row = conn.execute(
            "SELECT * FROM sped_files WHERE hash_sha256 = ?", ("rb123",),
        ).fetchone()
        assert row is None


# ── NF-e XML + itens (fluxo real do cruzamento) ──

class TestNfeXmlFlow:
    def test_insert_xml_and_items(self, conn):
        """Simula o fluxo real: upload XML → insert nfe_xmls + nfe_itens."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_nfe.txt", "nfe_flow_123"),
        )
        conn.commit()
        file_id = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("nfe_flow_123",),
        ).fetchone()[0]

        conn.execute(
            "INSERT INTO nfe_xmls (file_id, chave_nfe, numero_nfe, vl_doc, vl_icms, qtd_itens, prot_cstat) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, "TEST_CHAVE_44_DIGITOS_123456789012345678901234", "1234", 1931.49, 120.00, 2, "100"),
        )
        conn.commit()
        nfe_id = conn.execute(
            "SELECT id FROM nfe_xmls WHERE chave_nfe = ?",
            ("TEST_CHAVE_44_DIGITOS_123456789012345678901234",),
        ).fetchone()[0]

        # Inserir itens
        conn.execute(
            "INSERT INTO nfe_itens (nfe_id, num_item, cfop, cst_icms, aliq_icms, vbc_icms, vl_icms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nfe_id, 1, "6102", "000", 12.0, 1000.00, 120.00),
        )
        conn.execute(
            "INSERT INTO nfe_itens (nfe_id, num_item, cfop, cst_icms, aliq_icms, vbc_icms, vl_icms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (nfe_id, 2, "6102", "000", 12.0, 500.00, 60.00),
        )
        conn.commit()

        # Verificar itens
        itens = conn.execute(
            "SELECT * FROM nfe_itens WHERE nfe_id = ? ORDER BY num_item", (nfe_id,),
        ).fetchall()
        assert len(itens) == 2
        assert itens[0]["cfop"] == "6102"
        assert itens[1]["vl_icms"] == 60.0

    def test_validation_errors_with_legal_basis(self, conn):
        """Insert e leitura de validation_errors com legal_basis JSON."""
        conn.execute(
            "INSERT INTO sped_files (filename, hash_sha256) VALUES (?, ?)",
            ("test_legal.txt", "legal_123"),
        )
        conn.commit()
        file_id = conn.execute(
            "SELECT id FROM sped_files WHERE hash_sha256 = ?", ("legal_123",),
        ).fetchone()[0]

        legal = json.dumps({
            "fonte": "Guia Pratico EFD",
            "artigo": "Registro C100, campo 12",
            "trecho": "VL_DOC deve corresponder ao vNF do XML",
        })
        conn.execute(
            "INSERT INTO validation_errors "
            "(file_id, line_number, register, error_type, severity, message, "
            " friendly_message, legal_basis, categoria) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (file_id, 10, "C100", "XML003", "critical",
             "VL_DOC diverge", "Mensagem amigavel", legal, "cruzamento_xml"),
        )
        conn.commit()

        row = conn.execute(
            "SELECT legal_basis, friendly_message FROM validation_errors "
            "WHERE file_id = ? AND error_type = ?",
            (file_id, "XML003"),
        ).fetchone()
        assert row["friendly_message"] == "Mensagem amigavel"
        # legal_basis deve ser string JSON (parseavel)
        parsed = json.loads(row["legal_basis"])
        assert parsed["fonte"] == "Guia Pratico EFD"


# ── get_connection switch (DATABASE_URL) ──

class TestConnectionSwitch:
    def test_sqlite_when_no_env(self, tmp_path, monkeypatch):
        """Sem DATABASE_URL, deve usar SQLite."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        from src.services.database import init_audit_db
        db_path = tmp_path / "test.db"
        conn = init_audit_db(db_path)
        # sqlite3.Connection tem 'execute' e 'isolation_level'
        assert hasattr(conn, "isolation_level")
        conn.close()

    def test_pg_when_env_set(self, monkeypatch):
        """Com DATABASE_URL, deve retornar PgConnection."""
        monkeypatch.setenv("DATABASE_URL", DSN)
        from src.services.database import get_connection
        conn = get_connection("ignorado.db")
        assert type(conn).__name__ == "PgConnection"
        conn.close()
