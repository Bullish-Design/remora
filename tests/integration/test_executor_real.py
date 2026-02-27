from __future__ import annotations

from pathlib import Path

import pytest
from structured_agents.events import ModelResponseEvent, ToolCallEvent, ToolResultEvent

from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.context import ContextBuilder
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.executor import GraphExecutor
from remora.core.graph import build_graph
from remora.utils import PathResolver
from tests.integration.helpers import (
    agentfs_available,
    load_vllm_config,
    vllm_available,
    write_bundle,
    write_tool_bundle,
)


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


@pytest.mark.asyncio
async def test_vllm_graph_executor_end_to_end(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    bundle_dir = tmp_path / "smoke_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        system_prompt="You are a test agent. Respond with a short confirmation.",
        max_turns=2,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=2, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)
    context_builder = ContextBuilder()

    executor = GraphExecutor(
        config,
        event_bus,
        context_builder=context_builder,
        project_root=project_root,
    )
    results = await executor.run(graph, "graph-e2e")

    assert results
    assert any(isinstance(event, ModelResponseEvent) for event in events)
    assert context_builder.get_knowledge()


@pytest.mark.asyncio
async def test_vllm_tool_call_writes_and_submits(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def greet():\n    return 'hello'\n", encoding="utf-8")

    output_path = project_root / "output.txt"
    content = "hello from tool"
    summary = "tool wrote output"

    tool_body = (
        """
from grail import Input, external

path: str = Input("path")
content: str = Input("content")
summary: str = Input("summary")

@external
async def write_file(path: str, content: str) -> bool:
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    ...

try:
    await write_file(path, content)
    await submit_result(summary, [path])
    result = {"summary": summary, "outcome": "success"}
except Exception as exc:
    result = {"summary": f"error: {exc}", "outcome": "error", "error": str(exc)}

result
""".lstrip()
    )

    system_prompt = (
        "You are a strict tool-calling agent.\n"
        "Call the tool `write_and_submit` exactly once with:\n"
        f'- path: "{output_path}"\n'
        f'- content: "{content}"\n'
        f'- summary: "{summary}"\n'
        "Do not respond with any other text."
    )

    bundle_dir = tmp_path / "tool_bundle"
    bundle_path = write_tool_bundle(
        bundle_dir,
        name="tool_agent",
        system_prompt=system_prompt,
        tools={"write_and_submit": tool_body},
        max_turns=3,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=3, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"function": bundle_path})

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "tool-call")

    assert results
    result = next(iter(results.values()))
    assert result.output == summary
    assert any(isinstance(event, ToolCallEvent) for event in events)
    assert any(isinstance(event, ToolResultEvent) for event in events)

    agent_id = next(iter(results.keys()))
    workspace_service = CairnWorkspaceService(config.workspace, "tool-call", project_root=project_root)
    await workspace_service.initialize(sync=False)
    workspace = await workspace_service.get_agent_workspace(agent_id)
    resolver = PathResolver(project_root)
    workspace_path = resolver.to_workspace_path(output_path)
    stored = await workspace.read(workspace_path)
    assert stored == content
    await workspace_service.close()
