"""Graph executor for running agents in dependency order.

Uses structured-agents kernels with Remora-managed tools.
Configuration passed directly - no global environment variables.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import yaml
from structured_agents.agent import get_response_parser, load_manifest
from structured_agents.client import build_client
from structured_agents.events import Event as StructuredEvent
from structured_agents.events.observer import Observer
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.types import Message

from cairn.orchestrator.lifecycle import SUBMISSION_KEY, SubmissionRecord

from remora.core.config import ErrorPolicy, RemoraConfig
from remora.core.context import ContextBuilder
from remora.core.errors import ExecutionError
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentSkippedEvent,
    AgentStartEvent,
    CheckpointRestoredEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    GraphStartEvent,
)
from remora.core.event_bus import EventBus
from remora.core.graph import AgentNode, get_execution_batches
from remora.core.cairn_bridge import CairnWorkspaceService
from remora.core.tools.grail import build_virtual_fs, discover_grail_tools
from remora.core.workspace import CairnDataProvider
from remora.utils import PathResolver

if TYPE_CHECKING:
    from structured_agents.types import RunResult

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Execution state of an agent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class ResultSummary:
    """Summary of an agent execution result."""

    agent_id: str
    success: bool
    output: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize for checkpoint storage."""
        return {
            "agent_id": self.agent_id,
            "success": self.success,
            "output": self.output,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ResultSummary":
        return cls(
            agent_id=data["agent_id"],
            success=data["success"],
            output=data["output"],
            error=data.get("error"),
        )


@dataclass
class ExecutorState:
    """State of graph execution for checkpointing."""

    graph_id: str
    nodes: dict[str, AgentNode]
    states: dict[str, AgentState] = field(default_factory=dict)
    completed: dict[str, ResultSummary] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    failed: set[str] = field(default_factory=set)
    skipped: set[str] = field(default_factory=set)


class _EventBusObserver(Observer):
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def emit(self, event: StructuredEvent) -> None:
        await self._bus.emit(event)


class GraphExecutor:
    """Executes agent graph in dependency order.

    Features:
    - Bounded concurrency via semaphore
    - Error policies (STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE)
    - Event emission at lifecycle points
    - Checkpoint save/restore support
    """

    def __init__(
        self,
        config: RemoraConfig,
        event_bus: EventBus,
        context_builder: ContextBuilder | None = None,
        project_root: Path | str | None = None,
    ):
        self.config = config
        self.event_bus = event_bus
        self.context_builder = context_builder or ContextBuilder()
        self._observer = _EventBusObserver(event_bus)
        self._path_resolver = PathResolver(Path(project_root or Path.cwd()))

        # Subscribe context builder to events
        event_bus.subscribe_all(self.context_builder.handle)

    async def run(
        self,
        graph: list[AgentNode],
        graph_id: str,
    ) -> dict[str, ResultSummary]:
        """Execute all agents in topological order."""
        state = ExecutorState(
            graph_id=graph_id,
            nodes={n.id: n for n in graph},
            pending=set(n.id for n in graph),
        )

        return await self._run_with_state(graph, state, emit_graph_start=True)

    async def resume(
        self,
        state: ExecutorState,
        *,
        checkpoint_id: str | None = None,
    ) -> dict[str, ResultSummary]:
        """Resume execution from a restored checkpoint state."""
        graph = list(state.nodes.values())
        if checkpoint_id:
            await self.event_bus.emit(
                CheckpointRestoredEvent(
                    graph_id=state.graph_id,
                    checkpoint_id=checkpoint_id,
                )
            )
        return await self._run_with_state(graph, state, emit_graph_start=False)

    async def _run_with_state(
        self,
        graph: list[AgentNode],
        state: ExecutorState,
        *,
        emit_graph_start: bool,
    ) -> dict[str, ResultSummary]:
        self._normalize_state(state)

        if emit_graph_start:
            await self.event_bus.emit(
                GraphStartEvent(
                    graph_id=state.graph_id,
                    node_count=len(graph),
                )
            )

        workspace_service = CairnWorkspaceService(
            self.config.workspace,
            state.graph_id,
            project_root=self._path_resolver.project_root,
        )
        await workspace_service.initialize(sync=True)
        semaphore = asyncio.Semaphore(self.config.execution.max_concurrency)

        try:
            batches = get_execution_batches(graph)

            for batch in batches:
                runnable = [
                    n
                    for n in batch
                    if n.id in state.pending and n.id not in state.skipped and n.id not in state.failed
                ]

                if not runnable:
                    continue

                tasks = [self._execute_agent(n, state, workspace_service, semaphore) for n in runnable]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                should_stop = await self._process_results(runnable, results, state, graph)

                if should_stop:
                    break

            await self.event_bus.emit(
                GraphCompleteEvent(
                    graph_id=state.graph_id,
                    completed_count=len(state.completed),
                    failed_count=len(state.failed),
                )
            )

        except Exception as e:
            await self.event_bus.emit(
                GraphErrorEvent(
                    graph_id=state.graph_id,
                    error=str(e),
                )
            )
            raise ExecutionError(f"Graph execution failed: {e}") from e

        finally:
            await workspace_service.close()

        return state.completed

    def _normalize_state(self, state: ExecutorState) -> None:
        node_ids = set(state.nodes)
        if not state.pending:
            state.pending = node_ids - set(state.completed) - set(state.failed) - set(state.skipped)

        for node_id in node_ids:
            if node_id in state.completed:
                state.states[node_id] = AgentState.COMPLETED
            elif node_id in state.failed:
                state.states[node_id] = AgentState.FAILED
            elif node_id in state.skipped:
                state.states[node_id] = AgentState.SKIPPED
            elif node_id in state.pending:
                state.states.setdefault(node_id, AgentState.PENDING)
            else:
                state.states.setdefault(node_id, AgentState.PENDING)

    async def _execute_agent(
        self,
        node: AgentNode,
        state: ExecutorState,
        workspace_service: CairnWorkspaceService,
        semaphore: asyncio.Semaphore,
    ) -> ResultSummary:
        async with semaphore:
            state.states[node.id] = AgentState.RUNNING

            await self.event_bus.emit(
                AgentStartEvent(
                    graph_id=state.graph_id,
                    agent_id=node.id,
                    node_name=node.name,
                )
            )

            try:
                workspace = await workspace_service.get_agent_workspace(node.id)
                externals = workspace_service.get_externals(node.id, workspace)

                data_provider = CairnDataProvider(workspace, self._path_resolver)
                files = await data_provider.load_files(node.target)

                manifest = load_manifest(node.bundle_path)
                requires_context = getattr(manifest, "requires_context", True)
                prompt = self._build_prompt(node, files, requires_context=requires_context)

                async def files_provider() -> dict[str, str | bytes]:
                    current_files = await data_provider.load_files(node.target)
                    return build_virtual_fs(current_files)

                tools = discover_grail_tools(
                    manifest.agents_dir,
                    externals=externals,
                    files_provider=files_provider,
                )

                model_name = self._resolve_model_name(node.bundle_path, manifest)
                result = await self._run_agent(manifest, prompt, tools, model_name=model_name)
                agent_result = cast(Any, result)
                output = getattr(agent_result, "output", None)
                if output is None:
                    final_message = getattr(agent_result, "final_message", None)
                    output = getattr(final_message, "content", "") if final_message else ""

                submission_summary = await self._load_submission_summary(workspace, node.id)
                if submission_summary:
                    output = submission_summary

                summary = ResultSummary(
                    agent_id=node.id,
                    success=True,
                    output=_truncate(str(output), self.config.execution.truncation_limit),
                )

                await self.event_bus.emit(
                    AgentCompleteEvent(
                        graph_id=state.graph_id,
                        agent_id=node.id,
                        result_summary=summary.output[:200],
                    )
                )

                return summary

            except Exception as e:
                logger.error("Agent %s failed: %s", node.id, e)

                summary = ResultSummary(
                    agent_id=node.id,
                    success=False,
                    output="",
                    error=str(e),
                )

                await self.event_bus.emit(
                    AgentErrorEvent(
                        graph_id=state.graph_id,
                        agent_id=node.id,
                        error=str(e),
                    )
                )

                return summary

    async def _run_agent(
        self,
        manifest: Any,
        prompt: str,
        tools: list[Any],
        *,
        model_name: str,
    ) -> "RunResult":
        parser = get_response_parser(manifest.model)
        pipeline = ConstraintPipeline(manifest.grammar_config) if manifest.grammar_config else None

        adapter = ModelAdapter(
            name=manifest.model,
            response_parser=parser,
            constraint_pipeline=pipeline,
        )

        if not model_name:
            model_name = self.config.model.default_model or getattr(manifest, "model", "")
        client = build_client(
            {
                "base_url": self.config.model.base_url,
                "api_key": self.config.model.api_key or "EMPTY",
                "model": model_name,
                "timeout": self.config.execution.timeout,
            }
        )

        kernel = AgentKernel(
            client=client,
            adapter=adapter,
            tools=tools,
            observer=self._observer,
        )

        try:
            messages = [
                Message(role="system", content=manifest.system_prompt),
                Message(role="user", content=prompt),
            ]
            tool_schemas = [tool.schema for tool in tools]
            if manifest.grammar_config and not manifest.grammar_config.send_tools_to_api:
                tool_schemas = []
            max_turns = getattr(manifest, "max_turns", None) or self.config.execution.max_turns
            if self.config.execution.timeout > 0:
                return await asyncio.wait_for(
                    kernel.run(
                        messages,
                        tool_schemas,
                        max_turns=max_turns,
                    ),
                    timeout=self.config.execution.timeout,
                )
            return await kernel.run(
                messages,
                tool_schemas,
                max_turns=max_turns,
            )
        finally:
            await kernel.close()

    def _resolve_model_name(self, bundle_path: Path, manifest: Any) -> str:
        path = bundle_path
        if path.is_dir():
            path = path / "bundle.yaml"

        override: str | None = None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            model_data = data.get("model")
            if isinstance(model_data, dict):
                override = (
                    model_data.get("id")
                    or model_data.get("name")
                    or model_data.get("model")
                )
        except Exception:
            override = None

        if override:
            return str(override)

        return self.config.model.default_model or getattr(manifest, "model", "")

    def _build_prompt(
        self,
        node: AgentNode,
        files: dict[str, str],
        *,
        requires_context: bool,
    ) -> str:
        sections: list[str] = []

        sections.append(f"# Target: {node.name}")
        sections.append(f"File: {node.target.file_path}")
        sections.append(f"Lines: {node.target.start_line}-{node.target.end_line}")

        workspace_path = self._path_resolver.to_workspace_path(node.target.file_path)
        code = files.get(workspace_path)
        if code is None and node.target.file_path in files:
            code = files[node.target.file_path]

        if code is not None:
            sections.append("\n## Code")
            sections.append("```")
            sections.append(code)
            sections.append("```")

        if requires_context:
            context = self.context_builder.build_context_for(node.target)
            if context:
                sections.append(context)

        return "\n".join(sections)

    async def _load_submission_summary(self, workspace: Any, agent_id: str) -> str | None:
        try:
            repo = workspace.cairn.kv.repository(prefix="", model_type=SubmissionRecord)
            record = await repo.load(SUBMISSION_KEY)
        except Exception as exc:
            logger.debug("No submission record for %s: %s", agent_id, exc)
            return None

        if not record or not record.submission:
            return None

        summary = record.submission.get("summary")
        if not summary:
            return None

        return str(summary)

    async def _process_results(
        self,
        nodes: list[AgentNode],
        results: list[ResultSummary | BaseException],
        state: ExecutorState,
        graph: list[AgentNode],
    ) -> bool:
        should_stop = False

        for node, result in zip(nodes, results):
            if isinstance(result, BaseException):
                result = ResultSummary(
                    agent_id=node.id,
                    success=False,
                    output="",
                    error=str(result),
                )

            state.pending.discard(node.id)

            if result.success:
                state.states[node.id] = AgentState.COMPLETED
                state.completed[node.id] = result
            else:
                state.states[node.id] = AgentState.FAILED
                state.failed.add(node.id)

                if self.config.execution.error_policy == ErrorPolicy.STOP_GRAPH:
                    should_stop = True

                elif self.config.execution.error_policy == ErrorPolicy.SKIP_DOWNSTREAM:
                    downstream = self._get_all_downstream(node.id, graph)
                    for skip_id in downstream:
                        if skip_id not in state.completed and skip_id not in state.failed:
                            state.skipped.add(skip_id)
                            state.states[skip_id] = AgentState.SKIPPED
                            state.pending.discard(skip_id)

                            await self.event_bus.emit(
                                AgentSkippedEvent(
                                    graph_id=state.graph_id,
                                    agent_id=skip_id,
                                    reason=f"Upstream agent {node.id} failed",
                                )
                            )

        return should_stop

    def _get_all_downstream(self, node_id: str, graph: list[AgentNode]) -> set[str]:
        node_by_id = {n.id: n for n in graph}
        downstream: set[str] = set()
        queue = list(node_by_id[node_id].downstream)

        while queue:
            current = queue.pop()
            if current not in downstream:
                downstream.add(current)
                if current in node_by_id:
                    queue.extend(node_by_id[current].downstream)

        return downstream


def _truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


__all__ = [
    "AgentState",
    "ResultSummary",
    "ExecutorState",
    "GraphExecutor",
]
