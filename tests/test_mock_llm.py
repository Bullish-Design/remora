"""Tests for the enhanced MockLLMClient."""

from __future__ import annotations

import pytest

from remora.lsp.runner import LLMResponse, ToolCall
from remora_demo.neovim.mock_llm import (
    MockContext,
    MockLLMClient,
    parse_context,
    ContentChangedAnalyzeScript,
    HumanChatScript,
    TestAgentUpdateScript,
    TestAgentToolFollowupScript,
    RejectionFeedbackScript,
    GenericToolFollowupScript,
)


# ---------------------------------------------------------------------------
# parse_context tests
# ---------------------------------------------------------------------------


class TestParseContext:
    def test_extracts_agent_name_from_system_prompt(self) -> None:
        msgs = [{"role": "system", "content": "You are the agent for `load_config`."}]
        ctx = parse_context(msgs)
        assert ctx.agent_name == "load_config"

    def test_extracts_node_type(self) -> None:
        msgs = [{"role": "system", "content": "node_type: function\nYou are the agent for `foo`."}]
        ctx = parse_context(msgs)
        assert ctx.agent_type == "function"

    def test_detects_test_function_extension(self) -> None:
        msgs = [{"role": "system", "content": "You are a test function agent. TestFunction extension."}]
        ctx = parse_context(msgs)
        assert ctx.extension_name == "TestFunction"

    def test_detects_package_init_extension(self) -> None:
        msgs = [{"role": "system", "content": "PackageInit. You represent __init__.py."}]
        ctx = parse_context(msgs)
        assert ctx.extension_name == "PackageInit"

    def test_counts_rounds(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
            {"role": "user", "content": "again"},
        ]
        ctx = parse_context(msgs)
        assert ctx.round_number == 1

    def test_detects_human_chat_trigger(self) -> None:
        msgs = [
            {"role": "system", "content": "You are the agent for `foo`."},
            {"role": "user", "content": "what do you do?"},
        ]
        ctx = parse_context(msgs)
        assert ctx.trigger_type == "human_chat"

    def test_detects_agent_message_trigger(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "[From load_config] Please update your tests."},
        ]
        ctx = parse_context(msgs)
        assert ctx.trigger_type == "agent_message"
        assert ctx.from_agent == "load_config"

    def test_detects_content_changed_trigger(self) -> None:
        msgs = [
            {"role": "system", "content": "You are the agent for `load_config`."},
            {"role": "user", "content": "The function has changed: timeout parameter added."},
        ]
        ctx = parse_context(msgs)
        assert ctx.trigger_type == "content_changed"

    def test_detects_rejection_trigger(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "[Feedback on rejected proposal] The test is wrong."},
        ]
        ctx = parse_context(msgs)
        assert ctx.trigger_type == "rejection"

    def test_detects_tool_followup_trigger(self) -> None:
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "[Tool result for read_node] def load_config(...):"},
        ]
        ctx = parse_context(msgs)
        assert ctx.trigger_type == "tool_followup"


# ---------------------------------------------------------------------------
# Script matching tests
# ---------------------------------------------------------------------------


class TestHumanChatScript:
    def test_matches_human_chat_round_0(self) -> None:
        script = HumanChatScript()
        ctx = MockContext(trigger_type="human_chat", round_number=0)
        assert script.matches(ctx)

    def test_does_not_match_round_1(self) -> None:
        script = HumanChatScript()
        ctx = MockContext(trigger_type="human_chat", round_number=1)
        assert not script.matches(ctx)

    def test_known_agent_gets_specific_response(self) -> None:
        script = HumanChatScript()
        ctx = MockContext(trigger_type="human_chat", round_number=0, agent_name="load_config")
        resp = script.respond(ctx)
        assert isinstance(resp, LLMResponse)
        assert "load_config" in resp.content
        assert resp.tool_calls == []

    def test_unknown_agent_gets_generic_response(self) -> None:
        script = HumanChatScript()
        ctx = MockContext(trigger_type="human_chat", round_number=0, agent_name="some_func")
        resp = script.respond(ctx)
        assert "some_func" in resp.content


class TestContentChangedAnalyzeScript:
    def test_matches_source_function_content_changed(self) -> None:
        script = ContentChangedAnalyzeScript()
        ctx = MockContext(
            extension_name="",
            agent_type="function",
            round_number=0,
            trigger_type="content_changed",
        )
        assert script.matches(ctx)

    def test_does_not_match_test_function(self) -> None:
        script = ContentChangedAnalyzeScript()
        ctx = MockContext(
            extension_name="TestFunction",
            agent_type="function",
            round_number=0,
            trigger_type="content_changed",
        )
        assert not script.matches(ctx)

    def test_does_not_match_human_chat(self) -> None:
        script = ContentChangedAnalyzeScript()
        ctx = MockContext(
            extension_name="",
            agent_type="function",
            round_number=0,
            trigger_type="human_chat",
        )
        assert not script.matches(ctx)

    def test_response_includes_message_node_tool_call(self) -> None:
        script = ContentChangedAnalyzeScript()
        ctx = MockContext(
            agent_name="load_config",
            agent_type="function",
            trigger_type="content_changed",
        )
        resp = script.respond(ctx)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "message_node"
        assert resp.tool_calls[0].arguments["target_id"] == "test_load_yaml"


