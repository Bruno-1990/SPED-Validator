"""Testes do indexador (chunking, field extraction, schema)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.indexer import (
    _chunk_markdown,
    _extract_heading,
    _extract_register_code,
    _extract_register_fields,
    _guess_field_name,
    _insert_chunks,
    _insert_register_fields,
    _is_field_definition_table,
    _map_columns,
    _parse_markdown_table,
    _row_to_register_field,
    _split_tables_and_text,
    index_all_markdown,
    init_db,
)
from src.models import Chunk, RegisterField

# ──────────────────────────────────────────────
# init_db
# ──────────────────────────────────────────────

class TestInitDb:
    def test_creates_tables(self, db_conn: sqlite3.Connection) -> None:
        tables = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "chunks" in table_names
        assert "register_fields" in table_names
        assert "indexed_files" in table_names

    def test_creates_fts_table(self, db_conn: sqlite3.Connection) -> None:
        tables = db_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "chunks_fts" in table_names

    def test_idempotent(self) -> None:
        conn = init_db(":memory:")
        conn2 = init_db(":memory:")  # Should not raise
        conn.close()
        conn2.close()


# ──────────────────────────────────────────────
# _extract_heading
# ──────────────────────────────────────────────

class TestExtractHeading:
    def test_h2_heading(self) -> None:
        assert _extract_heading("## Registro C100\nConteúdo") == "Registro C100"

    def test_h3_heading(self) -> None:
        assert _extract_heading("### Campo IND_OPER\nConteúdo") == "Campo IND_OPER"

    def test_no_heading(self) -> None:
        assert _extract_heading("Texto sem heading") == "(sem título)"


# ──────────────────────────────────────────────
# _extract_register_code
# ──────────────────────────────────────────────

class TestExtractRegisterCode:
    def test_c100(self) -> None:
        assert _extract_register_code("Registro C100 - Nota Fiscal") == "C100"

    def test_0000(self) -> None:
        # Regex exige [A-Z] como primeiro char, "0000" não casa
        assert _extract_register_code("Registro 0000 - Abertura") is None

    def test_register_starting_with_letter(self) -> None:
        assert _extract_register_code("Registro H010 - Inventário") == "H010"

    def test_e110(self) -> None:
        assert _extract_register_code("E110 Apuração ICMS") == "E110"

    def test_no_register(self) -> None:
        assert _extract_register_code("Texto sem registro") is None


# ──────────────────────────────────────────────
# _split_tables_and_text
# ──────────────────────────────────────────────

class TestSplitTablesAndText:
    def test_text_only(self) -> None:
        tables, texts = _split_tables_and_text("Apenas texto\nMais texto")
        assert len(tables) == 0
        assert len(texts) >= 1

    def test_table_only(self) -> None:
        section = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        tables, texts = _split_tables_and_text(section)
        assert len(tables) == 1
        assert "| A | B |" in tables[0]

    def test_mixed(self) -> None:
        section = "Texto antes\n| A | B |\n| --- | --- |\n| 1 | 2 |\nTexto depois"
        tables, texts = _split_tables_and_text(section)
        assert len(tables) == 1
        assert len(texts) >= 1


# ──────────────────────────────────────────────
# _parse_markdown_table
# ──────────────────────────────────────────────

class TestParseMarkdownTable:
    def test_basic_table(self) -> None:
        table = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        rows = _parse_markdown_table(table)
        assert len(rows) == 2  # header + 1 data row (separator skipped)
        assert rows[0] == ["A", "B"]
        assert rows[1] == ["1", "2"]

    def test_empty_table(self) -> None:
        rows = _parse_markdown_table("")
        assert len(rows) == 0

    def test_separator_skipped(self) -> None:
        table = "| H1 | H2 |\n| --- | --- |\n| V1 | V2 |"
        rows = _parse_markdown_table(table)
        # Should not contain separator row
        for row in rows:
            assert not all(c.strip() in ("---", "") for c in row)


# ──────────────────────────────────────────────
# _chunk_markdown
# ──────────────────────────────────────────────

class TestChunkMarkdown:
    def test_creates_chunks(self) -> None:
        content = """## Registro C100

Descrição do registro C100 com texto suficiente para chunk.

