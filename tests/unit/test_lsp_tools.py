"""Tests for LSP tool classes (rewrite_self, message_node, read_node).

These tools follow the same interface as SwarmTool:
- schema property returns ToolSchema
- execute(arguments, context) returns ToolResult
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.projections import NodeProjection
from remora.lsp.tools import (
    ReadNodeTool,
    RewriteSelfTool,
    MessageNodeTool,
    build_lsp_tools,
)


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


@pytest.fixture
async def event_store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await es.initialize()
    # Insert a target node for read_node tests
    target = _make_agent(node_id="rm_target", name="bar", source_code="def bar(): pass")
    row = target.to_row()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    es._conn.execute(
        f"INSERT INTO nodes ({cols}) VALUES ({placeholders})",
        list(row.values()),
    )
    es._conn.commit()
    yield es
    await es.close()


# =========================================================================
# 1. RewriteSelfTool
# =========================================================================


class TestRewriteSelfTool:
    """Verify RewriteSelfTool creates proposals via callback."""

    def test_schema_name(self):
        agent = _make_agent()
        tool = RewriteSelfTool(agent, create_proposal=AsyncMock())
        assert tool.schema.name == "rewrite_self"

    def test_schema_has_new_source_param(self):
        agent = _make_agent()
        tool = RewriteSelfTool(agent, create_proposal=AsyncMock())
        params = tool.schema.parameters
        assert "new_source" in params["properties"]
        assert "new_source" in params["required"]

    @pytest.mark.asyncio
    async def test_execute_calls_create_proposal(self):
        agent = _make_agent()
        mock_create = AsyncMock()
        tool = RewriteSelfTool(agent, create_proposal=mock_create)

        result = await tool.execute({"new_source": "def foo():\n    return 2\n"}, None)

        assert not result.is_error
        mock_create.assert_called_once_with(agent, "def foo():\n    return 2\n", "rm_test1")

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        agent = _make_agent()
        mock_create = AsyncMock(side_effect=RuntimeError("proposal failed"))
        tool = RewriteSelfTool(agent, create_proposal=mock_create)

        result = await tool.execute({"new_source": "x = 1"}, None)

        assert result.is_error
        assert "proposal failed" in result.output

    @pytest.mark.asyncio
    async def test_execute_with_emit_tool_event(self):
        agent = _make_agent()
        mock_create = AsyncMock()
        mock_emit = AsyncMock()
        tool = RewriteSelfTool(agent, create_proposal=mock_create, emit_tool_event=mock_emit)

        await tool.execute({"new_source": "x = 1"}, None)

        mock_emit.assert_called_once()
        call_args = mock_emit.call_args[0]
        assert call_args[0] == "rm_test1"  # agent_id
        assert call_args[1] == "rewrite_self"  # summary


# =========================================================================
# 2. MessageNodeTool
# =========================================================================


class TestMessageNodeTool:
    """Verify MessageNodeTool sends messages via callback."""

    def test_schema_name(self):
        agent = _make_agent()
        tool = MessageNodeTool(agent, message_node=AsyncMock())
        assert tool.schema.name == "message_node"

    def test_schema_has_required_params(self):
        agent = _make_agent()
        tool = MessageNodeTool(agent, message_node=AsyncMock())
        params = tool.schema.parameters
        assert "target_id" in params["properties"]
        assert "message" in params["properties"]
        assert "target_id" in params["required"]
        assert "message" in params["required"]

    @pytest.mark.asyncio
    async def test_execute_calls_message_node(self):
        agent = _make_agent()
        mock_msg = AsyncMock()
        tool = MessageNodeTool(agent, message_node=mock_msg)

        result = await tool.execute({"target_id": "rm_other", "message": "hello"}, None)

        assert not result.is_error
        mock_msg.assert_called_once_with("rm_test1", "rm_other", "hello", "")

    @pytest.mark.asyncio
    async def test_parent_resolution(self):
        agent = _make_agent(parent_id="rm_parent")
        mock_msg = AsyncMock()
        tool = MessageNodeTool(agent, message_node=mock_msg)

        result = await tool.execute({"target_id": "parent", "message": "hi"}, None)

        assert not result.is_error
        mock_msg.assert_called_once_with("rm_test1", "rm_parent", "hi", "")

    @pytest.mark.asyncio
    async def test_unresolved_parent_returns_error(self):
        agent = _make_agent(parent_id=None)
        mock_msg = AsyncMock()
        tool = MessageNodeTool(agent, message_node=mock_msg)

        result = await tool.execute({"target_id": "parent", "message": "hi"}, None)

        assert result.is_error
        assert "Cannot resolve" in result.output
        mock_msg.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_error_handling(self):
        agent = _make_agent()
        mock_msg = AsyncMock(side_effect=RuntimeError("send failed"))
        tool = MessageNodeTool(agent, message_node=mock_msg)

        result = await tool.execute({"target_id": "rm_other", "message": "hi"}, None)

        assert result.is_error
        assert "send failed" in result.output


# =========================================================================
# 3. ReadNodeTool
# =========================================================================


class TestReadNodeTool:
    """Verify ReadNodeTool reads node source from EventStore."""

    @pytest.mark.asyncio
    async def test_read_existing_node(self, event_store):
        agent = _make_agent()
        tool = ReadNodeTool(agent, event_store)

        result = await tool.execute({"target_id": "rm_target"}, None)

        assert not result.is_error
        parsed = json.loads(result.output)
        assert parsed["name"] == "bar"
        assert "def bar()" in parsed["source"]

    @pytest.mark.asyncio
    async def test_read_missing_node(self, event_store):
        agent = _make_agent()
        tool = ReadNodeTool(agent, event_store)

        result = await tool.execute({"target_id": "rm_nonexistent"}, None)

        assert result.is_error
        assert "not found" in result.output

    @pytest.mark.asyncio
    async def test_parent_resolution(self, event_store):
        agent = _make_agent(parent_id="rm_target")
        tool = ReadNodeTool(agent, event_store)

        result = await tool.execute({"target_id": "parent"}, None)

        assert not result.is_error
        parsed = json.loads(result.output)
        assert parsed["name"] == "bar"

    def test_schema_name(self, event_store):
        # event_store fixture not needed for schema test but required by fixture
        agent = _make_agent()
        mock_es = MagicMock()
        tool = ReadNodeTool(agent, mock_es)
        assert tool.schema.name == "read_node"

    def test_schema_has_target_id_param(self):
        agent = _make_agent()
        mock_es = MagicMock()
        tool = ReadNodeTool(agent, mock_es)
        params = tool.schema.parameters
        assert "target_id" in params["properties"]
        assert "target_id" in params["required"]


# =========================================================================
# 4. build_lsp_tools
# =========================================================================


class TestBuildLspTools:
    """Verify build_lsp_tools factory function."""

    def test_returns_three_tools(self):
        agent = _make_agent()
        mock_es = MagicMock()
        tools = build_lsp_tools(
            agent,
            mock_es,
            create_proposal=AsyncMock(),
            message_node=AsyncMock(),
        )
        assert len(tools) == 3

    def test_tool_names(self):
        agent = _make_agent()
        mock_es = MagicMock()
        tools = build_lsp_tools(
            agent,
            mock_es,
            create_proposal=AsyncMock(),
            message_node=AsyncMock(),
        )
        names = {t.schema.name for t in tools}
        assert names == {"rewrite_self", "message_node", "read_node"}

    def test_emit_tool_event_passed_through(self):
        agent = _make_agent()
        mock_es = MagicMock()
        mock_emit = AsyncMock()
        tools = build_lsp_tools(
            agent,
            mock_es,
            create_proposal=AsyncMock(),
            message_node=AsyncMock(),
            emit_tool_event=mock_emit,
        )
        # All tools should have the emit callback
        for tool in tools:
            assert tool._emit_tool_event is mock_emit
