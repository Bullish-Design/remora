"""MicroSwarm base types and orchestrator."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from remora.core.agents.agent_node import AgentNode
    from remora.core.agents.workspace import AgentWorkspace
    from remora.core.events.event_bus import EventBus

logger = logging.getLogger("remora.companion.swarms")


@dataclass
class SwarmContext:
    """All context a MicroSwarm might need."""

    node_id: str
    node: "AgentNode"
    workspace: "AgentWorkspace"
    session_id: str
    user_message: str
    assistant_message: str
    event_bus: "EventBus"
    model_name: str
    model_base_url: str
    model_api_key: str


class MicroSwarm(Protocol):
    """Protocol for MicroSwarm implementations."""

    async def run(self, ctx: SwarmContext) -> None: ...


async def run_post_exchange_swarms(ctx: SwarmContext, swarms: list[MicroSwarm]) -> None:
    """Run all swarms in parallel. Failures are logged and ignored."""

    async def _run_one(swarm: MicroSwarm) -> None:
        try:
            await swarm.run(ctx)
        except Exception:
            logger.exception("MicroSwarm %s failed for node %s", type(swarm).__name__, ctx.node_id)

    await asyncio.gather(*[_run_one(swarm) for swarm in swarms])


__all__ = ["SwarmContext", "MicroSwarm", "run_post_exchange_swarms"]
