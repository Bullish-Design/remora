from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
import asyncio
import json

import pytest

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
from remora.errors import AGENT_002, AGENT_003, AGENT_004
from remora.orchestrator import RemoraAgentContext
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


def _make_ctx(agent_id: str = "ws-1", operation: str = "lint") -> RemoraAgentContext:
    return RemoraAgentContext(
        agent_id=agent_id,
        task=f"{operation} on hello",
        operation=operation,
        node_id="node-1",
    )


class FakeToolCallFunction:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class FakeToolCall:
    def __init__(self, *, name: str, arguments: str, call_id: str = "call-1") -> None:
        self.id = call_id
        self.type = "function"
        self.function = FakeToolCallFunction(name, arguments)


class FakeCompletionMessage:
    def __init__(self, *, content: str | None = None, tool_calls: list[FakeToolCall] | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, *, exclude_none: bool = False) -> dict[str, Any]:
        tool_calls = None
        if self.tool_calls is not None:
            tool_calls = [
                {
                    "id": call.id,
                    "type": call.type,
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in self.tool_calls
            ]
        data: dict[str, Any] = {"role": "assistant", "content": self.content, "tool_calls": tool_calls}
        if exclude_none:
            return {key: value for key, value in data.items() if value is not None}
        return data


class FakeCompletionChoice:
    def __init__(self, message: FakeCompletionMessage) -> None:
        self.message = message


class FakeCompletionResponse:
    def __init__(self, message: FakeCompletionMessage) -> None:
        self.choices = [FakeCompletionChoice(message)]


class FakeChatCompletions:
    def __init__(self, responses: list[FakeCompletionMessage], *, error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any | None = None,
        max_tokens: int,
        temperature: float,
    ) -> FakeCompletionResponse:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError("No responses queued for FakeChatCompletions")
        return FakeCompletionResponse(self.responses.pop(0))


class FakeAsyncOpenAI:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: int,
        responses: list[FakeCompletionMessage] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=FakeChatCompletions(responses or [], error=error))





def _tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _make_definition(
    *,
    tools: list[ToolDefinition] | None = None,
    max_turns: int = 10,
    tool_schemas: list[dict[str, Any]] | None = None,
) -> SubagentDefinition:
    if tools is None:
        tools = [
            ToolDefinition(
                tool_name="submit_result",
                pym=Path("submit.pym"),
                tool_description="Submit the result.",
                context_providers=[],
            )
        ]
    definition = SubagentDefinition(
        name="lint_agent",
        max_turns=max_turns,
        initial_context=InitialContext(
            system_prompt="You are a lint agent.",
            node_context="node {{ node_name }} {{ node_type }} {{ node_text }}",
        ),
        tools=tools,
    )
    if tool_schemas is None:
        tool_schemas = [
            _tool_schema(
                tool.name,
                tool.tool_description,
                {"type": "object", "additionalProperties": False, "properties": {}},
            )
            for tool in tools
        ]
    definition._tool_schemas = tool_schemas
    return definition


def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type=NodeType.FUNCTION,
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
        start_line=1,
        end_line=1,
    )


def _make_server_config() -> ServerConfig:
    return ServerConfig(
        base_url="http://remora-server:8000/v1",
        api_key="EMPTY",
        timeout=30,
        default_adapter="google/functiongemma-270m-it",
    )


def _make_runner_config() -> RunnerConfig:
    return RunnerConfig(max_tokens=128, temperature=0.0, tool_choice="required")


def _tool_call_message(name: str, arguments: dict[str, Any], *, call_id: str = "call-1") -> FakeCompletionMessage:
    return FakeCompletionMessage(tool_calls=[FakeToolCall(name=name, arguments=json.dumps(arguments), call_id=call_id)])


def _patch_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[FakeCompletionMessage] | None = None,
    error: Exception | None = None,
) -> None:
    def _factory(*_: Any, **kwargs: Any) -> FakeAsyncOpenAI:
        return FakeAsyncOpenAI(
            base_url=kwargs["base_url"],
            api_key=kwargs["api_key"],
            timeout=kwargs["timeout"],
            responses=list(responses or []),
            error=error,
        )

    monkeypatch.setattr("remora.runner.AsyncOpenAI", _factory)


def test_runner_initializes_model_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_openai(monkeypatch, responses=[_tool_call_message("submit_result", {})])

    definition = _make_definition()
    node = _make_node()

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=_make_ctx(),
        ctx=_make_ctx(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
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
    _patch_openai(monkeypatch, error=FakeConnectionError("boom"))

    definition = _make_definition()
    node = _make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=_make_ctx(),
        ctx=_make_ctx(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"


def test_run_returns_submit_result_on_first_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_openai(
        monkeypatch,
        responses=[
            _tool_call_message("submit_result", {"summary": "Done", "changed_files": ["src/example.py"], "details": {}})
        ],
    )

    definition = _make_definition()
    node = _make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        ctx=_make_ctx(),
        ctx=_make_ctx(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "Done"
    assert result.changed_files == ["src/example.py"]
    assert result.workspace_id == "ws-1"
    assert runner.turn_count == 1


def test_run_handles_multiple_tool_turns_then_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_message("inspect", {"value": "a"}),
        _tool_call_message("inspect", {"value": "b"}),
        _tool_call_message("submit_result", {"summary": "Done", "changed_files": [], "details": {"calls": 2}}),
    ]
    _patch_openai(monkeypatch, responses=responses)

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
        _tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {"value": {"type": "string"}}},
        ),
        _tool_schema(
            "submit_result",
            "Submit the result.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
    ]

    definition = _make_definition(tools=[tool_def, submit_def], tool_schemas=tool_schemas)
    node = _make_node()
        ctx=_make_ctx(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.details == {"calls": 2}
    assert runner.turn_count == 3


def test_run_respects_turn_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_message("inspect", {}),
        _tool_call_message("inspect", {}),
        _tool_call_message("inspect", {}),
    ]
    _patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        tool_name="inspect",
        pym=Path("inspect.pym"),
        tool_description="Inspect something.",
        context_providers=[],
    )

    tool_schemas = [
        _tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        )
    ]

    definition = _make_definition(tools=[tool_def], max_turns=2, tool_schemas=tool_schemas)
    node = _make_node()
        ctx=_make_ctx(),
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_004


def test_context_providers_injected_before_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_message("inspect", {}),
        _tool_call_message("submit_result", {"summary": "Done", "changed_files": []}),
    ]
    _patch_openai(monkeypatch, responses=responses)

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
        _tool_schema(
            "inspect",
            "Inspect something.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
        _tool_schema(
            "submit_result",
            "Submit the result.",
            {"type": "object", "additionalProperties": False, "properties": {}},
        ),
    ]

    definition = _make_definition(tools=[tool_def, submit_def], tool_schemas=tool_schemas)
    node = _make_node()
    grail_executor=cairn,
        server_config=_make_server_config(),
        runner_config=_make_runner_config(),
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
