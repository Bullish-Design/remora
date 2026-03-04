"""Tests for notifications.py — verifies it reads from EventStore and uses debounce."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from remora.core.agent_node import AgentNode
from tests.unit.conftest import make_node as _make_node


@pytest.fixture()
def mock_server():
    """Create a mock server with event_store and db."""
    with patch("remora.lsp.notifications.server") as srv:
        srv.event_store = AsyncMock()
        srv.db = AsyncMock()
        yield srv


@pytest.mark.asyncio()
async def test_cursor_moved_reads_from_event_store(mock_server):
    """on_cursor_moved should call event_store.get_node_at_position, not db."""
    node = _make_node()
    mock_server.event_store.get_node_at_position = AsyncMock(return_value=node)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved({"uri": "/tmp/test.py", "line": 15})

    mock_server.event_store.get_node_at_position.assert_awaited_once_with("/tmp/test.py", 15)
    # After Workstream D, on_cursor_moved delegates to schedule_cursor_update (debounced)
    # instead of calling db.update_cursor_focus directly.
    mock_server.schedule_cursor_update.assert_called_once_with(node.node_id, "/tmp/test.py", 15, delay_ms=200)
    # Must NOT have called db methods directly
    mock_server.db.update_cursor_focus.assert_not_awaited()
    mock_server.db.get_node_at_position.assert_not_awaited()


@pytest.mark.asyncio()
async def test_cursor_moved_no_node_found(mock_server):
    """When no node found, agent_id should be None."""
    mock_server.event_store.get_node_at_position = AsyncMock(return_value=None)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved({"uri": "/tmp/test.py", "line": 5})

    mock_server.event_store.get_node_at_position.assert_awaited_once_with("/tmp/test.py", 5)
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
    mock_server.event_store.get_node_at_position = AsyncMock(return_value=node)

    from remora.lsp.notifications import on_cursor_moved

    await on_cursor_moved({"uri": "/tmp/test.py", "line": 3})

    # The agent_id passed to schedule_cursor_update should be node.node_id
    mock_server.schedule_cursor_update.assert_called_once_with("rm_xyz789", "/tmp/test.py", 3, delay_ms=200)