| Nº | Campo | Tipo |
| --- | --- | --- |
| 01 | REG | C |
| 02 | IND_OPER | C |
"""
        chunks = _chunk_markdown(content, "test.md")
        assert len(chunks) > 0

    def test_chunks_have_register(self) -> None:
        content = "## Registro C100\n\nDescrição do C100 com conteúdo."
        chunks = _chunk_markdown(content, "test.md")
        assert any(c.register == "C100" for c in chunks)

    def test_chunks_have_source_file(self) -> None:
        content = "## Registro C100\n\nDescrição do C100 com conteúdo."
        chunks = _chunk_markdown(content, "myfile.md")
        for c in chunks:
            assert c.source_file == "myfile.md"

    def test_field_chunks_from_table(self) -> None:
        content = """## Registro C100

| Nº | Campo | Tipo |
| --- | --- | --- |
| 01 | REG | C |
| 02 | IND_OPER | C |
"""
        chunks = _chunk_markdown(content, "test.md")
        field_chunks = [c for c in chunks if c.field_name]
        assert len(field_chunks) >= 1

    def test_empty_content(self) -> None:
        chunks = _chunk_markdown("", "test.md")
        assert len(chunks) == 0


# ──────────────────────────────────────────────
# _is_field_definition_table
# ──────────────────────────────────────────────

class TestIsFieldDefinitionTable:
    def test_sped_field_table(self) -> None:
        assert _is_field_definition_table(["nº", "campo", "descrição", "tipo", "tam"]) is True

    def test_generic_table(self) -> None:
        assert _is_field_definition_table(["coluna1", "coluna2", "coluna3"]) is False

    def test_partial_match(self) -> None:
        assert _is_field_definition_table(["nº", "campo"]) is True


# ──────────────────────────────────────────────
# _map_columns
# ──────────────────────────────────────────────

class TestMapColumns:
    def test_standard_sped_header(self) -> None:
        header = ["nº", "campo", "descrição", "tipo", "tam", "dec", "obrig", "valores válidos"]
        mapping = _map_columns(header)
        assert mapping["no"] == 0
        assert mapping["campo"] == 1
        assert mapping["descricao"] == 2
        assert mapping["tipo"] == 3
        assert mapping["tamanho"] == 4
        assert mapping["decimal"] == 5
        assert mapping["obrig"] == 6
        assert mapping["valores"] == 7


# ──────────────────────────────────────────────
# _extract_register_fields
# ──────────────────────────────────────────────

class TestExtractRegisterFields:
    def test_extracts_fields(self) -> None:
        content = """## Registro C100

| Nº | Campo | Descrição | Tipo | Tam | Dec | Obrig |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | REG | Registro | C | 4 | - | O |
| 02 | IND_OPER | Indicador | C | 1 | - | O |
"""
        fields = _extract_register_fields(content)
        assert len(fields) >= 2
        assert fields[0].register == "C100"
        assert fields[0].field_name == "REG"
        assert fields[1].field_name == "IND_OPER"

    def test_no_register_in_heading(self) -> None:
        content = """## Introdução

| Coluna | Valor |
| --- | --- |
| A | 1 |
"""
        fields = _extract_register_fields(content)
        assert len(fields) == 0

    def test_field_properties_parsed(self) -> None:
        content = """## Registro E110

| Nº | Campo | Descrição | Tipo | Tam | Dec | Obrig |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | REG | Registro | C | 4 | - | O |
| 02 | VL_TOT_DEBITOS | Total débitos | N | 255 | 2 | O |
"""
        fields = _extract_register_fields(content)
        vl_field = [f for f in fields if f.field_name == "VL_TOT_DEBITOS"]
        assert len(vl_field) == 1
        assert vl_field[0].field_type == "N"
        assert vl_field[0].field_size == 255
        assert vl_field[0].decimals == 2
        assert vl_field[0].required == "O"

    def test_valid_values_extraction(self) -> None:
        content = """## Registro C100

