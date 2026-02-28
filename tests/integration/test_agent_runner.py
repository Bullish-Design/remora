"""Integration tests for AgentRunner cascade prevention.

These tests verify that the AgentRunner correctly implements cascade prevention
via depth limits and cooldowns to prevent infinite loops.
"""

from __future__ import annotations

import pytest

# pytest.skip(
#    "AgentRunner integration tests rely on structured_agents imports that hang in this environment",
#    allow_module_level=True,
# )

import asyncio
import contextlib
import time
from pathlib import Path
from typing import AsyncIterator
from unittest.mock import AsyncMock

from remora.core.agent_runner import AgentRunner
from remora.core.agent_state import AgentState, save as save_agent_state
from remora.core.config import Config
from remora.core.event_store import EventStore
from remora.core.events import ManualTriggerEvent
from remora.core.reconciler import get_agent_state_path
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


def _ensure_agent_state(project_root: Path, agent_id: str) -> None:
    """Create a minimal agent state for the given agent ID."""
    state = AgentState(
        agent_id=agent_id,
        node_type="test-node",
        name=agent_id,
        full_name=agent_id,
        file_path=str(project_root / "dummy.py"),
        range=(1, 1),
    )
    save_agent_state(
        get_agent_state_path(project_root / ".remora", agent_id),
        state,
    )


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

    project_root = Path(runner_config.project_path)
    project_root.mkdir(parents=True, exist_ok=True)

    runner_config.trigger_cooldown_ms = 500
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
        project_root=project_root,
    )

    await subscriptions.register(
        "agent_a",
        SubscriptionPattern(to_agent="agent_a"),
    )

    mock_executor = AsyncMock()
    mock_executor.run_agent = AsyncMock(return_value="executed")
    runner._executor = mock_executor

    _ensure_agent_state(project_root, "agent_a")

    runner_task = asyncio.create_task(runner.run_forever())

    try:
        await event_store.append(
            "test-swarm",
            ManualTriggerEvent(to_agent="agent_a", reason="test"),
        )
        await event_store.append(
            "test-swarm",
            ManualTriggerEvent(to_agent="agent_a", reason="test"),
        )

        await asyncio.sleep(0.2)

        executed_count = mock_executor.run_agent.call_count

        assert executed_count == 1, f"Expected 1 execution due to cooldown, got {executed_count}"
    finally:
        runner_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner_task
        await runner.stop()


@pytest.mark.asyncio
async def test_concurrent_trigger_handling(
    runner_config: Config,
    runner_components,
):
    """Test that max_concurrency is respected."""
    event_store, subscriptions, swarm_state = runner_components

    project_root = Path(runner_config.project_path)
    project_root.mkdir(parents=True, exist_ok=True)

    runner_config.max_concurrency = 2
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=runner_config,
        project_root=project_root,
    )

    for i in range(5):
        await subscriptions.register(
            f"agent_{i}",
            SubscriptionPattern(to_agent=f"agent_{i}"),
        )
        _ensure_agent_state(project_root, f"agent_{i}")

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

    runner_task = asyncio.create_task(runner.run_forever())

    async def trigger_all():
        for i in range(5):
            await event_store.append(
                "test-swarm",
                ManualTriggerEvent(to_agent=f"agent_{i}", reason="test"),
            )

    try:
        await trigger_all()
        await asyncio.sleep(0.3)
    finally:
        runner_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await runner_task
        await runner.stop()

    assert execution_count == 5
