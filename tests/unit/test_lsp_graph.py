# tests/unit/test_lsp_graph.py
"""Tests for LazyGraph — reads nodes from EventStore DB, edges from RemoraDB.

Covers all public API: get_parent, get_callers, ensure_loaded, invalidate, close.
Also covers edge cases: nonexistent nodes, idempotency, depth traversal, multiple
edge types coexisting.
"""

from __future__ import annotations

import sqlite3

import pytest

from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph



async def _update_edges(db, nodes_dict_list):
    """Bypasses db.update_edges to manually insert edge tests, as db.update_edges
    was refactored to only support 'parent_of' edges organically."""
    import contextlib
    with contextlib.closing(db.conn.cursor()) as cursor:
        cursor.execute("BEGIN IMMEDIATE")
        try:
            for d in nodes_dict_list:
                node_id = d["node_id"]
                if "parent_id" in d and d["parent_id"]:
                    cursor.execute(
                        "INSERT OR REPLACE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'parent_of')",
                        (d["parent_id"], node_id),
                    )
                for callee in d.get("callee_ids", []):
                    cursor.execute(
                        "INSERT OR REPLACE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, 'calls')",
                        (node_id, callee),
                    )
            cursor.execute("COMMIT")
        except Exception:
            cursor.execute("ROLLBACK")
            raise


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def event_store(tmp_path):
    store = EventStore(str(tmp_path / "events.db"), projection=NodeProjection())
    await store.initialize()
    yield store
    await store.close()


@pytest.fixture
async def remora_db(tmp_path):
    db = RemoraDB(str(tmp_path / "lsp.db"))
    yield db
    db.close()


# ── Seed helpers ──────────────────────────────────────────────────────────────


async def _seed_class_and_method(store: EventStore) -> None:
    """Create a small tree: class → method (both in /tmp/test.py)."""
    await store.append(
        "nodes",
        NodeDiscoveredEvent(
            node_id="rm_class1",
            node_type="class",
            name="MyClass",
            full_name="test.MyClass",
            file_path="/tmp/test.py",
            start_line=1,
            end_line=20,
            source_code="class MyClass:\n    def method(self): pass",
            source_hash="abc123",
            parent_id=None,
        ),
    )
    await store.append(
        "nodes",
        NodeDiscoveredEvent(
            node_id="rm_method1",
            node_type="method",
            name="method",
            full_name="test.MyClass.method",
            file_path="/tmp/test.py",
            start_line=2,
            end_line=3,
            source_code="def method(self): pass",
            source_hash="def456",
            parent_id="rm_class1",
        ),
    )


async def _seed_call_graph(store: EventStore) -> None:
    """Create nodes for a call graph: func_a calls func_b, func_c calls func_b.

    All in /tmp/calls.py.
    """
    for nid, name in [("rm_func_a", "func_a"), ("rm_func_b", "func_b"), ("rm_func_c", "func_c")]:
        await store.append(
            "nodes",
            NodeDiscoveredEvent(
                node_id=nid,
                node_type="function",
                name=name,
                full_name=f"calls.{name}",
                file_path="/tmp/calls.py",
                start_line=1,
                end_line=5,
                source_code=f"def {name}(): pass",
                source_hash=f"hash_{name}",
                parent_id=None,
            ),
        )


async def _seed_deep_chain(store: EventStore) -> None:
    """Create a 4-level deep chain: file → class → method → inner_func.

    All in /tmp/deep.py.
    """
    nodes = [
        ("rm_file1", "file", "deep.py", None),
        ("rm_deep_class", "class", "DeepClass", "rm_file1"),
        ("rm_deep_method", "method", "deep_method", "rm_deep_class"),
        ("rm_inner_func", "function", "inner_func", "rm_deep_method"),
    ]
    for nid, ntype, name, parent in nodes:
        await store.append(
            "nodes",
            NodeDiscoveredEvent(
                node_id=nid,
                node_type=ntype,
                name=name,
                full_name=f"deep.{name}",
                file_path="/tmp/deep.py",
                start_line=1,
                end_line=5,
                source_code=f"# {name}",
                source_hash=f"hash_{nid}",
                parent_id=parent,
            ),
        )


