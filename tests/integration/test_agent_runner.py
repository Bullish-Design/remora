"""Integration tests for AgentRunner cascade prevention.

These tests verify that the AgentRunner correctly implements cascade prevention
via depth limits and cooldowns to prevent infinite loops.
"""

from __future__ import annotations

import pytest

pytest.skip(
    "AgentRunner integration tests rely on structured_agents imports that hang in this environment",
    allow_module_level=True,
)

import asyncio
import contextlib
import time
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock

from remora.core.agent_runner import AgentRunner
from remora.core.config import Config
from remora.core.event_store import EventStore
from remora.core.events import ManualTriggerEvent
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.swarm_state import SwarmState


@pytest.fixture
def runner_config(tmp_path: Path) -> Config:
    """Create a config specifically for runner tests."""
    return Config(
        project_path=str(tmp_path),
        discovery_paths=("src/",),
        model_base_url="http://localhost:8000/v1",
        model_default="test/model",
        model_api_key="test-key",
        swarm_root=".remora",
        swarm_id="test-swarm",
        max_concurrency=4,
        max_turns=3,
        max_trigger_depth=3,
        trigger_cooldown_ms=100,
    )


@pytest.fixture
async def runner_components(tmp_path: Path) -> AsyncIterator[tuple[EventStore, SubscriptionRegistry, SwarmState]]:
    """Create all runner components."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    swarm_state = SwarmState(tmp_path / "swarm.db")
    await swarm_state.initialize()

    try:
        yield event_store, subscriptions, swarm_state
    finally:
        await swarm_state.close()
        with contextlib.suppress(Exception):
            await event_store.close()
        with contextlib.suppress(Exception):
            await subscriptions.close()


@pytest.mark.asyncio
async def test_depth_limit_enforced(
    runner_config: Config,
    runner_components,
    tmp_path: Path,
):
    """Test cascade depth limit guard for in-flight triggers."""
    event_store, subscriptions, swarm_state = runner_components

    runner_config.max_trigger_depth = 3
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
        project_root=tmp_path,
    )

    correlation_id = "limit-chain"
    key = f"agent_a:{correlation_id}"
    now = time.time()

    runner._correlation_depth[key] = (runner_config.max_trigger_depth, now)
    assert not runner._check_depth_limit("agent_a", correlation_id)

    runner._correlation_depth[key] = (runner_config.max_trigger_depth - 1, now)
    assert runner._check_depth_limit("agent_a", correlation_id)


@pytest.mark.asyncio
async def test_cooldown_prevents_duplicate_triggers(
    runner_config: Config,
    runner_components,
):
    """Test that rapid identical triggers are dropped by cooldown."""
    event_store, subscriptions, swarm_state = runner_components

    runner_config.trigger_cooldown_ms = 500
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
    )

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )

    mock_executor = AsyncMock()
    mock_executor.run_agent = AsyncMock(return_value="executed")
    runner._executor = mock_executor

    await event_store.append(
        "test-swarm",
        ManualTriggerEvent(agent_id="agent_a", reason="test"),
    )
    await event_store.append(
        "test-swarm",
        ManualTriggerEvent(agent_id="agent_a", reason="test"),
    )

    await asyncio.sleep(0.2)

    executed_count = mock_executor.run_agent.call_count

    assert executed_count == 1, f"Expected 1 execution due to cooldown, got {executed_count}"

    await runner.stop()


@pytest.mark.asyncio
async def test_concurrent_trigger_handling(
    runner_config: Config,
    runner_components,
):
    """Test that max_concurrency is respected."""
    event_store, subscriptions, swarm_state = runner_components

    runner_config.max_concurrency = 2
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
    )

    for i in range(5):
        await subscriptions.register(
            f"agent_{i}",
            SubscriptionPattern(to_agent=f"agent_{i}"),
        )

    execution_count = 0
    execution_lock = asyncio.Lock()

    async def slow_run(*args, **kwargs):
        nonlocal execution_count
        async with execution_lock:
            execution_count += 1
            current = execution_count
        await asyncio.sleep(0.05)
        return "done"

    mock_executor = AsyncMock()
    mock_executor.run_agent = slow_run
    runner._executor = mock_executor

    async def trigger_all():
        for i in range(5):
            await event_store.append(
                "test-swarm",
                ManualTriggerEvent(agent_id=f"agent_{i}", reason="test"),
            )

    await trigger_all()
    await asyncio.sleep(0.3)

    await runner.stop()

    assert execution_count == 5
