# ABOUTME: Local embedding provider using sentence-transformers (all-MiniLM-L6-v2).
# ABOUTME: Free, runs locally, produces 384-dimensional embeddings.
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class LocalEmbeddingProvider:
    """Local embedding provider using sentence-transformers.

    Uses all-MiniLM-L6-v2 by default (384 dimensions).
    Model is lazy-loaded on first embed() call to avoid startup cost.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None

    def _load_model(self) -> None:
        """Load the sentence-transformers model (lazy, on first use)."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Returns a list of embedding vectors, one per input text.
        Each vector is a list of floats with length == self.dimensions().
        The synchronous encode call is run in a thread executor to avoid
        blocking the event loop.
        """
        self._load_model()
        assert self._model is not None
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(None, self._model.encode, texts)
        return [emb.tolist() for emb in embeddings]

    def dimensions(self) -> int:
        """Return the embedding dimension (384 for all-MiniLM-L6-v2)."""
        return 384
