"""NodeAgentRouter - routes EventBus events to the correct NodeAgent."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from remora.core.events.interaction_events import ContentChangedEvent, CursorFocusEvent, FileSavedEvent

if TYPE_CHECKING:
    from remora.companion.registry import NodeAgentRegistry
    from remora.core.store.event_store import EventStore

logger = logging.getLogger("remora.companion.router")


class NodeAgentRouter:
    """Subscribes to core interaction events and routes them to NodeAgents."""

    def __init__(self, registry: NodeAgentRegistry, event_store: EventStore) -> None:
        self._registry = registry
        self._event_store = event_store
        self._active_node_id: str | None = None

    def subscribe(self, event_bus) -> None:
        event_bus.subscribe(CursorFocusEvent, self._on_cursor_focus)
        event_bus.subscribe(ContentChangedEvent, self._on_content_changed)
        event_bus.subscribe(FileSavedEvent, self._on_file_saved)

    async def _on_cursor_focus(self, event: CursorFocusEvent) -> None:
        node_id = event.focused_agent_id
        if not node_id:
            return
        self._active_node_id = node_id
        node = await self._resolve_node(node_id)
        if node is None:
            logger.debug("cursor focus: no AgentNode found for %s", node_id)
            return
        try:
            agent = await self._registry.get_or_create(node)
            await agent.on_cursor_focus()
        except Exception:
            logger.exception("cursor focus handler failed for %s", node_id)

    async def _on_content_changed(self, event: ContentChangedEvent) -> None:
        for node_id, agent in list(self._registry._agents.items()):
            if agent.node.file_path == event.path:
                try:
                    await agent.on_content_changed(event.path, event.diff)
                except Exception:
                    logger.exception("content changed handler failed for %s", node_id)

    async def _on_file_saved(self, event: FileSavedEvent) -> None:
        for node_id, agent in list(self._registry._agents.items()):
            if agent.node.file_path == event.path:
                try:
                    await agent.on_file_saved(event.path)
                except Exception:
                    logger.exception("file saved handler failed for %s", node_id)

    async def _resolve_node(self, node_id: str):
        try:
            return await self._event_store.nodes.get_node(node_id)
        except Exception:
            logger.debug("node lookup failed for %s", node_id)
            return None

    @property
    def active_node_id(self) -> str | None:
        return self._active_node_id


__all__ = ["NodeAgentRouter"]