| Nº | Campo | Descrição | Tipo | Tam | Dec | Obrig | Valores Válidos |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | REG | Registro | C | 4 | - | O | |
| 02 | IND_OPER | Indicador | C | 1 | - | O | "0", "1" |
"""
        fields = _extract_register_fields(content)
        ind_field = [f for f in fields if f.field_name == "IND_OPER"]
        assert len(ind_field) == 1
        assert ind_field[0].valid_values == ["0", "1"]


# ──────────────────────────────────────────────
# _guess_field_name
# ──────────────────────────────────────────────

class TestGuessFieldName:
    def test_campo_column(self) -> None:
        header = ["Nº", "Campo", "Tipo"]
        row = ["01", "IND_OPER", "C"]
        assert _guess_field_name(header, row) == "IND_OPER"

    def test_nome_column(self) -> None:
        header = ["Nº", "Nome", "Tipo"]
        row = ["01", "REG", "C"]
        assert _guess_field_name(header, row) == "REG"

    def test_fallback_second_column(self) -> None:
        header = ["Nº", "Coluna2", "Tipo"]
        row = ["01", "CAMPO_X", "C"]
        assert _guess_field_name(header, row) == "CAMPO_X"

    def test_single_column(self) -> None:
        header = ["Val"]
        row = ["x"]
        result = _guess_field_name(header, row)
        assert result is None or result == "x"

    def test_empty_campo(self) -> None:
        header = ["Nº", "Campo", "Tipo"]
        row = ["01", "", "C"]
        # Campo vazio, deve usar fallback (segunda coluna, que é "")
        result = _guess_field_name(header, row)
        assert result is None


# ──────────────────────────────────────────────
# _row_to_register_field
# ──────────────────────────────────────────────

class TestRowToRegisterField:
    def test_basic_row(self) -> None:
        col_map = {"no": 0, "campo": 1, "tipo": 2, "tamanho": 3}
        row = ["01", "REG", "C", "4"]
        field = _row_to_register_field("C100", row, col_map)
        assert field is not None
        assert field.register == "C100"
        assert field.field_name == "REG"
        assert field.field_no == 1
        assert field.field_type == "C"
        assert field.field_size == 4

    def test_no_field_name_returns_none(self) -> None:
        col_map = {"no": 0, "campo": 1}
        row = ["01", ""]
        assert _row_to_register_field("C100", row, col_map) is None

    def test_non_numeric_no(self) -> None:
        col_map = {"no": 0, "campo": 1}
        row = ["abc", "REG"]
        field = _row_to_register_field("C100", row, col_map)
        assert field is not None
        assert field.field_no == 0

    def test_decimal_dash_ignored(self) -> None:
        col_map = {"no": 0, "campo": 1, "decimal": 2}
        row = ["01", "REG", "-"]
        field = _row_to_register_field("C100", row, col_map)
        assert field is not None
        assert field.decimals is None

    def test_valid_values_comma_separated(self) -> None:
        col_map = {"no": 0, "campo": 1, "valores": 2}
        row = ["01", "IND", "0, 1, 2"]
        field = _row_to_register_field("C100", row, col_map)
        assert field is not None
        assert field.valid_values == ["0", "1", "2"]


# ──────────────────────────────────────────────
# _insert_chunks
# ──────────────────────────────────────────────

class TestInsertChunks:
    def test_inserts_chunks(self, db_conn: sqlite3.Connection) -> None:
        chunks = [
            Chunk(source_file="f.md", register="C100", heading="h", content="conteudo 1"),
            Chunk(source_file="f.md", register="C100", heading="h", content="conteudo 2"),
        ]
        mock_embeddings = np.random.rand(2, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_embeddings):
            count = _insert_chunks(db_conn, chunks)
            assert count == 2

        rows = db_conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        assert rows[0] == 2

    def test_embeddings_stored(self, db_conn: sqlite3.Connection) -> None:
        chunks = [Chunk(source_file="f.md", heading="h", content="test")]
        mock_emb = np.random.rand(1, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_emb):
            _insert_chunks(db_conn, chunks)

        row = db_conn.execute("SELECT embedding FROM chunks WHERE id = 1").fetchone()
        assert row[0] is not None
        assert len(row[0]) == 384 * 4  # float32 = 4 bytes


# ──────────────────────────────────────────────
# _insert_register_fields
# ──────────────────────────────────────────────

class TestInsertRegisterFields:
    def test_inserts_fields(self, db_conn: sqlite3.Connection) -> None:
        fields = [
            RegisterField(register="C100", field_no=1, field_name="REG", field_type="C"),
            RegisterField(register="C100", field_no=2, field_name="IND_OPER", field_type="C"),
        ]
        count = _insert_register_fields(db_conn, fields)
        assert count == 2

        rows = db_conn.execute("SELECT COUNT(*) FROM register_fields").fetchone()
        assert rows[0] == 2

    def test_replace_on_conflict(self, db_conn: sqlite3.Connection) -> None:
        f1 = RegisterField(register="C100", field_no=1, field_name="REG", field_type="C")
        _insert_register_fields(db_conn, [f1])
        db_conn.commit()

        f1_updated = RegisterField(register="C100", field_no=1, field_name="REG", field_type="N")
        _insert_register_fields(db_conn, [f1_updated])
        db_conn.commit()

        row = db_conn.execute(
            "SELECT field_type FROM register_fields WHERE register='C100' AND field_no=1"
        ).fetchone()
        assert row[0] == "N"


# ──────────────────────────────────────────────
# index_all_markdown (integração)
# ──────────────────────────────────────────────

class TestIndexAllMarkdown:
    def test_indexes_md_files(self, tmp_path: Path) -> None:
        md_dir = tmp_path / "md"
        md_dir.mkdir()
        (md_dir / "c100.md").write_text("""## Registro C100

