"""Embedding search agent.

Searches the vector store for content similar to the current context.
Writes to /companion/search/similar/* workspace paths.
"""

from dataclasses import dataclass
from typing import Any

from remora_demo.companion.agents.base import AgentBase, WorkspaceInterface, subscribe
from remora_demo.companion.indexing import Indexer, SearchResult
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import SimilarResult


@dataclass
class EmbeddingSearcherConfig:
    """Configuration for embedding searcher."""

    max_results: int = 10
    min_score: float = 0.1  # Minimum similarity score to include
    debounce_ms: int = 200  # Debounce searches


class EmbeddingSearcher(AgentBase):
    """Searches for similar content via embeddings.

    Subscribes to: /companion/context/current_region
    Writes to: /companion/search/similar/*
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        indexer: Indexer,
        config: EmbeddingSearcherConfig | None = None,
    ) -> None:
        super().__init__("embedding_searcher")
        self.workspace = workspace
        self.indexer = indexer
        self.config = config or EmbeddingSearcherConfig()

    @subscribe("/companion/context/current_region", debounce_ms=200)
    async def on_region_change(self, change: PathChanged) -> None:
        """Handle context region changes."""
        if not change.value:
            return

        await self.search_similar(change.value)

    async def search_similar(self, query_text: str) -> list[SearchResult]:
        """Search for similar content and write results to workspace."""
        # Record input
        self.record_input("/companion/context/current_region", query_text[:100])

        # Get current file to exclude self-matches
        current_file = await self.workspace.read("/companion/context/file_path")

        # Search
        results = self.indexer.search(
            query=query_text,
            limit=self.config.max_results + 5,  # Get extra for filtering
        )

        # Filter and convert results
        similar_results = []
        for r in results:
            # Skip self-matches
            if current_file and r.chunk.file_path == current_file:
                continue

            # Skip low-score results
            if r.score < self.config.min_score:
                continue

            similar = SimilarResult(
                file=r.chunk.file_path,
                snippet=r.chunk.content[:200] + "..." if len(r.chunk.content) > 200 else r.chunk.content,
                score=r.score,
                content_type=r.chunk.content_type,
                start_line=r.chunk.start_line,
                end_line=r.chunk.end_line,
            )
            similar_results.append(similar)

            if len(similar_results) >= self.config.max_results:
                break

        # Clear old results
        old_paths = await self.workspace.list("/companion/search/similar/*")
        for path in old_paths:
            await self.workspace.delete(path)

        # Write new results
        for i, result in enumerate(similar_results):
            path = f"/companion/search/similar/{i}"
            await self.workspace.write(path, result)
            self.record_output(path)

        return results

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, PathChanged):
            await self.on_region_change(data)
