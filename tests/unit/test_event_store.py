from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.event_bus import EventBus
from remora.core.event_store import EventSourcedBus, EventStore
from remora.core.events import GraphStartEvent


@pytest.mark.asyncio
async def test_event_store_append_and_replay(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    event = GraphStartEvent(graph_id="graph-1", node_count=1)
    await store.append("graph-1", event)

    count = await store.get_event_count("graph-1")
    assert count == 1

    records = [record async for record in store.replay("graph-1")]
    assert records[0]["event_type"] == "GraphStartEvent"
    assert records[0]["payload"]["graph_id"] == "graph-1"

    graphs = await store.get_graph_ids()
    assert graphs[0]["graph_id"] == "graph-1"

    deleted = await store.delete_graph("graph-1")
    assert deleted == 1
    assert await store.get_event_count("graph-1") == 0


@pytest.mark.asyncio
async def test_event_sourced_bus_persists_and_emits(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    bus = EventBus()
    captured: list[object] = []
    bus.subscribe_all(captured.append)

    sourced = EventSourcedBus(bus, store, "graph-2")
    event = GraphStartEvent(graph_id="graph-2", node_count=2)
    await sourced.emit(event)

    assert captured == [event]
    assert await store.get_event_count("graph-2") == 1
