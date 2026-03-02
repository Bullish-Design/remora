"""TDD tests for 6.4: Typed externals protocol (AgentContext).

Verifies:
- AgentContext is a Pydantic BaseModel (not a dict)
- All required fields are typed (agent_id, correlation_id, callbacks)
- Cairn externals stored in typed field
- as_externals() returns a flat dict for backward compat with Grail
- SwarmTool classes accept AgentContext instead of dict[str, Any]
- build_swarm_tools accepts AgentContext
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import BaseModel


class TestAgentContextModel:
    """AgentContext must be a typed Pydantic model."""

    def test_is_pydantic(self):
        from remora.core.agent_context import AgentContext

        assert issubclass(AgentContext, BaseModel), "AgentContext must be a Pydantic BaseModel"

    def test_required_fields(self):
        from remora.core.agent_context import AgentContext

        fields = AgentContext.model_fields
        assert "agent_id" in fields
        assert "correlation_id" in fields
        assert "emit_event" in fields
        assert "register_subscription" in fields
        assert "unsubscribe_subscription" in fields
        assert "broadcast" in fields
        assert "query_agents" in fields

    def test_cairn_externals_field(self):
        """AgentContext should carry Cairn file-system externals."""
        from remora.core.agent_context import AgentContext

        fields = AgentContext.model_fields
        assert "cairn_externals" in fields

    def test_construct_with_all_fields(self):
        from remora.core.agent_context import AgentContext

        emit = AsyncMock()
        register = AsyncMock()
        unsub = AsyncMock()
        bcast = AsyncMock()
        query = AsyncMock()

        ctx = AgentContext(
            agent_id="test-agent",
            correlation_id="corr-123",
            emit_event=emit,
            register_subscription=register,
            unsubscribe_subscription=unsub,
            broadcast=bcast,
            query_agents=query,
            cairn_externals={"read_file": AsyncMock()},
        )
        assert ctx.agent_id == "test-agent"
        assert ctx.correlation_id == "corr-123"
        assert ctx.emit_event is emit

    def test_correlation_id_optional(self):
        """correlation_id should default to None."""
        from remora.core.agent_context import AgentContext

        ctx = AgentContext(
            agent_id="a",
            emit_event=AsyncMock(),
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        assert ctx.correlation_id is None

    def test_cairn_externals_default_empty(self):
        """cairn_externals should default to empty dict."""
        from remora.core.agent_context import AgentContext

        ctx = AgentContext(
            agent_id="a",
            emit_event=AsyncMock(),
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        assert ctx.cairn_externals == {}


class TestAgentContextAsExternals:
    """as_externals() must return flat dict for backward compat."""

    def test_as_externals_returns_dict(self):
        from remora.core.agent_context import AgentContext

        emit = AsyncMock()
        ctx = AgentContext(
            agent_id="a",
            emit_event=emit,
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
            cairn_externals={"read_file": AsyncMock(), "write_file": AsyncMock()},
        )
        ext = ctx.as_externals()
        assert isinstance(ext, dict)
        # Contains swarm keys
        assert ext["agent_id"] == "a"
        assert ext["emit_event"] is emit
        assert "register_subscription" in ext
        assert "unsubscribe_subscription" in ext
        assert "broadcast" in ext
        assert "query_agents" in ext
        # Contains cairn keys
        assert "read_file" in ext
        assert "write_file" in ext

    def test_as_externals_includes_correlation_id(self):
        from remora.core.agent_context import AgentContext

        ctx = AgentContext(
            agent_id="a",
            correlation_id="c-1",
            emit_event=AsyncMock(),
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        ext = ctx.as_externals()
        assert ext["correlation_id"] == "c-1"


class TestSwarmToolsAcceptContext:
    """Swarm tools must accept AgentContext."""

    def test_build_swarm_tools_with_context(self):
        from remora.core.agent_context import AgentContext
        from remora.core.tools.swarm import build_swarm_tools

        ctx = AgentContext(
            agent_id="a",
            emit_event=AsyncMock(),
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        tools = build_swarm_tools(ctx)
        assert len(tools) == 5

    def test_send_message_tool_uses_context(self):
        from remora.core.agent_context import AgentContext
        from remora.core.tools.swarm import SendMessageTool

        ctx = AgentContext(
            agent_id="sender",
            emit_event=AsyncMock(),
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        tool = SendMessageTool(ctx)
        assert tool._context.agent_id == "sender"

    async def test_send_message_executes(self):
        from remora.core.agent_context import AgentContext
        from remora.core.tools.swarm import SendMessageTool

        emit = AsyncMock()
        ctx = AgentContext(
            agent_id="sender",
            correlation_id="c-1",
            emit_event=emit,
            register_subscription=AsyncMock(),
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        tool = SendMessageTool(ctx)
        result = await tool.execute(
            {"to_agent": "receiver", "content": "hello"},
            None,
        )
        assert not result.is_error
        emit.assert_called_once()


class TestSwarmExecutorBuildsContext:
    """SwarmExecutor should build AgentContext (not raw dict)."""

    def test_agent_context_importable_from_core(self):
        """AgentContext should be importable from remora.core."""
        from remora.core import AgentContext  # noqa: F401
