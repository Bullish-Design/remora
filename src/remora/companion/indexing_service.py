from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.companion.config import IndexingConfig

if TYPE_CHECKING:
    from embeddy.models import IngestStats, SearchMode


class IndexingService:
    """Thin wrapper around embeddy for companion indexing and search."""

    def __init__(self, config: IndexingConfig, workspace_path: Path) -> None:
        # Import embeddy lazily; companion is optional and should not block
        # core LSP startup when companion is not actively used.
        from embeddy import Embedder, Pipeline, SearchService, VectorStore
        from embeddy.config import ChunkConfig, EmbedderConfig, StoreConfig

        self._config = config
        self._workspace_path = Path(workspace_path)
        store_db_path = config.resolve_store_db_path(self._workspace_path)
        store_db_path.parent.mkdir(parents=True, exist_ok=True)

        embedder_config = EmbedderConfig(**dict(config.embedder))
        store_config = StoreConfig(**{**dict(config.store), "db_path": str(store_db_path)})
        self._chunk_config = ChunkConfig(**dict(config.chunk))

        self._embedder = Embedder(embedder_config)
        self._store = VectorStore(store_config)
        self._pipeline_cls = Pipeline
        self._pipelines: dict[str, Any] = {}
        self._search = SearchService(embedder=self._embedder, store=self._store)

    async def initialize(self) -> None:
        await self._store.initialize()
        # Create pipelines per collection
        for collection_name in self._config.collections.values():
            self._pipelines[collection_name] = self._pipeline_cls(
                embedder=self._embedder,
                store=self._store,
                collection=collection_name,
                chunk_config=self._chunk_config,
            )

    async def index_file(self, path: str) -> IngestStats:
        collection = self._collection_for_file(path)
        pipeline = self._pipelines[collection]
        return await pipeline.ingest_file(path)

    async def reindex_file(self, path: str) -> IngestStats:
        collection = self._collection_for_file(path)
        pipeline = self._pipelines[collection]
        return await pipeline.reindex_file(path)

    async def search(
        self,
        query: str,
        collection: str | None = None,
        top_k: int = 10,
        mode: SearchMode | None = None,
    ) -> list[dict[str, object]]:
        if mode is None:
            from embeddy.models import SearchMode

            mode = SearchMode.HYBRID
        target = collection or "python"
        results = await self._search.search(
            query=query,
            collection=target,
            top_k=top_k,
            mode=mode,
        )
        return [
            {
                "file": r.source_path or "",
                "chunk_text": r.content,
                "score": r.score,
                "content_type": r.content_type,
                "chunk_type": r.chunk_type,
                "start_line": r.start_line or 0,
                "end_line": r.end_line or 0,
                "name": r.name,
            }
            for r in results.results
        ]

    async def index_directory(self, root: Path) -> IngestStats:
        from embeddy.models import IngestStats

        stats = IngestStats()
        for collection_name, pipeline in self._pipelines.items():
            include = self._include_for_collection(collection_name)
            result = await pipeline.ingest_directory(str(root), include=include)
            # Aggregate stats
            stats.files_processed += result.files_processed
            stats.chunks_stored += result.chunks_stored
            stats.chunks_skipped += result.chunks_skipped
        return stats

    def _collection_for_file(self, path: str) -> str:
        ext = Path(path).suffix.lower()
        mapping = {".py": "python", ".md": "markdown"}
        return mapping.get(ext, "config")

    def _include_for_collection(self, collection: str) -> list[str]:
        mapping = {
            "python": ["*.py"],
            "markdown": ["*.md"],
            "config": ["*.toml", "*.yaml", "*.yml", "*.json"],
        }
        return mapping.get(collection, ["*"])

    async def close(self) -> None:
        # embeddy cleanup if needed
        pass
