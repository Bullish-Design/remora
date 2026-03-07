"""Tests for AgentNode query methods on EventStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.events.events import NodeDiscoveredEvent
from remora.core.code.projections import NodeProjection


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db", projection=NodeProjection())
    await s.initialize()

    # Seed two nodes in the same file at different line ranges
    await s.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="id_foo",
            node_type="function",
            name="foo",
            full_name="test.foo",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="def foo(): pass",
            source_hash="hash_foo",
        ),
    )
    await s.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="id_Bar",
            node_type="class",
            name="Bar",
            full_name="test.Bar",
            file_path="/test.py",
            start_line=7,
            end_line=20,
            source_code="class Bar: pass",
            source_hash="hash_Bar",
        ),
    )

    yield s
    await s.close()


@pytest.mark.asyncio
async def test_get_node(store: EventStore):
    node = await store.nodes.get_node("id_foo")
    assert node is not None
    assert node.name == "foo"
    assert isinstance(node, AgentNode)


@pytest.mark.asyncio
async def test_get_node_not_found(store: EventStore):
    node = await store.nodes.get_node("nonexistent")
    assert node is None


@pytest.mark.asyncio
async def test_list_nodes(store: EventStore):
    nodes = await store.nodes.list_nodes()
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_file(store: EventStore):
    nodes = await store.nodes.list_nodes(file_path="/test.py")
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_type(store: EventStore):
    nodes = await store.nodes.list_nodes(node_type="class")
    assert len(nodes) == 1
    assert nodes[0].name == "Bar"


@pytest.mark.asyncio
async def test_get_node_at_position_hit(store: EventStore):
    """Line 3 is inside foo (lines 1-5)."""
    node = await store.nodes.get_node_at_position("/test.py", 3)
    assert node is not None
    assert node.node_id == "id_foo"


@pytest.mark.asyncio
async def test_get_node_at_position_miss(store: EventStore):
    """Line 6 is between foo and Bar — no node."""
    node = await store.nodes.get_node_at_position("/test.py", 6)
    assert node is None


@pytest.mark.asyncio
async def test_get_node_at_position_narrowest(store: EventStore, tmp_path: Path):
    """When a method is inside a class, return the method (narrowest)."""
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="id_method",
            node_type="method",
            name="baz",
            full_name="test.Bar.baz",
            file_path="/test.py",
            start_line=9,
            end_line=12,
            source_code="def baz(self): pass",
            source_hash="hash_baz",
            parent_id="id_Bar",
        ),
    )
    # Line 10 is inside both Bar (7-20) and baz (9-12). Should return baz.
    node = await store.nodes.get_node_at_position("/test.py", 10)
    assert node is not None
    assert node.node_id == "id_method"


@pytest.mark.asyncio
async def test_get_node_at_position_wrong_file(store: EventStore):
    """Querying a different file returns None."""
    node = await store.nodes.get_node_at_position("/other.py", 3)
    assert node is None


@pytest.mark.asyncio
async def test_set_node_status(store: EventStore):
    """set_node_status updates the status field."""
    await store.set_node_status("id_foo", "running")
    node = await store.nodes.get_node("id_foo")
    assert node is not None
    assert node.status == "running"

    await store.set_node_status("id_foo", "idle")
    node = await store.nodes.get_node("id_foo")
    assert node.status == "idle"


@pytest.mark.asyncio
async def test_remove_nodes_for_file(store: EventStore):
    """remove_nodes_for_file removes all nodes for a file path."""
    removed = await store.remove_nodes_for_file("/test.py")
    assert removed == 2

    nodes = await store.nodes.list_nodes(file_path="/test.py")
    assert len(nodes) == 0


@pytest.mark.asyncio
async def test_remove_nodes_for_file_no_match(store: EventStore):
    """Removing from a non-existent file returns 0."""
    removed = await store.remove_nodes_for_file("/nonexistent.py")
    assert removed == 0
