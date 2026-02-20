"""Tests for runner resume_tool dispatch integration."""

from __future__ import annotations

import json
from typing import Any
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from remora.discovery import NodeType
from remora.runner import FunctionGemmaRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_call(name: str, arguments: dict[str, Any]) -> MagicMock:
    """Build a mock OpenAI tool_call object."""
    tc = MagicMock()
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    tc.id = "call_001"
    return tc


def _make_runner(*, snapshot_manager: MagicMock | None = None) -> FunctionGemmaRunner:
    """Build a minimal FunctionGemmaRunner for dispatch testing.

    Uses MagicMock stubs for all dependencies to isolate _dispatch_tool logic.
    """
    definition = MagicMock()
    definition.name = "test_op"
    definition.tools_by_name = {}
    definition.tool_schemas = []
    definition.max_turns = 5
    definition.initial_context.render.return_value = "test context"
    definition.initial_context.system_prompt = "system"
    definition.grail_summary = {}

    node = MagicMock()
    node.node_id = "node-1"
    node.name = "TestNode"
    node.node_type = NodeType.FUNCTION
    node.file_path = Path("/test.py")
    node.text = "def foo(): pass"

    ctx = MagicMock()
    ctx.agent_id = "test-agent-1"

    server_config = MagicMock()
    server_config.base_url = "http://localhost:8000"
    server_config.api_key = "test"
    server_config.timeout = 30
    server_config.default_adapter = "default"
    server_config.retry.max_attempts = 1
    server_config.retry.initial_delay = 0.1
    server_config.retry.max_delay = 1.0
    server_config.retry.backoff_factor = 2.0

    runner_config = MagicMock()
    runner_config.tool_choice = "auto"
    runner_config.max_tokens = 1024
    runner_config.temperature = 0.1

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=ctx,
        server_config=server_config,
        runner_config=runner_config,
        snapshot_manager=snapshot_manager,
    )
    return runner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_resume_tool() -> None:
    """When snapshot_manager is set, resume_tool delegates to _handle_resume."""
    mgr = MagicMock()
    mgr.resume_script.return_value = {"error": False, "result": {"done": True}}

    runner = _make_runner(snapshot_manager=mgr)
    tc = _make_tool_call("resume_tool", {"snapshot_id": "snap-123"})

    result_str = await runner._dispatch_tool(tc)
    result = json.loads(result_str)

    assert result == {"error": False, "result": {"done": True}}
    mgr.resume_script.assert_called_once_with(
        snapshot_id="snap-123",
        return_value=None,
    )


@pytest.mark.asyncio
async def test_dispatch_resume_tool_with_context() -> None:
    """resume_tool with additional_context passes it as return_value."""
    mgr = MagicMock()
    mgr.resume_script.return_value = {
        "error": False,
        "suspended": True,
        "snapshot_id": "snap-123",
        "function_name": "ext_fn",
        "args": [],
        "kwargs": {},
        "resume_count": 1,
        "message": "Script still paused.",
    }

    runner = _make_runner(snapshot_manager=mgr)
    tc = _make_tool_call(
        "resume_tool",
        {
            "snapshot_id": "snap-123",
            "additional_context": "some extra data",
        },
    )

    result_str = await runner._dispatch_tool(tc)
    result = json.loads(result_str)

    assert result["suspended"] is True
    mgr.resume_script.assert_called_once_with(
        snapshot_id="snap-123",
        return_value="some extra data",
    )


@pytest.mark.asyncio
async def test_dispatch_resume_tool_disabled() -> None:
    """When snapshot_manager is None, resume_tool returns SNAPSHOTS_DISABLED."""
    runner = _make_runner(snapshot_manager=None)
    tc = _make_tool_call("resume_tool", {"snapshot_id": "snap-123"})

    result_str = await runner._dispatch_tool(tc)
    result = json.loads(result_str)

    assert result["error"] is True
    assert result["code"] == "SNAPSHOTS_DISABLED"
