from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import json

import pytest

from remora.discovery import CSTNode
from remora.errors import AGENT_002, AGENT_003
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


class FakeResponse:
    def __init__(self, text: str) -> None:
        self._text = text

    def text(self) -> str:
        return self._text


class FakeConversation:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def prompt(self, message: str) -> FakeResponse:
        self.prompts.append(message)
        if not self.responses:
            raise AssertionError("No responses queued for FakeConversation")
        return FakeResponse(self.responses.pop(0))


class FakeModel:
    def __init__(self, responses: list[str], *, can_use_tools: bool = False) -> None:
        self.responses = responses
        self.can_use_tools = can_use_tools
        self.conversation_calls: list[dict[str, Any]] = []

    def conversation(self, **kwargs: Any) -> FakeConversation:
        self.conversation_calls.append(kwargs)
        return FakeConversation(self.responses)


class FakeLLMModule:
    class UnknownModelError(Exception):
        pass

    def __init__(self) -> None:
        self.models: dict[str, FakeModel] = {}

    def get_model(self, model_id: str) -> FakeModel:
        if model_id not in self.models:
            raise FakeLLMModule.UnknownModelError(model_id)
        return self.models[model_id]


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
        model_id="ollama/functiongemma-4b-it",
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


def _tool_call_text(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps({"name": name, "arguments": arguments})


def test_runner_initializes_model_and_messages(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel([_tool_call_text("submit_result", {})])
    monkeypatch.setattr("remora.runner.llm", fake_llm)

    definition = _make_definition()
    node = _make_node()

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
    )

    assert runner.messages[0]["role"] == "system"
    assert "You have access to the following tools" in runner.messages[0]["content"]
    assert runner.messages[1]["role"] == "user"
    assert "node hello function" in runner.messages[1]["content"]
    assert runner.turn_count == 0


def test_missing_model_id_raises_agent_002(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = FakeLLMModule()
    monkeypatch.setattr("remora.runner.llm", fake_llm)

    definition = _make_definition()
    node = _make_node()

    with pytest.raises(AgentError) as excinfo:
        FunctionGemmaRunner(
            definition=definition,
            node=node,
            workspace_id="ws-1",
            cairn_client=FakeCairnClient(),
            model_id="ollama/missing-model",
        )

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"


def test_parse_tool_calls_handles_json_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel([_tool_call_text("submit_result", {})])
    monkeypatch.setattr("remora.runner.llm", fake_llm)

    runner = FunctionGemmaRunner(
        definition=_make_definition(),
        node=_make_node(),
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
    )

    raw = _tool_call_text("inspect", {"value": "a"})
    fenced = "```json\n" + _tool_call_text("inspect", {"value": "b"}) + "\n```"
    multi = "```json\n" + json.dumps([{"name": "inspect", "arguments": {}}, {"name": "submit_result"}]) + "\n```"

    assert runner._parse_tool_calls(raw)[0]["name"] == "inspect"
    assert runner._parse_tool_calls(fenced)[0]["name"] == "inspect"
    assert [call["name"] for call in runner._parse_tool_calls(multi)] == ["inspect", "submit_result"]


def test_run_returns_submit_result_on_first_turn(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel(
        [_tool_call_text("submit_result", {"summary": "Done", "changed_files": ["src/example.py"], "details": {}})]
    )
    monkeypatch.setattr("remora.runner.llm", fake_llm)

    definition = _make_definition()
    node = _make_node()
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=FakeCairnClient())

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
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel(responses)
    monkeypatch.setattr("remora.runner.llm", fake_llm)

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
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

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
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel(responses)
    monkeypatch.setattr("remora.runner.llm", fake_llm)

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
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    with pytest.raises(AgentError) as excinfo:
        asyncio.run(runner.run())

    assert excinfo.value.error_code == AGENT_003


def test_context_providers_injected_before_tool_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        _tool_call_text("inspect", {}),
        _tool_call_text("submit_result", {"summary": "Done", "changed_files": []}),
    ]
    fake_llm = FakeLLMModule()
    fake_llm.models["ollama/functiongemma-4b-it"] = FakeModel(responses)
    monkeypatch.setattr("remora.runner.llm", fake_llm)

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
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert [call[0] for call in cairn.calls][:3] == [Path("ctx-1.pym"), Path("ctx-2.pym"), Path("inspect.pym")]
    context_messages = [
        message["content"]
        for message in runner.messages
        if message.get("role") == "user" and str(message.get("content", "")).startswith("[Context]")
    ]
    assert context_messages == ["[Context] {'ctx': 'one'}", "[Context] {'ctx': 'two'}"]
