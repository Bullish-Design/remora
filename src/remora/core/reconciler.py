"""Startup reconciliation for the reactive swarm.

This module provides the reconcile_on_startup function that:
- Discovers current CST nodes
- Diffs against existing EventStore nodes table
- Emits NodeDiscoveredEvent for new/updated nodes (projected into nodes table)
- Emits NodeRemovedEvent for deleted nodes
- Registers default subscriptions
- Emits ContentChangedEvent for changed nodes
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.discovery import CSTNode, discover
from remora.core.events import ContentChangedEvent, NodeDiscoveredEvent, NodeRemovedEvent
from remora.core.subscriptions import SubscriptionRegistry
from remora.utils import PathLike, normalize_path, to_project_relative

if TYPE_CHECKING:
    from remora.core.event_store import EventStore

logger = logging.getLogger(__name__)


def get_agent_dir(swarm_root: Path, agent_id: str) -> Path:
    """Get the directory for an agent."""
    return swarm_root / "agents" / agent_id[:2] / agent_id


def get_agent_workspace_path(swarm_root: Path, agent_id: str) -> Path:
    """Get the path to an agent's workspace."""
    return get_agent_dir(swarm_root, agent_id) / "workspace.db"


def _compute_source_hash(text: str) -> str:
    """Compute a hash of the source code text."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


async def reconcile_on_startup(
    project_path: PathLike,
    subscriptions: SubscriptionRegistry,
    discovery_paths: list[str] | None = None,
    languages: list[str] | None = None,
    event_store: "EventStore | None" = None,
    swarm_id: str = "swarm",
) -> dict[str, Any]:
    """Reconcile EventStore nodes table with discovered nodes.

    Args:
        project_path: Path to the project root
        subscriptions: SubscriptionRegistry for agent subscriptions
        discovery_paths: Paths to discover (default: ["src/"])
        languages: Languages to filter (default: None for all)
        event_store: EventStore for persisting nodes and emitting events
        swarm_id: Swarm ID for event emission

    Returns:
        Dictionary with counts of created, deleted, and updated agents
    """
    project_path = normalize_path(project_path)

    nodes = discover(
        [project_path / p for p in (discovery_paths or ["src/"])],
        languages=languages,
    )

    node_map = {node.node_id: node for node in nodes}
    discovered_ids = set(node_map.keys())

    # Get existing nodes from EventStore
    existing_nodes: list = []
    if event_store is not None:
        existing_nodes = await event_store.list_nodes()
    existing_map = {n.node_id: n for n in existing_nodes}
    existing_ids = set(existing_map.keys())

    new_ids = discovered_ids - existing_ids
    deleted_ids = existing_ids - discovered_ids
    common_ids = discovered_ids & existing_ids

    created = 0
    orphaned = 0
    updated = 0

    # --- New nodes: emit NodeDiscoveredEvent ---
    for node_id in new_ids:
        node = node_map[node_id]
        source_hash = _compute_source_hash(node.text)

        if event_store is not None:
            event = NodeDiscoveredEvent(
                node_id=node.node_id,
                node_type=node.node_type,
                name=getattr(node, "name", ""),
                full_name=getattr(node, "full_name", ""),
                file_path=node.file_path,
                start_line=node.start_line,
                end_line=node.end_line,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                source_code=node.text,
                source_hash=source_hash,
                parent_id=None,
            )
            await event_store.append(swarm_id, event)

        relative_path = to_project_relative(project_path, node.file_path)
        await subscriptions.register_defaults(
            node.node_id,
            relative_path,
        )

        created += 1

    # --- Deleted nodes: emit NodeRemovedEvent + unregister subscriptions ---
    for node_id in deleted_ids:
        if event_store is not None:
            event = NodeRemovedEvent(node_id=node_id)
            await event_store.append(swarm_id, event)

        await subscriptions.unregister_all(node_id)
        orphaned += 1

    # --- Common nodes: check for changes via source_hash ---
    for node_id in common_ids:
        node = node_map[node_id]
        existing = existing_map[node_id]
        new_source_hash = _compute_source_hash(node.text)

        if new_source_hash != existing.source_hash:
            # Source code changed — re-emit NodeDiscoveredEvent to update
            if event_store is not None:
                discovered_event = NodeDiscoveredEvent(
                    node_id=node.node_id,
                    node_type=node.node_type,
                    name=getattr(node, "name", ""),
                    full_name=getattr(node, "full_name", ""),
                    file_path=node.file_path,
                    start_line=node.start_line,
                    end_line=node.end_line,
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    source_code=node.text,
                    source_hash=new_source_hash,
                    parent_id=None,
                )
                await event_store.append(swarm_id, discovered_event)

                # Also emit ContentChangedEvent for reactive triggers
                relative_path = to_project_relative(project_path, node.file_path)
                change_event = ContentChangedEvent(
                    path=relative_path,
                    diff="File modified while daemon offline.",
                )
                await event_store.append(swarm_id, change_event)

            updated += 1

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
    "get_agent_workspace_path",
    "reconcile_on_startup",
]
