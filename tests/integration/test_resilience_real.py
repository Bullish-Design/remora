from __future__ import annotations

import os
from pathlib import Path

import pytest

from remora.config import BundleConfig, ErrorPolicy, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.discovery import CSTNode, discover
from remora.event_bus import EventBus
from remora.events import AgentErrorEvent, AgentStartEvent
from remora.executor import AgentState, ExecutorState, GraphExecutor
from remora.graph import AgentNode
from remora.tools.grail import RemoraGrailTool
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()


def _make_project(tmp_path: Path, *, functions: int) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    body: list[str] = []
    for index in range(functions):
        body.append(f"def func_{index}():")
        body.extend(["    value = 1" for _ in range(12)])
        body.append("    return value")
        body.append("")
    target_file.write_text("\n".join(body), encoding="utf-8")
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
async def test_vllm_unavailable_mid_execution(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    project_root, target_file = _make_project(tmp_path, functions=2)
    nodes = discover([target_file], languages=["python"])
    function_nodes = sorted(
        [node for node in nodes if node.node_type == "function"],
        key=lambda node: node.name,
    )
    assert len(function_nodes) >= 2
    first_node, second_node = function_nodes[:2]

    bundle_dir = tmp_path / "resilience_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="resilience_agent",
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
    warm_results = await warm_executor.run([graph[0]], "resilience-mid-exec")
    first_summary = warm_results[first_node.node_id]

    state = ExecutorState(
        graph_id="resilience-mid-exec",
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

    failure_config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url="http://127.0.0.1:1/v1",
            api_key="EMPTY",
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=1, timeout=0.5),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(failure_config, event_bus, project_root=project_root)
    results = await executor.resume(state, checkpoint_id="mid-exec")

    assert first_node.node_id in results
    error_agents = {event.agent_id for event in events if isinstance(event, AgentErrorEvent)}
    assert second_node.node_id in error_agents


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exception, expected",
    [
        (ConnectionError("network partition"), "network partition"),
        (OSError(28, "No space left on device"), "No space left on device"),
    ],
)
async def test_tool_external_failure_is_reported(
    tmp_path: Path,
    exception: Exception,
    expected: str,
) -> None:
    tool_path = tmp_path / "tools"
    tool_path.mkdir(parents=True, exist_ok=True)
    script_path = tool_path / "unstable.pym"
    script_path.write_text(
        """
from grail import Input, external

path: str = Input("path")

@external
async def write_file(path: str) -> bool:
    ...

await write_file(path)
result = {"summary": "wrote", "outcome": "success"}
result
""".lstrip(),
        encoding="utf-8",
    )

    async def failing_write(path: str) -> bool:
        raise exception

    async def files_provider() -> dict[str, str]:
        return {}

    tool = RemoraGrailTool(
        script_path,
        externals={"write_file": failing_write},
        files_provider=files_provider,
    )

    result = await tool.execute({"path": "output.txt"}, None)

    assert result.is_error is True
    assert expected in result.output


@pytest.mark.asyncio
async def test_large_graph_graceful_degradation_under_load(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    function_count = int(os.environ.get("REMORA_RESILIENCE_FUNCTIONS", "8"))
    min_success = float(os.environ.get("REMORA_RESILIENCE_MIN_SUCCESS", "0.7"))
    concurrency = int(os.environ.get("REMORA_RESILIENCE_CONCURRENCY", "4"))

    project_root, target_file = _make_project(tmp_path, functions=function_count)
    nodes = discover([target_file], languages=["python"])
    function_nodes = sorted(
        [node for node in nodes if node.node_type == "function"],
        key=lambda node: node.name,
    )[:function_count]
    assert function_nodes

    bundle_dir = tmp_path / "resilience_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="resilience_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )
    missing_bundle = tmp_path / "missing" / "bundle.yaml"

    graph: list[AgentNode] = []
    valid_nodes: set[str] = set()
    for index, node in enumerate(function_nodes):
        if index % 3 == 0:
            graph.append(_make_agent_node(node, missing_bundle))
        else:
            graph.append(_make_agent_node(node, bundle_path))
            valid_nodes.add(node.node_id)

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(
            max_concurrency=max(1, concurrency),
            max_turns=1,
            timeout=120,
            error_policy=ErrorPolicy.CONTINUE,
        ),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "resilience-load")

    assert results
    success_rate = len(results) / max(len(valid_nodes), 1)
    assert success_rate >= min_success

    error_agents = {event.agent_id for event in events if isinstance(event, AgentErrorEvent)}
    assert error_agents
    started_agents = {event.agent_id for event in events if isinstance(event, AgentStartEvent)}
    assert started_agents.issuperset(valid_nodes)
