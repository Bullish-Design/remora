from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
import asyncio
import json

import pytest

from remora.config import ServerConfig
from remora.discovery import CSTNode
from remora.errors import AGENT_002, AGENT_003
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


class FakeCompletionMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeCompletionChoice:
    def __init__(self, content: str) -> None:
        self.message = FakeCompletionMessage(content)


class FakeCompletionResponse:
    def __init__(self, content: str) -> None:
        self.choices = [FakeCompletionChoice(content)]


class FakeChatCompletions:
    def __init__(self, responses: list[str], *, error: Exception | None = None) -> None:
        self.responses = responses
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float,
    ) -> FakeCompletionResponse:
        self.calls.append({"model": model, "messages": messages})
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
        responses: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.timeout = timeout
        self.chat = SimpleNamespace(completions=FakeChatCompletions(responses or [], error=error))


class FakeCairnClient:
    def __init__(self, responses: dict[Path, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[Path, str, dict[str, Any]]] = []

    async def run_pym(self, path: Any, workspace_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        resolved = Path(path)
        self.calls.append((resolved, workspace_id, inputs))
        return self.responses.get(resolved, {})


def _make_definition(
    *,
    tools: list[ToolDefinition] | None = None,
    max_turns: int = 10,
) -> SubagentDefinition:
    if tools is None:
        tools = [
            ToolDefinition(
                name="submit_result",
                pym=Path("submit.pym"),
                description="Submit the result.",
                parameters={
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {},
                },
                context_providers=[],
            )
        ]
    return SubagentDefinition(
        name="lint_agent",
        max_turns=max_turns,
        initial_context=InitialContext(
            system_prompt="You are a lint agent.",
            node_context="node {{ node_name }} {{ node_type }} {{ node_text }}",
        ),
        tools=tools,
    )


def _make_node() -> CSTNode:
    return CSTNode(
        node_id="node-1",
        node_type="function",
        name="hello",
        file_path=Path("src/example.py"),
        start_byte=0,
        end_byte=10,
        text="def hello(): ...",
    )


def _make_server_config() -> ServerConfig:
    return ServerConfig(
        base_url="http://function-gemma-server:8000/v1",
        api_key="EMPTY",
        timeout=30,
        default_adapter="google/functiongemma-270m-it",
    )


def _tool_call_text(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"name": name, "arguments": arguments})


def _patch_openai(
    monkeypatch: pytest.MonkeyPatch,
    *,
    responses: list[str] | None = None,
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
    _patch_openai(monkeypatch, responses=[_tool_call_text("submit_result", {})])

    definition = _make_definition()
    node = _make_node()

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
    )

    system_message = cast(dict[str, Any], runner.messages[0])
    user_message = cast(dict[str, Any], runner.messages[1])
    assert system_message["role"] == "system"
    assert "You have access to the following tools" in str(system_message.get("content", ""))
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
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"


def test_parse_tool_calls_handles_json_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_openai(monkeypatch, responses=[_tool_call_text("submit_result", {})])

    runner = FunctionGemmaRunner(
        definition=_make_definition(),
        node=_make_node(),
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
    )

    raw = _tool_call_text("inspect", {"value": "a"})
    fenced = "```json\n" + _tool_call_text("inspect", {"value": "b"}) + "\n```"
    multi = "```json\n" + json.dumps([{"name": "inspect", "arguments": {}}, {"name": "submit_result"}]) + "\n```"

    assert runner._parse_tool_calls(raw)[0]["name"] == "inspect"
    assert runner._parse_tool_calls(fenced)[0]["name"] == "inspect"
    assert [call["name"] for call in runner._parse_tool_calls(multi)] == ["inspect", "submit_result"]


def test_run_returns_submit_result_on_first_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_openai(
        monkeypatch,
        responses=[
            _tool_call_text("submit_result", {"summary": "Done", "changed_files": ["src/example.py"], "details": {}})
        ],
    )

    definition = _make_definition()
    node = _make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
        server_config=_make_server_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "Done"
    assert result.changed_files == ["src/example.py"]
    assert result.workspace_id == "ws-1"
    assert runner.turn_count == 1


def test_run_handles_multiple_tool_turns_then_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_text("inspect", {"value": "a"}),
        _tool_call_text("inspect", {"value": "b"}),
        _tool_call_text("submit_result", {"summary": "Done", "changed_files": [], "details": {"calls": 2}}),
    ]
    _patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        name="inspect",
        pym=Path("inspect.pym"),
        description="Inspect something.",
        parameters={"type": "object", "additionalProperties": False, "properties": {"value": {"type": "string"}}},
        context_providers=[],
    )
    submit_def = ToolDefinition(
        name="submit_result",
        pym=Path("submit.pym"),
        description="Submit the result.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[],
    )

    definition = _make_definition(tools=[tool_def, submit_def])
    node = _make_node()
    cairn = FakeCairnClient({Path("inspect.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=cairn,
        server_config=_make_server_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.details == {"calls": 2}
    assert runner.turn_count == 3


def test_run_respects_turn_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_text("inspect", {}),
        _tool_call_text("inspect", {}),
        _tool_call_text("inspect", {}),
    ]
    _patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        name="inspect",
        pym=Path("inspect.pym"),
        description="Inspect something.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[],
    )

    definition = _make_definition(tools=[tool_def], max_turns=2)
    node = _make_node()
    cairn = FakeCairnClient({Path("inspect.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=cairn,
        server_config=_make_server_config(),
    )

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_003


def test_context_providers_injected_before_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_text("inspect", {}),
        _tool_call_text("submit_result", {"summary": "Done", "changed_files": []}),
    ]
    _patch_openai(monkeypatch, responses=responses)

    tool_def = ToolDefinition(
        name="inspect",
        pym=Path("inspect.pym"),
        description="Inspect something.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[Path("ctx-1.pym"), Path("ctx-2.pym")],
    )
    submit_def = ToolDefinition(
        name="submit_result",
        pym=Path("submit.pym"),
        description="Submit the result.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[],
    )

    definition = _make_definition(tools=[tool_def, submit_def])
    node = _make_node()
    cairn = FakeCairnClient(
        {
            Path("ctx-1.pym"): {"ctx": "one"},
            Path("ctx-2.pym"): {"ctx": "two"},
            Path("inspect.pym"): {"ok": True},
        }
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=cairn,
        server_config=_make_server_config(),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert [call[0] for call in cairn.calls][:3] == [Path("ctx-1.pym"), Path("ctx-2.pym"), Path("inspect.pym")]
    context_messages: list[str] = []
    for message in runner.messages:
        message_data = cast(dict[str, Any], message)
        if message_data.get("role") == "user" and str(message_data.get("content", "")).startswith("[Context]"):
            context_messages.append(str(message_data.get("content", "")))
    assert context_messages == ["[Context] {'ctx': 'one'}", "[Context] {'ctx': 'two'}"]
