"""Swarm executor for reactive agent execution.

This module provides SwarmExecutor which runs single agent turns
in response to events from the EventStore trigger queue.

Since Workstream B, ``run_agent()`` delegates to the shared
``execute_agent_turn()`` function in ``core.execution``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from structured_agents import build_client

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.execution import execute_agent_turn
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.utils import truncate

if TYPE_CHECKING:
    from remora.core.config import Config
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


class SwarmExecutor:
    """Executor for single agent turns in reactive swarm mode."""

    def __init__(
        self,
        config: "Config",
        event_bus: "EventBus | None",
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        swarm_id: str,
        project_root: Path,
    ):
        self.config = config
        self._event_bus = event_bus
        self._event_store = event_store
        self._subscriptions = subscriptions
        self._swarm_id = swarm_id
        self._project_root = project_root

        self._workspace_service = CairnWorkspaceService(
            config=config,
            swarm_root=config.swarm_root,
            project_root=project_root,
        )
        self._workspace_initialized = False

        # Connection pooling: create the LLM client once and reuse it
        self._client = build_client(
            {
                "base_url": config.model_base_url,
                "api_key": config.model_api_key or "EMPTY",
                "model": config.model_default,
                "timeout": config.timeout_s,
            }
        )

    async def run_agent(self, node: AgentNode, trigger_event: Any = None) -> str:
        """Run a single agent turn.

        Delegates to the shared ``execute_agent_turn()`` pipeline so that
        both CLI and LSP paths use identical bundle resolution, tool
        discovery, kernel wiring, and audit-trail recording.

        Args:
            node: The AgentNode to run
            trigger_event: The event that triggered this agent (optional)

        Returns:
            The agent's response as a string
        """
        logger.info("SwarmExecutor.run_agent starting for %s", node.node_id)

        if not self._workspace_initialized:
            await self._workspace_service.initialize()
            self._workspace_initialized = True

        result = await execute_agent_turn(
            node=node,
            config=self.config,
            event_store=self._event_store,
            subscriptions=self._subscriptions,
            swarm_id=self._swarm_id,
            project_root=self._project_root,
            trigger_event=trigger_event,
            workspace_service=self._workspace_service,
            client=self._client,
        )

        truncated_response = truncate(result.response_text, max_len=self.config.truncation_limit)
        return truncated_response


__all__ = ["SwarmExecutor"]
