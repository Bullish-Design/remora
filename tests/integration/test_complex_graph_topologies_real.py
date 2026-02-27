from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.discovery import CSTNode, discover
from remora.core.event_bus import EventBus
from remora.core.events import AgentCompleteEvent, AgentStartEvent
from remora.core.executor import GraphExecutor
from remora.core.graph import AgentNode, get_execution_batches
from remora.core.errors import GraphError
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "complex_graph_project"


def _load_fixture_nodes() -> dict[str, CSTNode]:
    paths = [
        FIXTURE_ROOT / "alpha.py",
        FIXTURE_ROOT / "beta.py",
        FIXTURE_ROOT / "gamma.py",
        FIXTURE_ROOT / "delta.py",
    ]
    nodes = discover(paths, languages=["python"])
    function_nodes = {node.name: node for node in nodes if node.node_type == "function"}
    return function_nodes


def _make_agent_node(node: CSTNode, bundle_path: Path, upstream: set[str] | None = None) -> AgentNode:
    return AgentNode(
        id=node.node_id,
        name=node.name,
        target=node,
        bundle_path=bundle_path,
        upstream=frozenset(upstream or set()),
        downstream=frozenset(),
    )


def _index_events(events: list[object], event_type: type[object]) -> dict[str, int]:
    return {
        event.agent_id: index
        for index, event in enumerate(events)
        if isinstance(event, event_type)
    }


@pytest.mark.asyncio
async def test_deep_dependency_chain_execution_order(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    nodes_by_name = _load_fixture_nodes()
    alpha = nodes_by_name["alpha_task"]
    beta = nodes_by_name["beta_task"]
    gamma = nodes_by_name["gamma_task"]
    delta = nodes_by_name["delta_task"]
    assert {alpha.file_path, beta.file_path, gamma.file_path, delta.file_path} == {
        str(FIXTURE_ROOT / "alpha.py"),
        str(FIXTURE_ROOT / "beta.py"),
        str(FIXTURE_ROOT / "gamma.py"),
        str(FIXTURE_ROOT / "delta.py"),
    }

    bundle_dir = tmp_path / "chain_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="chain_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )

    graph = [
        _make_agent_node(alpha, bundle_path),
        _make_agent_node(beta, bundle_path, {alpha.node_id}),
        _make_agent_node(gamma, bundle_path, {beta.node_id}),
        _make_agent_node(delta, bundle_path, {gamma.node_id}),
    ]

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_concurrency=2, max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=FIXTURE_ROOT)
    results = await executor.run(graph, "chain-graph")

    assert set(results.keys()) == {node.id for node in graph}

    start_index = _index_events(events, AgentStartEvent)
    complete_index = _index_events(events, AgentCompleteEvent)

    assert complete_index[alpha.node_id] < start_index[beta.node_id]
    assert complete_index[beta.node_id] < start_index[gamma.node_id]
    assert complete_index[gamma.node_id] < start_index[delta.node_id]


@pytest.mark.asyncio
async def test_diamond_dependency_execution_order(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    nodes_by_name = _load_fixture_nodes()
    alpha = nodes_by_name["alpha_task"]
    beta = nodes_by_name["beta_task"]
    gamma = nodes_by_name["gamma_task"]
    delta = nodes_by_name["delta_task"]
    assert {alpha.file_path, beta.file_path, gamma.file_path, delta.file_path} == {
        str(FIXTURE_ROOT / "alpha.py"),
        str(FIXTURE_ROOT / "beta.py"),
        str(FIXTURE_ROOT / "gamma.py"),
        str(FIXTURE_ROOT / "delta.py"),
    }

    bundle_dir = tmp_path / "diamond_bundle"
    bundle_path = write_bundle(
        bundle_dir,
        name="diamond_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )

    graph = [
        _make_agent_node(alpha, bundle_path),
        _make_agent_node(beta, bundle_path, {alpha.node_id}),
        _make_agent_node(gamma, bundle_path, {alpha.node_id}),
        _make_agent_node(delta, bundle_path, {beta.node_id, gamma.node_id}),
    ]

    config = RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_concurrency=2, max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    executor = GraphExecutor(config, event_bus, project_root=FIXTURE_ROOT)
    results = await executor.run(graph, "diamond-graph")

    assert set(results.keys()) == {node.id for node in graph}

    start_index = _index_events(events, AgentStartEvent)
    complete_index = _index_events(events, AgentCompleteEvent)

    assert complete_index[alpha.node_id] < start_index[beta.node_id]
    assert complete_index[alpha.node_id] < start_index[gamma.node_id]
    assert start_index[delta.node_id] > complete_index[beta.node_id]
    assert start_index[delta.node_id] > complete_index[gamma.node_id]


def test_large_graph_batches() -> None:
    large_file = FIXTURE_ROOT / "large_module.py"
    nodes = discover([large_file], languages=["python"])
    function_nodes = [node for node in nodes if node.node_type == "function"]
    assert len(function_nodes) >= 50

    dummy_bundle = Path(__file__)
    graph = [_make_agent_node(node, dummy_bundle) for node in function_nodes]
    batches = get_execution_batches(graph)

    assert len(batches) == 1
    assert {node.id for node in batches[0]} == {node.node_id for node in function_nodes}


def test_cycle_detection_raises() -> None:
    nodes_by_name = _load_fixture_nodes()
    alpha = nodes_by_name["alpha_task"]
    beta = nodes_by_name["beta_task"]
    gamma = nodes_by_name["gamma_task"]

    dummy_bundle = Path(__file__)
    graph = [
        _make_agent_node(alpha, dummy_bundle, {gamma.node_id}),
        _make_agent_node(beta, dummy_bundle, {alpha.node_id}),
        _make_agent_node(gamma, dummy_bundle, {beta.node_id}),
    ]

    with pytest.raises(GraphError):
        get_execution_batches(graph)
