from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from remora.discovery import CSTNode
from remora.errors import AGENT_002
from remora.runner import AgentError, FunctionGemmaRunner, ModelCache
from remora.subagent import InitialContext, SubagentDefinition, ToolDefinition


class FakeLlama:
    init_calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        FakeLlama.init_calls.append(kwargs)


@pytest.fixture(autouse=True)
def _clear_model_cache() -> None:
    ModelCache.clear()
    FakeLlama.init_calls.clear()
    yield
    ModelCache.clear()


def _make_definition(model_path: Path) -> SubagentDefinition:
    return SubagentDefinition(
        name="lint_agent",
        model=model_path,
        max_turns=10,
        initial_context=InitialContext(
            system_prompt="You are a lint agent.",
            node_context="node {{ node_name }} {{ node_type }} {{ node_text }}",
        ),
        tools=[
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
        ],
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


def test_runner_initializes_model_and_messages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("remora.runner.Llama", FakeLlama)
    model_path = tmp_path / "model.gguf"
    model_path.write_text("", encoding="utf-8")

    definition = _make_definition(model_path)
    node = _make_node()

    runner = FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=object())

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
        FunctionGemmaRunner(definition=definition, node=node, workspace_id="ws-1", cairn_client=object())

    error = excinfo.value
    assert error.error_code == AGENT_002
    assert error.node_id == node.node_id
    assert error.operation == definition.name
    assert error.phase == "model_load"
