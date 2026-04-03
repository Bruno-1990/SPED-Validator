"""Wrapper para geração de embeddings vetoriais."""

from __future__ import annotations

import numpy as np

_model = None


def get_model():  # type: ignore[no-untyped-def]
    """Carrega o modelo de embeddings (lazy loading)."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def embed_texts(texts: list[str], batch_size: int = 64) -> np.ndarray:
    """Gera embeddings normalizados para uma lista de textos.

    Retorna array (N, 384) float32.
    """
    model = get_model()
    result: np.ndarray = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=len(texts) > 100,
        normalize_embeddings=True,
    )
    return result


def embed_single(text: str) -> np.ndarray:
    """Gera embedding para um único texto. Retorna vetor (384,) float32."""
    result: np.ndarray = embed_texts([text])[0]
    return result


def embedding_to_blob(embedding: np.ndarray) -> bytes:
    """Converte embedding numpy para bytes (para armazenar no SQLite)."""
    return embedding.astype(np.float32).tobytes()


def blob_to_embedding(blob: bytes) -> np.ndarray:
    """Converte bytes do SQLite de volta para numpy array."""
    return np.frombuffer(blob, dtype=np.float32)
