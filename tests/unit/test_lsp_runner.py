"""Tests for LSP runner using EventStore+AgentNode instead of RemoraDB+ASTAgentNode."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.projections import NodeProjection


def _make_agent_node(**overrides: Any) -> AgentNode:
    """Create a minimal AgentNode for tests."""
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
    """Create an EventStore with NodeProjection for tests."""
    es = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await es.initialize()
    # Insert a test node directly
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
    """Create a mock server with event_store set."""
    server = MagicMock()
    server.event_store = event_store
    server.db = MagicMock()
    server.db.get_activation_chain = AsyncMock(return_value=[])
    server.db.add_to_chain = AsyncMock()
    server.db.set_status = AsyncMock()
    server.db.store_proposal = AsyncMock()
    server.db.update_proposal_status = AsyncMock()
    server.proposals = {}
    server.generate_correlation_id = MagicMock(return_value="corr_1_test")
    server.workspace = MagicMock()
    server.workspace.root_path = "/tmp/test_project"
    server.subscriptions = None
    return server


@pytest.fixture
def runner(mock_server: MagicMock):
    """Create an AgentRunner with the mock server."""
    from remora.lsp.runner import AgentRunner

    return AgentRunner(mock_server)


class TestDispatchCommand:
    """Test _dispatch_command uses EventStore for node lookup."""

    @pytest.mark.asyncio
    async def test_execute_tool_uses_event_store(self, runner, mock_server, event_store):
        """execute_tool command should get node from EventStore, not RemoraDB."""
        cmd = {
            "id": 1,
            "command_type": "execute_tool",
            "agent_id": "rm_abc12",
            "payload": '{"tool_name": "test_tool", "params": {}}',
        }

        with patch("remora.lsp.runner.AgentRunner.execute_extension_tool", new_callable=AsyncMock) as mock_ext:
            await runner._dispatch_command(cmd)

            mock_ext.assert_called_once()
            agent_arg = mock_ext.call_args[0][0]
            # Should be an AgentNode, not ASTAgentNode
            assert isinstance(agent_arg, AgentNode)
            assert agent_arg.node_id == "rm_abc12"

        # RemoraDB.get_node should NOT be called
        mock_server.db.get_node.assert_not_called()


class TestExecuteTurn:
    """Test execute_turn uses EventStore for node operations."""

    @pytest.mark.asyncio
    async def test_sets_status_via_event_store(self, runner, event_store):
        """execute_turn should use event_store.set_node_status, not db.set_status."""
        from remora.core.execution import ExecutionResult
        from remora.lsp.runner import Trigger

        trigger = Trigger(agent_id="rm_abc12", correlation_id="corr_1")

        with (
            patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock),
            patch("remora.lsp.server.emit_event", new_callable=AsyncMock),
            patch(
                "remora.lsp.runner.execute_agent_turn",
                new_callable=AsyncMock,
                return_value=ExecutionResult(response_text="ok", kernel_events=[]),
            ),
        ):
            await runner.execute_turn(trigger)

        # Status should have been set to "running" then back to "idle"
        node = await event_store.get_node("rm_abc12")
        assert node is not None
        assert node.status == "idle"  # After finally block resets to idle

    @pytest.mark.asyncio
    async def test_gets_node_from_event_store(self, runner, mock_server, event_store):
        """execute_turn should get node from EventStore, not RemoraDB."""
        from remora.core.execution import ExecutionResult
        from remora.lsp.runner import Trigger

        trigger = Trigger(agent_id="rm_abc12", correlation_id="corr_1")

        with (
            patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock),
            patch("remora.lsp.server.emit_event", new_callable=AsyncMock),
            patch(
                "remora.lsp.runner.execute_agent_turn",
                new_callable=AsyncMock,
                return_value=ExecutionResult(response_text="ok", kernel_events=[]),
            ),
        ):
            await runner.execute_turn(trigger)

        # RemoraDB.get_node should NOT be called
        mock_server.db.get_node.assert_not_called()


class TestApplyExtensions:
    """Test apply_extensions uses core AgentExtension."""

    def test_applies_extension_data(self, runner):
        """apply_extensions should use core load_extensions + AgentExtension."""
        from remora.extensions import AgentExtension

        class TestExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return node_type == "function"

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "custom_system_prompt": "You are a test agent.",
                    "extension_name": "test_ext",
                }

        agent = _make_agent_node()

        with patch("remora.lsp.runner.load_extensions", return_value=[TestExt]):
            result = runner.apply_extensions(agent)

        assert result.custom_system_prompt == "You are a test agent."
        assert result.extension_name == "test_ext"

    def test_no_extension_match(self, runner):
        """apply_extensions with no matches should return agent unchanged."""
        agent = _make_agent_node()

        with patch("remora.lsp.runner.load_extensions", return_value=[]):
            result = runner.apply_extensions(agent)

        assert result.custom_system_prompt == ""
        assert result.extension_name is None


class TestRefreshCodeLens:
    """Test refresh_code_lens uses EventStore."""

    @pytest.mark.asyncio
    async def test_uses_event_store(self, runner, mock_server, event_store):
        """refresh_code_lens should query EventStore, not RemoraDB."""
        with patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock) as mock_refresh:
            await runner.refresh_code_lens("rm_abc12")

        mock_refresh.assert_called_once()
        mock_server.db.get_node.assert_not_called()
