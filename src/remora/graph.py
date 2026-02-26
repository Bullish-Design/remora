"""Graph topology - pure data, no execution.

This module provides:
1. AgentNode: A frozen dataclass representing a node in the execution graph
2. build_graph(): Pure function that creates the DAG from discovered nodes
3. get_ready_nodes(): Helper for finding nodes ready to execute

The key insight: topology is data, not behavior. AgentNode has no state,
no kernel, no workspace. It just describes "what agent, what target, what dependencies."
"""

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.discovery import CSTNode
    from remora.config import RemoraConfig


@dataclass(frozen=True)
class AgentNode:
    """A node in the execution graph. Immutable topology.

    This is pure data - no state, no kernel, no workspace.
    Just "what agent, what target, what dependencies."
    """

    id: str
    name: str
    target: "CSTNode"
    bundle_path: Path
    upstream: frozenset[str] = frozenset()
    downstream: frozenset[str] = frozenset()

    def __str__(self) -> str:
        return f"AgentNode({self.name}, upstream={len(self.upstream)}, downstream={len(self.downstream)})"


def build_graph(
    nodes: list["CSTNode"],
    bundles: dict[str, Path],
    config: "RemoraConfig | None" = None,
) -> list[AgentNode]:
    """Map discovered code nodes to agent nodes with dependency edges.

    This is a pure function - given the same inputs, it always returns
    the same output. No side effects, no state.

    Args:
        nodes: List of CSTNodes from discovery
        bundles: Mapping from node_type to bundle path
               e.g., {"function": Path("agents/lint"), "class": Path("agents/docstring")}
        config: Remora configuration (optional, for future extension)

    Returns:
        List of AgentNodes with dependency edges computed
    """
    agent_nodes: list[AgentNode] = []

    for node in nodes:
        bundle_path = bundles.get(node.node_type)
        if bundle_path is None:
            continue

        if not bundle_path.exists():
            continue

        agent_node = AgentNode(
            id=node.node_id,
            name=f"{node.node_type}:{node.name}",
            target=node,
            bundle_path=bundle_path,
        )
        agent_nodes.append(agent_node)

    agent_nodes = _compute_file_dependencies(agent_nodes)

    return agent_nodes


def _compute_file_dependencies(agent_nodes: list[AgentNode]) -> list[AgentNode]:
    """Compute dependency edges based on file proximity."""
    by_file: dict[Path, list[AgentNode]] = defaultdict(list)
    for node in agent_nodes:
        by_file[node.target.file_path].append(node)

    for file_path in by_file:
        by_file[file_path].sort(key=lambda n: n.target.start_line)

    result: list[AgentNode] = []
    node_by_id: dict[str, AgentNode] = {}

    for file_path, nodes in by_file.items():
        for i, node in enumerate(nodes):
            if i == 0:
                result.append(node)
                node_by_id[node.id] = node
            else:
                upstream_ids = frozenset(n.id for n in nodes[:i])
                new_node = AgentNode(
                    id=node.id,
                    name=node.name,
                    target=node.target,
                    bundle_path=node.bundle_path,
                    upstream=upstream_ids,
                    downstream=frozenset(),
                )
                result.append(new_node)
                node_by_id[new_node.id] = new_node

    final_result: list[AgentNode] = []
    for node in result:
        downstream_ids = frozenset(nid for nid, n in node_by_id.items() if node.id in n.upstream)
        final_node = AgentNode(
            id=node.id,
            name=node.name,
            target=node.target,
            bundle_path=node.bundle_path,
            upstream=node.upstream,
            downstream=downstream_ids,
        )
        final_result.append(final_node)

    return final_result


def get_ready_nodes(
    graph: list[AgentNode],
    completed: set[str],
) -> list[AgentNode]:
    """Get nodes that are ready to execute.

    A node is ready if:
    1. It's not already completed
    2. All its upstream dependencies are in the completed set
    """
    ready: list[AgentNode] = []

    for node in graph:
        if node.id in completed:
            continue
        if node.upstream <= completed:
            ready.append(node)

    return ready


def topological_sort(graph: list[AgentNode]) -> list[AgentNode]:
    """Return nodes in topological order (all dependencies before dependents)."""
    if not graph:
        return []

    node_by_id = {node.id: node for node in graph}
    in_degree = {node.id: len(node.upstream) for node in graph}

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    result: list[AgentNode] = []

    while queue:
        node_id = queue.pop(0)
        result.append(node_by_id[node_id])

        for other_node in graph:
            if node_id in other_node.upstream:
                in_degree[other_node.id] -= 1
                if in_degree[other_node.id] == 0:
                    queue.append(other_node.id)

    if len(result) != len(graph):
        raise ValueError("Graph contains cycles - cannot topologically sort")

    return result


def get_execution_batches(
    graph: list[AgentNode],
) -> list[list[AgentNode]]:
    """Group nodes into execution batches (parallel-safe groups)."""
    if not graph:
        return []

    node_by_id = {node.id: node for node in graph}
    completed: set[str] = set()
    batches: list[list[AgentNode]] = []

    while len(completed) < len(graph):
        ready = get_ready_nodes(graph, completed)
        if not ready:
            remaining = [n for n in graph if n.id not in completed]
            raise ValueError(
                f"Deadlock: {len(remaining)} nodes have unmet dependencies. "
                f"Remaining: {[n.id for n in remaining[:5]]}..."
            )

        batches.append(ready)

        for node in ready:
            completed.add(node.id)

    return batches


__all__ = [
    "AgentNode",
    "build_graph",
    "get_ready_nodes",
    "topological_sort",
    "get_execution_batches",
]
