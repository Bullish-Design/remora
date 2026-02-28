"""Integration tests for EventStore trigger queue.

These tests verify:
1. Concurrent event appending (SQLite lock handling)
2. Subscription-based trigger delivery pipeline
"""

from __future__ import annotations

import asyncio

import pytest

from remora.core.event_store import EventStore
from remora.core.events import (
    AgentMessageEvent,
    ContentChangedEvent,
    ManualTriggerEvent,
)
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry


@pytest.mark.asyncio
async def test_event_store_concurrent_append(tmp_path):
    """Test concurrent event appending to ensure SQLite locks hold up."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    async def worker(worker_id: int):
        for i in range(20):
            event = ContentChangedEvent(
                path=f"file_{worker_id}_{i}.py",
                diff=f"diff_{i}",
            )
            await store.append(f"graph_{worker_id}", event)

    await asyncio.gather(*(worker(i) for i in range(10)))

    total_count = await store.get_event_count("graph_0")
    assert total_count == 20

    total_all = 0
    for i in range(10):
        count = await store.get_event_count(f"graph_{i}")
        total_all += count

    assert total_all == 200

    await store.close()


@pytest.mark.asyncio
async def test_event_store_append_returns_event_id(tmp_path):
    """Test that append returns the event ID."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    event = ContentChangedEvent(path="test.py", diff=None)
    event_id = await store.append("graph_1", event)

    assert event_id > 0

    await store.close()


@pytest.mark.asyncio
async def test_event_store_replay(tmp_path):
    """Test replaying events from the store."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    for i in range(5):
        event = ContentChangedEvent(path=f"test_{i}.py", diff=f"diff_{i}")
        await store.append("graph_1", event)

    events = [e async for e in store.replay("graph_1")]

    assert len(events) == 5
    assert events[0]["payload"]["path"] == "test_0.py"

    await store.close()


@pytest.mark.asyncio
async def test_event_store_replay_with_filters(tmp_path):
    """Test replaying events with type and time filters."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    await store.append("graph_1", ContentChangedEvent(path="a.py"))
    await store.append("graph_1", AgentMessageEvent(from_agent="a", to_agent="b", content="msg"))
    await store.append("graph_1", ContentChangedEvent(path="b.py"))

    events = [
        e
        async for e in store.replay(
            "graph_1",
            event_types=["ContentChangedEvent"],
        )
    ]

    assert len(events) == 2
    for e in events:
        assert e["event_type"] == "ContentChangedEvent"

    await store.close()


@pytest.mark.asyncio
async def test_event_store_get_graph_ids(tmp_path):
    """Test retrieving graph execution IDs."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    await store.append("graph_1", ContentChangedEvent(path="a.py"))
    await store.append("graph_2", ContentChangedEvent(path="b.py"))
    await store.append("graph_1", ContentChangedEvent(path="c.py"))

    graph_ids = await store.get_graph_ids()

    assert len(graph_ids) == 2
    graph_ids_map = {g["graph_id"]: g for g in graph_ids}
    assert graph_ids_map["graph_1"]["event_count"] == 2
    assert graph_ids_map["graph_2"]["event_count"] == 1

    await store.close()


@pytest.mark.asyncio
async def test_event_store_delete_graph(tmp_path):
    """Test deleting all events for a graph."""
    store = EventStore(tmp_path / "events.db")
    await store.initialize()

    await store.append("graph_1", ContentChangedEvent(path="a.py"))
    await store.append("graph_1", ContentChangedEvent(path="b.py"))
    await store.append("graph_2", ContentChangedEvent(path="c.py"))

    deleted = await store.delete_graph("graph_1")
    assert deleted == 2

    count1 = await store.get_event_count("graph_1")
    assert count1 == 0

    count2 = await store.get_event_count("graph_2")
    assert count2 == 1

    await store.close()


@pytest.mark.asyncio
async def test_event_store_trigger_delivery_pipeline(tmp_path):
    """Test end-to-end trigger delivery without the runner."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await store.initialize()

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )

    await store.append(
        "test-swarm",
        AgentMessageEvent(from_agent="user", to_agent="agent_a", content="Hello"),
    )

    triggers = []
    async for agent_id, event_id, event in store.get_triggers():
        triggers.append((agent_id, event_id, event))
        if len(triggers) >= 1:
            break

    assert len(triggers) == 1
    assert triggers[0][0] == "agent_a"
    assert isinstance(triggers[0][2], AgentMessageEvent)

    await store.close()
    await subscriptions.close()


@pytest.mark.asyncio
async def test_event_store_trigger_multiple_matching(tmp_path):
    """Test that multiple agents can match the same event."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await store.initialize()

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )
    await subscriptions.register(
        "agent_b",
        SubscriptionPattern(to_agent="agent_a"),
    )
    await subscriptions.register(
        "agent_c",
        SubscriptionPattern(event_types=["AgentMessageEvent"]),
    )

    event = AgentMessageEvent(from_agent="user", to_agent="agent_a", content="Hello")
    event_id = await store.append("test-swarm", event)

    triggers = []
    async for agent_id, evt_id, evt in store.get_triggers():
        triggers.append(agent_id)
        if len(triggers) >= 3:
            break

    assert "agent_a" in triggers
    assert "agent_b" in triggers
    assert "agent_c" in triggers

    await store.close()
    await subscriptions.close()


@pytest.mark.asyncio
async def test_event_store_no_trigger_without_subscription(tmp_path):
    """Test that events without matching subscriptions don't produce triggers."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await store.initialize()

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )

    await store.append(
        "test-swarm",
        AgentMessageEvent(from_agent="user", to_agent="agent_b", content="Hello"),
    )

    trigger_iter = store.get_triggers().__aiter__()
    with pytest.raises((asyncio.TimeoutError, StopAsyncIteration)):
        await asyncio.wait_for(trigger_iter.__anext__(), timeout=0.1)

    await store.close()
    await subscriptions.close()