async def _seed_multi_file(store: EventStore) -> None:
    """Create nodes in two different files for invalidation testing."""
    await store.append(
        "nodes",
        NodeDiscoveredEvent(
            node_id="rm_alpha",
            node_type="function",
            name="alpha",
            full_name="a.alpha",
            file_path="/tmp/a.py",
            start_line=1,
            end_line=5,
            source_code="def alpha(): pass",
            source_hash="hash_alpha",
            parent_id=None,
        ),
    )
    await store.append(
        "nodes",
        NodeDiscoveredEvent(
            node_id="rm_beta",
            node_type="function",
            name="beta",
            full_name="b.beta",
            file_path="/tmp/b.py",
            start_line=1,
            end_line=5,
            source_code="def beta(): pass",
            source_hash="hash_beta",
            parent_id=None,
        ),
    )


# ── Original tests (preserved) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_reads_nodes_from_event_store(event_store, remora_db):
    """LazyGraph should read nodes from EventStore's DB."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        parent = await graph.get_parent("rm_method1")
        assert parent == "rm_class1"
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_invalidate_removes_file_nodes(event_store, remora_db):
    """LazyGraph.invalidate should remove nodes for a file."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_class1")
        assert "rm_class1" in graph.node_indices

        await graph.invalidate("/tmp/test.py")
        assert "rm_class1" not in graph.node_indices
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_node_queries_without_event_store(remora_db):
    """LazyGraph without event_store_db_path returns empty results for node queries."""
    graph = LazyGraph(db=remora_db)
    try:
        assert await graph._get_node("nonexistent") is None
        assert await graph._get_nodes_for_file("/tmp/test.py") == []
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_node_query_reads_event_store_db(event_store, remora_db):
    """LazyGraph._get_node reads from EventStore DB using node_id column."""
    await _seed_class_and_method(event_store)
    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        node = await graph._get_node("rm_class1")
        assert node is not None
        assert node.node_id == "rm_class1"
        assert getattr(node, "name", None) == "MyClass"
    finally:
        graph.close()


