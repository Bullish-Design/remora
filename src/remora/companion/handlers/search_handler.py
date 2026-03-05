from __future__ import annotations

from remora.core.events import _FrozenEvent
from remora.companion.events import CompanionContextExtracted, CompanionSearchCompleted
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState
from remora.companion.indexing_service import IndexingService
from embeddy.models import SearchMode

class SearchHandler(CompanionHandlerBase):
    """Searches for similar content using the current context."""
    
    def __init__(self, agent_id: str, indexing_service: IndexingService) -> None:
        super().__init__(agent_id)
        self.indexing = indexing_service

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, CompanionContextExtracted):
            return []
            
        # Use a combination of struct info and surrounding code as the query
        query_text = event.surrounding_code[:500]
        
        if not query_text.strip():
            return []
            
        results = await self.indexing.search(
            query=query_text,
            collection="python" if event.content_type == "code" else "markdown",
            top_k=10,
            mode=SearchMode.HYBRID
        )
        
        # Filter out self matches (exact chunk in same file)
        filtered_results = [r for r in results if not (r.file == event.file and r.start_line <= event.line <= r.end_line)]
        
        return [CompanionSearchCompleted(
            query=query_text[:100],
            results=tuple(filtered_results),
            search_type="hybrid"
        )]
