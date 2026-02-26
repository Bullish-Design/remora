# Implementation Guide: Step 5 - Graph Topology

## Overview

This step implements **Idea 4: Flatten the Agent Graph** from the design document. It separates graph topology from execution, making `AgentNode` a pure frozen dataclass and `build_graph()` a pure function.

## Contract Touchpoints
- `build_graph()` uses Remora-owned `BundleMetadata` mapping (node types → bundle path + priority).
- Graph output feeds `GraphExecutor` scheduling and `CheckpointManager` state.

## Done Criteria
- [ ] `AgentNode` is immutable and `build_graph()` is side-effect free.
- [ ] Graph includes upstream/downstream sets and supports topological ordering.
- [ ] Unit tests validate node filtering, ordering, and dependency wiring.

## What You're Building

- **`src/remora/graph.py`** — `AgentNode` frozen dataclass + `build_graph()` function + helper functions

## Prerequisites

- Step 1 (events.py, event_bus.py) completed — events are used for lifecycle notifications
- Discovery module available — `CSTNode` from `remora.discovery`

---

## Step 1: Create `src/remora/graph.py`

### Purpose

Create a pure data layer that describes the graph topology without any execution logic. This is the "what" (what agents, what targets, what dependencies), separate from the "how" (how to run them).

### Implementation

Create `src/remora/graph.py`:

```python
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
    
    The frozen dataclass ensures immutability - use dataclasses.replace()
    to create modified copies if needed.
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
        
    Example:
        >>> from remora.discovery import discover
        >>> from remora.config import RemoraConfig
        >>> 
        >>> nodes = discover([Path("src/")])
        >>> bundles = {
        ...     "function": Path("agents/lint"),
        ...     "class": Path("agents/docstring"),
        ... }
        >>> graph = build_graph(nodes, bundles)
        >>> len(graph)
        42
    """
    # Step 1: Create nodes for each CSTNode that has a matching bundle
    agent_nodes: list[AgentNode] = []
    
    for node in nodes:
        bundle_path = bundles.get(node.node_type)
        if bundle_path is None:
            continue  # Skip nodes with no matching bundle
            
        if not bundle_path.exists():
            continue  # Skip if bundle doesn't exist
            
        agent_node = AgentNode(
            id=node.node_id,
            name=f"{node.node_type}:{node.name}",
            target=node,
            bundle_path=bundle_path,
        )
        agent_nodes.append(agent_node)
    
    # Step 2: Compute dependency edges
    # Nodes in the same file have dependencies on each other (ordered by line number)
    # Earlier lines must complete before later lines can run
    agent_nodes = _compute_file_dependencies(agent_nodes)
    
    return agent_nodes


def _compute_file_dependencies(agent_nodes: list[AgentNode]) -> list[AgentNode]:
    """Compute dependency edges based on file proximity.
    
    Within each file, nodes are ordered by start_line.
    Nodes earlier in the file become upstream dependencies for later nodes.
    This ensures code is analyzed in logical order (imports before usage, etc.).
    
    Args:
        agent_nodes: List of AgentNodes without dependency edges
        
    Returns:
        List of AgentNodes with upstream/downstream frozensets populated
    """
    # Group nodes by file_path
    by_file: dict[Path, list[AgentNode]] = defaultdict(list)
    for node in agent_nodes:
        by_file[node.target.file_path].append(node)
    
    # Sort each file's nodes by line number (ascending)
    for file_path in by_file:
        by_file[file_path].sort(key=lambda n: n.target.start_line)
    
    # Compute dependencies: each node depends on all previous nodes in the same file
    result: list[AgentNode] = []
    node_by_id: dict[str, AgentNode] = {}
    
    for file_path, nodes in by_file.items():
        for i, node in enumerate(nodes):
            if i == 0:
                # First node in file has no file-internal dependencies
                result.append(node)
                node_by_id[node.id] = node
            else:
                # This node depends on all previous nodes in the file
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
    
    # Second pass: compute downstream (inverse of upstream)
    final_result: list[AgentNode] = []
    for node in result:
        # Find all nodes that have this node as upstream
        downstream_ids = frozenset(
            nid for nid, n in node_by_id.items()
            if node.id in n.upstream
        )
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
    
    Args:
        graph: The full list of AgentNodes
        completed: Set of node IDs that have completed execution
        
    Returns:
        List of AgentNodes ready to run (may be empty)
        
    Example:
        >>> ready = get_ready_nodes(graph, completed={"node-1", "node-2"})
        >>> for node in ready:
        ...     print(f"Ready: {node.name}")
    """
    ready: list[AgentNode] = []
    
    for node in graph:
        if node.id in completed:
            continue  # Already done.upstream <= completed
        if node:
            # All upstream dependencies are satisfied
            ready.append(node)
    
    return ready


def topological_sort(graph: list[AgentNode]) -> list[AgentNode]:
    """Return nodes in topological order (all dependencies before dependents).
    
    Uses a simple Kahn's algorithm variant.
    
    Args:
        graph: List of AgentNodes with dependency edges
        
    Returns:
        List of nodes in execution order
        
    Raises:
        ValueError: If graph contains cycles
    """
    if not graph:
        return []
    
    # Build adjacency info
    node_by_id = {node.id: node for node in graph}
    in_degree = {node.id: len(node.upstream) for node in graph}
    
    # Start with nodes that have no dependencies
    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    result: list[AgentNode] = []
    
    while queue:
        # Process next node
        node_id = queue.pop(0)
        result.append(node_by_id[node_id])
        
        # Reduce in-degree for dependents
        for other_node in graph:
            if node_id in other_node.upstream:
                in_degree[other_node.id] -= 1
                if in_degree[other_node.id] == 0:
                    queue.append(other_node.id)
    
    # Check for cycles
    if len(result) != len(graph):
        raise ValueError("Graph contains cycles - cannot topologically sort")
    
    return result


def get_execution_batches(
    graph: list[AgentNode],
) -> list[list[AgentNode]]:
    """Group nodes into execution batches (parallel-safe groups).
    
    Nodes in the same batch have no dependencies on each other and
    can run in parallel. Batches must be executed sequentially.
    
    Args:
        graph: List of AgentNodes with dependency edges
        
    Returns:
        List of batches, where each batch is a list of nodes that can run in parallel
        
    Example:
        >>> batches = get_execution_batches(graph)
        >>> for batch in batches:
        ...     print(f"Batch of {len(batch)} nodes can run in parallel")
    """
    if not graph:
        return []
    
    node_by_id = {node.id: node for node in graph}
    completed: set[str] = set()
    batches: list[list[AgentNode]] = []
    
    while len(completed) < len(graph):
        ready = get_ready_nodes(graph, completed)
        if not ready:
            # No ready nodes but not all done - indicates cycle or bug
            remaining = [n for n in graph if n.id not in completed]
            raise ValueError(
                f"Deadlock: {len(remaining)} nodes have unmet dependencies. "
                f"Remaining: {[n.id for n in remaining[:5]]}..."
            )
        
        batches.append(ready)
        
        # Mark these as completed for next iteration
        for node in ready:
            completed.add(node.id)
    
    return batches


# =============================================================================
# Module Exports
# =============================================================================

__all__ = [
    "AgentNode",
    "build_graph",
    "get_ready_nodes",
    "topological_sort",
    "get_execution_batches",
]
```

