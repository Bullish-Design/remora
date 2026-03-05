"""Unit tests for EventStore basic operations.

Tests basic CRUD operations without the reactive subscription layer.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from remora.core.event_store import EventStore
from remora.core.events import AgentStartEvent


@pytest.mark.asyncio
async def test_event_store_append_and_replay(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    event = AgentStartEvent(graph_id="graph-1", agent_id="agent-1", node_name="test")
    await store.append("graph-1", event)

    count = await store.get_event_count("graph-1")
    assert count == 1

    records = [record async for record in store.replay("graph-1")]
    assert records[0]["event_type"] == "AgentStartEvent"
    assert records[0]["graph_id"] == "graph-1"

    graphs = await store.get_graph_ids()
    assert graphs[0]["graph_id"] == "graph-1"

    deleted = await store.delete_graph("graph-1")
    assert deleted == 1
    assert await store.get_event_count("graph-1") == 0

    await store.close()


class _SlowProjection:
    def apply(self, conn, event):
        del conn, event
        time.sleep(0.2)
        return []


@pytest.mark.asyncio
async def test_append_cancellation_waits_for_inflight_write(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db", projection=_SlowProjection())
    await store.initialize()

    event = AgentStartEvent(graph_id="graph-1", agent_id="agent-1", node_name="slow")

    started_at = time.monotonic()
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(store.append("graph-1", event), timeout=0.01)
    elapsed = time.monotonic() - started_at

    # The timeout cancellation should wait for the in-flight writer thread.
    assert elapsed >= 0.18
    assert store._conn is not None and not store._conn.in_transaction

    await store.append("graph-1", AgentStartEvent(graph_id="graph-1", agent_id="agent-2", node_name="next"))
    assert await store.get_event_count("graph-1") == 2
    await store.close()


@pytest.mark.asyncio
async def test_append_recovers_stale_in_transaction_state(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    await store.initialize()
    assert store._conn is not None

    await asyncio.to_thread(store._conn.execute, "BEGIN IMMEDIATE")
    assert store._conn.in_transaction

    await store.append("graph-1", AgentStartEvent(graph_id="graph-1", agent_id="agent-1", node_name="recover"))
    assert not store._conn.in_transaction
    assert await store.get_event_count("graph-1") == 1
    await store.close()
