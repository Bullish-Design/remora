from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
import asyncio
import json

import pytest

from remora.discovery import CSTNode
from remora.errors import AGENT_002, AGENT_003
from remora.runner import AgentError, FunctionGemmaRunner, ModelCache
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


class FakeLlama:
    init_calls: list[dict[str, Any]] = []
    create_calls: list[dict[str, Any]] = []
    responses: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        FakeLlama.init_calls.append(kwargs)

    def create_chat_completion(self, **kwargs: Any) -> dict[str, Any]:
        FakeLlama.create_calls.append(kwargs)
        if not FakeLlama.responses:
            raise AssertionError("No responses queued for FakeLlama")
        return FakeLlama.responses.pop(0)


@pytest.fixture(autouse=True)
def _clear_model_cache() -> None:
    ModelCache.clear()
    FakeLlama.init_calls.clear()
    FakeLlama.create_calls.clear()
    FakeLlama.responses.clear()
    yield
    ModelCache.clear()


def _make_definition(
    model_path: Path,
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
        model=model_path,
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


def _tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> dict[str, Any]:
    return {"id": call_id, "function": {"name": name, "arguments": json.dumps(arguments)}}


def _tool_call_response(tool_calls: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {"role": "assistant", "tool_calls": tool_calls},
            }
        ]
    }


def _stop_response(content: str) -> dict[str, Any]:
    return {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}]}


class FakeCairnClient:
    def __init__(self, responses: dict[Path, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[Path, str, dict[str, Any]]] = []

    async def run_pym(self, path: Any, workspace_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        resolved = Path(path)
        self.calls.append((resolved, workspace_id, inputs))
        return self.responses.get(resolved, {})


def test_runner_initializes_model_and_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    definition = _make_definition(model_path)
    node = _make_node()

    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient(),
    )

    assert isinstance(runner.model, FakeLlama)
    assert runner.messages[0]["role"] == "system"
    assert runner.messages[1]["role"] == "user"
    assert "node hello function" in runner.messages[1]["content"]
    assert runner.turn_count == 0


def test_model_cache_returns_same_instance(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = str(tmp_path / "model.gguf")

    first = ModelCache.get(model_path, n_ctx=1)
    second = ModelCache.get(model_path, n_ctx=1)

    assert first is second
    assert len(FakeLlama.init_calls) == 1


def test_model_cache_is_thread_safe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = str(tmp_path / "model.gguf")

    def _fetch() -> FakeLlama:
        return ModelCache.get(model_path, n_ctx=1)

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: _fetch(), range(16)))

    assert all(result is results[0] for result in results)
    assert len(FakeLlama.init_calls) == 1


def test_missing_gguf_path_raises_agent_002(tmp_path: Path) -> None:
    definition = _make_definition(tmp_path / "missing.gguf")
    node = _make_node()

    with pytest.raises(AgentError) as excinfo:
        FunctionGemmaRunner(
            definition=definition,
            node=node,
            workspace_id="ws-1",
            cairn_client=FakeCairnClient(),
        )

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"


def test_run_returns_submit_result_on_first_turn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    FakeLlama.responses = [
        _tool_call_response(
            [
                _tool_call(
                    "submit_result",
                    {"summary": "Done", "changed_files": ["src/example.py"], "details": {"count": 1}},
                )
            ]
        )
    ]

    definition = _make_definition(model_path)
    node = _make_node()
    cairn = FakeCairnClient({Path("submit.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "Done"
    assert result.changed_files == ["src/example.py"]
    assert result.workspace_id == "ws-1"
    assert runner.turn_count == 1


def test_run_handles_multiple_tool_turns_then_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

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

    FakeLlama.responses = [
        _tool_call_response([_tool_call("inspect", {"value": "a"}, call_id="call-1")]),
        _tool_call_response([_tool_call("inspect", {"value": "b"}, call_id="call-2")]),
        _tool_call_response([_tool_call("inspect", {"value": "c"}, call_id="call-3")]),
        _tool_call_response(
            [
                _tool_call(
                    "submit_result",
                    {"summary": "Done", "changed_files": [], "details": {"calls": 3}},
                    call_id="call-4",
                )
            ]
        ),
    ]

    definition = _make_definition(model_path, tools=[tool_def, submit_def])
    node = _make_node()
    cairn = FakeCairnClient({Path("inspect.pym"): {"ok": True}, Path("submit.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert runner.turn_count == 4
    assert result.details == {"calls": 3}


def test_run_respects_turn_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    tool_def = ToolDefinition(
        name="inspect",
        pym=Path("inspect.pym"),
        description="Inspect something.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[],
    )

    FakeLlama.responses = [
        _tool_call_response([_tool_call("inspect", {}, call_id="call-1")]),
        _tool_call_response([_tool_call("inspect", {}, call_id="call-2")]),
        _tool_call_response([_tool_call("inspect", {}, call_id="call-3")]),
    ]

    definition = _make_definition(model_path, tools=[tool_def], max_turns=3)
    node = _make_node()
    cairn = FakeCairnClient({Path("inspect.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    result = asyncio.run(runner.run())

    assert result.status == "failed"
    assert result.error is not None
    assert AGENT_003 in result.error
    assert runner.turn_count == 3


def test_run_returns_plain_text_on_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    FakeLlama.responses = [_stop_response("All done")]

    definition = _make_definition(model_path)
    node = _make_node()
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="ws-1",
        cairn_client=FakeCairnClient({Path("submit.pym"): {"ok": True}}),
    )

    result = asyncio.run(runner.run())

    assert result.status == "success"
    assert result.summary == "All done"
    assert result.changed_files == []


def test_context_providers_injected_before_tool_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

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

    FakeLlama.responses = [
        _tool_call_response([_tool_call("inspect", {}, call_id="call-1")]),
        _tool_call_response([_tool_call("submit_result", {"summary": "Done", "changed_files": []}, call_id="call-2")]),
    ]

    definition = _make_definition(model_path, tools=[tool_def, submit_def])
    node = _make_node()
    cairn = FakeCairnClient(
        {
            Path("ctx-1.pym"): {"ctx": "one"},
            Path("ctx-2.pym"): {"ctx": "two"},
            Path("inspect.pym"): {"ok": True},
            Path("submit.pym"): {"ok": True},
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


def test_unknown_tool_is_reported_and_loop_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    submit_def = ToolDefinition(
        name="submit_result",
        pym=Path("submit.pym"),
        description="Submit the result.",
        parameters={"type": "object", "additionalProperties": False, "properties": {}},
        context_providers=[],
    )

    FakeLlama.responses = [
        _tool_call_response(
            [
                _tool_call("unknown_tool", {}, call_id="call-1"),
                _tool_call("submit_result", {"summary": "Done", "changed_files": []}, call_id="call-2"),
            ]
        )
    ]

    definition = _make_definition(model_path, tools=[submit_def])
    node = _make_node()
    cairn = FakeCairnClient({Path("submit.pym"): {"ok": True}})
    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=cairn)

    result = asyncio.run(runner.run())

    assert result.status == "success"
    tool_messages = [json.loads(message["content"]) for message in runner.messages if message.get("role") == "tool"]
    assert any("Unknown tool" in message.get("error", "") for message in tool_messages)