### Key Design Decisions

1. **Frozen dataclass** — `AgentNode` is immutable; use `dataclasses.replace()` to modify
2. **Pure function** — `build_graph()` has no side effects, same inputs = same outputs
3. **File-based dependencies** — Nodes in same file depend on earlier lines (simple heuristic)
4. **frozenset for dependencies** — Immutable, hashable, set operations work cleanly
5. **Multiple helper functions** — `get_ready_nodes`, `topological_sort`, `get_execution_batches` for different execution strategies

---

## Step 2: Update Exports in `src/remora/__init__.py`

### Purpose

Export the new graph types for the public API.

### Implementation

Edit `src/remora/__init__.py` to add:

```python
# Add to existing imports
from remora.graph import (
    AgentNode,
    build_graph,
    get_ready_nodes,
    topological_sort,
    get_execution_batches,
)

__all__ = [
    # ... existing exports ...
    # Graph topology
    "AgentNode",
    "build_graph",
    "get_ready_nodes",
    "topological_sort",
    "get_execution_batches",
]
```

---

## Step 3: Write Tests

### Purpose

Verify the graph topology code works correctly.

### Implementation

Create `tests/test_graph.py`:

```python
"""Tests for the graph topology module."""

import pytest
from dataclasses import replace
from pathlib import Path

from remora.graph import (
    AgentNode,
    build_graph,
    get_ready_nodes,
    topological_sort,
    get_execution_batches,
)


class MockCSTNode:
    """Mock CSTNode for testing."""
    
    def __init__(
        self,
        node_id: str,
        node_type: str,
        name: str,
        file_path: Path,
        start_line: int = 1,
        end_line: int = 10,
    ):
        self.node_id = node_id
        self.node_type = node_type
        self.name = name
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.text = f"def {name}():\n    pass"
        self.start_byte = 0
        self.end_byte = 100


class TestAgentNode:
    """Test AgentNode dataclass."""
    
    def test_create_agent_node(self):
        """Basic creation works."""
        node = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        agent = AgentNode(
            id="agent-1",
            name="lint:foo",
            target=node,
            bundle_path=Path("agents/lint"),
        )
        
        assert agent.id == "agent-1"
        assert agent.name == "lint:foo"
        assert agent.target.node_id == "n1"
        assert agent.bundle_path == Path("agents/lint")
        assert agent.upstream == frozenset()
        assert agent.downstream == frozenset()
    
    def test_agent_node_is_frozen(self):
        """AgentNode is immutable."""
        node = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        agent = AgentNode(
            id="agent-1",
            name="lint:foo",
            target=node,
            bundle_path=Path("agents/lint"),
        )
        
        with pytest.raises(AttributeError):
            agent.id = "different"  # type: ignore
    
    def test_agent_node_with_dependencies(self):
        """Can create node with dependencies."""
        node = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        agent = AgentNode(
            id="agent-1",
            name="lint:foo",
            target=node,
            bundle_path=Path("agents/lint"),
            upstream=frozenset({"dep-1", "dep-2"}),
            downstream=frozenset({"child-1"}),
        )
        
        assert agent.upstream == frozenset({"dep-1", "dep-2"})
        assert agent.downstream == frozenset({"child-1"})
    
    def test_agent_node_str(self):
        """String representation is useful."""
        node = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        agent = AgentNode(
            id="agent-1",
            name="lint:foo",
            target=node,
            bundle_path=Path("agents/lint"),
            upstream=frozenset({"dep-1"}),
            downstream=frozenset(),
        )
        
        assert "lint:foo" in str(agent)
        assert "upstream=1" in str(agent)


class TestBuildGraph:
    """Test build_graph function."""
    
    def test_build_graph_empty(self):
        """Empty input returns empty output."""
        result = build_graph([], {}, None)
        assert result == []
    
    def test_build_graph_filters_no_bundle(self):
        """Nodes without matching bundles are skipped."""
        nodes = [
            MockCSTNode("n1", "function", "foo", Path("src/foo.py")),
            MockCSTNode("n2", "class", "Bar", Path("src/bar.py")),
        ]
        bundles = {
            "function": Path("agents/lint"),
            # "class" not in bundles
        }
        
        result = build_graph(nodes, bundles, None)
        
        assert len(result) == 1
        assert result[0].name == "function:foo"
    
    def test_build_graph_filters_missing_bundle(self):
        """Nodes with non-existent bundles are skipped."""
        nodes = [
            MockCSTNode("n1", "function", "foo", Path("src/foo.py")),
        ]
        bundles = {
            "function": Path("agents/nonexistent"),
        }
        
        result = build_graph(nodes, bundles, None)
        
        assert len(result) == 0
    
    def test_build_graph_creates_nodes(self):
        """Nodes are created correctly."""
        nodes = [
            MockCSTNode("n1", "function", "foo", Path("src/foo.py")),
        ]
        bundles = {
            "function": Path("agents/lint"),
        }
        
        result = build_graph(nodes, bundles, None)
        
        assert len(result) == 1
        assert result[0].id == "n1"
        assert result[0].name == "function:foo"
    
    def test_build_graph_computes_dependencies(self):
        """Dependencies are computed from file proximity."""
        nodes = [
            MockCSTNode("n1", "function", "foo", Path("src/foo.py"), start_line=1, end_line=5),
            MockCSTNode("n2", "function", "bar", Path("src/foo.py"), start_line=10, end_line=15),
            MockCSTNode("n3", "function", "baz", Path("src/foo.py"), start_line=20, end_line=25),
        ]
        bundles = {
            "function": Path("agents/lint"),
        }
        
        result = build_graph(nodes, bundles, None)
        
        # Should have 3 nodes
        assert len(result) == 3
        
        # Find each by ID
        by_id = {n.id: n for n in result}
        
        # n1 has no upstream
        assert by_id["n1"].upstream == frozenset()
        
        # n2 depends on n1
        assert by_id["n2"].upstream == frozenset({"n1"})
        
        # n3 depends on n1 and n2
        assert by_id["n3"].upstream == frozenset({"n1", "n2"})
    
    def test_build_graph_different_files_no_deps(self):
        """Nodes in different files have no dependencies."""
        nodes = [
            MockCSTNode("n1", "function", "foo", Path("src/foo.py"), start_line=1),
            MockCSTNode("n2", "function", "bar", Path("src/bar.py"), start_line=1),
        ]
        bundles = {
            "function": Path("agents/lint"),
        }
        
        result = build_graph(nodes, bundles, None)
        
        # Both should have no dependencies (different files)
        for node in result:
            assert node.upstream == frozenset()


class TestGetReadyNodes:
    """Test get_ready_nodes function."""
    
    def test_empty_graph(self):
        """Empty graph returns empty list."""
        ready = get_ready_nodes([], set())
        assert ready == []
    
    def test_no_completed(self):
        """All nodes ready when nothing completed."""
        node1 = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "bar", Path("src/bar.py"))
        
        agent1 = AgentNode("n1", "lint:foo", node1, Path("agents/lint"))
        agent2 = AgentNode("n2", "lint:bar", node2, Path("agents/lint"))
        
        ready = get_ready_nodes([agent1, agent2], set())
        
        assert len(ready) == 2
    
    def test_some_completed(self):
        """Only nodes with satisfied dependencies are ready."""
        node1 = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "bar", Path("src/foo.py"), start_line=10)
        
        agent1 = AgentNode("n1", "lint:foo", node1, Path("agents/lint"))
        agent2 = AgentNode(
            "n2", "lint:bar", node2, Path("agents/lint"),
            upstream=frozenset({"n1"})
        )
        
        # n1 is done, so n2 should be ready
        ready = get_ready_nodes([agent1, agent2], completed={"n1"})
        
        assert len(ready) == 1
        assert ready[0].id == "n2"
    
    def test_blocked_by_incomplete_dependency(self):
        """Nodes with incomplete dependencies are blocked."""
        node1 = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "bar", Path("src/foo.py"), start_line=10)
        
        agent1 = AgentNode("n1", "lint:foo", node1, Path("agents/lint"))
        agent2 = AgentNode(
            "n2", "lint:bar", node2, Path("agents/lint"),
            upstream=frozenset({"n1"})
        )
        
        # Nothing completed, so n2 should be blocked
        ready = get_ready_nodes([agent1, agent2], set())
        
        assert len(ready) == 1
        assert ready[0].id == "n1"
    
    def test_already_completed_ignored(self):
        """Completed nodes are not returned."""
        node1 = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        
        agent1 = AgentNode("n1", "lint:foo", node1, Path("agents/lint"))
        
        ready = get_ready_nodes([agent1], completed={"n1"})
        
        assert ready == []


class TestTopologicalSort:
    """Test topological_sort function."""
    
    def test_empty(self):
        """Empty graph returns empty."""
        assert topological_sort([]) == []
    
    def test_single_node(self):
        """Single node returns itself."""
        node = MockCSTNode("n1", "function", "foo", Path("src/foo.py"))
        agent = AgentNode("n1", "lint:foo", node, Path("agents/lint"))
        
        result = topological_sort([agent])
        
        assert len(result) == 1
        assert result[0].id == "n1"
    
    def test_linear_chain(self):
        """Linear chain is sorted correctly."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/foo.py"), start_line=1)
        node2 = MockCSTNode("n2", "function", "b", Path("src/foo.py"), start_line=10)
        node3 = MockCSTNode("n3", "function", "c", Path("src/foo.py"), start_line=20)
        
        # n3 -> n2 -> n1 (dependencies)
        agent1 = AgentNode("n1", "lint:a", node1, Path("agents/lint"), downstream=frozenset({"n2", "n3"}))
        agent2 = AgentNode("n2", "lint:b", node2, Path("agents/lint"), upstream=frozenset({"n1"}), downstream=frozenset({"n3"}))
        agent3 = AgentNode("n3", "lint:c", node3, Path("agents/lint"), upstream=frozenset({"n1", "n2"}))
        
        result = topological_sort([agent3, agent1, agent2])  # Random order input
        
        # Should be sorted: n1, n2, n3
        assert result[0].id == "n1"
        assert result[1].id == "n2"
        assert result[2].id == "n3"
    
    def test_parallel_nodes(self):
        """Parallel nodes can be in any order."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "b", Path("src/bar.py"))
        
        agent1 = AgentNode("n1", "lint:a", node1, Path("agents/lint"))
        agent2 = AgentNode("n2", "lint:b", node2, Path("agents/lint"))
        
        result = topological_sort([agent1, agent2])
        
        assert len(result) == 2
    
    def test_cycle_raises_error(self):
        """Cycle raises ValueError."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "b", Path("src/foo.py"), start_line=10)
        
        # Cycle: n1 depends on n2, n2 depends on n1
        agent1 = AgentNode("n1", "lint:a", node1, Path("agents/lint"), upstream=frozenset({"n2"}))
        agent2 = AgentNode("n2", "lint:b", node2, Path("agents/lint"), upstream=frozenset({"n1"}))
        
        with pytest.raises(ValueError, match="cycle"):
            topological_sort([agent1, agent2])


class TestGetExecutionBatches:
    """Test get_execution_batches function."""
    
    def test_empty(self):
        """Empty graph returns empty."""
        assert get_execution_batches([]) == []
    
    def test_single_batch(self):
        """All nodes in one batch if no dependencies."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/foo.py"))
        node2 = MockCSTNode("n2", "function", "b", Path("src/bar.py"))
        
        agent1 = AgentNode("n1", "lint:a", node1, Path("agents/lint"))
        agent2 = AgentNode("n2", "lint:b", node2, Path("agents/lint"))
        
        batches = get_execution_batches([agent1, agent2])
        
        assert len(batches) == 1
        assert len(batches[0]) == 2
    
    def test_sequential_batches(self):
        """Sequential dependencies create multiple batches."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/foo.py"), start_line=1)
        node2 = MockCSTNode("n2", "function", "b", Path("src/foo.py"), start_line=10)
        node3 = MockCSTNode("n3", "function", "c", Path("src/foo.py"), start_line=20)
        
        # All in same file, so sequential
        graph = build_graph([node1, node2, node3], {"function": Path("agents/lint")})
        
        batches = get_execution_batches(graph)
        
        # Should have 3 batches (one per node)
        assert len(batches) == 3
        assert len(batches[0]) == 1  # First node
        assert len(batches[1]) == 1  # Second node
        assert len(batches[2]) == 1  # Third node
    
    def test_parallel_in_batch(self):
        """Nodes without dependencies can be in same batch."""
        node1 = MockCSTNode("n1", "function", "a", Path("src/file1.py"), start_line=1)
        node2 = MockCSTNode("n2", "function", "b", Path("src/file2.py"), start_line=1)
        
        # Different files, no dependencies
        graph = build_graph([node1, node2], {"function": Path("agents/lint")})
        
        batches = get_execution_batches(graph)
        
        # Single batch with both
        assert len(batches) == 1
        assert len(batches[0]) == 2
```