# ── get_callers tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_callers_single_caller(event_store, remora_db):
    """get_callers returns the single caller of a function."""
    await _seed_call_graph(event_store)
    # func_a calls func_b
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_func_a", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_b"},
            {"node_id": "rm_func_c"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        callers = await graph.get_callers("rm_func_b")
        assert callers == ["rm_func_a"]
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_callers_multiple_callers(event_store, remora_db):
    """get_callers returns all callers when multiple functions call the same target."""
    await _seed_call_graph(event_store)
    # func_a calls func_b, func_c also calls func_b
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_func_a", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_c", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_b"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        callers = await graph.get_callers("rm_func_b")
        assert sorted(callers) == ["rm_func_a", "rm_func_c"]
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_callers_no_callers(event_store, remora_db):
    """get_callers returns empty list for a function with no callers."""
    await _seed_call_graph(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_func_a"},
            {"node_id": "rm_func_b"},
            {"node_id": "rm_func_c"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        callers = await graph.get_callers("rm_func_a")
        assert callers == []
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_callers_nonexistent_node(event_store, remora_db):
    """get_callers returns empty list for a node_id that doesn't exist."""
    await _seed_call_graph(event_store)

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        callers = await graph.get_callers("rm_nonexistent")
        assert callers == []
    finally:
        graph.close()


# ── get_parent edge cases ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_parent_no_parent(event_store, remora_db):
    """get_parent returns None for a top-level node with no parent_of edge."""
    await _seed_class_and_method(event_store)
    # Only add the method -> class parent edge; class itself has no parent
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_class1"},
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        parent = await graph.get_parent("rm_class1")
        assert parent is None
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_parent_nonexistent_node(event_store, remora_db):
    """get_parent returns None for a node_id that doesn't exist."""
    await _seed_class_and_method(event_store)

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        parent = await graph.get_parent("rm_nonexistent")
        assert parent is None
    finally:
        graph.close()


# ── ensure_loaded tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_loaded_idempotent(event_store, remora_db):
    """Calling ensure_loaded twice for the same node_id must not duplicate nodes."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_class1")
        count_after_first = len(graph.node_indices)
        rx_node_count_first = graph.graph.num_nodes()

        await graph.ensure_loaded("rm_class1")
        count_after_second = len(graph.node_indices)
        rx_node_count_second = graph.graph.num_nodes()

        assert count_after_first == count_after_second
        assert rx_node_count_first == rx_node_count_second
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_ensure_loaded_nonexistent_node(event_store, remora_db):
    """ensure_loaded for a nonexistent node is a no-op (no crash, no nodes added)."""
    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_nonexistent")
        assert len(graph.node_indices) == 0
        assert graph.graph.num_nodes() == 0
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_ensure_loaded_populates_edges_in_rustworkx(event_store, remora_db):
    """ensure_loaded should add both nodes AND edges to the rustworkx graph."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_method1")

        assert graph.graph.num_nodes() >= 2
        assert graph.graph.num_edges() >= 1

        # Verify the edge data is "parent_of"
        parent_idx = graph.node_indices["rm_class1"]
        method_idx = graph.node_indices["rm_method1"]
        edge_data = graph.graph.get_edge_data(parent_idx, method_idx)
        assert edge_data == "parent_of"
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_ensure_loaded_without_event_store(remora_db):
    """ensure_loaded without event_store_db_path is a no-op (no crash)."""
    graph = LazyGraph(db=remora_db)
    try:
        await graph.ensure_loaded("rm_anything")
        assert len(graph.node_indices) == 0
    finally:
        graph.close()


# ── invalidate edge cases ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalidate_unloaded_file_is_noop(event_store, remora_db):
    """Invalidating a file that was never loaded is a harmless no-op."""
    await _seed_class_and_method(event_store)

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        # Don't load anything, just invalidate
        await graph.invalidate("/tmp/test.py")
        assert len(graph.node_indices) == 0
        assert graph.graph.num_nodes() == 0
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_invalidate_nonexistent_file_is_noop(event_store, remora_db):
    """Invalidating a file path that doesn't match any nodes is harmless."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, [{"node_id": "rm_method1", "parent_id": "rm_class1"}])

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_class1")
        count_before = len(graph.node_indices)

        await graph.invalidate("/tmp/nonexistent.py")
        assert len(graph.node_indices) == count_before
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_invalidate_clears_loaded_files(event_store, remora_db):
    """invalidate removes the file_path from loaded_files tracking."""
    await _seed_class_and_method(event_store)

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        graph.loaded_files.add("/tmp/test.py")
        assert "/tmp/test.py" in graph.loaded_files

        await graph.invalidate("/tmp/test.py")
        assert "/tmp/test.py" not in graph.loaded_files
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_invalidate_only_affects_target_file(event_store, remora_db):
    """Invalidating file A does not remove nodes from file B."""
    await _seed_multi_file(event_store)
    # alpha calls beta (cross-file edge)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_alpha", "callee_ids": ["rm_beta"]},
            {"node_id": "rm_beta"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        await graph.ensure_loaded("rm_alpha")
        assert "rm_alpha" in graph.node_indices
        assert "rm_beta" in graph.node_indices

        # Invalidate only a.py
        await graph.invalidate("/tmp/a.py")
        assert "rm_alpha" not in graph.node_indices
        # beta is in b.py — should still be there
        assert "rm_beta" in graph.node_indices
    finally:
        graph.close()


# ── Deep graph / neighborhood depth ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_neighborhood_depth_traversal(event_store, remora_db):
    """_get_neighborhood should walk edges to the configured depth."""
    await _seed_deep_chain(event_store)
    # file -> class -> method -> inner_func (3 levels of parent_of edges)
    await _update_edges(remora_db,
        [
            {"node_id": "rm_file1"},
            {"node_id": "rm_deep_class", "parent_id": "rm_file1"},
            {"node_id": "rm_deep_method", "parent_id": "rm_deep_class"},
            {"node_id": "rm_inner_func", "parent_id": "rm_deep_method"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        # Starting from the middle (rm_deep_method), depth=2 should
        neighbors = await graph._get_neighborhood("rm_deep_method", depth=2)
        neighbor_ids = {n.node_id for n in neighbors}

        # Should include self, plus 2 hops in each direction
        assert "rm_deep_method" in neighbor_ids
        # 1 hop: parent (rm_deep_class) and child (rm_inner_func)
        assert "rm_deep_class" in neighbor_ids
        assert "rm_inner_func" in neighbor_ids
        # 2 hops: grandparent (rm_file1)
        assert "rm_file1" in neighbor_ids
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_deep_get_parent_chain(event_store, remora_db):
    """get_parent should work through a 3-level deep chain."""
    await _seed_deep_chain(event_store)
    await _update_edges(remora_db,
        [
            {"node_id": "rm_file1"},
            {"node_id": "rm_deep_class", "parent_id": "rm_file1"},
            {"node_id": "rm_deep_method", "parent_id": "rm_deep_class"},
            {"node_id": "rm_inner_func", "parent_id": "rm_deep_method"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        assert await graph.get_parent("rm_inner_func") == "rm_deep_method"
        assert await graph.get_parent("rm_deep_method") == "rm_deep_class"
        assert await graph.get_parent("rm_deep_class") == "rm_file1"
        assert await graph.get_parent("rm_file1") is None
    finally:
        graph.close()


# ── Mixed edge types ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mixed_parent_and_call_edges(event_store, remora_db):
    """Both parent_of and calls edges should coexist correctly in the graph."""
    await _seed_class_and_method(event_store)
    await _seed_call_graph(event_store)
    # class -> method (parent_of), method -> func_b (calls)
    await _update_edges(remora_db,
        [
            {"node_id": "rm_class1"},
            {"node_id": "rm_method1", "parent_id": "rm_class1", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_a", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_b"},
            {"node_id": "rm_func_c"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        # method1's parent is class1
        assert await graph.get_parent("rm_method1") == "rm_class1"

        # func_b is called by method1 and func_a
        callers = await graph.get_callers("rm_func_b")
        assert "rm_method1" in callers
        assert "rm_func_a" in callers
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_callers_ignores_parent_edges(event_store, remora_db):
    """get_callers should only return nodes connected by 'calls' edges, not 'parent_of'."""
    await _seed_class_and_method(event_store)
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_class1"},
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        # method1 has a parent_of predecessor (class1), but no calls predecessor
        callers = await graph.get_callers("rm_method1")
        assert callers == []
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_get_parent_ignores_call_edges(event_store, remora_db):
    """get_parent should only return nodes connected by 'parent_of' edges, not 'calls'."""
    await _seed_call_graph(event_store)
    # func_a calls func_b — this is NOT a parent relationship
    await _update_edges(remora_db, 
        [
            {"node_id": "rm_func_a", "callee_ids": ["rm_func_b"]},
            {"node_id": "rm_func_b"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        parent = await graph.get_parent("rm_func_b")
        assert parent is None
    finally:
        graph.close()


# ── close() behavior ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_close_closes_connections(event_store, remora_db):
    """After close(), DB queries should fail."""
    await _seed_class_and_method(event_store)

    graph = LazyGraph(db=remora_db, event_store=event_store)
    # Verify it works before close
    node = await graph._get_node("rm_class1")
    assert node is not None

    graph.close()

    # After close, the edges connection should be closed
    with pytest.raises(Exception):
        await graph._get_neighborhood("rm_class1")


@pytest.mark.asyncio
async def test_close_without_event_store(remora_db):
    """close() without event_store_db_path should not raise."""
    graph = LazyGraph(db=remora_db)
    graph.close()  # Should not raise


# ── _normalize_node ──────────────────────────────────────────────────────────


@pytest.mark.skip(reason="_normalize_node removed")
def test_normalize_node_adds_id_from_node_id():
    """_normalize_node should add 'id' key when only 'node_id' exists."""
    # Create a mock sqlite3.Row-like dict
    # We test the static method directly with a real Row
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (node_id TEXT, name TEXT)")
    conn.execute("INSERT INTO t VALUES ('rm_test', 'TestFunc')")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM t").fetchone()
    conn.close()

    result = LazyGraph._normalize_node(row)
    assert result["node_id"] == "rm_test"
    assert result["id"] == "rm_test"
    assert result["name"] == "TestFunc"


@pytest.mark.skip(reason="_normalize_node removed")
def test_normalize_node_preserves_existing_id():
    """_normalize_node should not overwrite an existing 'id' key."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (id TEXT, node_id TEXT, name TEXT)")
    conn.execute("INSERT INTO t VALUES ('existing_id', 'rm_test', 'TestFunc')")
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM t").fetchone()
    conn.close()

    result = LazyGraph._normalize_node(row)
    assert result["id"] == "existing_id"
    assert result["node_id"] == "rm_test"


# ── Graph initialization ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_init_creates_empty_state(remora_db):
    """A fresh LazyGraph should have an empty graph and empty tracking dicts."""
    graph = LazyGraph(db=remora_db)
    try:
        assert graph.graph.num_nodes() == 0
        assert graph.graph.num_edges() == 0
        assert graph.node_indices == {}
        assert graph.loaded_files == set()
    finally:
        graph.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason="_nodes_conn removed")
async def test_graph_init_with_event_store(event_store, remora_db):
    """LazyGraph with event_store_db_path should have a nodes connection."""
    graph = LazyGraph(db=remora_db, event_store=event_store)
    try:
        assert graph._nodes_conn is not None
    finally:
        graph.close()


@pytest.mark.asyncio
@pytest.mark.skip(reason="_nodes_conn removed")
async def test_graph_init_without_event_store(remora_db):
    """LazyGraph without event_store_db_path should have no nodes connection."""
    graph = LazyGraph(db=remora_db)
    try:
        assert graph._nodes_conn is None
    finally:
        graph.close()
