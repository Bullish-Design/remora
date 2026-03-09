"""Companion system startup."""
from __future__ import annotations

import asyncio
import json
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
    async def _resolve_workspace_owner(node) -> str:
        try:
            raw = await event_store.nodes.read_graph(
                {"match": {"kind": "agent", "assigned_node_id": node.node_id}}
            )
            rows = json.loads(raw) if raw else []
            if isinstance(rows, list):
                agent_ids = sorted(
                    row.get("id")
                    for row in rows
                    if isinstance(row, dict) and isinstance(row.get("id"), str) and row.get("id")
                )
                if agent_ids:
                    return agent_ids[0]
        except Exception:
            logger.debug("workspace owner lookup failed for %s", node.node_id, exc_info=True)
        return node.node_id

    cfg = config or CompanionConfig()
    registry = NodeAgentRegistry(
        cairn_service=cairn_service,
        event_bus=event_bus,
        config=cfg,
        workspace_owner_resolver=_resolve_workspace_owner,
    )
    router = NodeAgentRouter(registry=registry, event_store=event_store)
    router.subscribe(event_bus)
    registry._router = router
    logger.info("Companion started (max_active_agents=%d)", cfg.max_active_agents)

    if cfg.auto_index:
        asyncio.create_task(_start_indexing_background(cfg))

    return registry


__all__ = ["start_companion"]
