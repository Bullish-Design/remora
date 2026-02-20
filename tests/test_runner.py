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

from remora.testing import (
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


def test_runner_sends_system_prompt_to_model() -> None:
    definition = make_definition()
    node = make_node()
    server_config = make_server_config()
    client = FakeAsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
        responses=[tool_call_message("submit_result", {})],
    )

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=server_config,
        runner_config=make_runner_config(),
        http_client=cast(Any, client),
    )

    asyncio.run(runner.run())

    chat_calls = client.chat.completions.calls
    assert len(chat_calls) >= 1

    first_call_messages = chat_calls[0]["messages"]
    system_messages = [message for message in first_call_messages if message.get("role") == "system"]
    user_messages = [message for message in first_call_messages if message.get("role") == "user"]

    assert len(system_messages) == 1
    assert "lint agent" in system_messages[0]["content"].lower()
    assert len(user_messages) == 1
    assert "node hello function" in str(user_messages[0].get("content", ""))


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


def test_run_returns_submit_result_on_first_turn() -> None:
    definition = make_definition()
    node = make_node()
    server_config = make_server_config()
    client = FakeAsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
        responses=[
            tool_call_message("submit_result", {"summary": "Done", "changed_files": ["src/example.py"], "details": {}})
        ],
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=server_config,
        runner_config=make_runner_config(),
        http_client=cast(Any, client),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "Done"
    assert result.changed_files == ["src/example.py"]
    assert result.workspace_id == "ws-1"

    chat_calls = client.chat.completions.calls
    assert len(chat_calls) == 1


def test_run_handles_multiple_tool_turns_then_submit() -> None:
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
    server_config = make_server_config()
    client = FakeAsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
        responses=[
            tool_call_message("inspect", {"value": "a"}),
            tool_call_message("inspect", {"value": "b"}),
            tool_call_message("submit_result", {"summary": "Done", "changed_files": [], "details": {"calls": 2}}),
        ],
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        server_config=server_config,
        runner_config=make_runner_config(),
        http_client=cast(Any, client),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.details == {"calls": 2}

    chat_calls = client.chat.completions.calls
    assert len(chat_calls) == 3


def test_context_manager_tracks_tool_results() -> None:
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
    server_config = make_server_config()
    client = FakeAsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
        responses=[
            tool_call_message("inspect", {}),
            tool_call_message("submit_result", {"summary": "Done", "changed_files": []}),
        ],
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        grail_executor=FakeGrailExecutor(),
        grail_dir=Path("/tmp"),
        server_config=server_config,
        runner_config=make_runner_config(),
        http_client=cast(Any, client),
    )

    asyncio.run(runner.run())

    assert runner.context_manager.packet.turn >= 1
    assert len(runner.context_manager.packet.recent_actions) == 1
    assert runner.context_manager.packet.recent_actions[0].tool == "inspect"


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


def test_context_providers_injected_before_tool_dispatch() -> None:
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
    server_config = make_server_config()
    client = FakeAsyncOpenAI(
        base_url=server_config.base_url,
        api_key=server_config.api_key,
        timeout=server_config.timeout,
        responses=[
            tool_call_message("inspect", {}),
            tool_call_message("submit_result", {"summary": "Done", "changed_files": []}),
        ],
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=make_ctx(),
        grail_executor=cairn,
        grail_dir=Path("/tmp"),
        server_config=server_config,
        runner_config=make_runner_config(),
        http_client=cast(Any, client),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert [call[0] for call in cairn.calls][:3] == [Path("ctx-1.pym"), Path("ctx-2.pym"), Path("inspect.pym")]

    chat_calls = client.chat.completions.calls
    assert len(chat_calls) >= 2
    tool_messages = [
        message for message in runner.messages if message.get("role") == "tool" and message.get("name") == "inspect"
    ]
    assert tool_messages[0]["content"] == '{"ctx": "one"}\n{"ctx": "two"}\n{"ok": true}'
