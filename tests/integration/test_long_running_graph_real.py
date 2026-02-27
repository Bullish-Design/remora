from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

from remora.cairn_bridge import CairnWorkspaceService
from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.discovery import discover
from remora.event_bus import EventBus
from remora.events import AgentCompleteEvent, AgentStartEvent
from remora.executor import GraphExecutor
from remora.graph import build_graph
from remora.utils import PathResolver
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_bundle, write_tool_bundle


pytestmark = [pytest.mark.integration, pytest.mark.slow]

VLLM_CONFIG = load_vllm_config()
FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "complex_graph_project"


def _log(message: str, indent: int = 0) -> None:
    prefix = "  " * indent
    print(f"{prefix}{message}")


def _format_seconds(seconds: float) -> str:
    return f"{seconds:.2f}s"


def _count_events(events: list[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        name = type(event).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


def _log_event_counts(events: list[object], indent: int = 0) -> None:
    counts = _count_events(events)
    if not counts:
        _log("events: none", indent)
        return
    _log("events:", indent)
    for name in sorted(counts):
        _log(f"{name}={counts[name]}", indent + 1)


@pytest.mark.asyncio
async def test_long_running_graph_end_to_end(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    start_time = time.perf_counter()
    _log("Long-running graph integration test")

    max_functions = int(os.environ.get("REMORA_LONG_GRAPH_FUNCTIONS", "60"))
    min_success = float(os.environ.get("REMORA_LONG_GRAPH_MIN_SUCCESS", "0.9"))
    concurrency = int(os.environ.get("REMORA_LONG_GRAPH_CONCURRENCY", "6"))

    _log("Config", 1)
    _log(f"max_functions={max_functions}", 2)
    _log(f"min_success={min_success:.2f}", 2)
    _log(f"concurrency={concurrency}", 2)

    project_root = tmp_path / "project"
    src_dir = project_root / "src"
    src_dir.mkdir(parents=True)

    _log("Project setup", 1)
    setup_time = time.perf_counter()
    fixture_files = [
        FIXTURE_ROOT / "large_module.py",
        FIXTURE_ROOT / "alpha.py",
    ]
    for fixture in fixture_files:
        target = src_dir / fixture.name
        target.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
        _log(f"synced fixture: {fixture.name}", 2)

    nodes = discover([project_root], languages=["python"])
    function_nodes = [node for node in nodes if node.node_type == "function"]
    file_nodes = [node for node in nodes if node.node_type == "file"]

    _log("Discovery", 1)
    discovery_time = time.perf_counter()
    _log(f"files={len(file_nodes)} functions={len(function_nodes)}", 2)

    assert function_nodes
    if max_functions > 0:
        function_nodes = function_nodes[:max_functions]
        _log(f"trimmed functions to {len(function_nodes)}", 2)

    selected_file_paths = {node.file_path for node in function_nodes}
    file_nodes = [node for node in file_nodes if node.file_path in selected_file_paths]
    nodes = file_nodes + function_nodes
    _log(f"graph nodes: files={len(file_nodes)} functions={len(function_nodes)}", 2)

    outputs_root = project_root.as_posix()

    _log("Bundle setup", 1)
    bundle_time = time.perf_counter()
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

await write_file(path, content)
await submit_result(summary, [path])
result = {"summary": summary, "outcome": "success"}
result
""".lstrip()
    )

    system_prompt = (
        "You are a tool-calling agent.\n"
        "Call the tool `write_and_submit` exactly once.\n"
        "The target name appears after '# Target:' in the user prompt.\n"
        f"Set `path` to '{outputs_root}/<target>.txt' where <target> is that name.\n"
        "Set `content` to '<target>'.\n"
        "Set `summary` to 'wrote <target>'.\n"
        "Do not respond with any other text."
    )

    bundle_root = tmp_path / "long_bundle"
    function_bundle = write_tool_bundle(
        bundle_root / "function",
        name="long_function_agent",
        system_prompt=system_prompt,
        tools={"write_and_submit": tool_body},
        max_turns=2,
    )
    file_bundle = write_bundle(
        bundle_root / "file",
        name="long_file_agent",
        system_prompt="Respond with OK.",
        max_turns=1,
    )
    _log(f"function bundle: {function_bundle}", 2)
    _log(f"file bundle: {file_bundle}", 2)

    config = RemoraConfig(
        bundles=BundleConfig(
            path=str(bundle_root),
            mapping={"function": function_bundle.name, "file": file_bundle.name},
        ),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(
            max_concurrency=max(1, concurrency),
            max_turns=2,
            timeout=180,
        ),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )

    graph = build_graph(nodes, {"function": function_bundle, "file": file_bundle})
    _log(f"graph built: {len(graph)} agent nodes", 1)

    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    _log("Execution", 1)
    exec_start = time.perf_counter()
    executor = GraphExecutor(config, event_bus, project_root=project_root)
    results = await executor.run(graph, "long-graph")
    exec_end = time.perf_counter()

    assert results
    _log(f"completed agents: {len(results)}", 2)

    start_index = {
        event.agent_id: idx
        for idx, event in enumerate(events)
        if isinstance(event, AgentStartEvent)
    }
    complete_index = {
        event.agent_id: idx
        for idx, event in enumerate(events)
        if isinstance(event, AgentCompleteEvent)
    }

    _log("Dependency checks", 1)
    dependency_time = time.perf_counter()
    for file_node in file_nodes:
        file_complete = complete_index[file_node.node_id]
        dependent_starts = [
            start_index[node.node_id]
            for node in function_nodes
            if node.file_path == file_node.file_path
        ]
        assert dependent_starts
        assert file_complete < min(dependent_starts)
        _log(f"file node {Path(file_node.file_path).name} completes before dependents", 2)

    resolver = PathResolver(project_root)
    service = CairnWorkspaceService(config.workspace, "long-graph", project_root=project_root)
    await service.initialize(sync=False)

    _log("Workspace validation", 1)
    validation_start = time.perf_counter()
    success = 0
    for node in function_nodes:
        expected_summary = f"wrote {node.name}"
        expected_path = Path(outputs_root) / f"{node.name}.txt"
        expected_workspace_path = resolver.to_workspace_path(expected_path)
        workspace = await service.get_agent_workspace(node.node_id)
        try:
            content = await workspace.read(expected_workspace_path)
        except Exception:
            content = None

        summary = results.get(node.node_id)
        if summary and summary.output == expected_summary and content == node.name:
            success += 1
            _log(f"[ok] {node.name} -> {expected_workspace_path}", 2)
        else:
            _log(f"[miss] {node.name} -> {expected_workspace_path}", 2)

    await service.close()

    validation_end = time.perf_counter()
    success_rate = success / len(function_nodes)
    _log(f"success_rate={success_rate:.2f}", 1)

    total_time = time.perf_counter() - start_time
    _log("Summary", 1)
    _log(f"setup={_format_seconds(discovery_time - setup_time)}", 2)
    _log(f"discovery={_format_seconds(bundle_time - discovery_time)}", 2)
    _log(f"bundle_setup={_format_seconds(exec_start - bundle_time)}", 2)
    _log(f"execution={_format_seconds(exec_end - exec_start)}", 2)
    _log(f"dependency_checks={_format_seconds(validation_start - dependency_time)}", 2)
    _log(f"workspace_validation={_format_seconds(validation_end - validation_start)}", 2)
    _log(f"total={_format_seconds(total_time)}", 2)
    _log_event_counts(events, 2)
    assert success_rate >= min_success
