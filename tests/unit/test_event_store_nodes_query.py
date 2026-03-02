"""Tests for AgentNode query methods on EventStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db", projection=NodeProjection())
    await s.initialize()

    # Seed two nodes
    for name, ntype in [("foo", "function"), ("Bar", "class")]:
        await s.append(
            "swarm",
            NodeDiscoveredEvent(
                node_id=f"id_{name}",
                node_type=ntype,
                name=name,
                full_name=f"{ntype}:{name}",
                file_path="/test.py",
                start_line=1,
                end_line=5,
                source_code=f"def {name}(): pass",
                source_hash=f"hash_{name}",
            ),
        )

    yield s
    await s.close()


@pytest.mark.asyncio
async def test_get_node(store: EventStore):
    node = await store.get_node("id_foo")
    assert node is not None
    assert node.name == "foo"
    assert isinstance(node, AgentNode)


@pytest.mark.asyncio
async def test_get_node_not_found(store: EventStore):
    node = await store.get_node("nonexistent")
    assert node is None


@pytest.mark.asyncio
async def test_list_nodes(store: EventStore):
    nodes = await store.list_nodes()
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_file(store: EventStore):
    nodes = await store.list_nodes(file_path="/test.py")
    assert len(nodes) == 2


@pytest.mark.asyncio
async def test_list_nodes_by_type(store: EventStore):
    nodes = await store.list_nodes(node_type="class")
    assert len(nodes) == 1
    assert nodes[0].name == "Bar"
