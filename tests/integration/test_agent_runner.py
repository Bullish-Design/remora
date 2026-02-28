"""Integration tests for AgentRunner cascade prevention.

These tests verify that the AgentRunner correctly implements cascade prevention
via depth limits and cooldowns to prevent infinite loops.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from remora.core.agent_runner import AgentRunner
from remora.core.config import Config
from remora.core.event_store import EventStore
from remora.core.events import AgentMessageEvent, ManualTriggerEvent
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
async def runner_components(tmp_path: Path):
    """Create all runner components."""
    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    swarm_state = SwarmState(tmp_path / "swarm.db")
    swarm_state.initialize()

    return event_store, subscriptions, swarm_state


@pytest.mark.asyncio
async def test_depth_limit_enforced(
    runner_config: Config,
    runner_components,
    tmp_path: Path,
):
    """Test that cascade depth limit is enforced.

    Verifies that events triggering other agents stop at max_trigger_depth.
    """
    event_store, subscriptions, swarm_state = runner_components

    runner_config.max_trigger_depth = 3
    runner_config.max_concurrency = 5
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
        project_root=tmp_path,
    )

    execution_count = 0

    async def fake_execute_turn(agent_id: str, trigger_event: AgentMessageEvent) -> None:
        nonlocal execution_count
        execution_count += 1
        await asyncio.sleep(0.05)

    runner._execute_turn = fake_execute_turn

    event = AgentMessageEvent(
        from_agent="user",
        to_agent="agent_a",
        correlation_id="depth-chain",
        content="start",
    )

    tasks = [
        asyncio.create_task(
            runner._process_trigger("agent_a", index, event, "depth-chain")
        )
        for index in range(5)
    ]

    await asyncio.gather(*tasks)

    assert execution_count == runner_config.max_trigger_depth


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
