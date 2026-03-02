# ABOUTME: Tests for the local embedding provider (sentence-transformers).
# ABOUTME: Contains fast unit tests (mocked model) and slow integration tests (real model).
from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from forkhub.embeddings.local import LocalEmbeddingProvider
from forkhub.interfaces import EmbeddingProvider

# ===========================================================================
# Fast unit tests (mock the model)
# ===========================================================================


class TestLocalEmbeddingProviderUnit:
    """Unit tests for LocalEmbeddingProvider with mocked sentence-transformers."""

    def test_conforms_to_protocol(self) -> None:
        """LocalEmbeddingProvider satisfies EmbeddingProvider protocol."""
        provider = LocalEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)

    def test_dimensions_returns_384(self) -> None:
        """Default model returns 384 dimensions."""
        provider = LocalEmbeddingProvider()
        assert provider.dimensions() == 384

    def test_lazy_loading_no_model_at_init(self) -> None:
        """Model is not loaded during __init__."""
        provider = LocalEmbeddingProvider()
        assert provider._model is None

    async def test_embed_calls_model_encode(self) -> None:
        """embed() calls the underlying model's encode method."""
        mock_model = MagicMock()
        fake_embeddings = np.array([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
        mock_model.encode.return_value = fake_embeddings

        provider = LocalEmbeddingProvider()
        provider._model = mock_model

        result = await provider.embed(["hello", "world"])

        mock_model.encode.assert_called_once_with(["hello", "world"])
        assert len(result) == 2

    async def test_embed_returns_list_of_lists(self) -> None:
        """embed() returns list[list[float]]."""
        mock_model = MagicMock()
        fake_embeddings = np.array([[0.1, 0.2], [0.3, 0.4]])
        mock_model.encode.return_value = fake_embeddings

        provider = LocalEmbeddingProvider()
        provider._model = mock_model

        result = await provider.embed(["a", "b"])

        assert isinstance(result, list)
        for vec in result:
            assert isinstance(vec, list)
            for val in vec:
                assert isinstance(val, float)

    async def test_embed_handles_empty_input(self) -> None:
        """embed([]) returns []."""
        mock_model = MagicMock()
        # numpy returns a 2D array with shape (0, dim) for empty input
        mock_model.encode.return_value = np.array([]).reshape(0, 384)

        provider = LocalEmbeddingProvider()
        provider._model = mock_model

        result = await provider.embed([])

        assert result == []

    def test_custom_model_name(self) -> None:
        """Can initialize with a custom model name."""
        provider = LocalEmbeddingProvider(model_name="paraphrase-MiniLM-L3-v2")
        assert provider._model_name == "paraphrase-MiniLM-L3-v2"

    async def test_load_model_called_on_first_embed(self) -> None:
        """_load_model is invoked when embed() is called and _model is None."""
        mock_model = MagicMock()
        fake_embeddings = np.array([[0.1, 0.2, 0.3]])
        mock_model.encode.return_value = fake_embeddings

        provider = LocalEmbeddingProvider()
        assert provider._model is None

        with patch(
            "sentence_transformers.SentenceTransformer", return_value=mock_model
        ) as mock_cls:
            result = await provider.embed(["test"])

        mock_cls.assert_called_once_with("all-MiniLM-L6-v2")
        assert provider._model is mock_model
        assert len(result) == 1

    async def test_model_not_reloaded_on_subsequent_calls(self) -> None:
        """Model is loaded once and reused on subsequent embed() calls."""
        mock_model = MagicMock()
        fake_embeddings = np.array([[0.1, 0.2, 0.3]])
        mock_model.encode.return_value = fake_embeddings

        provider = LocalEmbeddingProvider()
        provider._model = mock_model

        await provider.embed(["first"])
        await provider.embed(["second"])

        # encode should be called twice, but model should still be the same object
        assert mock_model.encode.call_count == 2
        assert provider._model is mock_model


# ===========================================================================
# Slow integration tests (real model download)
# ===========================================================================


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    dot = np.dot(a_arr, b_arr)
    norm = np.linalg.norm(a_arr) * np.linalg.norm(b_arr)
    if norm == 0:
        return 0.0
    return float(dot / norm)


@pytest.mark.slow
class TestLocalEmbeddingProviderIntegration:
    """Integration tests that use the real sentence-transformers model."""

    async def test_real_embed_produces_384_dim_vectors(self) -> None:
        """Real embedding produces 384-dimensional vectors."""
        provider = LocalEmbeddingProvider()
        result = await provider.embed(["Hello world"])

        assert len(result) == 1
        assert len(result[0]) == 384
        # Values should be real floats, not all zeros
        assert any(v != 0.0 for v in result[0])

    async def test_similar_texts_have_high_similarity(self) -> None:
        """Similar texts should produce similar embeddings (cosine > 0.8)."""
        provider = LocalEmbeddingProvider()
        result = await provider.embed([
            "The cat sat on the mat",
            "A cat was sitting on a mat",
        ])

        similarity = _cosine_similarity(result[0], result[1])
        assert similarity > 0.8, f"Expected similarity > 0.8, got {similarity}"

    async def test_different_texts_have_lower_similarity(self) -> None:
        """Unrelated texts should have lower similarity than similar texts."""
        provider = LocalEmbeddingProvider()
        result = await provider.embed([
            "The cat sat on the mat",
            "A cat was sitting on a mat",
            "Quantum mechanics describes subatomic particles",
        ])

        similar_score = _cosine_similarity(result[0], result[1])
        different_score = _cosine_similarity(result[0], result[2])

        assert similar_score > different_score, (
            f"Similar texts ({similar_score}) should score higher "
            f"than different texts ({different_score})"
        )

    async def test_multiple_texts_batch(self) -> None:
        """Embedding multiple texts returns one vector per input."""
        provider = LocalEmbeddingProvider()
        texts = ["alpha", "beta", "gamma", "delta"]
        result = await provider.embed(texts)

        assert len(result) == 4
        for vec in result:
            assert len(vec) == 384
