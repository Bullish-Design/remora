"""Tests for AgentRunner — execute_turn, create_proposal, depth tracking.

After the Workstream B refactoring, the runner delegates actual agent execution
to ``execute_agent_turn()`` from ``remora.core.execution``.  Tests that
exercised the removed LLM loop / handle_response / get_agent_tools / ToolCall /
LLMResponse have been deleted.  The remaining tests verify the runner's own
responsibilities: status management, cascade tracking, error handling, proposal
creation, and chat-history assembly.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode
from remora.core.events import AgentCompleteEvent, AgentErrorEvent, AgentStartEvent, ContentChangedEvent
from remora.core.execution import ExecutionResult
from remora.lsp.runner import AgentRunner, Trigger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "rm_test1",
        "node_type": "function",
        "name": "foo",
        "full_name": "mod.foo",
        "file_path": "src/mod.py",
        "start_line": 1,
        "end_line": 5,
        "source_code": "def foo():\n    return 1\n",
        "source_hash": "abc",
        "status": "idle",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


def _make_mock_server() -> MagicMock:
    server = MagicMock()
    server.event_store = MagicMock()
    server.event_store.set_node_status = AsyncMock()
    server.event_store.get_node = AsyncMock(return_value=_make_agent())
    server.event_store.get_events_for_correlation = AsyncMock(return_value=[])
    server.event_store.append = AsyncMock(return_value=1)
    server.db = MagicMock()
    server.db.get_activation_chain = AsyncMock(return_value=[])
    server.db.add_to_chain = AsyncMock()
    server.db.store_proposal = AsyncMock()
    server.proposals = {}
    server.generate_correlation_id = MagicMock(return_value="corr_test")
    # workspace mock for project_root resolution
    server.workspace = MagicMock()
    server.workspace.root_path = "/tmp/test_project"
    # subscriptions
    server.subscriptions = None
    server.emit_event = AsyncMock()
    return server


_EXEC_PATCH = "remora.lsp.runner.execute_agent_turn"


def _ok_result(text: str = "Done.") -> ExecutionResult:
    return ExecutionResult(response_text=text, kernel_events=[])


# =========================================================================
# 1. execute_turn — main flow
# =========================================================================


class TestExecuteTurn:
    """Verify execute_turn orchestration (status, chain, error handling)."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_sets_running_then_idle(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should have set status to running, then back to idle
        status_calls = server.event_store.set_node_status.call_args_list
        assert status_calls[0][0] == ("rm_test1", "running")
        assert status_calls[-1][0] == ("rm_test1", "idle")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_missing_node_emits_error(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        server.event_store.get_node = AsyncMock(return_value=None)
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_missing", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # emit_error goes through server.emit_event (not module-level emit_event)
        error_calls = [
            c
            for c in server.emit_event.call_args_list
            if hasattr(c[0][0], "error") and "not found" in str(c[0][0].error).lower()
        ]
        assert len(error_calls) >= 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_execution_error_emits_error(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.side_effect = RuntimeError("connection refused")
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # emit_error goes through server.emit_event (not module-level emit_event)
        error_calls = [
            c
            for c in server.emit_event.call_args_list
            if hasattr(c[0][0], "error") and "connection refused" in str(c[0][0].error)
        ]
        assert len(error_calls) >= 1
        # Should still reset to idle
        last_status = server.event_store.set_node_status.call_args_list[-1][0]
        assert last_status == ("rm_test1", "idle")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_adds_to_chain(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        server.db.add_to_chain.assert_called_once_with("corr_1", "rm_test1")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_includes_rejection_feedback(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(
            agent_id="rm_test1",
            correlation_id="corr_1",
            context={"rejection_feedback": "too many changes"},
        )
        await runner.execute_turn(trigger)

        # execute_agent_turn should have been called with chat_history containing rejection
        call_kwargs = mock_exec.call_args[1]
        chat_history = call_kwargs.get("chat_history", [])
        feedback_msgs = [m for m in chat_history if "too many changes" in m.get("content", "")]
        assert len(feedback_msgs) >= 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_emits_text_response(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = _ok_result("Hello from the agent.")
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should emit AgentTextResponse event
        text_events = [
            c
            for c in mock_emit.call_args_list
            if c[0][0].event_type == "AgentTextResponse" and c[0][0].payload.get("content") == "Hello from the agent."
        ]
        assert len(text_events) == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_no_text_response_no_emit(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = ExecutionResult(response_text="", kernel_events=[])
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should NOT emit AgentTextResponse event for empty text
        text_events = [c for c in mock_emit.call_args_list if c[0][0].event_type == "AgentTextResponse"]
        assert len(text_events) == 0

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_turn_passes_extra_tools(self, mock_exec, mock_emit, mock_refresh):
        """execute_agent_turn is called with LSP tools in extra_tools."""
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        call_kwargs = mock_exec.call_args[1]
        extra_tools = call_kwargs.get("extra_tools", [])
        # Should have 3 LSP tools: rewrite_self, message_node, read_node
        assert len(extra_tools) == 3

    def test_no_executor_attribute(self):
        """After cleanup, AgentRunner should not have an executor attribute."""
        server = _make_mock_server()
        runner = AgentRunner(server)
        assert not hasattr(runner, "executor"), "Dead executor path should be removed"


# =========================================================================
# 2. create_proposal
# =========================================================================


class TestCreateProposal:
    """Verify proposal creation stores and emits correctly."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_stored_on_server(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        assert len(server.proposals) == 1
        proposal = list(server.proposals.values())[0]
        assert proposal.agent_id == "rm_test1"
        assert proposal.new_source == "new code"
        assert proposal.old_source == agent.source_code
        assert proposal.correlation_id == "corr_1"

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_emits_event(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        proposal_events = [c for c in mock_emit.call_args_list if c[0][0].event_type == "RewriteProposalEvent"]
        assert len(proposal_events) == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_sets_pending_approval(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        server.event_store.set_node_status.assert_called_once_with("rm_test1", "pending_approval")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_publishes_diagnostics(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        mock_diag.assert_called_once()
        call_args = mock_diag.call_args[0]
        assert call_args[0] == "src/mod.py"  # file_path


# =========================================================================
# 3. Depth tracking in execute_turn
# =========================================================================


class TestExecuteTurnDepthTracking:
    """Verify depth tracking increments/decrements during execute_turn."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_depth_incremented_during_turn(self, mock_exec, mock_emit, mock_refresh):
        server = _make_mock_server()
        depth_during_turn = []

        async def capture_depth(**kwargs):
            key = "rm_test1:corr_1"
            depth_during_turn.append(runner._correlation_depth.get(key, (0, 0)))
            return _ok_result()

        mock_exec.side_effect = capture_depth
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # During the execution call, depth should be 1
        assert depth_during_turn[0][0] == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_depth_decremented_after_turn(self, mock_exec, mock_emit, mock_refresh):
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # After turn, depth entry should be cleaned up (was 1, decremented to 0 and removed)
        assert "rm_test1:corr_1" not in runner._correlation_depth


# =========================================================================
# 4. AgentStartEvent / AgentCompleteEvent / AgentErrorEvent emission
# =========================================================================


class TestExecuteTurnEmitsDomainEvents:
    """Verify execute_turn emits AgentStartEvent/AgentCompleteEvent/AgentErrorEvent
    via event_store.append() so that NodeProjection populates last_trigger_event
    and last_completed_at (Workstream E — Gap #11)."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_emits_agent_start_event(self, mock_exec, mock_emit, mock_refresh):
        """execute_turn should append an AgentStartEvent before calling execute_agent_turn."""
        mock_exec.return_value = _ok_result()
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Find AgentStartEvent in event_store.append calls
        start_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentStartEvent)
        ]
        assert len(start_events) == 1
        event = start_events[0][0][1]
        assert event.agent_id == "rm_test1"
        assert event.node_name == "foo"

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_emits_agent_complete_event(self, mock_exec, mock_emit, mock_refresh):
        """execute_turn should append an AgentCompleteEvent after successful execution."""
        mock_exec.return_value = _ok_result("Agent completed successfully.")
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Find AgentCompleteEvent in event_store.append calls
        complete_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        event = complete_events[0][0][1]
        assert event.agent_id == "rm_test1"
        assert event.timestamp > 0
        assert event.tags == ()  # Default: no tags

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_emits_agent_error_event_on_failure(self, mock_exec, mock_emit, mock_refresh):
        """execute_turn should append an AgentErrorEvent when execution raises."""
        mock_exec.side_effect = RuntimeError("LLM timeout")
        server = _make_mock_server()
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Find AgentErrorEvent in event_store.append calls
        error_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentErrorEvent)
        ]
        assert len(error_events) == 1
        event = error_events[0][0][1]
        assert event.agent_id == "rm_test1"
        assert "LLM timeout" in event.error

        # Should NOT have emitted AgentCompleteEvent
        complete_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 0

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_start_event_emitted_before_execution(self, mock_exec, mock_emit, mock_refresh):
        """AgentStartEvent should be appended BEFORE execute_agent_turn is called."""
        call_order = []

        async def track_append(graph_id, event):
            call_order.append(("append", type(event).__name__))
            return 1

        async def track_exec(**kwargs):
            call_order.append(("exec",))
            return _ok_result()

        server = _make_mock_server()
        server.event_store.append = AsyncMock(side_effect=track_append)
        mock_exec.side_effect = track_exec
        runner = AgentRunner(server)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # AgentStartEvent should come before exec
        start_idx = next(i for i, c in enumerate(call_order) if c == ("append", "AgentStartEvent"))
        exec_idx = next(i for i, c in enumerate(call_order) if c == ("exec",))
        assert start_idx < exec_idx

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_scaffold_trigger_adds_scaffold_tag(self, mock_exec, mock_emit, mock_refresh):
        """When trigger carries a ScaffoldRequestEvent, AgentCompleteEvent should have tags=('scaffold',)."""
        from remora.core.events import ScaffoldRequestEvent

        mock_exec.return_value = _ok_result("Scaffolded.")
        server = _make_mock_server()
        runner = AgentRunner(server)

        scaffold_event = ScaffoldRequestEvent(
            node_id="rm_test1",
            to_agent="rm_test1",
            node_type="function",
        )
        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1", trigger_event=scaffold_event)
        await runner.execute_turn(trigger)

        complete_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0][0][1].tags == ("scaffold",)

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch(_EXEC_PATCH, new_callable=AsyncMock)
    async def test_non_scaffold_trigger_has_no_tags(self, mock_exec, mock_emit, mock_refresh):
        """When trigger carries a non-scaffold event, AgentCompleteEvent tags should be empty."""
        mock_exec.return_value = _ok_result("Done.")
        server = _make_mock_server()
        runner = AgentRunner(server)

        content_event = ContentChangedEvent(path="/src/foo.py")
        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1", trigger_event=content_event)
        await runner.execute_turn(trigger)

        complete_events = [
            call for call in server.event_store.append.call_args_list if isinstance(call[0][1], AgentCompleteEvent)
        ]
        assert len(complete_events) == 1
        assert complete_events[0][0][1].tags == ()


# =========================================================================
# 5. EventStore trigger bridge (Gap #1 — reactive loop closure)
# =========================================================================


class TestRunFromEventStore:
    """Verify run_from_event_store bridges subscription-matched triggers
    from EventStore._trigger_queue into the runner's asyncio.Queue."""

    @pytest.mark.asyncio
    async def test_bridges_triggers_to_runner(self):
        """run_from_event_store should call trigger() for each event from get_triggers()."""
        server = _make_mock_server()
        runner = AgentRunner(server, trigger_cooldown_ms=0)
        runner._running = True

        event = ContentChangedEvent(path="/src/foo.py")
        triggers_yielded = [(("agent_1", 1, event))]

        async def fake_get_triggers():
            for t in triggers_yielded:
                yield t

        mock_event_store = MagicMock()
        mock_event_store.get_triggers = fake_get_triggers

        # Run with a timeout to avoid hanging
        bridge_task = asyncio.create_task(runner.run_from_event_store(mock_event_store))
        await asyncio.sleep(0.1)
        runner._running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        # The trigger should have been enqueued
        assert not runner.queue.empty()
        trigger = runner.queue.get_nowait()
        assert trigger.agent_id == "agent_1"

    @pytest.mark.asyncio
    async def test_uses_event_correlation_id(self):
        """If the event has a correlation_id, it should be used."""
        server = _make_mock_server()
        runner = AgentRunner(server, trigger_cooldown_ms=0)
        runner._running = True

        event = MagicMock()
        event.correlation_id = "corr_from_event"

        async def fake_get_triggers():
            yield ("agent_1", 1, event)

        mock_event_store = MagicMock()
        mock_event_store.get_triggers = fake_get_triggers

        bridge_task = asyncio.create_task(runner.run_from_event_store(mock_event_store))
        await asyncio.sleep(0.1)
        runner._running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        trigger = runner.queue.get_nowait()
        assert trigger.correlation_id == "corr_from_event"

    @pytest.mark.asyncio
    async def test_generates_correlation_id_when_missing(self):
        """If the event lacks correlation_id, generate one."""
        server = _make_mock_server()
        runner = AgentRunner(server, trigger_cooldown_ms=0)
        runner._running = True

        event = ContentChangedEvent(path="/src/foo.py")

        async def fake_get_triggers():
            yield ("agent_1", 1, event)

        mock_event_store = MagicMock()
        mock_event_store.get_triggers = fake_get_triggers

        bridge_task = asyncio.create_task(runner.run_from_event_store(mock_event_store))
        await asyncio.sleep(0.1)
        runner._running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        trigger = runner.queue.get_nowait()
        assert trigger.correlation_id == "corr_test"  # from mock server

    @pytest.mark.asyncio
    async def test_cooldown_deduplicates(self):
        """If trigger() was called recently for same agent, subscription trigger is suppressed."""
        server = _make_mock_server()
        runner = AgentRunner(server, trigger_cooldown_ms=5000)
        runner._running = True

        # Manually trigger first — consumes cooldown
        await runner.trigger("agent_1", "manual_corr")

        event = ContentChangedEvent(path="/src/foo.py")

        async def fake_get_triggers():
            yield ("agent_1", 1, event)

        mock_event_store = MagicMock()
        mock_event_store.get_triggers = fake_get_triggers

        bridge_task = asyncio.create_task(runner.run_from_event_store(mock_event_store))
        await asyncio.sleep(0.1)
        runner._running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        # Only the manual trigger should be in the queue (subscription trigger suppressed)
        assert runner.queue.qsize() == 1
        trigger = runner.queue.get_nowait()
        assert trigger.correlation_id == "manual_corr"

    @pytest.mark.asyncio
    async def test_waits_for_running(self):
        """run_from_event_store should wait until _running is True."""
        server = _make_mock_server()
        runner = AgentRunner(server, trigger_cooldown_ms=0)
        # _running starts as False

        event = ContentChangedEvent(path="/src/foo.py")

        async def fake_get_triggers():
            yield ("agent_1", 1, event)

        mock_event_store = MagicMock()
        mock_event_store.get_triggers = fake_get_triggers

        bridge_task = asyncio.create_task(runner.run_from_event_store(mock_event_store))

        # Initially should not have consumed triggers (waiting for _running)
        await asyncio.sleep(0.15)
        assert runner.queue.empty()

        # Now set _running = True — should consume
        runner._running = True
        await asyncio.sleep(0.15)

        runner._running = False
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass

        assert not runner.queue.empty()
        trigger = runner.queue.get_nowait()
        assert trigger.agent_id == "agent_1"
