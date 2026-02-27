from __future__ import annotations

import asyncio
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest
from structured_agents.events import ToolCallEvent, ToolResultEvent

from remora.cairn_bridge import CairnWorkspaceService
from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.discovery import CSTNode, discover
from remora.event_bus import EventBus
from remora.executor import GraphExecutor, ResultSummary
from remora.graph import build_graph
from remora.utils import PathResolver
from tests.integration.helpers import agentfs_available, load_vllm_config, vllm_available, write_tool_bundle


pytestmark = pytest.mark.integration

VLLM_CONFIG = load_vllm_config()

DEFAULT_RUNS = int(os.environ.get("REMORA_WORKFLOW_RUNS", "20"))
DEFAULT_CONCURRENCY = int(os.environ.get("REMORA_WORKFLOW_CONCURRENCY", "8"))
DEFAULT_MIN_SUCCESS = float(os.environ.get("REMORA_WORKFLOW_MIN_SUCCESS", "0.8"))


@dataclass(frozen=True, slots=True)
class TrialSpec:
    index: int
    graph_id: str
    bundle_dir: Path
    bundle_path: Path
    output_path: Path
    content: str
    summary: str


@dataclass(frozen=True, slots=True)
class TrialResult:
    spec: TrialSpec
    success: bool
    stage: str
    error_type: str
    error_detail: str | None
    had_tool_call: bool
    had_tool_result: bool
    summary_output: str | None


@pytest.mark.asyncio
async def test_vllm_agent_workflow_concurrent(tmp_path: Path) -> None:
    if not await agentfs_available():
        pytest.skip("AgentFS not reachable")
    if not vllm_available(VLLM_CONFIG["base_url"]):
        pytest.skip("vLLM server not reachable")

    runs = max(1, DEFAULT_RUNS)
    concurrency = max(1, DEFAULT_CONCURRENCY)
    min_success = max(0.0, min(1.0, DEFAULT_MIN_SUCCESS))

    project_root = tmp_path / "project"
    project_root.mkdir()
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "sample.py"
    target_file.write_text("def hello():\n    return 'hi'\n", encoding="utf-8")

    nodes = discover([target_file], languages=["python"])
    tool_body = _build_tool_body()

    specs: list[TrialSpec] = []
    bundles_root = tmp_path / "bundles"
    bundles_root.mkdir()

    for index in range(runs):
        output_path = project_root / f"output-{index}.txt"
        content = f"payload-{index}"
        summary = f"workflow-{index}-ok"
        system_prompt = _build_system_prompt(output_path, content, summary)

        bundle_dir = bundles_root / f"bundle-{index}"
        bundle_path = write_tool_bundle(
            bundle_dir,
            name=f"workflow_agent_{index}",
            system_prompt=system_prompt,
            tools={"write_and_submit": tool_body},
            max_turns=3,
        )

        specs.append(
            TrialSpec(
                index=index,
                graph_id=f"workflow-{index:03d}",
                bundle_dir=bundle_dir,
                bundle_path=bundle_path,
                output_path=output_path,
                content=content,
                summary=summary,
            )
        )

    semaphore = asyncio.Semaphore(min(concurrency, runs))

    async def run_trial(spec: TrialSpec) -> TrialResult:
        async with semaphore:
            return await _run_workflow_trial(spec, nodes, project_root, tmp_path / "workspaces")

    results = await asyncio.gather(*(run_trial(spec) for spec in specs))

    report = _format_report(results)
    print(report)

    success_count = sum(1 for result in results if result.success)
    success_rate = success_count / len(results) if results else 0.0
    assert success_rate >= min_success, report


