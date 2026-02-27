from __future__ import annotations

from pathlib import Path

import pytest

from remora.config import (
    BundleConfig,
    ErrorPolicy,
    ExecutionConfig,
    ModelConfig,
    RemoraConfig,
    WorkspaceConfig,
)
from remora.discovery import discover
from remora.event_bus import EventBus
from remora.events import AgentErrorEvent, AgentSkippedEvent
from remora.executor import GraphExecutor
from remora.graph import build_graph
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


@pytest.mark.asyncio
async def test_vllm_skip_downstream_on_failure(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text(
        "def first():\n    return 1\n\n\ndef second():\n    return 2\n",
        encoding="utf-8",
    )

    file_bundle_dir = tmp_path / "file_bundle"
    file_bundle_path = write_bundle(
        file_bundle_dir,
        system_prompt="You are a test agent. Respond briefly.",
        max_turns=1,
    )
    function_bundle_dir = tmp_path / "function_bundle"
    function_bundle_path = write_bundle(
        function_bundle_dir,
        system_prompt="You are a test agent. Respond briefly.",
        max_turns=1,
    )

    config = RemoraConfig(
        bundles=BundleConfig(path=str(tmp_path), mapping={}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(
            max_turns=1,
            timeout=0.001,
            error_policy=ErrorPolicy.SKIP_DOWNSTREAM,
        ),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    nodes = discover([target_file], languages=["python"])
    graph = build_graph(nodes, {"file": file_bundle_path, "function": function_bundle_path})
    file_nodes = [node for node in graph if node.target.node_type == "file"]
    function_nodes = [node for node in graph if node.target.node_type == "function"]

    assert file_nodes
    assert function_nodes

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "skip-downstream")

    assert not results
    error_agents = {event.agent_id for event in events if isinstance(event, AgentErrorEvent)}
    skipped_agents = {event.agent_id for event in events if isinstance(event, AgentSkippedEvent)}
    assert file_nodes[0].id in error_agents
    assert skipped_agents == {node.id for node in function_nodes}
