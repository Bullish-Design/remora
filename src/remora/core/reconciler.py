"""Startup reconciliation for the reactive swarm.

This module provides the reconcile_on_startup function that:
- Discovers current CST nodes
- Diff against existing swarm state
- Creates new agents, marks deleted agents as orphaned
- Registers default subscriptions
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from remora.core.discovery import CSTNode, discover
from remora.core.agent_state import AgentState, save as save_agent_state
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.utils import PathLike, normalize_path

logger = logging.getLogger(__name__)


def get_agent_dir(swarm_root: Path, agent_id: str) -> Path:
    """Get the directory for an agent."""
    return swarm_root / "agents" / agent_id[:2] / agent_id


def get_agent_state_path(swarm_root: Path, agent_id: str) -> Path:
    """Get the path to an agent's state file."""
    return get_agent_dir(swarm_root, agent_id) / "state.jsonl"


def get_agent_workspace_path(swarm_root: Path, agent_id: str) -> Path:
    """Get the path to an agent's workspace."""
    return swarm_root / "workspaces" / f"{agent_id}.db"


async def reconcile_on_startup(
    project_path: PathLike,
    swarm_state: SwarmState,
    subscriptions: SubscriptionRegistry,
    discovery_paths: list[str] | None = None,
    languages: list[str] | None = None,
) -> dict[str, Any]:
    """Reconcile swarm state with discovered nodes.

    Args:
        project_path: Path to the project root
        swarm_state: SwarmState registry
        subscriptions: SubscriptionRegistry for agent subscriptions
        discovery_paths: Paths to discover (default: ["src/"])
        languages: Languages to filter (default: None for all)

    Returns:
        Dictionary with counts of created, deleted, and updated agents
    """
    project_path = normalize_path(project_path)
    swarm_root = project_path / ".remora"

    nodes = discover(
        [project_path / p for p in (discovery_paths or ["src/"])],
        languages=languages,
    )

    node_map = {node.node_id: node for node in nodes}

    existing_agents = swarm_state.list_agents(status="active")
    existing_ids = {agent["agent_id"] for agent in existing_agents}

    discovered_ids = set(node_map.keys())

    new_ids = discovered_ids - existing_ids
    deleted_ids = existing_ids - discovered_ids

    created = 0
    orphaned = 0

    for node_id in new_ids:
        node = node_map[node_id]
        metadata = AgentMetadata(
            agent_id=node.node_id,
            node_type=node.node_type,
            file_path=node.file_path,
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
        )
        swarm_state.upsert(metadata)

        agent_dir = get_agent_dir(swarm_root, node.node_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        state = AgentState(
            agent_id=node.node_id,
            node_type=node.node_type,
            file_path=node.file_path,
            range=(node.start_line, node.end_line),
        )
        save_agent_state(get_agent_state_path(swarm_root, node.node_id), state)

        await subscriptions.register_defaults(
            node.node_id,
            node.file_path,
        )

        created += 1

    for agent_id in deleted_ids:
        swarm_state.mark_orphaned(agent_id)
        await subscriptions.unregister_all(agent_id)
        orphaned += 1

    logger.info(f"Reconciliation complete: {created} new, {orphaned} orphaned")

    return {
        "created": created,
        "orphaned": orphaned,
        "total": len(discovered_ids),
    }


__all__ = [
    "get_agent_dir",
    "get_agent_state_path",
    "get_agent_workspace_path",
    "reconcile_on_startup",
]
