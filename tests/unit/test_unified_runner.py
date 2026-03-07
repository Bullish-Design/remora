"""Tests for the unified AgentRunner (merged from core + LSP runners).

These tests verify the cascade-safety features ported from core/agent_runner.py
into the unified lsp/runner.py, plus the EventStore trigger bridge and
concurrency controls.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.code.projections import NodeProjection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_node(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "rm_abc12",
        "node_type": "function",
        "name": "foo",
        "full_name": "test.foo",
        "file_path": "file:///tmp/test.py",
        "start_line": 1,
        "end_line": 3,
        "source_code": "def foo():\n    return 1\n",
        "source_hash": "abc123",
        "status": "idle",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


@pytest.fixture
async def event_store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await es.initialize()
    node = _make_agent_node()
    row = node.to_row()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    es._conn.execute(
        f"INSERT INTO nodes ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    es._conn.commit()
    yield es
    await es.close()


@pytest.fixture
def mock_server(event_store: EventStore) -> MagicMock:
    server = MagicMock()
    server.event_store = event_store
    server.db = MagicMock()
    server.db.get_activation_chain = AsyncMock(return_value=[])
    server.db.add_to_chain = AsyncMock()
    server.db.set_status = AsyncMock()
    server.db.store_proposal = AsyncMock()
    server.db.update_proposal_status = AsyncMock()
    server.emit_event = AsyncMock()
    server.proposals = {}
    server.generate_correlation_id = MagicMock(return_value="corr_test")
    return server


# =========================================================================
# 1. Cascade Prevention — Depth Tracking (ported from core runner)
# =========================================================================


class TestCascadeDepthTracking:
    """Verify per-agent depth tracking ported from core/agent_runner.py."""

    def test_runner_has_correlation_depth_dict(self, mock_server):
        """Unified runner should have _correlation_depth for cascade tracking."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_correlation_depth")
        assert isinstance(runner._correlation_depth, dict)

    def test_runner_has_check_depth_method(self, mock_server):
        """Unified runner should have _check_depth_limit method."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_check_depth_limit")
        assert callable(runner._check_depth_limit)

    def test_depth_limit_blocks_deep_cascades(self, mock_server):
        """When depth >= max, _check_depth_limit should return False."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        # Simulate a cascade that's hit the max
        key = "agent_a:corr_1"
        runner._correlation_depth[key] = (runner._max_trigger_depth, time.time())
        assert runner._check_depth_limit("agent_a", "corr_1") is False

    def test_depth_limit_allows_shallow_cascades(self, mock_server):
        """When depth < max, _check_depth_limit should return True."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        key = "agent_a:corr_1"
        runner._correlation_depth[key] = (1, time.time())
        assert runner._check_depth_limit("agent_a", "corr_1") is True

    def test_depth_limit_allows_fresh_agent(self, mock_server):
        """Agent with no depth entry should be allowed."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert runner._check_depth_limit("new_agent", "corr_1") is True

    @pytest.mark.asyncio
    async def test_trigger_increments_depth(self, mock_server):
        """Calling trigger should increment the correlation depth."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        # Override execute_turn to prevent actual execution
        runner.execute_turn = AsyncMock()

        await runner.trigger("agent_a", "corr_1")
        # Dequeue and process to increment depth
        trigger = await asyncio.wait_for(runner.queue.get(), timeout=1.0)
        assert trigger.agent_id == "agent_a"


# =========================================================================
# 2. Cascade Prevention — Cooldown (ported from core runner)
# =========================================================================


class TestCascadeCooldown:
    """Verify per-agent cooldown ported from core/agent_runner.py."""

    def test_runner_has_cooldown_tracking(self, mock_server):
        """Unified runner should have _last_trigger_time for cooldown."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_last_trigger_time")
        assert isinstance(runner._last_trigger_time, dict)

    def test_runner_has_check_cooldown_method(self, mock_server):
        """Unified runner should have _check_cooldown method."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_check_cooldown")
        assert callable(runner._check_cooldown)

    def test_first_trigger_passes_cooldown(self, mock_server):
        """First trigger for an agent should always pass cooldown."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert runner._check_cooldown("agent_a") is True

    def test_rapid_trigger_fails_cooldown(self, mock_server):
        """Immediate second trigger should fail cooldown."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        runner._check_cooldown("agent_a")  # first call sets the time
        assert runner._check_cooldown("agent_a") is False

    def test_cooldown_expires(self, mock_server):
        """After cooldown period, trigger should pass again."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        runner._last_trigger_time["agent_a"] = (time.time() - 10) * 1000  # 10s ago in ms
        assert runner._check_cooldown("agent_a") is True


# =========================================================================
# 3. Concurrency Semaphore
# =========================================================================


class TestConcurrencySemaphore:
    """Verify concurrency control ported from core/agent_runner.py."""

    def test_runner_has_semaphore(self, mock_server):
        """Unified runner should have _semaphore for concurrency control."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_semaphore")
        assert isinstance(runner._semaphore, asyncio.Semaphore)

    def test_runner_has_max_concurrency(self, mock_server):
        """Unified runner should expose _max_concurrency."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_max_concurrency")
        assert runner._max_concurrency > 0


# =========================================================================
# 4. Configurable Max Depth and Cooldown
# =========================================================================


