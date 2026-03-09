"""Coordinator helpers for bootstrap self-assignment flow."""

from __future__ import annotations

import json
from dataclasses import dataclass

from remora.bootstrap.activation import default_agent_id
from remora.bootstrap.bedrock import BootstrapEvent
from remora.core.store.event_store import EventStore


@dataclass
class AgentNeededPlan:
    node_id: str
    agent_id: str


async def find_unassigned_modules(event_store: EventStore) -> list[AgentNeededPlan]:
    """Find module nodes that do not yet have an assigned agent."""
    modules_raw = await event_store.nodes.read_graph({"match": {"kind": "module"}})
    module_rows = json.loads(modules_raw) if modules_raw else []
    if not isinstance(module_rows, list):
        module_rows = []

    agents_raw = await event_store.nodes.read_graph({"match": {"kind": "agent"}})
    agent_rows = json.loads(agents_raw) if agents_raw else []
    if not isinstance(agent_rows, list):
        agent_rows = []

    assigned_node_ids = {
        str(attrs.get("assigned_node_id"))
        for row in agent_rows
        if isinstance(row, dict)
        for attrs in [row.get("attrs")]
        if isinstance(attrs, dict) and attrs.get("assigned_node_id")
    }

    plans: list[AgentNeededPlan] = []
    for row in module_rows:
        if not isinstance(row, dict):
            continue
        node_id = row.get("id")
        if not isinstance(node_id, str) or not node_id:
            continue
        if node_id in assigned_node_ids:
            continue
        plans.append(AgentNeededPlan(node_id=node_id, agent_id=default_agent_id(node_id)))

    return plans


async def emit_agent_needed_events(
    event_store: EventStore,
    *,
    swarm_id: str,
    coordinator_id: str = "coordinator",
) -> int:
    """Emit AgentNeededEvent for each currently unassigned module."""
    plans = await find_unassigned_modules(event_store)
    emitted = 0

    for plan in plans:
        event = BootstrapEvent(
            event_type="AgentNeededEvent",
            node_id=plan.node_id,
            payload={
                "node_id": plan.node_id,
                "agent_id": plan.agent_id,
            },
            from_agent=coordinator_id,
            tags=("bootstrap", "agent-needed"),
        )
        await event_store.append(swarm_id, event)
        emitted += 1

    return emitted


__all__ = [
    "AgentNeededPlan",
    "find_unassigned_modules",
    "emit_agent_needed_events",
]
