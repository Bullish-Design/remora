from __future__ import annotations

import json
from pathlib import Path

import pytest

from remora.core.code.projections import NodeProjection
from remora.core.events.code_events import NodeDiscoveredEvent
from remora.core.store.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await event_store.initialize()

    await event_store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="id_file",
            node_type="file",
            name="mod.py",
            full_name="mod",
            file_path="/mod.py",
            start_line=1,
            end_line=20,
            source_code="def f():\n    return 1\n",
            source_hash="hash_file",
        ),
    )
    await event_store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="id_func",
            node_type="function",
            name="f",
            full_name="mod.f",
            file_path="/mod.py",
            start_line=1,
            end_line=2,
            source_code="def f():\n    return 1\n",
            source_hash="hash_func",
            parent_id="id_file",
        ),
    )

    yield event_store
    await event_store.close()


@pytest.mark.asyncio
async def test_read_graph_returns_code_node_projection(store: EventStore) -> None:
    payload = json.loads(await store.nodes.read_graph({"node": "id_func"}))
    assert payload is not None
    assert payload["id"] == "id_func"
    assert payload["kind"] == "function"
    assert payload["attrs"]["full_name"] == "mod.f"


@pytest.mark.asyncio
async def test_write_graph_add_node_generates_id(store: EventStore) -> None:
    created = json.loads(await store.nodes.write_graph("add_node", {"kind": "agent", "attrs": {"name": "coordinator"}}))
    assert created["id"]
    assert created["kind"] == "agent"

    matches = json.loads(await store.nodes.read_graph({"match": {"kind": "agent"}}))
    assert len(matches) == 1
    assert matches[0]["attrs"]["name"] == "coordinator"


@pytest.mark.asyncio
async def test_write_graph_add_node_preserves_provided_id(store: EventStore) -> None:
    created = json.loads(
        await store.nodes.write_graph(
            "add_node",
            {"id": "agent:owner", "kind": "agent", "attrs": {"name": "owner"}},
        )
    )
    assert created["id"] == "agent:owner"


@pytest.mark.asyncio
async def test_read_graph_neighbors_for_generic_nodes(store: EventStore) -> None:
    await store.nodes.write_graph("add_node", {"id": "agent:a", "kind": "agent", "attrs": {"name": "a"}})
    await store.nodes.write_graph("add_node", {"id": "task:1", "kind": "task", "attrs": {"title": "t1"}})
    await store.nodes.write_graph(
        "add_edge",
        {"from": "agent:a", "to": "task:1", "kind": "assigned_to", "attrs": {"priority": "high"}},
    )

    neighbors = json.loads(await store.nodes.read_graph({"neighbors": "agent:a", "dir": "out"}))
    assert len(neighbors) == 1
    assert neighbors[0]["id"] == "task:1"
    assert neighbors[0]["edge_kind"] == "assigned_to"


@pytest.mark.asyncio
async def test_module_alias_maps_to_file_nodes(store: EventStore) -> None:
    modules = json.loads(await store.nodes.read_graph({"match": {"kind": "module"}}))
    assert len(modules) == 1
    assert modules[0]["id"] == "id_file"
    assert modules[0]["kind"] == "module"


@pytest.mark.asyncio
async def test_write_graph_rejects_code_kinds(store: EventStore) -> None:
    with pytest.raises(ValueError):
        await store.nodes.write_graph("add_node", {"kind": "function", "attrs": {}})