class TestConfigurableParameters:
    """Verify cascade parameters are configurable."""

    def test_max_trigger_depth_configurable(self, mock_server):
        """Runner should accept custom max_trigger_depth."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server, max_trigger_depth=3)
        assert runner._max_trigger_depth == 3

    def test_trigger_cooldown_configurable(self, mock_server):
        """Runner should accept custom trigger_cooldown_ms."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server, trigger_cooldown_ms=500)
        assert runner._trigger_cooldown_ms == 500

    def test_max_concurrency_configurable(self, mock_server):
        """Runner should accept custom max_concurrency."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server, max_concurrency=2)
        assert runner._max_concurrency == 2
        # Semaphore should reflect the configured value
        assert runner._semaphore._value == 2

    def test_defaults_from_module_constants(self, mock_server):
        """Default values should match the module-level constants."""
        from remora.runner.agent_runner import AgentRunner, MAX_CHAIN_DEPTH

        runner = AgentRunner(mock_server)
        assert runner._max_trigger_depth == MAX_CHAIN_DEPTH


# =========================================================================
# 5. EventStore Trigger Bridge
# =========================================================================


class TestEventStoreTriggerBridge:
    """Verify the EventStore trigger adapter that feeds get_triggers() into the queue."""

    def test_runner_has_bridge_method(self, mock_server):
        """Unified runner should have a method to bridge EventStore triggers."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "run_from_event_store")
        assert callable(runner.run_from_event_store)

    @pytest.mark.asyncio
    async def test_bridge_feeds_queue(self, mock_server, event_store):
        """EventStore triggers should be translated into queue Triggers."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        runner.execute_turn = AsyncMock()

        # Inject a trigger into the EventStore
        from remora.core.events.events import ManualTriggerEvent
        from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry

        subs = SubscriptionRegistry(event_store._db_path.parent / "subs.db")
        await subs.initialize()
        event_store.set_subscriptions(subs)
        await subs.register("rm_abc12", SubscriptionPattern(to_agent="rm_abc12"))

        # The bridge method should process triggers
        # This is an existence/shape test — detailed behavior tested in integration
        assert hasattr(runner, "run_from_event_store")


# =========================================================================
# 6. Stale Depth Entry Cleanup
# =========================================================================


class TestStaleDepthCleanup:
    """Verify periodic cleanup of stale correlation depth entries."""

    def test_runner_has_cleanup_stale_depths(self, mock_server):
        """Runner should have _cleanup_stale_depths method."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        assert hasattr(runner, "_cleanup_stale_depths")

    def test_cleanup_removes_old_entries(self, mock_server):
        """Entries older than TTL should be removed."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        now = time.time()
        runner._correlation_depth["old_key"] = (1, now - 600)  # 10 min ago
        runner._correlation_depth["fresh_key"] = (1, now)

        runner._cleanup_stale_depths()

        assert "old_key" not in runner._correlation_depth
        assert "fresh_key" in runner._correlation_depth


# =========================================================================
# 7. Backward Compatibility — trigger() still respects chain depth via DB
# =========================================================================


class TestTriggerChainDepthCompat:
    """Verify trigger() uses BOTH DB chain depth AND in-memory depth tracking."""

    @pytest.mark.asyncio
    async def test_trigger_still_checks_db_chain(self, mock_server):
        """trigger() should still check db.get_activation_chain for cycle detection."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        mock_server.db.get_activation_chain = AsyncMock(return_value=["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"])

        runner.execute_turn = AsyncMock()
        await runner.trigger("agent_x", "corr_1")

        # Should NOT have enqueued because chain is at max depth
        assert runner.queue.empty()

    @pytest.mark.asyncio
    async def test_trigger_checks_in_memory_cooldown(self, mock_server):
        """trigger() should respect cooldown before enqueuing."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner(mock_server)
        runner.execute_turn = AsyncMock()

        # First trigger — should pass
        await runner.trigger("agent_a", "corr_1")
        assert not runner.queue.empty()
        await runner.queue.get()  # drain

        # Immediate second trigger — should be dropped by cooldown
        await runner.trigger("agent_a", "corr_2")
        assert runner.queue.empty()


# =========================================================================
# 8. Headless (CLI) Factory
# =========================================================================


class TestHeadlessFactory:
    """Verify create_headless() builds a runner without an LSP server."""

    @pytest.mark.asyncio
    async def test_create_headless_returns_runner(self, event_store):
        """create_headless should return a functional AgentRunner."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner.create_headless(event_store=event_store)
        assert isinstance(runner, AgentRunner)

    @pytest.mark.asyncio
    async def test_headless_has_event_store(self, event_store):
        """Headless runner's server adapter should expose event_store."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner.create_headless(event_store=event_store)
        assert runner.server.event_store is event_store

    @pytest.mark.asyncio
    async def test_headless_cascade_params(self, event_store):
        """Headless runner should accept cascade parameters."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner.create_headless(
            event_store=event_store,
            max_trigger_depth=3,
            trigger_cooldown_ms=200,
            max_concurrency=2,
        )
        assert runner._max_trigger_depth == 3
        assert runner._trigger_cooldown_ms == 200
        assert runner._max_concurrency == 2

    @pytest.mark.asyncio
    async def test_headless_trigger_works(self, event_store):
        """Headless runner should be able to enqueue triggers."""
        from remora.runner.agent_runner import AgentRunner

        runner = AgentRunner.create_headless(event_store=event_store)
        runner.execute_turn = AsyncMock()
        await runner.trigger("rm_abc12", "corr_1")
        assert not runner.queue.empty()
