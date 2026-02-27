"""Agent graph topology.

This module defines the pure data structures for graph topology.
AgentNode is immutable - execution state is tracked separately.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from remora.core.discovery import CSTNode
from remora.core.errors import GraphError


@dataclass(frozen=True, slots=True)
class AgentNode:
    """A node in the execution graph. Immutable topology.

    Contains only topology information - no mutable state.
    Execution state is tracked by GraphExecutor separately.
    """

    id: str
    name: str
    target: CSTNode
    bundle_path: Path
    upstream: frozenset[str] = frozenset()
    downstream: frozenset[str] = frozenset()
    priority: int = 0

    def __hash__(self) -> int:
        return hash(self.id)


def build_graph(
    nodes: list[CSTNode],
    bundle_mapping: dict[str, Path],
    priority_mapping: dict[str, int] | None = None,
) -> list[AgentNode]:
    """Build agent graph from discovered nodes.

    Maps each CSTNode to an AgentNode based on node_type -> bundle_path mapping.
    Computes dependency edges based on file relationships.

    Args:
        nodes: Discovered CSTNodes from discovery.discover()
        bundle_mapping: Maps node_type (e.g., "function") to bundle path
        priority_mapping: Optional priority per node_type (higher = earlier)

    Returns:
        List of AgentNode sorted by priority and dependency order

    Raises:
        GraphError: If graph contains cycles
    """
    priority_mapping = priority_mapping or {}

    agent_nodes: dict[str, AgentNode] = {}
    file_node_ids_by_path: dict[str, str] = {}

    if "file" in bundle_mapping:
        for cst_node in nodes:
            if cst_node.node_type == "file":
                file_node_ids_by_path[cst_node.file_path] = cst_node.node_id

    for cst_node in nodes:
        bundle_path = bundle_mapping.get(cst_node.node_type)
        if bundle_path is None:
            continue

        upstream = _compute_upstream(cst_node, file_node_ids_by_path)

        agent_node = AgentNode(
            id=cst_node.node_id,
            name=cst_node.name,
            target=cst_node,
            bundle_path=bundle_path,
            upstream=frozenset(upstream),
            priority=priority_mapping.get(cst_node.node_type, 0),
        )
        agent_nodes[agent_node.id] = agent_node

    downstream_map = _compute_downstream_map(agent_nodes)

    final_nodes = []
    for node in agent_nodes.values():
        updated_node = AgentNode(
            id=node.id,
            name=node.name,
            target=node.target,
            bundle_path=node.bundle_path,
            upstream=node.upstream,
            downstream=frozenset(downstream_map[node.id]),
            priority=node.priority,
        )
        final_nodes.append(updated_node)

    sorted_nodes = _topological_sort(final_nodes)

    return sorted_nodes


def _compute_upstream(
    cst_node: CSTNode,
    file_node_ids_by_path: dict[str, str],
) -> set[str]:
    """Compute upstream dependencies for a node."""
    upstream: set[str] = set()

    if cst_node.node_type in ("function", "class", "method"):
        file_node_id = file_node_ids_by_path.get(cst_node.file_path)
        if file_node_id:
            upstream.add(file_node_id)

    return upstream


def _compute_downstream_map(agent_nodes: dict[str, AgentNode]) -> dict[str, set[str]]:
    """Build downstream mapping in single O(V+E) pass."""
    downstream_map: dict[str, set[str]] = defaultdict(set)

    for node in agent_nodes.values():
        for upstream_id in node.upstream:
            downstream_map[upstream_id].add(node.id)

    return downstream_map


def _topological_sort(nodes: list[AgentNode]) -> list[AgentNode]:
    """Kahn's algorithm with O(V+E) complexity.

    Uses deque for O(1) popleft operations while keeping priority ordering.
    """
    node_by_id = {n.id: n for n in nodes}

    adjacency: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {n.id: 0 for n in nodes}

    for node in nodes:
        for upstream_id in node.upstream:
            if upstream_id in node_by_id:
                adjacency[upstream_id].append(node.id)
                in_degree[node.id] += 1

    queue: deque[AgentNode] = deque(
        sorted(
            [n for n in nodes if in_degree[n.id] == 0],
            key=lambda n: -n.priority,
        )
    )

    result: list[AgentNode] = []

    while queue:
        node = queue.popleft()
        result.append(node)

        newly_ready: list[AgentNode] = []
        for downstream_id in adjacency[node.id]:
            in_degree[downstream_id] -= 1
            if in_degree[downstream_id] == 0:
                newly_ready.append(node_by_id[downstream_id])

        if newly_ready:
            newly_ready.sort(key=lambda n: -n.priority)
            queue.extend(newly_ready)

    if len(result) != len(nodes):
        cycle_nodes = [n.id for n in nodes if in_degree[n.id] > 0]
        raise GraphError(f"Cycle detected involving nodes: {cycle_nodes}")

    return result


def get_execution_batches(nodes: list[AgentNode]) -> list[list[AgentNode]]:
    """Group nodes into batches that can execute in parallel."""
    node_by_id = {n.id: n for n in nodes}
    completed: set[str] = set()
    batches: list[list[AgentNode]] = []
    remaining = set(n.id for n in nodes)

    while remaining:
        batch = [node_by_id[nid] for nid in remaining if node_by_id[nid].upstream <= completed]

        if not batch:
            raise GraphError("Unable to make progress - possible cycle")

        batch.sort(key=lambda n: -n.priority)
        batches.append(batch)

        for node in batch:
            completed.add(node.id)
            remaining.discard(node.id)

    return batches


__all__ = [
    "AgentNode",
    "build_graph",
    "get_execution_batches",
]
