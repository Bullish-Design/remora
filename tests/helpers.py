from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from openai import APIConnectionError

from remora.config import RunnerConfig, ServerConfig
from remora.discovery import CSTNode, NodeType
from remora.orchestrator import RemoraAgentContext
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


def make_ctx(agent_id: str = "ws-1", operation: str = "lint") -> RemoraAgentContext:
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


class FakeGrailExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def execute(
        self,
        pym_path: Path,
        grail_dir: Path,
        inputs: dict[str, Any],
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append((pym_path, inputs))
        if pym_path.name == "inspect.pym":
             return {"result": {"ok": True}}
        if pym_path.name == "ctx-1.pym":
             return {"result": {"ctx": "one"}}
        if pym_path.name == "ctx-2.pym":
             return {"result": {"ctx": "two"}}
        return {"result": {}}


def tool_schema(name: str, description: str, parameters: dict[str, Any]) -> dict[str, Any]:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def make_definition(
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
            tool_schema(
                tool.name,
                tool.tool_description,
                {"type": "object", "additionalProperties": False, "properties": {}},
            )
            for tool in tools
        ]
    definition._tool_schemas = tool_schemas
    return definition


def make_node() -> CSTNode:
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


def make_server_config() -> ServerConfig:
    return ServerConfig(
        base_url="http://remora-server:8000/v1",
        api_key="EMPTY",
        timeout=30,
        default_adapter="google/functiongemma-270m-it",
    )


def make_runner_config() -> RunnerConfig:
    return RunnerConfig(max_tokens=128, temperature=0.0, tool_choice="required")


def tool_call_message(name: str, arguments: dict[str, Any], *, call_id: str = "call-1") -> FakeCompletionMessage:
    return FakeCompletionMessage(tool_calls=[FakeToolCall(name=name, arguments=json.dumps(arguments), call_id=call_id)])


def patch_openai(
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
