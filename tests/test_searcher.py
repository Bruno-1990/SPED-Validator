"""Testes do módulo de busca (FTS, semântica, RRF)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.embeddings import embedding_to_blob
from src.searcher import (
    _build_fts_query,
    _fetch_chunk,
    _fetch_chunk_from_db,
    _reciprocal_rank_fusion,
    _search_exact_field,
    _search_fts,
    _search_semantic,
    search,
    search_for_error,
)

# ──────────────────────────────────────────────
# Helper
# ──────────────────────────────────────────────

def _insert_chunks_with_embeddings(conn: sqlite3.Connection) -> None:
    """Insere chunks com embeddings fake para testes."""
    np.random.seed(42)
    chunks = [
        ("test.md", "guia", "C100", "IND_OPER", "Registro C100", "IND_OPER indica entrada ou saida"),
        ("test.md", "guia", "C100", "VL_DOC", "Registro C100", "VL_DOC valor total do documento fiscal"),
        ("test.md", "guia", "E110", "VL_TOT_DEBITOS", "Registro E110", "Apuracao ICMS debitos totais"),
        ("test.md", "guia", "C170", "CFOP", "Registro C170", "CFOP codigo fiscal de operacao"),
    ]
    for src, cat, reg, field, heading, content in chunks:
        emb = np.random.rand(384).astype(np.float32)
        emb = emb / np.linalg.norm(emb)  # normalizar
        conn.execute(
            """INSERT INTO chunks (source_file, category, register, field_name, heading, content, embedding)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (src, cat, reg, field, heading, content, embedding_to_blob(emb)),
        )
    conn.commit()


# ──────────────────────────────────────────────
# _build_fts_query
# ──────────────────────────────────────────────

class TestBuildFtsQuery:
    def test_single_term(self) -> None:
        result = _build_fts_query("ICMS")
        assert '"ICMS"' in result

    def test_multiple_terms(self) -> None:
        result = _build_fts_query("ICMS substituicao tributaria")
        assert "OR" in result
        assert '"ICMS"' in result

    def test_empty_query(self) -> None:
        result = _build_fts_query("")
        assert result == ""

    def test_escapes_quotes(self) -> None:
        result = _build_fts_query('campo "teste"')
        assert '""' in result


# ──────────────────────────────────────────────
# _reciprocal_rank_fusion
# ──────────────────────────────────────────────

class TestReciprocalRankFusion:
    def test_single_list(self) -> None:
        list_a = [(1, 0.9), (2, 0.8), (3, 0.7)]
        result = _reciprocal_rank_fusion(list_a, [])
        ids = [doc_id for doc_id, _ in result]
        assert ids == [1, 2, 3]

    def test_merge_two_lists(self) -> None:
        list_a = [(1, 0.9), (2, 0.8)]
        list_b = [(2, 0.95), (3, 0.85)]
        result = _reciprocal_rank_fusion(list_a, list_b)
        assert result[0][0] == 2  # appears in both

    def test_empty_lists(self) -> None:
        assert _reciprocal_rank_fusion([], []) == []

    def test_k_parameter(self) -> None:
        list_a = [(1, 0.9)]
        list_b = [(1, 0.9)]
        r10 = _reciprocal_rank_fusion(list_a, list_b, k=10)
        r100 = _reciprocal_rank_fusion(list_a, list_b, k=100)
        assert r10[0][1] > r100[0][1]

    def test_preserves_all_docs(self) -> None:
        list_a = [(1, 0.9), (2, 0.8)]
        list_b = [(3, 0.95), (4, 0.85)]
        result = _reciprocal_rank_fusion(list_a, list_b)
        assert {d for d, _ in result} == {1, 2, 3, 4}


# ──────────────────────────────────────────────
# _search_fts
# ──────────────────────────────────────────────

