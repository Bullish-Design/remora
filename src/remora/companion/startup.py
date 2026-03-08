"""Companion system startup."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from remora.companion.config import CompanionConfig
from remora.companion.registry import NodeAgentRegistry
from remora.companion.router import NodeAgentRouter

if TYPE_CHECKING:
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.event_bus import EventBus
    from remora.core.store.event_store import EventStore

logger = logging.getLogger("remora.companion.startup")


async def start_companion(
    event_store: EventStore,
    event_bus: EventBus,
    cairn_service: CairnWorkspaceService,
    config: CompanionConfig | None = None,
) -> NodeAgentRegistry:
    """Start the companion system and return the NodeAgentRegistry."""
    cfg = config or CompanionConfig()
    registry = NodeAgentRegistry(cairn_service=cairn_service, event_bus=event_bus, config=cfg)
    router = NodeAgentRouter(registry=registry, event_store=event_store)
    router.subscribe(event_bus)
    registry._router = router
    logger.info("Companion started (max_active_agents=%d)", cfg.max_active_agents)

    if cfg.auto_index:
        import asyncio

        try:
            from remora.companion.indexing_service import IndexingService

            indexing = IndexingService(cfg.indexing)
            await indexing.initialize()
            asyncio.create_task(indexing.index_directory(cfg.workspace_path))
            logger.info("Background workspace indexing started")
        except Exception:
            logger.warning("Failed to start vector indexing (non-fatal)", exc_info=True)

    return registry


__all__ = ["start_companion"]
