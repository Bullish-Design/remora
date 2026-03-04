"""Embedding model abstraction for Companion.

Supports configurable embedding models via sentence-transformers
or any compatible backend.

Default model: Qwen/Qwen3-Embedding-0.6B (configurable)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class EmbeddingConfig:
    """Configuration for embedding model."""

    model_name: str = "Qwen/Qwen3-Embedding-0.6B"
    device: str = "cpu"  # "cpu", "cuda", "mps"
    normalize: bool = True
    batch_size: int = 32
    cache_dir: Path | None = None


class EmbedderBase(ABC):
    """Abstract base class for embedding models."""

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a list of texts.

        Args:
            texts: List of text strings to embed

        Returns:
            numpy array of shape (len(texts), embedding_dim)
        """
        pass

    @abstractmethod
    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query text.

        Some models use different prompts for queries vs documents.

        Args:
            query: Query text to embed

        Returns:
            numpy array of shape (embedding_dim,)
        """
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the embedding dimension."""
        pass


class SentenceTransformerEmbedder(EmbedderBase):
    """Embedder using sentence-transformers library.

    Supports any model from HuggingFace that works with sentence-transformers,
    including Qwen3-Embedding models.
    """

    def __init__(self, config: EmbeddingConfig | None = None) -> None:
        self.config = config or EmbeddingConfig()
        self._model = None
        self._dimension: int | None = None

    @property
    def model(self):
        """Lazy-load the model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            kwargs = {"device": self.config.device}
            if self.config.cache_dir:
                kwargs["cache_folder"] = str(self.config.cache_dir)

            self._model = SentenceTransformer(self.config.model_name, **kwargs)
            self._dimension = self._model.get_sentence_embedding_dimension()
        return self._model

    @property
    def dimension(self) -> int:
        """Return the embedding dimension."""
        if self._dimension is None:
            # Force model load to get dimension
            _ = self.model
        return self._dimension or 0

    def embed(self, texts: list[str]) -> np.ndarray:
        """Embed a list of texts."""
        embeddings = self.model.encode(
            texts,
            batch_size=self.config.batch_size,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        return np.array(embeddings)

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query.

        For Qwen3-Embedding, queries should be prefixed with "query: "
        but sentence-transformers handles this via prompts if configured.
        """
        embedding = self.model.encode(
            query,
            normalize_embeddings=self.config.normalize,
            show_progress_bar=False,
        )
        return np.array(embedding)


def create_embedder(config: EmbeddingConfig | None = None) -> EmbedderBase:
    """Factory function to create an embedder.

    Currently only supports sentence-transformers backend.
    Can be extended to support other backends (vLLM, Ollama, etc.)
    """
    return SentenceTransformerEmbedder(config)
