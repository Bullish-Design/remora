"""Companion system startup."""
from __future__ import annotations

import asyncio
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


def _build_indexing_service(config: CompanionConfig):
    from remora.companion.indexing_service import IndexingService

    return IndexingService(config.indexing, config.workspace_path)


async def _start_indexing_background(config: CompanionConfig) -> None:
    try:
        indexing = await asyncio.to_thread(_build_indexing_service, config)
        await indexing.initialize()
        asyncio.create_task(indexing.index_directory(config.workspace_path))
        logger.info("Background workspace indexing started")
    except Exception:
        logger.warning("Failed to start vector indexing (non-fatal)", exc_info=True)


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
        asyncio.create_task(_start_indexing_background(cfg))

    return registry


__all__ = ["start_companion"]
