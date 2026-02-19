from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from remora.errors import AGENT_002, AGENT_003, AGENT_004
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import ToolDefinition

from tests.helpers import (
    FakeAsyncOpenAI,
    FakeChatCompletions,
    FakeCompletionMessage,
    FakeGrailExecutor,
    FakeToolCall,
    make_ctx,
    make_definition,
    make_node,
    make_runner_config,
    make_server_config,
    patch_openai,
    tool_call_message,
    tool_schema,
)


def test_runner_initializes_model_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_openai(monkeypatch, responses=[tool_call_message("submit_result", {})])

    definition = make_definition()
    node = make_node()

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    system_message = cast(dict[str, Any], runner.messages[0])
    user_message = cast(dict[str, Any], runner.messages[1])
    assert system_message["role"] == "system"
    assert system_message.get("content") == "You are a lint agent."
    assert user_message["role"] == "user"
    assert "node hello function" in str(user_message.get("content", ""))
    assert runner.turn_count == 0


def test_missing_model_id_raises_agent_002(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeConnectionError(Exception):
        pass

    monkeypatch.setattr("remora.runner.APIConnectionError", FakeConnectionError)
    patch_openai(monkeypatch, error=FakeConnectionError("boom"))

    definition = make_definition()
    node = make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"


def test_run_returns_submit_result_on_first_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_openai(
        monkeypatch,
        responses=[
            tool_call_message("submit_result", {"summary": "Done", "changed_files": ["src/example.py"], "details": {}})
        ],
    )

    definition = make_definition()
    node = make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "Done"
    assert result.changed_files == ["src/example.py"]
    assert result.workspace_id == "ws-1"
    assert runner.turn_count == 1


def test_run_handles_multiple_tool_turns_then_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        tool_call_message("inspect", {"value": "a"}),
        tool_call_message("inspect", {"value": "b"}),
        tool_call_message("submit_result", {"summary": "Done", "changed_files": [], "details": {"calls": 2}}),
    ]
    patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        tool_name="inspect",
        pym=Path("inspect.pym"),
        tool_description="Inspect something.",
        context_providers=[],
    )
    submit_def = ToolDefinition(
        tool_name="submit_result",
        pym=Path("submit.pym"),
        tool_description="Submit the result.",
        context_providers=[],
    )

    tool_schemas = [
        tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {"value": {"type": "string"}}},
        ),
        tool_schema(
            "submit_result",
            "Submit the result.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
    ]

    definition = make_definition(tools=[tool_def, submit_def], tool_schemas=tool_schemas)
    node = make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.details == {"calls": 2}
    assert runner.turn_count == 3


def test_run_respects_turn_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        tool_call_message("inspect", {}),
        tool_call_message("inspect", {}),
        tool_call_message("inspect", {}),
    ]
    patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        tool_name="inspect",
        pym=Path("inspect.pym"),
        tool_description="Inspect something.",
        context_providers=[],
    )

    tool_schemas = [
        tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        )
    ]

    definition = make_definition(tools=[tool_def], max_turns=2, tool_schemas=tool_schemas)
    node = make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_004


def test_context_providers_injected_before_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        tool_call_message("inspect", {}),
        tool_call_message("submit_result", {"summary": "Done", "changed_files": []}),
    ]
    patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        tool_name="inspect",
        pym=Path("inspect.pym"),
        tool_description="Inspect something.",
        context_providers=[Path("ctx-1.pym"), Path("ctx-2.pym")],
    )
    submit_def = ToolDefinition(
        tool_name="submit_result",
        pym=Path("submit.pym"),
        tool_description="Submit the result.",
        context_providers=[],
    )

    tool_schemas = [
        tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        tool_schema(
            "submit_result",
            "Submit the result.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
    ]

    definition = make_definition(tools=[tool_def, submit_def], tool_schemas=tool_schemas)
    node = make_node()
    cairn = FakeGrailExecutor()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        grail_executor=cairn,
        grail_dir=Path("/tmp"),
        server_config=make_server_config(),
        runner_config=make_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert [call[0] for call in cairn.calls][:3] == [Path("ctx-1.pym"), Path("ctx-2.pym"), Path("inspect.pym")]
    tool_messages = [
        cast(dict[str, Any], message)
        for message in runner.messages
        if cast(dict[str, Any], message).get("role") == "tool"
        and cast(dict[str, Any], message).get("name") == "inspect"
    ]
    assert tool_messages[0]["content"] == '{"ctx": "one"}\n{"ctx": "two"}\n{"ok": true}'