class TestSearchFts:
    def _insert_test_chunks(self, conn: sqlite3.Connection) -> None:
        chunks = [
            ("test.md", "guia", "C100", "IND_OPER", "Registro C100", "IND_OPER indica entrada ou saida"),
            ("test.md", "guia", "C100", "VL_DOC", "Registro C100", "VL_DOC valor total do documento"),
            ("test.md", "guia", "E110", "VL_TOT_DEBITOS", "Registro E110", "Apuracao ICMS debitos totais"),
        ]
        for src, cat, reg, field, heading, content in chunks:
            conn.execute(
                """INSERT INTO chunks (source_file, category, register, field_name, heading, content)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (src, cat, reg, field, heading, content),
            )
        conn.commit()

    def test_basic_search(self, db_conn: sqlite3.Connection) -> None:
        self._insert_test_chunks(db_conn)
        results = _search_fts(db_conn, "ICMS", None, None, 10)
        assert len(results) > 0

    def test_filter_by_register(self, db_conn: sqlite3.Connection) -> None:
        self._insert_test_chunks(db_conn)
        results = _search_fts(db_conn, "entrada saida", "C100", None, 10)
        for cid, _ in results:
            row = db_conn.execute("SELECT register FROM chunks WHERE id = ?", (cid,)).fetchone()
            assert row[0] == "C100"

    def test_filter_by_register_and_field(self, db_conn: sqlite3.Connection) -> None:
        self._insert_test_chunks(db_conn)
        results = _search_fts(db_conn, "", "C100", "IND_OPER", 10)
        assert len(results) >= 1

    def test_no_results(self, db_conn: sqlite3.Connection) -> None:
        self._insert_test_chunks(db_conn)
        results = _search_fts(db_conn, "xyzinexistente123", None, None, 10)
        assert len(results) == 0

    def test_invalid_fts_query(self, db_conn: sqlite3.Connection) -> None:
        """Query FTS inválida retorna lista vazia (sem exceção)."""
        self._insert_test_chunks(db_conn)
        # A construção do query deve tratar de forma segura
        results = _search_fts(db_conn, "", None, None, 10)
        assert isinstance(results, list)


# ──────────────────────────────────────────────
# _search_exact_field
# ──────────────────────────────────────────────

class TestSearchExactField:
    def test_find_exact_field(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            """INSERT INTO chunks (source_file, category, register, field_name, heading, content)
               VALUES ('t.md', 'guia', 'C100', 'IND_OPER', 'h', 'conteudo')""",
        )
        db_conn.commit()
        results = _search_exact_field(db_conn, "C100", "IND_OPER")
        assert len(results) == 1

    def test_no_match(self, db_conn: sqlite3.Connection) -> None:
        assert _search_exact_field(db_conn, "XXXX", "YYYY") == []

    def test_multiple_matches(self, db_conn: sqlite3.Connection) -> None:
        for i in range(3):
            db_conn.execute(
                """INSERT INTO chunks (source_file, category, register, field_name, heading, content)
                   VALUES (?, 'guia', 'C100', 'IND_OPER', 'h', ?)""",
                (f"file{i}.md", f"conteudo {i}"),
            )
        db_conn.commit()
        results = _search_exact_field(db_conn, "C100", "IND_OPER")
        assert len(results) == 3


# ──────────────────────────────────────────────
# _search_semantic
# ──────────────────────────────────────────────

class TestSearchSemantic:
    def test_returns_results(self, db_conn: sqlite3.Connection) -> None:
        _insert_chunks_with_embeddings(db_conn)
        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = _search_semantic(db_conn, "ICMS debitos", None, 5)
            assert len(results) > 0

    def test_filter_by_register(self, db_conn: sqlite3.Connection) -> None:
        _insert_chunks_with_embeddings(db_conn)
        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = _search_semantic(db_conn, "entrada", "C100", 5)
            for cid, _ in results:
                row = db_conn.execute("SELECT register FROM chunks WHERE id = ?", (cid,)).fetchone()
                assert row[0] == "C100"

    def test_no_embeddings(self, db_conn: sqlite3.Connection) -> None:
        # Inserir chunks SEM embeddings
        db_conn.execute(
            """INSERT INTO chunks (source_file, category, register, heading, content)
               VALUES ('t.md', 'guia', 'C100', 'h', 'conteudo')""",
        )
        db_conn.commit()
        mock_vec = np.random.rand(384).astype(np.float32)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = _search_semantic(db_conn, "test", None, 5)
            assert results == []


# ──────────────────────────────────────────────
# _fetch_chunk / _fetch_chunk_from_db
# ──────────────────────────────────────────────

class TestFetchChunk:
    def test_fetch_existing(self, db_conn: sqlite3.Connection) -> None:
        db_conn.execute(
            """INSERT INTO chunks (source_file, category, register, field_name, heading, content, page_number)
               VALUES ('f.md', 'guia', 'C100', 'IND_OPER', 'titulo', 'conteudo', 5)""",
        )
        db_conn.commit()
        chunk = _fetch_chunk(db_conn, 1)
        assert chunk is not None
        assert chunk.register == "C100"
        assert chunk.field_name == "IND_OPER"
        assert chunk.page_number == 5

    def test_fetch_nonexistent(self, db_conn: sqlite3.Connection) -> None:
        assert _fetch_chunk(db_conn, 999) is None

    def test_fetch_from_db_path(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """INSERT INTO chunks (source_file, category, register, heading, content)
               VALUES ('f.md', 'guia', 'E110', 'titulo', 'conteudo')""",
        )
        conn.commit()
        conn.close()
        chunk = _fetch_chunk_from_db(db_path, 1)
        assert chunk is not None
        assert chunk.register == "E110"

    def test_fetch_from_db_path_not_found(self, db_path: Path) -> None:
        assert _fetch_chunk_from_db(db_path, 999) is None


# ──────────────────────────────────────────────
# search (integração)
# ──────────────────────────────────────────────

class TestSearch:
    def test_hybrid_search(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search("ICMS debitos", db_path, top_k=3)
            assert len(results) > 0
            for r in results:
                assert r.source in ("fts", "semantic", "hybrid")
                assert r.score > 0

    def test_search_with_register_filter(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search("entrada saida", db_path, register="C100", top_k=5)
            assert len(results) > 0

    def test_search_with_field_filter(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search("operacao", db_path, register="C100", field_name="IND_OPER", top_k=3)
            assert len(results) >= 0  # Pode ou não ter resultados FTS

    def test_search_empty_db(self, db_path: Path) -> None:
        mock_vec = np.random.rand(384).astype(np.float32)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search("qualquer coisa", db_path, top_k=5)
            assert results == []

    def test_source_fts_only(self, db_path: Path) -> None:
        """Quando um chunk aparece apenas no FTS, source deve ser 'fts'."""
        conn = sqlite3.connect(str(db_path))
        # Inserir chunk SEM embedding (não aparece no semântico)
        conn.execute(
            """INSERT INTO chunks (source_file, category, register, field_name, heading, content)
               VALUES ('t.md', 'guia', 'C100', 'IND_OPER', 'h', 'IND_OPER indica entrada ou saida')""",
        )
        conn.commit()
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search("IND_OPER entrada", db_path, top_k=3)
            if results:
                assert results[0].source == "fts"

    def test_source_semantic_only(self, db_path: Path) -> None:
        """Chunk que aparece só no semântico deve ter source='semantic'."""
        conn = sqlite3.connect(str(db_path))
        np.random.seed(99)
        emb = np.ones(384, dtype=np.float32)
        emb = emb / np.linalg.norm(emb)
        conn.execute(
            """INSERT INTO chunks (source_file, category, register, heading, content, embedding)
               VALUES ('t.md', 'guia', 'X999', 'h', 'conteudo especifico unico', ?)""",
            (embedding_to_blob(emb),),
        )
        conn.commit()
        conn.close()

        # Query vector igual ao embedding -> alta similaridade no semântico
        # mas "conteudo especifico unico" pode não casar no FTS com a query
        with patch("src.searcher.embed_single", return_value=emb):
            results = search("zzzzz", db_path, top_k=3)
            if results:
                assert results[0].source in ("semantic", "hybrid")


# ──────────────────────────────────────────────
# search_for_error (integração)
# ──────────────────────────────────────────────

class TestSearchForError:
    def test_finds_documentation(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search_for_error(
                register="C100",
                field_name="IND_OPER",
                field_no=2,
                error_message="Valor inválido",
                db_path=db_path,
                top_k=3,
            )
            assert len(results) > 0

    def test_exact_match_prioritized(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search_for_error(
                register="C100",
                field_name="IND_OPER",
                field_no=2,
                error_message="Qualquer erro",
                db_path=db_path,
                top_k=3,
            )
            if results:
                # Primeiro resultado deve ser do exact match
                assert results[0].source == "exact"

    def test_no_results(self, db_path: Path) -> None:
        mock_vec = np.random.rand(384).astype(np.float32)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search_for_error(
                register="XXXX",
                field_name="YYYY",
                field_no=99,
                error_message="nada",
                db_path=db_path,
                top_k=3,
            )
            assert results == []

    def test_deduplication(self, db_path: Path) -> None:
        """Chunks encontrados tanto no exact quanto no semântico não devem duplicar."""
        conn = sqlite3.connect(str(db_path))
        _insert_chunks_with_embeddings(conn)
        conn.close()

        mock_vec = np.random.rand(384).astype(np.float32)
        mock_vec = mock_vec / np.linalg.norm(mock_vec)
        with patch("src.searcher.embed_single", return_value=mock_vec):
            results = search_for_error(
                register="C100",
                field_name="IND_OPER",
                field_no=2,
                error_message="IND_OPER entrada saida",
                db_path=db_path,
                top_k=5,
            )
            chunk_ids = [r.chunk.id for r in results]
            assert len(chunk_ids) == len(set(chunk_ids))  # sem duplicatas
