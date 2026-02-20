"""Tests for ContextManager."""

import pytest

from remora.context import ContextManager


class TestContextManager:
    @pytest.fixture
    def initial_context(self):
        return {
            "agent_id": "test-001",
            "goal": "Fix lint errors in foo.py",
            "operation": "lint",
            "node_id": "foo.py:bar",
            "node_summary": "A utility function",
        }

    def test_init_creates_packet(self, initial_context):
        """ContextManager initializes a DecisionPacket."""
        ctx = ContextManager(initial_context)

        assert ctx.packet.agent_id == "test-001"
        assert ctx.packet.goal == "Fix lint errors in foo.py"
        assert ctx.packet.operation == "lint"
        assert ctx.packet.turn == 0

    def test_apply_tool_result_with_summary(self, initial_context):
        """Tool-provided summaries are used."""
        ctx = ContextManager(initial_context)

        ctx.apply_event(
            {
                "type": "tool_result",
                "tool_name": "run_linter",
                "data": {
                    "summary": "Found 3 lint errors",
                    "knowledge_delta": {"lint_errors": 3},
                },
            }
        )

        assert len(ctx.packet.recent_actions) == 1
        assert ctx.packet.recent_actions[0].summary == "Found 3 lint errors"
        assert ctx.packet.knowledge["lint_errors"].value == 3

    def test_apply_tool_result_error(self, initial_context):
        """Errors are tracked correctly."""
        ctx = ContextManager(initial_context)

        ctx.apply_event(
            {
                "type": "tool_result",
                "tool_name": "run_linter",
                "data": {
                    "error": "File not found",
                },
            }
        )

        assert ctx.packet.recent_actions[0].outcome == "error"
        assert ctx.packet.last_error == "File not found"
        assert ctx.packet.error_count == 1

    def test_get_prompt_context(self, initial_context):
        """Prompt context is properly formatted."""
        ctx = ContextManager(initial_context)
        ctx.packet.turn = 2
        ctx.packet.add_action("run_linter", "Found 3 errors", "success")
        ctx.packet.update_knowledge("errors", 3)

        prompt_ctx = ctx.get_prompt_context()

        assert prompt_ctx["goal"] == "Fix lint errors in foo.py"
        assert prompt_ctx["turn"] == 2
        assert len(prompt_ctx["recent_actions"]) == 1
        assert prompt_ctx["knowledge"]["errors"] == 3

    def test_increment_turn(self, initial_context):
        """Turn counter increments correctly."""
        ctx = ContextManager(initial_context)

        assert ctx.packet.turn == 0
        ctx.increment_turn()
        assert ctx.packet.turn == 1
        ctx.increment_turn()
        assert ctx.packet.turn == 2
