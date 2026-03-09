"""NodeAgentRegistry - manages the pool of live NodeAgent instances."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from remora.companion.node_agent import NodeAgent

if TYPE_CHECKING:
    from remora.companion.config import CompanionConfig
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.event_bus import EventBus
    WorkspaceOwnerResolver = Callable[[AgentNode], Awaitable[str]]
else:
    WorkspaceOwnerResolver = Callable[[object], Awaitable[str]]

logger = logging.getLogger("remora.companion.registry")


class NodeAgentRegistry:
    """Lazy-loading, LRU-evicting pool of NodeAgent instances."""

    def __init__(
        self,
        cairn_service: CairnWorkspaceService,
        event_bus: EventBus,
        config: CompanionConfig,
        workspace_owner_resolver: WorkspaceOwnerResolver | None = None,
    ) -> None:
        self._cairn = cairn_service
        self._event_bus = event_bus
        self._config = config
        self._workspace_owner_resolver = workspace_owner_resolver or self._default_workspace_owner
        self._agents: dict[str, NodeAgent] = {}
        self._workspace_owner_by_node: dict[str, str] = {}
        self._node_locks: dict[str, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()

    async def _default_workspace_owner(self, node: AgentNode) -> str:
        return node.node_id

    async def _resolve_workspace_owner(self, node: AgentNode) -> str:
        try:
            owner = await self._workspace_owner_resolver(node)
        except Exception:
            logger.exception("workspace owner resolver failed for %s", node.node_id)
            return node.node_id
        return owner or node.node_id

    async def get_or_create(self, node: AgentNode) -> NodeAgent:
        node_id = node.node_id
        workspace_owner_id = await self._resolve_workspace_owner(node)
        current_owner = self._workspace_owner_by_node.get(node_id)
        if node_id in self._agents and current_owner == workspace_owner_id:
            return self._agents[node_id]

        async with self._pool_lock:
            if node_id not in self._node_locks:
                self._node_locks[node_id] = asyncio.Lock()

        async with self._node_locks[node_id]:
            workspace_owner_id = await self._resolve_workspace_owner(node)
            current_owner = self._workspace_owner_by_node.get(node_id)
            if node_id in self._agents and current_owner == workspace_owner_id:
                return self._agents[node_id]
            if node_id in self._agents and current_owner != workspace_owner_id:
                self._agents.pop(node_id, None)
                logger.debug(
                    "NodeAgent workspace owner changed for %s: %s -> %s",
                    node_id,
                    current_owner,
                    workspace_owner_id,
                )
            if len(self._agents) >= self._config.max_active_agents:
                await self._evict_lru()
            workspace = await self._cairn.get_agent_workspace(workspace_owner_id)
            agent = NodeAgent(node=node, workspace=workspace, event_bus=self._event_bus, config=self._config)
            await agent.initialize()
            self._agents[node_id] = agent
            self._workspace_owner_by_node[node_id] = workspace_owner_id
            logger.debug("NodeAgent created for %s (pool size: %d)", node_id, len(self._agents))
            return agent

    def get(self, node_id: str) -> NodeAgent | None:
        return self._agents.get(node_id)

    async def evict(self, node_id: str) -> None:
        async with self._pool_lock:
            self._agents.pop(node_id, None)
            self._workspace_owner_by_node.pop(node_id, None)
            logger.debug("NodeAgent evicted: %s", node_id)

    async def _evict_lru(self) -> None:
        if not self._agents:
            return
        lru_id = min(self._agents, key=lambda nid: self._agents[nid]._last_visited)
        self._agents.pop(lru_id)
        self._workspace_owner_by_node.pop(lru_id, None)
        logger.debug("NodeAgent LRU evicted: %s", lru_id)

    @property
    def active_count(self) -> int:
        return len(self._agents)


__all__ = ["NodeAgentRegistry"]
