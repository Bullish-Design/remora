# tests/unit/test_lsp_graph.py
"""Tests for LazyGraph — reads nodes from EventStore DB, edges from RemoraDB."""

from __future__ import annotations

import pytest

from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection
from remora.lsp.db import RemoraDB
from remora.lsp.graph import LazyGraph, RUSTWORKX_AVAILABLE

pytestmark = pytest.mark.skipif(not RUSTWORKX_AVAILABLE, reason="rustworkx not installed")


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


async def _seed_nodes(store: EventStore):
    """Create a small tree: file → class → method."""
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


@pytest.mark.asyncio
async def test_graph_reads_nodes_from_event_store(event_store, remora_db):
    """LazyGraph should read nodes from EventStore's DB."""
    await _seed_nodes(event_store)
    # Add parent_of edge to RemoraDB
    await remora_db.update_edges(
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store_db_path=str(event_store._db_path))
    try:
        parent = graph.get_parent("rm_method1")
        assert parent == "rm_class1"
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_invalidate_removes_file_nodes(event_store, remora_db):
    """LazyGraph.invalidate should remove nodes for a file."""
    await _seed_nodes(event_store)
    await remora_db.update_edges(
        [
            {"node_id": "rm_method1", "parent_id": "rm_class1"},
        ]
    )

    graph = LazyGraph(db=remora_db, event_store_db_path=str(event_store._db_path))
    try:
        # Load nodes first
        graph.ensure_loaded("rm_class1")
        assert "rm_class1" in graph.node_indices

        # Invalidate
        graph.invalidate("/tmp/test.py")
        assert "rm_class1" not in graph.node_indices
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_node_queries_without_event_store(remora_db):
    """LazyGraph without event_store_db_path returns empty results for node queries."""
    graph = LazyGraph(db=remora_db)
    try:
        assert graph._get_node("nonexistent") is None
        assert graph._get_nodes_for_file("/tmp/test.py") == []
    finally:
        graph.close()


@pytest.mark.asyncio
async def test_graph_node_query_reads_event_store_db(event_store, remora_db):
    """LazyGraph._get_node reads from EventStore DB using node_id column."""
    await _seed_nodes(event_store)
    graph = LazyGraph(db=remora_db, event_store_db_path=str(event_store._db_path))
    try:
        node = graph._get_node("rm_class1")
        assert node is not None
        assert node["node_id"] == "rm_class1"
        assert node["id"] == "rm_class1"  # normalized
        assert node["name"] == "MyClass"
    finally:
        graph.close()
