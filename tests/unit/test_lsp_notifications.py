"""Tests for notifications.py — verifies it reads from EventStore and uses debounce."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.unit.conftest import make_node as _make_node


@pytest.fixture()
def mock_server():
    """Create a mock server."""
    srv = MagicMock()
    srv.event_store = AsyncMock()
    srv.db = AsyncMock()
    srv.emit_event = AsyncMock()
    srv.bootstrap_runner = None
    return srv


@pytest.mark.asyncio()
async def test_cursor_moved_reads_from_event_store(mock_server):
    """on_cursor_moved should call event_store.get_node_at_position, not db."""
    node = _make_node()
    mock_server.event_store.nodes.get_node_at_position = AsyncMock(return_value=node)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved(mock_server, {"uri": "/tmp/test.py", "line": 15})

    mock_server.event_store.nodes.get_node_at_position.assert_awaited_once_with("/tmp/test.py", 15)
    # After Workstream D, on_cursor_moved delegates to schedule_cursor_update (debounced)
    # instead of calling db.update_cursor_focus directly.
    mock_server.schedule_cursor_update.assert_called_once_with(node.node_id, "/tmp/test.py", 15, delay_ms=200)
    # Must NOT have called db methods directly
    mock_server.db.update_cursor_focus.assert_not_awaited()
    mock_server.db.nodes.get_node_at_position.assert_not_awaited()


@pytest.mark.asyncio()
async def test_cursor_moved_no_node_found(mock_server):
    """When no node found, agent_id should be None."""
    mock_server.event_store.nodes.get_node_at_position = AsyncMock(return_value=None)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved(mock_server, {"uri": "/tmp/test.py", "line": 5})

    mock_server.event_store.nodes.get_node_at_position.assert_awaited_once_with("/tmp/test.py", 5)
    mock_server.schedule_cursor_update.assert_called_once_with(None, "/tmp/test.py", 5, delay_ms=200)


@pytest.mark.asyncio()
async def test_cursor_moved_uses_node_id_not_remora_id(mock_server):
    """Verify we access node.node_id (AgentNode attribute), not node['remora_id'] (dict)."""
    node = _make_node(
        node_id="rm_xyz789",
        name="other_func",
        full_name="test.other_func",
        start_line=1,
        end_line=5,
        source_code="def other_func(): pass",
    )
    mock_server.event_store.nodes.get_node_at_position = AsyncMock(return_value=node)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved(mock_server, {"uri": "/tmp/test.py", "line": 3})

    # The agent_id passed to schedule_cursor_update should be node.node_id
    mock_server.schedule_cursor_update.assert_called_once_with("rm_xyz789", "/tmp/test.py", 3, delay_ms=200)


@pytest.mark.asyncio()
async def test_input_submitted_emits_and_triggers_runner(mock_server):
    """Chat submit should emit HumanChatEvent then trigger runner."""
    mock_server.generate_correlation_id.return_value = "corr_test_1"
    mock_server.runner = AsyncMock()
    mock_server.runner.trigger = AsyncMock()

    from remora.lsp import notifications

    print("BEFORE", mock_server.emit_event.mock_calls)
    await notifications.on_input_submitted(mock_server, {"agent_id": "rm_agent", "input": "hello"})
    print("AFTER", mock_server.emit_event.mock_calls)

    mock_server.emit_event.assert_awaited_once()
    mock_server.runner.trigger.assert_awaited_once_with("rm_agent", "corr_test_1")


@pytest.mark.asyncio()
async def test_input_submitted_emit_timeout_skips_runner(
    mock_server: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
):
    """If emit_event stalls, handler should timeout and not trigger runner."""
    mock_server.generate_correlation_id.return_value = "corr_test_2"
    mock_server.runner = AsyncMock()
    mock_server.runner.trigger = AsyncMock()

    from remora.lsp import notifications

    monkeypatch.setattr(notifications, "SUBMIT_EMIT_EVENT_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(notifications, "SUBMIT_RUNNER_TRIGGER_TIMEOUT_SECONDS", 0.05)

    async def _slow_emit(_event):
        await __import__("asyncio").sleep(0.2)

    mock_server.emit_event.side_effect = _slow_emit
    await notifications.on_input_submitted(mock_server, {"agent_id": "rm_agent", "input": "hello"})

    mock_server.runner.trigger.assert_not_awaited()


@pytest.mark.asyncio()
async def test_input_submitted_request_id_routes_to_bootstrap_runner(mock_server):
    mock_server.bootstrap_runner = AsyncMock()
    mock_server.bootstrap_runner.handle_human_input_response = AsyncMock(return_value=True)

    from remora.lsp import notifications

    await notifications.on_input_submitted(
        mock_server,
        {
            "request_id": "req-1",
            "agent_id": "agent-app",
            "node_id": "module:src/app.py",
            "input": "Use caching.",
            "question": "How should this work?",
        },
    )

    mock_server.bootstrap_runner.handle_human_input_response.assert_awaited_once_with(
        agent_id="agent-app",
        node_id="module:src/app.py",
        request_id="req-1",
        response="Use caching.",
        question="How should this work?",
    )
    mock_server.emit_event.assert_not_awaited()


@pytest.mark.asyncio()
async def test_input_submitted_request_id_falls_back_to_human_input_event(mock_server):
    from remora.lsp import notifications

    await notifications.on_input_submitted(
        mock_server,
        {
            "request_id": "req-2",
            "input": "Return cached data.",
        },
    )

    mock_server.emit_event.assert_awaited_once()
    event = mock_server.emit_event.await_args.args[0]
    assert event.request_id == "req-2"
    assert event.response == "Return cached data."
