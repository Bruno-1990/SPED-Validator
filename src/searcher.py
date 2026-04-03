"""Busca híbrida: FTS5 (exata) + vetorial (semântica) com Reciprocal Rank Fusion."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np

from .embeddings import blob_to_embedding, embed_single
from .models import Chunk, SearchResult


def search(
    query: str,
    db_path: str | Path,
    register: str | None = None,
    field_name: str | None = None,
    top_k: int = 5,
) -> list[SearchResult]:
    """Busca híbrida na documentação.

    Combina resultados de FTS5 (busca exata) e similaridade vetorial
    usando Reciprocal Rank Fusion.
    """
    conn = sqlite3.connect(str(db_path))

    fts_results = _search_fts(conn, query, register, field_name, top_k * 2)
    semantic_results = _search_semantic(conn, query, register, top_k * 2)

    # Merge com RRF
    merged = _reciprocal_rank_fusion(fts_results, semantic_results, k=60)

    # Buscar chunks completos dos top_k resultados
    results: list[SearchResult] = []
    for chunk_id, score in merged[:top_k]:
        chunk = _fetch_chunk(conn, chunk_id)
        if chunk:
            # Determinar fonte
            source = "hybrid"
            fts_ids = {r[0] for r in fts_results}
            sem_ids = {r[0] for r in semantic_results}
            if chunk_id in fts_ids and chunk_id not in sem_ids:
                source = "fts"
            elif chunk_id in sem_ids and chunk_id not in fts_ids:
                source = "semantic"

            results.append(SearchResult(chunk=chunk, score=score, source=source))

    conn.close()
    return results


def search_for_error(
    register: str,
    field_name: str,
    field_no: int,
    error_message: str,
    db_path: str | Path,
    top_k: int = 3,
) -> list[SearchResult]:
    """Busca documentação específica para um erro de validação.

    Usa o registro e campo para busca exata, e a mensagem de erro para busca semântica.
    """
    conn = sqlite3.connect(str(db_path))

    # Primeiro: busca exata por registro + campo
    exact = _search_exact_field(conn, register, field_name)

    # Segundo: busca semântica com a mensagem de erro como contexto
    query = f"{register} {field_name} campo {field_no} {error_message}"
    semantic = _search_semantic(conn, query, register, top_k * 2)

    conn.close()

    # Priorizar resultado exato
    results: list[SearchResult] = []
    seen_ids: set[int] = set()

    for chunk_id in exact:
        chunk = _fetch_chunk_from_db(db_path, chunk_id)
        if chunk and chunk_id not in seen_ids:
            results.append(SearchResult(chunk=chunk, score=1.0, source="exact"))
            seen_ids.add(chunk_id)

    for chunk_id, score in semantic:
        if chunk_id not in seen_ids:
            chunk = _fetch_chunk_from_db(db_path, chunk_id)
            if chunk:
                results.append(SearchResult(chunk=chunk, score=score, source="semantic"))
                seen_ids.add(chunk_id)

    return results[:top_k]


# ──────────────────────────────────────────────
# FTS5
# ──────────────────────────────────────────────

def _search_fts(
    conn: sqlite3.Connection,
    query: str,
    register: str | None,
    field_name: str | None,
    limit: int,
) -> list[tuple[int, float]]:
    """Busca via FTS5. Retorna lista de (chunk_id, rank)."""
    try:
        if register and field_name:
            rows = conn.execute(
                """SELECT rowid, rank FROM chunks_fts
                   WHERE register = ? AND field_name = ?
                   ORDER BY rank LIMIT ?""",
                (register, field_name, limit),
            ).fetchall()
        elif register:
            # Buscar no registro + query no conteúdo
            fts_query = _build_fts_query(query)
            rows = conn.execute(
                """SELECT rowid, rank FROM chunks_fts
                   WHERE register = ? AND chunks_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (register, fts_query, limit),
            ).fetchall()
        else:
            fts_query = _build_fts_query(query)
            rows = conn.execute(
                """SELECT rowid, rank FROM chunks_fts
                   WHERE chunks_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (fts_query, limit),
            ).fetchall()

        return [(row[0], row[1]) for row in rows]
    except sqlite3.OperationalError:
        # Query FTS inválida — retornar vazio
        return []


def _build_fts_query(query: str) -> str:
    """Constrói query FTS5 a partir do texto de busca.

    Adiciona * para prefix matching em cada termo.
    """
    terms = query.strip().split()
    # Escapar aspas e caracteres especiais do FTS5
    safe_terms = []
    for t in terms:
        t = t.replace('"', '""')
        safe_terms.append(f'"{t}"')
    return " OR ".join(safe_terms)


def _search_exact_field(
    conn: sqlite3.Connection,
    register: str,
    field_name: str,
) -> list[int]:
    """Busca exata por registro + campo. Retorna lista de chunk_ids."""
    rows = conn.execute(
        "SELECT id FROM chunks WHERE register = ? AND field_name = ? LIMIT 10",
        (register, field_name),
    ).fetchall()
    return [r[0] for r in rows]


# ──────────────────────────────────────────────
# Busca semântica
# ──────────────────────────────────────────────

def _search_semantic(
    conn: sqlite3.Connection,
    query: str,
    register: str | None,
    limit: int,
) -> list[tuple[int, float]]:
    """Busca por similaridade vetorial. Retorna lista de (chunk_id, score)."""
    query_vec = embed_single(query)

    # Carregar embeddings (filtrado por register se possível)
    if register:
        rows = conn.execute(
            "SELECT id, embedding FROM chunks WHERE register = ? AND embedding IS NOT NULL",
            (register,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, embedding FROM chunks WHERE embedding IS NOT NULL"
        ).fetchall()

    if not rows:
        return []

    ids = [r[0] for r in rows]
    embeddings = np.stack([blob_to_embedding(r[1]) for r in rows])

    # Dot product = cosine similarity (embeddings normalizados)
    scores = embeddings @ query_vec
    top_indices = np.argsort(scores)[-limit:][::-1]

    return [(ids[i], float(scores[i])) for i in top_indices]


# ──────────────────────────────────────────────
# Reciprocal Rank Fusion
# ──────────────────────────────────────────────

def _reciprocal_rank_fusion(
    list_a: list[tuple[int, float]],
    list_b: list[tuple[int, float]],
    k: int = 60,
) -> list[tuple[int, float]]:
    """Combina duas listas ranqueadas usando Reciprocal Rank Fusion.

    Score = sum(1 / (k + rank)) para cada lista.
    """
    scores: dict[int, float] = {}

    for rank, (doc_id, _) in enumerate(list_a):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

    for rank, (doc_id, _) in enumerate(list_b):
        scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (k + rank + 1)

    # Ordenar por score decrescente
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


# ──────────────────────────────────────────────
# Fetch
# ──────────────────────────────────────────────

def _fetch_chunk(conn: sqlite3.Connection, chunk_id: int) -> Chunk | None:
    """Busca dados completos de um chunk pelo ID."""
    row = conn.execute(
        """SELECT id, source_file, register, field_name, heading, content, page_number
           FROM chunks WHERE id = ?""",
        (chunk_id,),
    ).fetchone()

    if not row:
        return None

    return Chunk(
        id=row[0],
        source_file=row[1],
        register=row[2],
        field_name=row[3],
        heading=row[4],
        content=row[5],
        page_number=row[6],
    )


def _fetch_chunk_from_db(db_path: str | Path, chunk_id: int) -> Chunk | None:
    """Abre conexão, busca chunk, fecha conexão."""
    conn = sqlite3.connect(str(db_path))
    chunk = _fetch_chunk(conn, chunk_id)
    conn.close()
    return chunk
