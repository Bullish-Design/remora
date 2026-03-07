"""Integration tests for the unified AgentRunner cascade prevention.

These tests verify that the unified AgentRunner (lsp/runner.py) correctly
implements cascade prevention via depth limits and cooldowns, using the
create_headless() factory for CLI/headless mode.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.events import ManualTriggerEvent
from remora.core.code.projections import NodeProjection
from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.runner.agent_runner import AgentRunner


def _make_agent_node(node_id: str = "agent_a", **overrides) -> AgentNode:
    defaults = {
        "node_id": node_id,
        "node_type": "function",
        "name": node_id,
        "full_name": f"test.{node_id}",
        "file_path": "file:///tmp/test.py",
        "start_line": 1,
        "end_line": 3,
        "source_code": "def foo():\n    return 1\n",
        "source_hash": "abc123",
        "status": "idle",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


def _insert_node(event_store: EventStore, node: AgentNode) -> None:
    """Insert a node directly into the EventStore DB."""
    row = node.to_row()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    event_store._conn.execute(
        f"INSERT OR REPLACE INTO nodes ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    event_store._conn.commit()


@pytest.fixture
async def runner_components(tmp_path: Path) -> AsyncIterator[tuple[EventStore, SubscriptionRegistry]]:
    """Create EventStore and SubscriptionRegistry for runner tests."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        tmp_path / "events.db",
        subscriptions=subscriptions,
        projection=NodeProjection(),
    )
    await event_store.initialize()

    event_store.set_subscriptions(subscriptions)

    try:
        yield event_store, subscriptions
    finally:
        with contextlib.suppress(Exception):
            await event_store.close()
        with contextlib.suppress(Exception):
            await subscriptions.close()


@pytest.mark.asyncio
async def test_depth_limit_enforced(runner_components):
    """Test cascade depth limit guard for in-flight triggers."""
    event_store, subscriptions = runner_components

    runner = AgentRunner.create_headless(
        event_store=event_store,
        max_trigger_depth=3,
    )

    correlation_id = "limit-chain"
    key = f"agent_a:{correlation_id}"
    now = time.time()

    runner._correlation_depth[key] = (3, now)
    assert not runner._check_depth_limit("agent_a", correlation_id)

    runner._correlation_depth[key] = (2, now)
    assert runner._check_depth_limit("agent_a", correlation_id)


@pytest.mark.asyncio
async def test_cooldown_prevents_duplicate_triggers(runner_components):
    """Test that rapid identical triggers are dropped by cooldown."""
    event_store, subscriptions = runner_components

    node = _make_agent_node("agent_a")
    _insert_node(event_store, node)

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )

    runner = AgentRunner.create_headless(
        event_store=event_store,
        trigger_cooldown_ms=500,
    )
    runner.execute_turn = AsyncMock()

    # First trigger — should pass cooldown
    await runner.trigger("agent_a", "corr_1")
    assert not runner.queue.empty()
    await runner.queue.get()  # drain

    # Immediate second trigger — should be dropped by cooldown
    await runner.trigger("agent_a", "corr_2")
    assert runner.queue.empty()


@pytest.mark.asyncio
async def test_concurrent_trigger_handling(runner_components):
    """Test that max_concurrency is respected via semaphore."""
    event_store, subscriptions = runner_components

    max_concurrent_observed = 0
    current_concurrent = 0
    concurrent_lock = asyncio.Lock()
    execution_count = 0

    for i in range(5):
        node = _make_agent_node(f"agent_{i}")
        _insert_node(event_store, node)

    runner = AgentRunner.create_headless(
        event_store=event_store,
        max_concurrency=2,
        trigger_cooldown_ms=0,  # disable cooldown for this test
    )

    original_execute = runner.execute_turn

    async def tracking_execute(trigger):
        nonlocal max_concurrent_observed, current_concurrent, execution_count
        async with concurrent_lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent_observed:
                max_concurrent_observed = current_concurrent
        try:
            await asyncio.sleep(0.05)
        finally:
            async with concurrent_lock:
                current_concurrent -= 1
                execution_count += 1

    runner.execute_turn = tracking_execute

    # Enqueue 5 triggers directly (bypass cooldown)
    for i in range(5):
        await runner.queue.put(
            __import__("remora.runner.agent_runner", fromlist=["Trigger"]).Trigger(
                agent_id=f"agent_{i}",
                correlation_id=f"corr_{i}",
            )
        )

    runner._running = True

    async def run_with_timeout():
        while not runner.queue.empty():
            trigger = await runner.queue.get()
            await tracking_execute(trigger)

    # Process all triggers — run them through the semaphore
    tasks = []
    for i in range(5):
        trigger = await runner.queue.get()
        tasks.append(asyncio.create_task(tracking_execute(trigger)))

    await asyncio.gather(*tasks)

    assert execution_count == 5