Descrição do registro C100 com texto suficiente.

| Nº | Campo | Descrição | Tipo | Tam |
| --- | --- | --- | --- | --- |
| 01 | REG | Registro | C | 4 |
| 02 | IND_OPER | Indicador | C | 1 |
""", encoding="utf-8")

        db_path = tmp_path / "test.db"
        mock_embs = np.random.rand(3, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_embs):
            count = index_all_markdown(md_dir, db_path, category="guia")
            assert count > 0

        # Verify data in DB
        conn = sqlite3.connect(str(db_path))
        chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        assert chunks > 0
        fields = conn.execute("SELECT COUNT(*) FROM register_fields").fetchone()[0]
        assert fields >= 2
        indexed = conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()[0]
        assert indexed == 1
        conn.close()

    def test_skip_existing(self, tmp_path: Path) -> None:
        md_dir = tmp_path / "md"
        md_dir.mkdir()
        (md_dir / "test.md").write_text("## Registro C100\n\nConteúdo.", encoding="utf-8")

        db_path = tmp_path / "test.db"
        mock_embs = np.random.rand(1, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_embs):
            count1 = index_all_markdown(md_dir, db_path, skip_existing=True)
            count2 = index_all_markdown(md_dir, db_path, skip_existing=True)
            assert count1 > 0
            assert count2 == 0  # skipped

    def test_force_reindex(self, tmp_path: Path) -> None:
        md_dir = tmp_path / "md"
        md_dir.mkdir()
        (md_dir / "test.md").write_text("## Registro C100\n\nConteúdo.", encoding="utf-8")

        db_path = tmp_path / "test.db"
        mock_embs = np.random.rand(1, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_embs):
            count1 = index_all_markdown(md_dir, db_path, skip_existing=True)
            count2 = index_all_markdown(md_dir, db_path, skip_existing=False)
            assert count1 > 0
            assert count2 > 0  # re-indexed

    def test_empty_directory(self, tmp_path: Path) -> None:
        md_dir = tmp_path / "md"
        md_dir.mkdir()
        db_path = tmp_path / "test.db"
        count = index_all_markdown(md_dir, db_path)
        assert count == 0

    def test_category_stored(self, tmp_path: Path) -> None:
        md_dir = tmp_path / "md"
        md_dir.mkdir()
        (md_dir / "lei.md").write_text("## Registro C100\n\nLegislação.", encoding="utf-8")

        db_path = tmp_path / "test.db"
        mock_embs = np.random.rand(1, 384).astype(np.float32)
        with patch("src.indexer.embed_texts", return_value=mock_embs):
            index_all_markdown(md_dir, db_path, category="legislacao")

        conn = sqlite3.connect(str(db_path))
        row = conn.execute("SELECT category FROM indexed_files").fetchone()
        assert row[0] == "legislacao"
        conn.close()
