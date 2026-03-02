"""Deeper tests for AgentRunner — execute_turn, handle_response, tool loop.

Covers:
- execute_turn flow (success, missing node, no LLM, executor path)
- handle_response routing (rewrite_self, message_node, read_node, text-only, unknown)
- _extract_text_tool_calls (Qwen XML tags)
- get_agent_tools (base tools + extra_tools)
- Tool call loop (multi-round LLM↔tool until text response)
- create_proposal (proposal creation and storage)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agent_node import AgentNode, ToolSchema
from remora.lsp.runner import AgentRunner, LLMResponse, ToolCall, Trigger


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
    server.db = MagicMock()
    server.db.get_activation_chain = AsyncMock(return_value=[])
    server.db.add_to_chain = AsyncMock()
    server.db.store_proposal = AsyncMock()
    server.proposals = {}
    server.generate_correlation_id = MagicMock(return_value="corr_test")
    return server


# =========================================================================
# 1. _extract_text_tool_calls — Qwen XML tag extraction
# =========================================================================


class TestExtractTextToolCalls:
    """Verify extraction of tool calls from <tool_call> XML tags."""

    def test_single_tool_call(self):
        content = '<tool_call>\n{"name": "rewrite_self", "arguments": {"new_source": "x = 1"}}\n</tool_call>'
        calls = AgentRunner._extract_text_tool_calls(content)
        assert len(calls) == 1
        assert calls[0].name == "rewrite_self"
        assert calls[0].arguments == {"new_source": "x = 1"}

    def test_multiple_tool_calls(self):
        content = (
            '<tool_call>{"name": "read_node", "arguments": {"target_id": "a"}}</tool_call>'
            " some text "
            '<tool_call>{"name": "read_node", "arguments": {"target_id": "b"}}</tool_call>'
        )
        calls = AgentRunner._extract_text_tool_calls(content)
        assert len(calls) == 2
        assert calls[0].arguments["target_id"] == "a"
        assert calls[1].arguments["target_id"] == "b"

    def test_no_tool_calls(self):
        content = "Just a plain text response with no tool calls."
        calls = AgentRunner._extract_text_tool_calls(content)
        assert calls == []

    def test_malformed_json_skipped(self):
        content = "<tool_call>not valid json</tool_call>"
        calls = AgentRunner._extract_text_tool_calls(content)
        assert calls == []

    def test_missing_name_skipped(self):
        content = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
        calls = AgentRunner._extract_text_tool_calls(content)
        assert calls == []

    def test_string_arguments_parsed(self):
        content = '<tool_call>{"name": "rewrite_self", "arguments": "{\\"new_source\\": \\"y = 2\\"}"}</tool_call>'
        calls = AgentRunner._extract_text_tool_calls(content)
        assert len(calls) == 1
        assert calls[0].arguments == {"new_source": "y = 2"}


# =========================================================================
# 2. get_agent_tools — base tools + extra tools
# =========================================================================


class TestGetAgentTools:
    """Verify tool list generation for an agent."""

    def test_base_tools_present(self):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        tools = runner.get_agent_tools(agent)
        tool_names = [t["function"]["name"] for t in tools]
        assert "rewrite_self" in tool_names
        assert "message_node" in tool_names
        assert "read_node" in tool_names

    def test_base_tools_count(self):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        tools = runner.get_agent_tools(agent)
        assert len(tools) == 3  # rewrite_self, message_node, read_node

    def test_extra_tools_included(self):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        extra = ToolSchema(
            name="custom_tool",
            description="A custom tool",
            parameters={"type": "object", "properties": {}},
        )
        agent = _make_agent(extra_tools=[extra])
        tools = runner.get_agent_tools(agent)
        assert len(tools) == 4
        tool_names = [t["function"]["name"] for t in tools]
        assert "custom_tool" in tool_names

    def test_tool_schema_format(self):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        tools = runner.get_agent_tools(agent)
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "description" in tool["function"]
            assert "parameters" in tool["function"]


# =========================================================================
# 3. handle_response — text-only response
# =========================================================================


class TestHandleResponseTextOnly:
    """Verify handle_response with text-only LLM response."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_text_response_emits_event(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(content="I analyzed the code.", tool_calls=[])

        result = await runner.handle_response(agent, response, "corr_1")

        assert result == []
        mock_emit.assert_called_once()
        emitted = mock_emit.call_args[0][0]
        assert emitted.event_type == "AgentTextResponse"
        assert emitted.payload["content"] == "I analyzed the code."

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_empty_content_no_event(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(content=None, tool_calls=[])

        result = await runner.handle_response(agent, response, "corr_1")

        assert result == []
        mock_emit.assert_not_called()

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_empty_string_content_no_event(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(content="", tool_calls=[])

        result = await runner.handle_response(agent, response, "corr_1")

        assert result == []
        mock_emit.assert_not_called()


# =========================================================================
# 4. handle_response — rewrite_self tool call
# =========================================================================


class TestHandleResponseRewriteSelf:
    """Verify handle_response routes rewrite_self to create_proposal."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_rewrite_self_creates_proposal(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="rewrite_self", arguments={"new_source": "def foo():\n    return 2\n"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        # rewrite_self is side-effect only — returns empty (no tool results to feed back)
        assert result == []
        # Proposal should be stored on server
        assert len(server.proposals) == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_rewrite_self_emits_tool_result_event(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="rewrite_self", arguments={"new_source": "x = 1"})],
        )

        await runner.handle_response(agent, response, "corr_1")

        # Should emit RewriteProposalEvent + ToolResultEvent
        tool_result_calls = [c for c in mock_emit.call_args_list if c[0][0].event_type == "ToolResultEvent"]
        assert len(tool_result_calls) == 1
        assert tool_result_calls[0][0][0].payload["tool_name"] == "rewrite_self"


# =========================================================================
# 5. handle_response — read_node tool call
# =========================================================================


class TestHandleResponseReadNode:
    """Verify handle_response routes read_node to EventStore lookup."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_read_node_found(self, mock_emit):
        server = _make_mock_server()
        target = _make_agent(node_id="rm_target", name="bar", source_code="def bar(): pass")
        server.event_store.get_node = AsyncMock(return_value=target)
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="read_node", arguments={"target_id": "rm_target"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        assert len(result) == 1
        assert result[0]["tool"] == "read_node"
        parsed = json.loads(result[0]["result"])
        assert parsed["name"] == "bar"
        assert "def bar()" in parsed["source"]

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_read_node_not_found(self, mock_emit):
        server = _make_mock_server()
        server.event_store.get_node = AsyncMock(return_value=None)
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="read_node", arguments={"target_id": "rm_missing"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        assert len(result) == 1
        assert "not found" in result[0]["result"]

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_read_node_parent_resolution(self, mock_emit):
        server = _make_mock_server()
        parent = _make_agent(node_id="rm_parent", name="Parent")
        server.event_store.get_node = AsyncMock(return_value=parent)
        runner = AgentRunner(server, llm=None)
        agent = _make_agent(parent_id="rm_parent")
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="read_node", arguments={"target_id": "parent"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        assert len(result) == 1
        # Should have resolved "parent" to the actual parent_id
        server.event_store.get_node.assert_called_with("rm_parent")


# =========================================================================
# 6. handle_response — message_node tool call
# =========================================================================


class TestHandleResponseMessageNode:
    """Verify handle_response routes message_node correctly."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_message_node_sends_and_triggers(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="message_node", arguments={"target_id": "rm_other", "message": "hello"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        # message_node is side-effect only
        assert result == []
        # Should emit AgentMessageEvent
        msg_calls = [c for c in mock_emit.call_args_list if hasattr(c[0][0], "to_agent")]
        assert len(msg_calls) == 1
        assert msg_calls[0][0][0].to_agent == "rm_other"

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_message_node_parent_resolution(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent(parent_id="rm_parent")
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="message_node", arguments={"target_id": "parent", "message": "hi"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        assert result == []
        msg_calls = [c for c in mock_emit.call_args_list if hasattr(c[0][0], "to_agent")]
        assert len(msg_calls) == 1
        assert msg_calls[0][0][0].to_agent == "rm_parent"

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_message_node_unresolved_parent_emits_error(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent(parent_id=None)  # No parent
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="message_node", arguments={"target_id": "parent", "message": "hi"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        assert result == []
        # Should emit error about unresolved target
        error_calls = [c for c in mock_emit.call_args_list if hasattr(c[0][0], "error")]
        assert len(error_calls) == 1


# =========================================================================
# 7. handle_response — unknown tool dispatched to extension
# =========================================================================


class TestHandleResponseUnknownTool:
    """Verify unknown tool calls are dispatched to execute_extension_tool."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_unknown_tool_dispatches_extension(self, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="custom_tool", arguments={"param": "value"})],
        )

        result = await runner.handle_response(agent, response, "corr_1")

        # Extension tools are side-effect only
        assert result == []
        # Should emit ToolResultEvent for custom_tool
        tool_calls = [
            c
            for c in mock_emit.call_args_list
            if c[0][0].event_type == "ToolResultEvent" and c[0][0].payload.get("tool_name") == "custom_tool"
        ]
        assert len(tool_calls) == 1


# =========================================================================
# 8. handle_response — text content with embedded tool calls (Qwen)
# =========================================================================


class TestHandleResponseTextToolCalls:
    """Verify handle_response extracts tool calls from text content."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_text_embedded_read_node(self, mock_emit):
        server = _make_mock_server()
        target = _make_agent(node_id="rm_target", name="bar", source_code="def bar(): pass")
        server.event_store.get_node = AsyncMock(return_value=target)
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()
        response = LLMResponse(
            content='Let me read that: <tool_call>{"name": "read_node", "arguments": {"target_id": "rm_target"}}</tool_call>',
            tool_calls=[],  # Empty structured tool calls
        )

        result = await runner.handle_response(agent, response, "corr_1")

        # Should have extracted the read_node call from text
        assert len(result) == 1
        assert result[0]["tool"] == "read_node"


# =========================================================================
# 9. execute_turn — main flow
# =========================================================================


class TestExecuteTurn:
    """Verify execute_turn orchestration."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_sets_running_then_idle(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="Done.", tool_calls=[]))
        runner = AgentRunner(server, llm=mock_llm)

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
        runner = AgentRunner(server, llm=None)

        trigger = Trigger(agent_id="rm_missing", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should have emitted error about missing node
        error_calls = [
            c
            for c in mock_emit.call_args_list
            if hasattr(c[0][0], "error") and "not found" in str(c[0][0].error).lower()
        ]
        assert len(error_calls) >= 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_no_llm_emits_error(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should emit error about no LLM
        error_calls = [
            c for c in mock_emit.call_args_list if hasattr(c[0][0], "error") and "llm" in str(c[0][0].error).lower()
        ]
        assert len(error_calls) >= 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_llm_exception_emits_error(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=RuntimeError("connection refused"))
        runner = AgentRunner(server, llm=mock_llm)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should emit error with exception message
        error_calls = [
            c
            for c in mock_emit.call_args_list
            if hasattr(c[0][0], "error") and "connection refused" in str(c[0][0].error)
        ]
        assert len(error_calls) >= 1
        # Should still reset to idle
        last_status = server.event_store.set_node_status.call_args_list[-1][0]
        assert last_status == ("rm_test1", "idle")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_adds_to_chain(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
        runner = AgentRunner(server, llm=mock_llm)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        server.db.add_to_chain.assert_called_once_with("corr_1", "rm_test1")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_includes_rejection_feedback(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="ok", tool_calls=[]))
        runner = AgentRunner(server, llm=mock_llm)

        trigger = Trigger(
            agent_id="rm_test1",
            correlation_id="corr_1",
            context={"rejection_feedback": "too many changes"},
        )
        await runner.execute_turn(trigger)

        # The messages sent to LLM should include rejection feedback
        call_args = mock_llm.chat.call_args
        messages = call_args[0][0]
        feedback_msgs = [
            m
            for m in messages
            if "rejection_feedback" in str(m.get("content", "")).lower()
            or "too many changes" in str(m.get("content", ""))
        ]
        assert len(feedback_msgs) >= 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_turn_executor_path(self, mock_emit, mock_refresh):
        """When executor is set, execute_turn delegates to executor.run_agent."""
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        mock_executor = MagicMock()
        mock_executor.run_agent = AsyncMock()
        runner.executor = mock_executor

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # _load_agent_state returns None by default, so run_agent won't be called
        # (because the `if state:` check fails)
        mock_executor.run_agent.assert_not_called()


# =========================================================================
# 10. Tool call loop — multi-round
# =========================================================================


class TestToolCallLoop:
    """Verify multi-round LLM↔tool loop in execute_turn."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_multi_round_read_then_text(self, mock_emit, mock_refresh):
        """LLM returns read_node first, then text response on second round."""
        server = _make_mock_server()
        target = _make_agent(node_id="rm_target", name="bar", source_code="def bar(): pass")
        server.event_store.get_node = AsyncMock(return_value=target)

        mock_llm = MagicMock()
        # Round 1: read_node tool call
        round1 = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="read_node", arguments={"target_id": "rm_target"})],
        )
        # Round 2: text response (no tool calls)
        round2 = LLMResponse(content="The function looks fine.", tool_calls=[])
        mock_llm.chat = AsyncMock(side_effect=[round1, round2])

        runner = AgentRunner(server, llm=mock_llm)
        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # LLM should have been called twice
        assert mock_llm.chat.call_count == 2
        # Second call should include tool result in messages
        second_call_messages = mock_llm.chat.call_args_list[1][0][0]
        tool_result_msgs = [m for m in second_call_messages if "Tool result" in m.get("content", "")]
        assert len(tool_result_msgs) == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_max_rounds_stops_loop(self, mock_emit, mock_refresh):
        """Loop should stop after MAX_TOOL_ROUNDS even if LLM keeps returning tool calls."""
        server = _make_mock_server()
        target = _make_agent(node_id="rm_target", name="bar", source_code="def bar(): pass")
        server.event_store.get_node = AsyncMock(return_value=target)

        mock_llm = MagicMock()
        # Always return a read_node tool call (never a text-only response)
        always_tool = LLMResponse(
            content=None,
            tool_calls=[ToolCall(name="read_node", arguments={"target_id": "rm_target"})],
        )
        mock_llm.chat = AsyncMock(return_value=always_tool)

        runner = AgentRunner(server, llm=mock_llm)
        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # Should stop after MAX_TOOL_ROUNDS (5)
        from remora.lsp.runner import MAX_TOOL_ROUNDS

        assert mock_llm.chat.call_count == MAX_TOOL_ROUNDS

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_side_effect_tool_ends_loop(self, mock_emit, mock_refresh):
        """rewrite_self returns no tool results, so the loop should end after one round."""
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(
            return_value=LLMResponse(
                content=None,
                tool_calls=[ToolCall(name="rewrite_self", arguments={"new_source": "x = 1"})],
            )
        )
        runner = AgentRunner(server, llm=mock_llm)
        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")

        with patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock):
            await runner.execute_turn(trigger)

        # Only one LLM call because rewrite_self returns empty tool_results
        assert mock_llm.chat.call_count == 1


# =========================================================================
# 11. create_proposal
# =========================================================================


class TestCreateProposal:
    """Verify proposal creation stores and emits correctly."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_stored_on_server(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
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
        runner = AgentRunner(server, llm=None)
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
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        server.event_store.set_node_status.assert_called_once_with("rm_test1", "pending_approval")

    @pytest.mark.asyncio
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    @patch("remora.lsp.server.publish_diagnostics", new_callable=AsyncMock)
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    async def test_proposal_publishes_diagnostics(self, mock_refresh, mock_diag, mock_emit):
        server = _make_mock_server()
        runner = AgentRunner(server, llm=None)
        agent = _make_agent()

        await runner.create_proposal(agent, "new code", "corr_1")

        mock_diag.assert_called_once()
        call_args = mock_diag.call_args[0]
        assert call_args[0] == "src/mod.py"  # file_path


# =========================================================================
# 12. Depth tracking in execute_turn
# =========================================================================


class TestExecuteTurnDepthTracking:
    """Verify depth tracking increments/decrements during execute_turn."""

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_depth_incremented_during_turn(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()

        depth_during_turn = []

        async def capture_depth(messages, tools):
            key = "rm_test1:corr_1"
            depth_during_turn.append(runner._correlation_depth.get(key, (0, 0)))
            return LLMResponse(content="done", tool_calls=[])

        mock_llm.chat = AsyncMock(side_effect=capture_depth)
        runner = AgentRunner(server, llm=mock_llm)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # During the LLM call, depth should be 1
        assert depth_during_turn[0][0] == 1

    @pytest.mark.asyncio
    @patch("remora.lsp.server.refresh_code_lenses", new_callable=AsyncMock)
    @patch("remora.lsp.server.emit_event", new_callable=AsyncMock)
    async def test_depth_decremented_after_turn(self, mock_emit, mock_refresh):
        server = _make_mock_server()
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=LLMResponse(content="done", tool_calls=[]))
        runner = AgentRunner(server, llm=mock_llm)

        trigger = Trigger(agent_id="rm_test1", correlation_id="corr_1")
        await runner.execute_turn(trigger)

        # After turn, depth entry should be cleaned up (was 1, decremented to 0 and removed)
        assert "rm_test1:corr_1" not in runner._correlation_depth
