from __future__ import annotations

import asyncio
from pydantic import BaseModel
from remora.core.events import _FrozenEvent, CursorFocusEvent, ContentChangedEvent, FileSavedEvent
from remora.companion.events import (
    CompanionContextExtracted, CompanionSearchCompleted, CompanionConnectionsFound,
    CompanionEditSummary, CompanionTaskInferred, CompanionClaimsChecked
)
from remora.companion.state import CompanionState
from remora.companion.handlers.base import CompanionHandler

# Reusing definitions from the plan
class HandlerConfig(BaseModel):
    handler_id: str
    debounce_ms: int = 0

class CompanionDispatcher:
    """Routes events to companion handlers via EventBus."""
    
    def __init__(
        self,
        event_store,
        event_bus,
        state: CompanionState,
        handlers: dict[str, CompanionHandler],
        handler_configs: dict[str, HandlerConfig] | None = None,
        session_id: str = "companion",
    ) -> None:
        self._store = event_store
        self._bus = event_bus
        self._state = state
        self._handlers = handlers
        self._configs = handler_configs or {}
        self._session_id = session_id
        self._debounce_tasks: dict[str, asyncio.Task] = {}
        
    def _build_routing_table(self) -> dict[type[_FrozenEvent], list[str]]:
        return {
            CursorFocusEvent: ["companion.context_extractor"],
            ContentChangedEvent: ["companion.edit_summarizer"],
            FileSavedEvent: ["companion.indexing_handler"],
            CompanionContextExtracted: [
                "companion.search_handler",
                "companion.task_inferrer",
                "companion.claim_checker",
                "companion.sidebar_composer",
            ],
            CompanionSearchCompleted: [
                "companion.connection_finder",
                "companion.sidebar_composer",
            ],
            CompanionConnectionsFound: ["companion.sidebar_composer"],
            CompanionEditSummary: ["companion.sidebar_composer"],
            CompanionTaskInferred: ["companion.sidebar_composer"],
            CompanionClaimsChecked: ["companion.sidebar_composer"],
        }
    
    async def start(self) -> None:
        """Register EventBus subscriptions for all handlers."""
        routing = self._build_routing_table()
        
        for event_type, handler_ids in routing.items():
            async def make_on_event(hids):
                async def on_event(event):
                    self._state.apply(event)
                    for hid in hids:
                        await self._dispatch(hid, event)
                return on_event
                
            handler_callback = await make_on_event(handler_ids)
            self._bus.subscribe(event_type.__name__, handler_callback)
            
    async def _dispatch(self, handler_id: str, event: _FrozenEvent) -> None:
        config = self._configs.get(handler_id)
        if config and config.debounce_ms > 0:
            await self._dispatch_debounced(handler_id, event, config.debounce_ms)
        else:
            await self._invoke(handler_id, event)
            
    async def _invoke(self, handler_id: str, event: _FrozenEvent) -> None:
        handler = self._handlers[handler_id]
        new_events = await handler.handle(event, self._state)
        for new_event in new_events:
            await self._store.append(self._session_id, new_event)
            await self._bus.publish(new_event)
            
    async def _dispatch_debounced(
        self, handler_id: str, event: _FrozenEvent, ms: int
    ) -> None:
        if handler_id in self._debounce_tasks:
            self._debounce_tasks[handler_id].cancel()
            
        async def delayed():
            await asyncio.sleep(ms / 1000)
            await self._invoke(handler_id, event)
            
        self._debounce_tasks[handler_id] = asyncio.create_task(delayed())
