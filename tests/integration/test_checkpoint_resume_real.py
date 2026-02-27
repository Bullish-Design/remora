from __future__ import annotations

from pathlib import Path

import pytest

from remora.checkpoint import CheckpointManager
from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.discovery import CSTNode, discover
from remora.event_bus import EventBus
from remora.events import AgentStartEvent, CheckpointRestoredEvent
from remora.executor import AgentState, ExecutorState, GraphExecutor
from remora.graph import AgentNode
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


def _make_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text(
        "def first_task():\n    return 1\n\n\ndef second_task():\n    return 2\n",
        encoding="utf-8",
    )
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
async def test_checkpoint_resume_executes_pending(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path)
    nodes = discover([target_file], languages=["python"])
    function_nodes = sorted(
        [node for node in nodes if node.node_type == "function"],
        key=lambda node: node.name,
    )
    assert len(function_nodes) >= 2
    first_node, second_node = function_nodes[:2]

    bundle_dir = tmp_path / "checkpoint_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="checkpoint_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )

    graph = [
        _make_agent_node(first_node, bundle_path),
        _make_agent_node(second_node, bundle_path, {first_node.node_id}),
    ]

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

    warm_bus = EventBus()
    warm_executor = GraphExecutor(config, warm_bus, project_root=project_root)
    first_results = await warm_executor.run([graph[0]], "checkpoint-resume")
    first_summary = first_results[first_node.node_id]

    state = ExecutorState(
        graph_id="checkpoint-resume",
        nodes={node.id: node for node in graph},
        states={
            first_node.node_id: AgentState.COMPLETED,
            second_node.node_id: AgentState.PENDING,
        },
        completed={first_node.node_id: first_summary},
        pending={second_node.node_id},
        failed=set(),
        skipped=set(),
    )

    manager = CheckpointManager(tmp_path / "checkpoints")
    checkpoint_id = await manager.save(state, {})
    restored_state, _ = await manager.restore(checkpoint_id)

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)
    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.resume(restored_state, checkpoint_id=checkpoint_id)

    assert first_node.node_id in results
    assert second_node.node_id in results

    started = {event.agent_id for event in events if isinstance(event, AgentStartEvent)}
    assert second_node.node_id in started
    assert first_node.node_id not in started
    assert any(isinstance(event, CheckpointRestoredEvent) for event in events)
