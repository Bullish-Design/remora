"""Coordinator helpers for bootstrap self-assignment flow.

PHASE-1 NOTE: this is the Python coordinator implementation. A future phase
will shift orchestration to the LLM coordinator schema in
``bootstrap/agents/coordinator.yaml`` while keeping these helpers as utilities.
"""

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


async def _read_assigned_node_ids(event_store: EventStore) -> set[str]:
    agents_raw = await event_store.nodes.read_graph({"match": {"kind": "agent"}})
    agent_rows = json.loads(agents_raw) if agents_raw else []
    if not isinstance(agent_rows, list):
        return set()

    assigned: set[str] = set()
    for row in agent_rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attrs")
        if isinstance(attrs, dict) and attrs.get("assigned_node_id"):
            assigned.add(str(attrs["assigned_node_id"]))
    return assigned


async def find_unassigned_nodes(
    event_store: EventStore,
    *,
    file_path: str | None = None,
    node_types: set[str] | None = None,
) -> list[AgentNeededPlan]:
    """Find code nodes that do not yet have an assigned bootstrap agent."""
    assigned_node_ids = await _read_assigned_node_ids(event_store)
    node_rows = await event_store.nodes.list_nodes(file_path=file_path)

    plans: list[AgentNeededPlan] = []
    ordered_nodes = sorted(
        node_rows,
        key=lambda node: (
            node.file_path,
            node.start_line,
            node.end_line,
            node.node_type,
            node.node_id,
        ),
    )
    for node in ordered_nodes:
        if node_types and node.node_type not in node_types:
            continue
        node_id = node.node_id
        if not node_id or node_id in assigned_node_ids:
            continue
        plans.append(AgentNeededPlan(node_id=node_id, agent_id=default_agent_id(node_id)))

    return plans


async def find_unassigned_modules(event_store: EventStore) -> list[AgentNeededPlan]:
    """Find file/module nodes that do not yet have an assigned agent.

    Convenience wrapper around ``find_unassigned_nodes(..., node_types={"file"})``.
    """
    return await find_unassigned_nodes(event_store, node_types={"file"})


async def emit_agent_needed_events(
    event_store: EventStore,
    *,
    swarm_id: str,
    coordinator_id: str = "coordinator",
) -> int:
    """Emit AgentNeededEvent for each currently unassigned module."""
    return await emit_agent_needed_events_for_nodes(
        event_store,
        swarm_id=swarm_id,
        coordinator_id=coordinator_id,
        node_types={"file"},
    )


async def emit_agent_needed_events_for_nodes(
    event_store: EventStore,
    *,
    swarm_id: str,
    coordinator_id: str = "coordinator",
    file_path: str | None = None,
    node_types: set[str] | None = None,
) -> int:
    """Emit AgentNeededEvent for currently unassigned nodes."""
    plans = await find_unassigned_nodes(
        event_store,
        file_path=file_path,
        node_types=node_types,
    )
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
    "find_unassigned_nodes",
    "find_unassigned_modules",
    "emit_agent_needed_events_for_nodes",
    "emit_agent_needed_events",
]
