"""Testes do módulo de embeddings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np

from src.embeddings import (
    blob_to_embedding,
    embed_single,
    embed_texts,
    embedding_to_blob,
    get_model,
)


class TestEmbeddingConversion:
    def test_embedding_to_blob(self) -> None:
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        blob = embedding_to_blob(vec)
        assert isinstance(blob, bytes)
        assert len(blob) == 12  # 3 floats * 4 bytes

    def test_blob_to_embedding(self) -> None:
        vec = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        blob = embedding_to_blob(vec)
        recovered = blob_to_embedding(blob)
        np.testing.assert_array_almost_equal(recovered, vec)

    def test_roundtrip(self) -> None:
        original = np.random.rand(384).astype(np.float32)
        blob = embedding_to_blob(original)
        recovered = blob_to_embedding(blob)
        np.testing.assert_array_almost_equal(recovered, original)

    def test_float64_converted_to_float32(self) -> None:
        vec = np.array([1.0, 2.0], dtype=np.float64)
        blob = embedding_to_blob(vec)
        recovered = blob_to_embedding(blob)
        assert recovered.dtype == np.float32


class TestEmbedTexts:
    def test_returns_array(self) -> None:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(2, 384).astype(np.float32)
        with patch("src.embeddings.get_model", return_value=mock_model):
            result = embed_texts(["hello", "world"])
            assert result.shape == (2, 384)

    def test_batch_size_forwarded(self) -> None:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        with patch("src.embeddings.get_model", return_value=mock_model):
            embed_texts(["test"], batch_size=32)
            mock_model.encode.assert_called_once()
            call_kwargs = mock_model.encode.call_args
            assert call_kwargs[1]["batch_size"] == 32

    def test_progress_bar_for_large_batches(self) -> None:
        mock_model = MagicMock()
        texts = [f"text_{i}" for i in range(150)]
        mock_model.encode.return_value = np.random.rand(150, 384).astype(np.float32)
        with patch("src.embeddings.get_model", return_value=mock_model):
            embed_texts(texts)
            call_kwargs = mock_model.encode.call_args
            assert call_kwargs[1]["show_progress_bar"] is True

    def test_no_progress_bar_for_small_batches(self) -> None:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(3, 384).astype(np.float32)
        with patch("src.embeddings.get_model", return_value=mock_model):
            embed_texts(["a", "b", "c"])
            call_kwargs = mock_model.encode.call_args
            assert call_kwargs[1]["show_progress_bar"] is False


class TestEmbedSingle:
    def test_returns_1d(self) -> None:
        mock_model = MagicMock()
        mock_model.encode.return_value = np.random.rand(1, 384).astype(np.float32)
        with patch("src.embeddings.get_model", return_value=mock_model):
            result = embed_single("hello")
            assert result.shape == (384,)


class TestGetModel:
    def test_lazy_loading(self) -> None:
        import src.embeddings as emb
        original = emb._model
        try:
            emb._model = None
            mock_cls = MagicMock()
            mock_instance = MagicMock()
            mock_cls.return_value = mock_instance
            with (
                patch("src.embeddings.SentenceTransformer", mock_cls, create=True),
                patch.dict("sys.modules", {"sentence_transformers": MagicMock(SentenceTransformer=mock_cls)}),
            ):
                    # Force reimport
                    model = get_model()
                    assert model is not None
        finally:
            emb._model = original

    def test_cached_after_first_call(self) -> None:
        import src.embeddings as emb
        original = emb._model
        try:
            emb._model = "cached_model"
            model = get_model()
            assert model == "cached_model"
        finally:
            emb._model = original