---

## Step 4: Verification

### Run Basic Import Test
```bash
cd /home/andrew/Documents/Projects/remora
python -c "from remora import AgentNode, build_graph; print('Import OK')"
```

### Run Tests
```bash
cd /home/andrew/Documents/Projects/remora
python -m pytest tests/test_graph.py -v
```

### Expected Output
All tests should pass.

---

## Common Pitfalls to Avoid

1. **Forgetting `frozenset`** — Use `frozenset`, not `set`, for upstream/downstream (mutable sets don't work well as dict keys or in certain contexts)
2. **File path equality** — Use `Path` objects consistently; string paths may not match correctly
3. **Dependency cycles** — The dependency computation is simple (same-file ordering); more complex dependencies require different logic
4. **Mutable default arguments** — Don't use `= set()` or `= []` in function signatures; use `= None` and create inside function

---

## Files Created/Modified Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/graph.py` | CREATE | ~250 lines - AgentNode + build_graph + helpers |
| `src/remora/__init__.py` | MODIFY | Add graph exports |
| `tests/test_graph.py` | CREATE | ~300 lines - Comprehensive tests |

---

## Next Step

After this step is complete and verified, proceed to **Step 6: Context Module** (Idea 6) which creates the `ContextBuilder` as an EventBus subscriber for building bounded context from the event stream.
