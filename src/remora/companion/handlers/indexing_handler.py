from __future__ import annotations

from remora.core.events import _FrozenEvent, FileSavedEvent
from remora.companion.events import CompanionIndexUpdated
from remora.companion.handlers.base import CompanionHandlerBase
from remora.companion.state import CompanionState
from remora.companion.indexing_service import IndexingService

class IndexingHandler(CompanionHandlerBase):
    """Automatically indexes files when they are saved."""
    
    def __init__(self, agent_id: str, indexing_service: IndexingService) -> None:
        super().__init__(agent_id)
        self.indexing = indexing_service

    async def handle(self, event: _FrozenEvent, state: CompanionState) -> list[_FrozenEvent]:
        if not isinstance(event, FileSavedEvent):
            return []
            
        # Index the file using embeddy Pipeline
        index_updated_event = await self.indexing.reindex_file(event.path)
        
        return [index_updated_event]
