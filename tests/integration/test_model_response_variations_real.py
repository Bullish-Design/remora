from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.events import AgentErrorEvent, KernelEndEvent, ToolCallEvent, ToolResultEvent
from remora.core.executor import GraphExecutor
from remora.core.graph import build_graph
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle, write_tool_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text(
        "def example(value: int) -> int:\n    return value + 1\n",
        encoding="utf-8",
    )
    return project_root, target_file


def _make_config(tmp_path: Path, bundle_dir: Path, bundle_path: Path, *, max_turns: int, timeout: float = 120.0) -> RemoraConfig:
    return RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=max_turns, timeout=timeout),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )


async def _run_graph(
    tmp_path: Path,
    *,
    bundle_dir: Path,
    bundle_path: Path,
    project_root: Path,
    target_file: Path,
    graph_id: str,
    max_turns: int,
    timeout: float = 120.0,
) -> tuple[dict[str, object], list[object]]:
    config = _make_config(tmp_path, bundle_dir, bundle_path, max_turns=max_turns, timeout=timeout)
    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, graph_id)
    return results, events


@pytest.mark.asyncio
async def test_model_text_only_response(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    tool_body = (
        """
from grail import Input

note: str = Input("note")

result = {"summary": f"note={note}", "outcome": "success"}
result
""".lstrip()
    )

    system_prompt = (
        "Respond with the exact text: TEXT_ONLY_OK. "
        "Do not call any tools, even if they are available."
    )

    bundle_dir = tmp_path / "text_only_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="text_only_agent",
        system_prompt=system_prompt,
        tools={"noop": tool_body},
        max_turns=2,
        include_grammar=False,
    )

    results, events = await _run_graph(
        tmp_path,
        bundle_dir=bundle_dir,
        bundle_path=bundle_path,
        project_root=project_root,
        target_file=target_file,
        graph_id="model-text-only",
        max_turns=2,
    )

    assert results
    summary = next(iter(results.values()))
    assert "TEXT_ONLY_OK" in summary.output
    assert not any(isinstance(event, ToolCallEvent) for event in events)

    kernel_end = next(
        event for event in events if isinstance(event, KernelEndEvent)
    )
    assert kernel_end.termination_reason == "no_tool_calls"


@pytest.mark.asyncio
async def test_model_unknown_tool_call(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    system_prompt = (
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"ghost_tool\", \"arguments\": {\"note\": \"missing\"}}</tool_call>"
    )

    bundle_dir = tmp_path / "unknown_tool_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="unknown_tool_agent",
        system_prompt=system_prompt,
        max_turns=1,
    )

    results, events = await _run_graph(
        tmp_path,
        bundle_dir=bundle_dir,
        bundle_path=bundle_path,
        project_root=project_root,
        target_file=target_file,
        graph_id="model-unknown-tool",
        max_turns=1,
    )

    assert results
    tool_calls = [event for event in events if isinstance(event, ToolCallEvent)]
    assert tool_calls
    assert tool_calls[0].tool_name == "ghost_tool"

    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert not tool_results

    summary = next(iter(results.values()))
    assert "Unknown tool" in summary.output


@pytest.mark.asyncio
async def test_model_invalid_argument_types(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    tool_body = (
        """
from typing import Any
from grail import Input

count: Any = Input("count")

if not isinstance(count, int):
    raise ValueError("count must be int")

result = {"summary": f"count={count}", "outcome": "success"}
result
""".lstrip()
    )

    system_prompt = (
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"validate_count\", \"arguments\": {\"count\": \"not-a-number\"}}</tool_call>"
    )

    bundle_dir = tmp_path / "invalid_args_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="invalid_args_agent",
        system_prompt=system_prompt,
        tools={"validate_count": tool_body},
        max_turns=1,
        include_grammar=True,
        send_tools_to_api=False,
    )

    results, events = await _run_graph(
        tmp_path,
        bundle_dir=bundle_dir,
        bundle_path=bundle_path,
        project_root=project_root,
        target_file=target_file,
        graph_id="model-invalid-args",
        max_turns=1,
    )

    assert results
    tool_results = [event for event in events if isinstance(event, ToolResultEvent)]
    assert tool_results
    assert tool_results[0].is_error is True
    assert "count must be int" in tool_results[0].output_preview


@pytest.mark.asyncio
async def test_model_max_turns_enforced(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    tool_body = (
        """
from grail import Input

value: str = Input("value")

result = {"summary": f"value={value}", "outcome": "success"}
result
""".lstrip()
    )

    system_prompt = (
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"echo_value\", \"arguments\": {\"value\": \"ping\"}}</tool_call>"
    )

    bundle_dir = tmp_path / "max_turns_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="max_turns_agent",
        system_prompt=system_prompt,
        tools={"echo_value": tool_body},
        max_turns=1,
        include_grammar=False,
    )

    results, events = await _run_graph(
        tmp_path,
        bundle_dir=bundle_dir,
        bundle_path=bundle_path,
        project_root=project_root,
        target_file=target_file,
        graph_id="model-max-turns",
        max_turns=1,
    )

    assert results
    assert any(isinstance(event, ToolCallEvent) for event in events)
    kernel_end = next(
        event for event in events if isinstance(event, KernelEndEvent)
    )
    assert kernel_end.termination_reason == "max_turns"


@pytest.mark.asyncio
async def test_model_malformed_tool_call_json(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    system_prompt = (
        "Output exactly this string and nothing else:\n"
        "<tool_call>{this is not valid json}</tool_call>"
    )

    bundle_dir = tmp_path / "malformed_json_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="malformed_json_agent",
        system_prompt=system_prompt,
        max_turns=1,
    )

    results, events = await _run_graph(
        tmp_path,
        bundle_dir=bundle_dir,
        bundle_path=bundle_path,
        project_root=project_root,
        target_file=target_file,
        graph_id="model-malformed-json",
        max_turns=1,
    )

    assert results
    summary = next(iter(results.values()))
    assert "<tool_call>" in summary.output
    assert not any(isinstance(event, ToolCallEvent) for event in events)


@pytest.mark.asyncio
async def test_model_timeout_interrupt(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    system_prompt = (
        "Write a detailed, multi-paragraph explanation of how virtual filesystems "
        "work and include at least 10 bullet points."
    )

    bundle_dir = tmp_path / "timeout_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="timeout_agent",
        system_prompt=system_prompt,
        max_turns=1,
    )

    config = _make_config(tmp_path, bundle_dir, bundle_path, max_turns=1, timeout=0.001)
    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "model-timeout")

    assert not results
    assert any(isinstance(event, AgentErrorEvent) for event in events)