class TestTestAgentUpdateScript:
    def test_matches_test_agent_message(self) -> None:
        script = TestAgentUpdateScript()
        ctx = MockContext(extension_name="TestFunction", trigger_type="agent_message")
        assert script.matches(ctx)

    def test_round_0_reads_source(self) -> None:
        script = TestAgentUpdateScript()
        ctx = MockContext(
            extension_name="TestFunction",
            trigger_type="agent_message",
            round_number=0,
        )
        resp = script.respond(ctx)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "read_node"

    def test_round_1_proposes_rewrite(self) -> None:
        script = TestAgentUpdateScript()
        ctx = MockContext(
            extension_name="TestFunction",
            trigger_type="agent_message",
            round_number=1,
        )
        resp = script.respond(ctx)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "rewrite_self"
        assert "test_load_yaml_with_timeout" in resp.tool_calls[0].arguments["new_source"]


class TestTestAgentToolFollowupScript:
    def test_matches_test_agent_tool_followup(self) -> None:
        script = TestAgentToolFollowupScript()
        ctx = MockContext(
            extension_name="TestFunction",
            trigger_type="tool_followup",
            round_number=1,
        )
        assert script.matches(ctx)

    def test_response_proposes_rewrite(self) -> None:
        script = TestAgentToolFollowupScript()
        ctx = MockContext(
            extension_name="TestFunction",
            trigger_type="tool_followup",
            round_number=1,
        )
        resp = script.respond(ctx)
        assert resp.tool_calls[0].name == "rewrite_self"


class TestRejectionFeedbackScript:
    def test_matches_rejection(self) -> None:
        script = RejectionFeedbackScript()
        ctx = MockContext(trigger_type="rejection")
        assert script.matches(ctx)

    def test_response_mentions_rejection(self) -> None:
        script = RejectionFeedbackScript()
        ctx = MockContext(trigger_type="rejection", trigger_message="Bad test")
        resp = script.respond(ctx)
        assert "rejected" in resp.content


class TestGenericToolFollowupScript:
    def test_matches_non_test_tool_followup(self) -> None:
        script = GenericToolFollowupScript()
        ctx = MockContext(trigger_type="tool_followup", round_number=1)
        assert script.matches(ctx)

    def test_does_not_match_round_0(self) -> None:
        script = GenericToolFollowupScript()
        ctx = MockContext(trigger_type="tool_followup", round_number=0)
        assert not script.matches(ctx)


# ---------------------------------------------------------------------------
# MockLLMClient integration tests
# ---------------------------------------------------------------------------


class TestMockLLMClient:
    @pytest.mark.asyncio
    async def test_human_chat_golden_path(self) -> None:
        """Beat 5: user asks load_config 'what do you do?'"""
        client = MockLLMClient()
        msgs = [
            {"role": "system", "content": "You are the agent for `load_config`. node_type: function"},
            {"role": "user", "content": "what do you do?"},
        ]
        resp = await client.chat(msgs)
        assert isinstance(resp, LLMResponse)
        assert "load_config" in resp.content
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_content_changed_golden_path(self) -> None:
        """Beat 7: load_config changed, should message test_load_yaml."""
        client = MockLLMClient()
        msgs = [
            {"role": "system", "content": "You are the agent for `load_config`. node_type: function"},
            {"role": "user", "content": "Your source code has changed: timeout parameter added."},
        ]
        resp = await client.chat(msgs)
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "message_node"
        assert resp.tool_calls[0].arguments["target_id"] == "test_load_yaml"

    @pytest.mark.asyncio
    async def test_test_agent_cascade_golden_path(self) -> None:
        """Beats 8-9: test agent reads source then proposes rewrite."""
        client = MockLLMClient()

        # Round 0: agent message triggers read_node
        msgs = [
            {
                "role": "system",
                "content": "You are a test function agent. TestFunction extension. agent for `test_load_yaml`.",
            },
            {"role": "user", "content": "[From load_config] Please update the test."},
        ]
        resp = await client.chat(msgs)
        assert resp.tool_calls[0].name == "read_node"

        # Round 1: after reading, proposes rewrite
        msgs.append({"role": "assistant", "content": resp.content})
        msgs.append({"role": "user", "content": "[Tool result for read_node] def load_config(path, timeout=30): ..."})
        resp = await client.chat(msgs)
        assert resp.tool_calls[0].name == "rewrite_self"
        assert "test_load_yaml_with_timeout" in resp.tool_calls[0].arguments["new_source"]

    @pytest.mark.asyncio
    async def test_fallback_for_unknown_context(self) -> None:
        """Unknown agent/trigger gets a generic acknowledgment."""
        client = MockLLMClient()
        msgs = [
            {"role": "system", "content": "You are the agent for `mystery_func`. node_type: class"},
            {"role": "user", "content": "Do something weird."},
        ]
        resp = await client.chat(msgs)
        assert "mystery_func" in resp.content
        assert resp.tool_calls == []

    @pytest.mark.asyncio
    async def test_call_count_increments(self) -> None:
        client = MockLLMClient()
        assert client.call_count == 0
        await client.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
        assert client.call_count == 1
        await client.chat([{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}])
        assert client.call_count == 2

    @pytest.mark.asyncio
    async def test_close_is_noop(self) -> None:
        client = MockLLMClient()
        await client.close()  # Should not raise
