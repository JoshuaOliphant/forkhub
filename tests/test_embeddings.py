# ABOUTME: Tests for the local embedding provider (sentence-transformers).
# ABOUTME: Contains fast unit tests (mocked model) and slow integration tests (real model).
from __future__ import annotations

from forkhub.embeddings.local import LocalEmbeddingProvider

# ===========================================================================
# Fast unit tests (mock the model)
# ===========================================================================


class TestLocalEmbeddingProviderUnit:
    """Unit tests for LocalEmbeddingProvider with mocked sentence-transformers."""

    def test_dimensions_returns_384(self) -> None:
        """Default model returns 384 dimensions."""
        provider = LocalEmbeddingProvider()
        assert provider.dimensions() == 384
