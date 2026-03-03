"""Indexing infrastructure for Companion: embeddings, chunking, vector store."""

from remora_demo.companion.indexing.chunker import ChunkConfig, chunk_file, chunk_text
from remora_demo.companion.indexing.embedder import (
    EmbedderBase,
    EmbeddingConfig,
    SentenceTransformerEmbedder,
    create_embedder,
)
from remora_demo.companion.indexing.indexer import IndexConfig, Indexer, index_workspace
from remora_demo.companion.indexing.store import Chunk, SearchResult, VectorStore

__all__ = [
    # Store
    "VectorStore",
    "Chunk",
    "SearchResult",
    # Embedder
    "EmbedderBase",
    "EmbeddingConfig",
    "SentenceTransformerEmbedder",
    "create_embedder",
    # Chunker
    "ChunkConfig",
    "chunk_file",
    "chunk_text",
    # Indexer
    "IndexConfig",
    "Indexer",
    "index_workspace",
]
