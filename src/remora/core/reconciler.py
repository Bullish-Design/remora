"""Startup reconciliation for the reactive swarm.

This module provides the reconcile_on_startup function that:
- Discovers current CST nodes
- Diff against existing swarm state
- Creates new agents, marks deleted agents as orphaned
- Registers default subscriptions
- Emits ContentChangedEvent for changed nodes
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.discovery import CSTNode, discover
from remora.core.agent_state import AgentState, load as load_agent_state, save as save_agent_state
from remora.core.events import ContentChangedEvent
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.utils import PathLike, normalize_path, to_project_relative

if TYPE_CHECKING:
    from remora.core.event_store import EventStore

logger = logging.getLogger(__name__)


def get_agent_dir(swarm_root: Path, agent_id: str) -> Path:
    """Get the directory for an agent."""
    return swarm_root / "agents" / agent_id[:2] / agent_id


def get_agent_state_path(swarm_root: Path, agent_id: str) -> Path:
    """Get the path to an agent's state file."""
    return get_agent_dir(swarm_root, agent_id) / "state.jsonl"


def get_agent_workspace_path(swarm_root: Path, agent_id: str) -> Path:
    """Get the path to an agent's workspace."""
    return get_agent_dir(swarm_root, agent_id) / "workspace.db"


async def reconcile_on_startup(
    project_path: PathLike,
    swarm_state: SwarmState,
    subscriptions: SubscriptionRegistry,
    discovery_paths: list[str] | None = None,
    languages: list[str] | None = None,
    event_store: "EventStore | None" = None,
    swarm_id: str = "swarm",
) -> dict[str, Any]:
    """Reconcile swarm state with discovered nodes.

    Args:
        project_path: Path to the project root
        swarm_state: SwarmState registry
        subscriptions: SubscriptionRegistry for agent subscriptions
        discovery_paths: Paths to discover (default: ["src/"])
        languages: Languages to filter (default: None for all)
        event_store: Optional EventStore for emitting ContentChangedEvents
        swarm_id: Swarm ID for event emission

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

    existing_agents = await swarm_state.list_agents(status="active")
    existing_ids = {agent.agent_id for agent in existing_agents}

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
            name=getattr(node, "name", ""),
            full_name=getattr(node, "full_name", ""),
            file_path=node.file_path,
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
        )
        await swarm_state.upsert(metadata)

        agent_dir = get_agent_dir(swarm_root, node.node_id)
        agent_dir.mkdir(parents=True, exist_ok=True)

        state = AgentState(
            agent_id=node.node_id,
            node_type=node.node_type,
            name=getattr(node, "name", ""),
            full_name=getattr(node, "full_name", ""),
            file_path=node.file_path,
            range=(node.start_line, node.end_line),
        )
        save_agent_state(get_agent_state_path(swarm_root, node.node_id), state)

        relative_path = to_project_relative(project_path, node.file_path)
        await subscriptions.register_defaults(
            node.node_id,
            relative_path,
        )

        created += 1

    for agent_id in deleted_ids:
        await swarm_state.mark_orphaned(agent_id)
        await subscriptions.unregister_all(agent_id)
        orphaned += 1

    updated = 0
    common_ids = discovered_ids.intersection(existing_ids)

    for node_id in common_ids:
        node = node_map[node_id]
        state_path = get_agent_state_path(swarm_root, node.node_id)
        try:
            state = load_agent_state(state_path)
            if state is None:
                continue

            file_path = Path(node.file_path)
            if not file_path.exists():
                continue

            file_mtime = file_path.stat().st_mtime
            if state.last_updated < file_mtime:
                if event_store is not None:
                    relative_path = to_project_relative(project_path, node.file_path)
                    event = ContentChangedEvent(
                        path=relative_path,
                        diff="File modified while daemon offline.",
                    )
                    await event_store.append(swarm_id, event)

                updated += 1
                state.last_updated = time.time()
                save_agent_state(state_path, state)

        except Exception as exc:
            logger.warning("Failed to reconcile state for %s: %s", node_id, exc)

    logger.info(
        "Reconciliation complete: %d new, %d orphaned, %d updated",
        created,
        orphaned,
        updated,
    )

    return {
        "created": created,
        "orphaned": orphaned,
        "updated": updated,
        "total": len(discovered_ids),
    }


__all__ = [
    "get_agent_dir",
    "get_agent_state_path",
    "get_agent_workspace_path",
    "reconcile_on_startup",
]
