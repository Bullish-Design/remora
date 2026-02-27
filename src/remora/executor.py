"""Graph executor for running agents in dependency order.

Uses structured-agents Agent.from_bundle() for execution.
Configuration passed directly - no global environment variables.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from structured_agents import Agent
from structured_agents.events import Event as StructuredEvent
from structured_agents.events.observer import Observer
from structured_agents.exceptions import KernelError

from remora.config import ErrorPolicy, RemoraConfig
from remora.context import ContextBuilder
from remora.errors import ExecutionError
from remora.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentSkippedEvent,
    AgentStartEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    GraphStartEvent,
)
from remora.event_bus import EventBus
from remora.graph import AgentNode, get_execution_batches
from remora.workspace import CairnDataProvider, WorkspaceManager

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
    ):
        self.config = config
        self.event_bus = event_bus
        self.context_builder = context_builder or ContextBuilder()
        self._observer = _EventBusObserver(event_bus)

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

        # Initialize states for detected nodes
        for node_id in state.nodes:
            state.states[node_id] = AgentState.PENDING

        await self.event_bus.emit(
            GraphStartEvent(
                graph_id=graph_id,
                node_count=len(graph),
            )
        )

        workspace_mgr = WorkspaceManager(self.config.workspace, graph_id)
        semaphore = asyncio.Semaphore(self.config.execution.max_concurrency)

        try:
            batches = get_execution_batches(graph)

            for batch in batches:
                runnable = [n for n in batch if n.id not in state.skipped and n.id not in state.failed]

                if not runnable:
                    continue

                tasks = [self._execute_agent(n, state, workspace_mgr, semaphore) for n in runnable]

                results = await asyncio.gather(*tasks, return_exceptions=True)

                should_stop = await self._process_results(runnable, results, state, graph)

                if should_stop:
                    break

            await self.event_bus.emit(
                GraphCompleteEvent(
                    graph_id=graph_id,
                    completed_count=len(state.completed),
                    failed_count=len(state.failed),
                )
            )

        except Exception as e:
            await self.event_bus.emit(
                GraphErrorEvent(
                    graph_id=graph_id,
                    error=str(e),
                )
            )
            raise ExecutionError(f"Graph execution failed: {e}") from e

        finally:
            await workspace_mgr.cleanup()

        return state.completed

    async def _execute_agent(
        self,
        node: AgentNode,
        state: ExecutorState,
        workspace_mgr: WorkspaceManager,
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
                workspace = await workspace_mgr.get_workspace(node.id)

                data_provider = CairnDataProvider(workspace)
                files = await data_provider.load_files(node.target)

                prompt = self._build_prompt(node, files)
                result = await self._run_agent(node, prompt)
                agent_result = cast(Any, result)
                output = getattr(agent_result, "output", None)
                if output is None:
                    final_message = getattr(agent_result, "final_message", None)
                    output = getattr(final_message, "content", "") if final_message else ""

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

    async def _run_agent(self, node: AgentNode, prompt: str) -> "RunResult":
        agent = await Agent.from_bundle(
            node.bundle_path,
            observer=self._observer,
            base_url=self.config.model.base_url,
            api_key=self.config.model.api_key or None,
            model=self.config.model.default_model,
        )

        try:
            return await agent.run(
                prompt,
                max_turns=self.config.execution.max_turns,
            )
        finally:
            await agent.close()

    def _build_prompt(self, node: AgentNode, files: dict[str, str]) -> str:
        sections: list[str] = []

        sections.append(f"# Target: {node.name}")
        sections.append(f"File: {node.target.file_path}")
        sections.append(f"Lines: {node.target.start_line}-{node.target.end_line}")

        if node.target.file_path in files:
            sections.append("\n## Code")
            sections.append("```")
            sections.append(node.target.text)
            sections.append("```")

        context = self.context_builder.build_context_for(node.target)
        if context:
            sections.append(context)

        return "\n".join(sections)

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
