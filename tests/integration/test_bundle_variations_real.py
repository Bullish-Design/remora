from __future__ import annotations

from pathlib import Path

import pytest
from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.events import AgentErrorEvent, AgentStartEvent, KernelEndEvent, ModelRequestEvent, ToolCallEvent
from remora.core.executor import GraphExecutor
from remora.core.graph import build_graph
from tests.integration.helpers import (
    agentfs_available,
    load_vllm_config,
    vllm_available,
    write_bundle,
    write_tool_bundle,
)


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text(
        "class Example:\n"
        "    def method(self) -> int:\n"
        "        return 1\n\n"
        "def helper() -> int:\n"
        "    return 2\n",
        encoding="utf-8",
    )
    return project_root, target_file


def _make_custom_bundle(bundle_dir: Path, *, model_id: str, system_prompt: str) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    tools_dir = bundle_dir / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / "bundle.yaml"
    bundle_path.write_text(
        "\n".join(
            [
                "name: custom_bundle",
                "model:",
                "  plugin: qwen",
                f"  id: {model_id}",
                "initial_context:",
                "  system_prompt: |",
                f"    {system_prompt}",
                "agents_dir: tools",
                "max_turns: 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return bundle_path


@pytest.mark.asyncio
async def test_bundle_max_turns_overrides_execution_config(tmp_path: Path) -> None:
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
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"record_note\", \"arguments\": {\"note\": \"turns\"}}</tool_call>"
    )
    bundle_dir = tmp_path / "turns_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="turns_agent",
        system_prompt=system_prompt,
        tools={"record_note": tool_body},
        max_turns=1,
        include_grammar=False,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=4, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "bundle-max-turns")

    assert results
    kernel_end = next(event for event in events if isinstance(event, KernelEndEvent))
    assert kernel_end.turn_count == 1
    assert kernel_end.termination_reason == "max_turns"


@pytest.mark.asyncio
async def test_bundle_model_override_used_in_request(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")

    project_root, target_file = _make_project(tmp_path)

    bundle_path = _make_custom_bundle(
        tmp_path / "model_override_bundle",
        model_id="bundle-model",
        system_prompt="Respond with OK.",
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_path.parent), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url="http://127.0.0.1:1/v1",
            api_key="EMPTY",
            default_model="config-model",
        ),
        execution=ExecutionConfig(max_turns=1, timeout=0.5),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "bundle-model-override")

    assert not results
    model_request = next(event for event in events if isinstance(event, ModelRequestEvent))
    assert model_request.model == "bundle-model"


@pytest.mark.asyncio
async def test_bundle_missing_file_emits_error(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")

    project_root, target_file = _make_project(tmp_path)
    missing_bundle = tmp_path / "missing" / "bundle.yaml"

    config = RemoraConfig(
        bundles=BundleConfig(path=str(tmp_path), mapping={"function": str(missing_bundle)}),
        model=ModelConfig(
            base_url="http://127.0.0.1:1/v1",
            api_key="EMPTY",
            default_model="unused",
        ),
        execution=ExecutionConfig(max_turns=1, timeout=0.5),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": missing_bundle})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "bundle-missing")

    assert not results
    assert any(isinstance(event, AgentErrorEvent) for event in events)


def test_bundle_node_type_filtering(tmp_path: Path) -> None:
    _, target_file = _make_project(tmp_path)

    nodes = discover([target_file], languages=["python"])
    bundle_path = tmp_path / "bundle.yaml"
    graph = build_graph(nodes, {"function": bundle_path})

    assert graph
    assert all(node.target.node_type == "function" for node in graph)


@pytest.mark.asyncio
async def test_bundle_priority_ordering(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)

    bundle_dir = tmp_path / "priority_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="priority_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"class": bundle_path.name, "function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_concurrency=1, max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(
        nodes,
        {"class": bundle_path, "function": bundle_path},
        priority_mapping={"class": 10, "function": 1},
    )

    class_ids = {node.id for node in graph if node.target.node_type == "class"}
    function_ids = {node.id for node in graph if node.target.node_type == "function"}
    assert class_ids
    assert function_ids

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "bundle-priority")

    assert results
    start_index = {
        event.agent_id: index
        for index, event in enumerate(events)
        if isinstance(event, AgentStartEvent)
    }
    assert min(start_index[agent_id] for agent_id in class_ids) < min(
        start_index[agent_id] for agent_id in function_ids
    )


@pytest.mark.asyncio
async def test_bundle_grammar_send_tools_to_api_false(tmp_path: Path) -> None:
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
        "If you can see a tool list that includes 'record_note', call it.\n"
        "If you cannot see any tool list, respond with exactly: NO_TOOLS.\n"
        "Do not invent tool names."
    )
    bundle_dir = tmp_path / "grammar_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="grammar_agent",
        system_prompt=system_prompt,
        tools={"record_note": tool_body},
        max_turns=1,
        include_grammar=True,
        send_tools_to_api=False,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "bundle-grammar")

    assert results
    summary = next(iter(results.values()))
    assert "NO_TOOLS" in summary.output
    assert not any(isinstance(event, ToolCallEvent) for event in events)