async def _run_workflow_trial(
    spec: TrialSpec,
    nodes: list[CSTNode],
    project_root: Path,
    workspace_root: Path,
) -> TrialResult:
    event_bus = EventBus()
    events: list[object] = []
    event_bus.subscribe_all(events.append)

    config = RemoraConfig(
        bundles=BundleConfig(path=str(spec.bundle_dir), mapping={"function": spec.bundle_path.name}),
        model=ModelConfig(
            base_url=VLLM_CONFIG["base_url"],
            api_key=VLLM_CONFIG["api_key"],
            default_model=VLLM_CONFIG["model"],
        ),
        execution=ExecutionConfig(max_turns=3, timeout=120),
        workspace=WorkspaceConfig(base_path=str(workspace_root)),
    )

    graph = build_graph(nodes, {"function": spec.bundle_path})
    executor = GraphExecutor(config, event_bus, project_root=project_root)

    try:
        results = await executor.run(graph, spec.graph_id)
    except Exception as exc:
        return TrialResult(
            spec=spec,
            success=False,
            stage="executor",
            error_type="exception",
            error_detail=str(exc),
            had_tool_call=False,
            had_tool_result=False,
            summary_output=None,
        )

    had_tool_call = any(isinstance(event, ToolCallEvent) for event in events)
    had_tool_result = any(isinstance(event, ToolResultEvent) for event in events)

    if not results:
        return TrialResult(
            spec=spec,
            success=False,
            stage="executor",
            error_type="no_results",
            error_detail=None,
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=None,
        )

    summary = next(iter(results.values()))
    if not isinstance(summary, ResultSummary) or not summary.success:
        return TrialResult(
            spec=spec,
            success=False,
            stage="executor",
            error_type="agent_error",
            error_detail=getattr(summary, "error", None),
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=getattr(summary, "output", None),
        )

    if not had_tool_call:
        return TrialResult(
            spec=spec,
            success=False,
            stage="model",
            error_type="missing_tool_call",
            error_detail=None,
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    if not had_tool_result:
        return TrialResult(
            spec=spec,
            success=False,
            stage="tool",
            error_type="missing_tool_result",
            error_detail=None,
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    tool_errors = [
        event
        for event in events
        if isinstance(event, ToolResultEvent) and getattr(event, "is_error", False)
    ]
    if tool_errors:
        return TrialResult(
            spec=spec,
            success=False,
            stage="tool",
            error_type="tool_error",
            error_detail=str(getattr(tool_errors[0], "output_preview", "")),
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    if summary.output != spec.summary:
        return TrialResult(
            spec=spec,
            success=False,
            stage="submission",
            error_type="summary_mismatch",
            error_detail=f"expected={spec.summary} actual={summary.output}",
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    agent_id = next(iter(results.keys()))
    workspace_result = await _read_workspace_output(
        workspace_root,
        spec.graph_id,
        project_root,
        agent_id,
        spec.output_path,
    )

    if workspace_result.error:
        return TrialResult(
            spec=spec,
            success=False,
            stage="workspace",
            error_type="workspace_error",
            error_detail=workspace_result.error,
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    if workspace_result.content != spec.content:
        return TrialResult(
            spec=spec,
            success=False,
            stage="workspace",
            error_type="content_mismatch",
            error_detail=f"expected={spec.content} actual={workspace_result.content}",
            had_tool_call=had_tool_call,
            had_tool_result=had_tool_result,
            summary_output=summary.output,
        )

    return TrialResult(
        spec=spec,
        success=True,
        stage="success",
        error_type="",
        error_detail=None,
        had_tool_call=had_tool_call,
        had_tool_result=had_tool_result,
        summary_output=summary.output,
    )


@dataclass(frozen=True, slots=True)
class WorkspaceOutput:
    content: str | None
    error: str | None


async def _read_workspace_output(
    workspace_root: Path,
    graph_id: str,
    project_root: Path,
    agent_id: str,
    output_path: Path,
) -> WorkspaceOutput:
    service = CairnWorkspaceService(WorkspaceConfig(base_path=str(workspace_root)), graph_id, project_root=project_root)
    try:
        await service.initialize(sync=False)
        workspace = await service.get_agent_workspace(agent_id)
        resolver = PathResolver(project_root)
        workspace_path = resolver.to_workspace_path(output_path)
        content = await workspace.read(workspace_path)
        return WorkspaceOutput(content=content, error=None)
    except Exception as exc:
        return WorkspaceOutput(content=None, error=str(exc))
    finally:
        await service.close()


def _build_system_prompt(output_path: Path, content: str, summary: str) -> str:
    return (
        "You are a strict tool-calling agent.\n"
        "Call the tool `write_and_submit` exactly once with:\n"
        f'- path: "{output_path}"\n'
        f'- content: "{content}"\n'
        f'- summary: "{summary}"\n'
        "Do not respond with any other text."
    )


def _build_tool_body() -> str:
    return (
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


def _format_report(results: list[TrialResult]) -> str:
    total = len(results)
    success_count = sum(1 for result in results if result.success)
    success_rate = success_count / total if total else 0.0
    tool_calls = sum(1 for result in results if result.had_tool_call)
    tool_results = sum(1 for result in results if result.had_tool_result)

    failures = [result for result in results if not result.success]
    error_counts = Counter(f"{result.stage}:{result.error_type}" for result in failures)

    lines = [
        "Agent workflow report",
        f"total={total} success={success_count} success_rate={success_rate:.1%}",
        f"tool_calls={tool_calls} tool_results={tool_results}",
    ]

    if error_counts:
        lines.append("failures:")
        for key, count in error_counts.most_common():
            lines.append(f"- {key} count={count} rate={count / total:.1%}")

    if failures:
        lines.append("examples:")
        for result in failures[:5]:
            detail = f" detail={result.error_detail}" if result.error_detail else ""
            lines.append(f"- {result.spec.graph_id} {result.stage}:{result.error_type}{detail}")

    return "\n".join(lines)
