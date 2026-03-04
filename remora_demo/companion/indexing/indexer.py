"""Main indexing pipeline for Companion.

Orchestrates chunking, embedding, and storage.
Supports incremental updates and web content ingestion.
"""

import fnmatch
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from remora_demo.companion.indexing.chunker import ChunkConfig, chunk_file, chunk_text
from remora_demo.companion.indexing.embedder import EmbedderBase, EmbeddingConfig, create_embedder
from remora_demo.companion.indexing.store import Chunk, VectorStore

logger = logging.getLogger(__name__)


@dataclass
class IndexConfig:
    """Configuration for the indexing pipeline."""

    # Paths
    db_path: Path = field(default_factory=lambda: Path(".companion/index.db"))

    # File filtering
    include_patterns: list[str] = field(default_factory=lambda: ["*.py", "*.md", "*.txt", "*.js", "*.ts", "*.rst"])
    exclude_patterns: list[str] = field(
        default_factory=lambda: [
            "**/node_modules/**",
            "**/.git/**",
            "**/__pycache__/**",
            "**/.venv/**",
            "**/venv/**",
            "**/.mypy_cache/**",
            "**/.pytest_cache/**",
            "**/dist/**",
            "**/build/**",
            "**/*.min.js",
            "**/*.min.css",
        ]
    )

    # Embedding
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)

    # Chunking
    chunking: ChunkConfig = field(default_factory=ChunkConfig)

    # Batching
    batch_size: int = 32


class Indexer:
    """Main indexing pipeline.

    Handles:
    - Scanning directories for files
    - Chunking files into semantic pieces
    - Embedding chunks
    - Storing in vector database
    - Incremental updates
    """

    def __init__(self, config: IndexConfig | None = None) -> None:
        self.config = config or IndexConfig()
        self._embedder: EmbedderBase | None = None
        self._store: VectorStore | None = None

    @property
    def embedder(self) -> EmbedderBase:
        """Lazy-load embedder."""
        if self._embedder is None:
            self._embedder = create_embedder(self.config.embedding)
        return self._embedder

    @property
    def store(self) -> VectorStore:
        """Lazy-load vector store."""
        if self._store is None:
            # Ensure parent directory exists
            self.config.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._store = VectorStore(self.config.db_path, embedding_dim=self.embedder.dimension)
        return self._store

    def _should_include(self, path: Path) -> bool:
        """Check if a file should be indexed."""
        path_str = str(path)

        # Check exclude patterns first
        for pattern in self.config.exclude_patterns:
            if fnmatch.fnmatch(path_str, pattern):
                return False

        # Check include patterns
        for pattern in self.config.include_patterns:
            if fnmatch.fnmatch(path.name, pattern):
                return True

        return False

    def _scan_directory(self, root: Path) -> Iterator[Path]:
        """Scan directory for indexable files."""
        for path in root.rglob("*"):
            if path.is_file() and self._should_include(path):
                yield path

    def _embed_chunks(self, chunks: list[Chunk]) -> list[Chunk]:
        """Embed a batch of chunks."""
        if not chunks:
            return chunks

        texts = [c.content for c in chunks]
        embeddings = self.embedder.embed(texts)

        for chunk, embedding in zip(chunks, embeddings, strict=True):
            chunk.embedding = embedding

        return chunks

    def index_file(self, file_path: Path) -> int:
        """Index a single file.

        Args:
            file_path: Path to the file

        Returns:
            Number of chunks indexed
        """
        logger.info(f"Indexing {file_path}")

        # Remove existing chunks for this file (for updates)
        self.store.delete_by_file(str(file_path))

        # Chunk the file
        chunks = list(chunk_file(file_path, config=self.config.chunking))

        if not chunks:
            logger.debug(f"No chunks generated for {file_path}")
            return 0

        # Embed and store in batches
        total = 0
        for i in range(0, len(chunks), self.config.batch_size):
            batch = chunks[i : i + self.config.batch_size]
            batch = self._embed_chunks(batch)
            self.store.add_many(batch)
            total += len(batch)

        logger.info(f"Indexed {total} chunks from {file_path}")
        return total

    def index_directory(self, root: Path, progress_callback: callable = None) -> dict[str, int]:
        """Index all files in a directory.

        Args:
            root: Root directory to index
            progress_callback: Optional callback(file_path, chunks_indexed)

        Returns:
            Dict with statistics
        """
        files = list(self._scan_directory(root))
        total_files = len(files)
        total_chunks = 0
        errors = []

        logger.info(f"Found {total_files} files to index in {root}")

        for i, file_path in enumerate(files):
            try:
                chunks_indexed = self.index_file(file_path)
                total_chunks += chunks_indexed

                if progress_callback:
                    progress_callback(file_path, chunks_indexed)

            except Exception as e:
                logger.error(f"Error indexing {file_path}: {e}")
                errors.append((str(file_path), str(e)))

        return {
            "total_files": total_files,
            "total_chunks": total_chunks,
            "errors": errors,
            "store_stats": self.store.stats(),
        }

    def index_text(
        self,
        content: str,
        source_id: str,
        content_type: str = "markdown",
        metadata: dict | None = None,
    ) -> int:
        """Index raw text content (e.g., from web clipper).

        Args:
            content: Text content to index
            source_id: Unique identifier for the source (URL, etc.)
            content_type: Type of content ("markdown", "prose")
            metadata: Additional metadata to attach to chunks

        Returns:
            Number of chunks indexed
        """
        logger.info(f"Indexing text from {source_id}")

        # Remove existing chunks for this source
        self.store.delete_by_file(source_id)

        # Chunk the text
        chunks = list(chunk_text(content, source_id, content_type, self.config.chunking))

        if not chunks:
            logger.debug(f"No chunks generated for {source_id}")
            return 0

        # Add metadata to chunks
        if metadata:
            for chunk in chunks:
                chunk.metadata = {**(chunk.metadata or {}), **metadata}

        # Embed and store
        chunks = self._embed_chunks(chunks)
        self.store.add_many(chunks)

        logger.info(f"Indexed {len(chunks)} chunks from {source_id}")
        return len(chunks)

    def search(
        self,
        query: str,
        limit: int = 10,
        content_type: str | None = None,
    ) -> list:
        """Search for similar content.

        Args:
            query: Search query text
            limit: Maximum results
            content_type: Filter by content type

        Returns:
            List of SearchResult
        """
        query_embedding = self.embedder.embed_query(query)
        return self.store.search(query_embedding, limit=limit, content_type=content_type)

    def close(self) -> None:
        """Close resources."""
        if self._store:
            self._store.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# Convenience function for CLI usage
def index_workspace(
    workspace_path: Path,
    db_path: Path | None = None,
    model_name: str | None = None,
) -> dict:
    """Index a workspace directory.

    Args:
        workspace_path: Directory to index
        db_path: Path for the database (default: .companion/index.db)
        model_name: Embedding model name (default: Qwen/Qwen3-Embedding-0.6B)

    Returns:
        Indexing statistics
    """
    config = IndexConfig()

    if db_path:
        config.db_path = db_path

    if model_name:
        config.embedding.model_name = model_name

    with Indexer(config) as indexer:
        return indexer.index_directory(workspace_path)
