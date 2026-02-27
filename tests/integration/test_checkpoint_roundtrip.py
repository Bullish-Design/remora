from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.checkpoint import CheckpointManager
from remora.core.executor import AgentState, ExecutorState, ResultSummary
from remora.core.graph import build_graph
from remora.core.discovery import discover


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_checkpoint_roundtrip(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    bundle_path = tmp_path / "bundle.yaml"
    bundle_path.write_text("name: checkpoint\nmodel: qwen\n", encoding="utf-8")

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"file": bundle_path})
    node = graph[0]

    summary = ResultSummary(agent_id=node.id, success=True, output="done")
    state = ExecutorState(
        graph_id="checkpoint",
        nodes={node.id: node},
        states={node.id: AgentState.COMPLETED},
        completed={node.id: summary},
        pending=set(),
        failed=set(),
        skipped=set(),
    )

    manager = CheckpointManager(tmp_path / "checkpoints")
    checkpoint_id = await manager.save(state, {})
    restored, workspaces = await manager.restore(checkpoint_id)

    assert not workspaces
    assert restored.graph_id == state.graph_id
    assert restored.states[node.id] == AgentState.COMPLETED
    assert restored.completed[node.id].output == "done"
    assert restored.nodes[node.id].id == node.id
