"""Unit tests for EventStore basic operations.

Tests basic CRUD operations without the reactive subscription layer.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.event_store import EventStore
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

    await store.close()
