"""NodeAgentRegistry - manages the pool of live NodeAgent instances."""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from remora.companion.node_agent import NodeAgent

if TYPE_CHECKING:
    from remora.companion.config import CompanionConfig
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.event_bus import EventBus

logger = logging.getLogger("remora.companion.registry")


class NodeAgentRegistry:
    """Lazy-loading, LRU-evicting pool of NodeAgent instances."""

    def __init__(
        self,
        cairn_service: "CairnWorkspaceService",
        event_bus: "EventBus",
        config: "CompanionConfig",
    ) -> None:
        self._cairn = cairn_service
        self._event_bus = event_bus
        self._config = config
        self._agents: dict[str, NodeAgent] = {}
        self._node_locks: dict[str, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()

    async def get_or_create(self, node: "AgentNode") -> NodeAgent:
        node_id = node.node_id
        if node_id in self._agents:
            return self._agents[node_id]

        async with self._pool_lock:
            if node_id not in self._node_locks:
                self._node_locks[node_id] = asyncio.Lock()

        async with self._node_locks[node_id]:
            if node_id in self._agents:
                return self._agents[node_id]
            if len(self._agents) >= self._config.max_active_agents:
                await self._evict_lru()
            workspace = await self._cairn.get_agent_workspace(node_id)
            agent = NodeAgent(node=node, workspace=workspace, event_bus=self._event_bus, config=self._config)
            await agent.initialize()
            self._agents[node_id] = agent
            logger.debug("NodeAgent created for %s (pool size: %d)", node_id, len(self._agents))
            return agent

    def get(self, node_id: str) -> NodeAgent | None:
        return self._agents.get(node_id)

    async def evict(self, node_id: str) -> None:
        async with self._pool_lock:
            self._agents.pop(node_id, None)
            logger.debug("NodeAgent evicted: %s", node_id)

    async def _evict_lru(self) -> None:
        if not self._agents:
            return
        lru_id = min(self._agents, key=lambda nid: self._agents[nid]._last_visited)
        self._agents.pop(lru_id)
        logger.debug("NodeAgent LRU evicted: %s", lru_id)

    @property
    def active_count(self) -> int:
        return len(self._agents)


__all__ = ["NodeAgentRegistry"]
