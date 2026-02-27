from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.context import ContextBuilder
from remora.core.discovery import CSTNode, discover
from remora.core.event_bus import EventBus
from remora.core.executor import GraphExecutor
from remora.core.graph import AgentNode
from tests.integration.helpers import (
    agentfs_available,
    load_vllm_config,
    vllm_available,
    write_bundle,
    write_tool_bundle,
)


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


def _make_project(tmp_path: Path, *, function_count: int) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    functions = [
        f"def func_{index}():\n    return {index}\n" for index in range(function_count)
    ]
    target_file.write_text("\n".join(functions), encoding="utf-8")
    return project_root, target_file


def _make_agent_node(
    node: CSTNode,
    bundle_path: Path,
    upstream: set[str] | None = None,
) -> AgentNode:
    return AgentNode(
        id=node.node_id,
        name=node.name,
        target=node,
        bundle_path=bundle_path,
        upstream=frozenset(upstream or set()),
        downstream=frozenset(),
    )


@pytest.mark.asyncio
async def test_context_builder_injects_recent_and_prior(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path, function_count=2)
    nodes = discover([target_file], languages=["python"])
    function_nodes = sorted(
        [node for node in nodes if node.node_type == "function"],
        key=lambda node: node.name,
    )
    assert len(function_nodes) >= 2
    first_node, second_node = function_nodes[:2]

    tool_body = (
        """
from grail import Input

note: str = Input("note")

result = {"summary": f"note={note}", "outcome": "success"}
result
""".lstrip()
    )
    tool_prompt = (
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"record_note\", \"arguments\": {\"note\": \"first\"}}</tool_call>"
    )
    tool_bundle_dir = tmp_path / "tool_bundle"
    tool_bundle_path = write_tool_bundle(
        tool_bundle_dir,
        name="tool_agent",
        system_prompt=tool_prompt,
        tools={"record_note": tool_body},
        max_turns=1,
        include_grammar=False,
    )

    check_prompt = (
        "If the user prompt includes both '## Recent Actions' and '## Prior Analysis', "
        "respond exactly with CONTEXT_OK. Otherwise respond with CONTEXT_MISSING."
    )
    check_bundle_dir = tmp_path / "check_bundle"
    check_bundle_path = write_bundle(
        check_bundle_dir,
        name="check_agent",
        system_prompt=check_prompt,
        max_turns=1,
    )

    graph = [
        _make_agent_node(first_node, tool_bundle_path),
        _make_agent_node(second_node, check_bundle_path, {first_node.node_id}),
    ]

    config = RemoraConfig(
        bundles=BundleConfig(path=str(tmp_path), mapping={}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=2, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    context_builder = ContextBuilder()

    executor = GraphExecutor(
        config,
        event_bus,
        context_builder=context_builder,
        project_root=project_root,
    )
    results = await executor.run(graph, "context-injection")

    assert results
    assert "CONTEXT_OK" in results[second_node.node_id].output

    recent_actions = context_builder.get_recent_actions()
    assert recent_actions
    assert recent_actions[-1].tool == "record_note"

    knowledge = context_builder.get_knowledge()
    assert first_node.node_id in knowledge
    assert second_node.node_id in knowledge


@pytest.mark.asyncio
async def test_context_builder_recent_window_trims(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path, function_count=3)
    nodes = discover([target_file], languages=["python"])
    function_nodes = sorted(
        [node for node in nodes if node.node_type == "function"],
        key=lambda node: node.name,
    )
    assert len(function_nodes) >= 3

    tool_body = (
        """
from grail import Input

note: str = Input("note")

result = {"summary": f"note={note}", "outcome": "success"}
result
""".lstrip()
    )
    tool_prompt = (
        "Output exactly this tool call and nothing else:\n"
        "<tool_call>{\"name\": \"record_note\", \"arguments\": {\"note\": \"step\"}}</tool_call>"
    )
    tool_bundle_dir = tmp_path / "tool_bundle"
    tool_bundle_path = write_tool_bundle(
        tool_bundle_dir,
        name="tool_agent",
        system_prompt=tool_prompt,
        tools={"record_note": tool_body},
        max_turns=1,
        include_grammar=False,
    )

    graph = []
    upstream: set[str] = set()
    for node in function_nodes[:3]:
        graph.append(_make_agent_node(node, tool_bundle_path, upstream.copy()))
        upstream = {node.node_id}

    config = RemoraConfig(
        bundles=BundleConfig(path=str(tmp_path), mapping={}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    context_builder = ContextBuilder(window_size=2)

    executor = GraphExecutor(
        config,
        event_bus,
        context_builder=context_builder,
        project_root=project_root,
    )
    results = await executor.run(graph, "context-window")

    assert results
    recent_actions = context_builder.get_recent_actions()
    assert len(recent_actions) == 2
