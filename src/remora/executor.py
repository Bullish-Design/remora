from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from structured_agents.agent import Agent
from structured_agents.exceptions import KernelError
from structured_agents.types import RunResult

from remora.context import ContextBuilder
from remora.config import RemoraConfig
from remora.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    GraphCompleteEvent,
    GraphStartEvent,
    ToolResultEvent,
)
from remora.graph import AgentNode, get_execution_batches
from remora.workspace import (
    CairnDataProvider,
    CairnResultHandler,
    CairnWorkspace,
    ResultSummary,
    create_workspace,
)


class ErrorPolicy(StrEnum):
    """Graph-level error handling policies."""

    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


@dataclass
class ExecutorState:
    """Tracks execution state across a graph run."""

    graph_id: str
    nodes: dict[str, AgentNode]
    completed: dict[str, ResultSummary] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    workspaces: dict[str, CairnWorkspace] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def get_agent_state(self, agent_id: str) -> str:
        if agent_id in self.completed:
            summary = self.completed[agent_id]
            if not summary.success:
                return "failed"
            return "completed"
        if agent_id in self.pending:
            return "running"
        return "pending"

    def mark_completed(self, agent_id: str, summary: ResultSummary) -> None:
        self.completed[agent_id] = summary
        self.pending.discard(agent_id)

    def mark_started(self, agent_id: str) -> None:
        self.pending.add(agent_id)


@dataclass
class ExecutionConfig:
    """Configuration for graph execution."""

    max_concurrency: int = 4
    timeout: float = 300.0
    error_policy: ErrorPolicy = ErrorPolicy.STOP_GRAPH
    max_turns: int = 10

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.max_turns < 1:
            raise ValueError("max_turns must be >= 1")


async def execute_agent(
    node: AgentNode,
    workspace: CairnWorkspace,
    context_builder: ContextBuilder,
    result_handler: CairnResultHandler,
    observer: Any,
    remora_config: RemoraConfig,
    max_turns: int,
) -> ResultSummary:
    """Execute an agent via structured-agents and persist outputs."""
    data_provider = CairnDataProvider(workspace)
    prompt = await _build_agent_prompt(node, context_builder, data_provider)

    _set_structured_agents_env(remora_config)

    agent = await Agent.from_bundle(node.bundle_path, observer=observer)
    try:
        run_result = await agent.run(prompt, max_turns=max_turns)
    finally:
        await agent.close()

    payload = _parse_payload(run_result.final_message.content)
    summary = await result_handler.handle(node.id, run_result, payload, workspace)
    return summary


async def _build_agent_prompt(
    node: AgentNode,
    context_builder: ContextBuilder,
    data_provider: CairnDataProvider,
) -> str:
    parts: list[str] = []

    context = context_builder.build_context_for(node)
    if context.strip():
        parts.append("## Context")
        parts.append(context)

    parts.append("## Target Node")
    parts.append(f"- id: {node.id}")
    parts.append(f"- name: {node.name}")
    parts.append(f"- type: {node.target.node_type}")
    if node.target.file_path:
        parts.append(f"- file: {node.target.file_path}")

    parts.append("\n## Source")
    if node.target.text:
        parts.append(_truncate(node.target.text))

    files = await data_provider.load_files(node.target)
    if files:
        parts.append("\n## Workspace Files")
        for path in sorted(files):
            content = files[path]
            text = content.decode("utf-8", errors="ignore") if isinstance(content, (bytes, bytearray)) else str(content)
            parts.append(f"### {path}\n{_truncate(text)}")

    return "\n".join(parts)


def _truncate(text: str, limit: int = 1024) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _parse_payload(content: str | None) -> dict[str, Any]:
    if not content:
        return {}
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {
            "message": content,
        }


def _set_structured_agents_env(config: RemoraConfig) -> None:
    os.environ["STRUCTURED_AGENTS_BASE_URL"] = config.model_base_url
    os.environ["STRUCTURED_AGENTS_API_KEY"] = config.api_key


class GraphExecutor:
    """Runs agents in dependency order with bounded concurrency."""

    def __init__(
        self,
        config: ExecutionConfig,
        event_bus: Any,
        remora_config: RemoraConfig,
        context_builder: ContextBuilder | None = None,
        result_handler: CairnResultHandler | None = None,
    ) -> None:
        self.config = config
        self.event_bus = event_bus
        self.remora_config = remora_config
        self.context_builder = context_builder or ContextBuilder()
        self.result_handler = result_handler or CairnResultHandler()
        self._subscribe_context_builder()

    def _subscribe_context_builder(self) -> None:
        self.event_bus.subscribe(ToolResultEvent, self.context_builder.handle)
        self.event_bus.subscribe(AgentCompleteEvent, self.context_builder.handle)

    async def run(
        self,
        graph: list[AgentNode],
        workspace_config: Any,
    ) -> dict[str, Any]:
        graph_id = uuid.uuid4().hex
        results: dict[str, dict[str, Any]] = {}
        state = ExecutorState(
            graph_id=graph_id,
            nodes={node.id: node for node in graph},
        )

        self.context_builder.clear()

        await self.event_bus.emit(
            GraphStartEvent(
                graph_id=graph_id,
                node_count=len(graph),
            )
        )

        batches = get_execution_batches(graph)
        stop_execution = False

        for batch in batches:
            for node in batch:
                ws_handle = await create_workspace(node.id, workspace_config)
                state.workspaces[node.id] = ws_handle
                state.mark_started(node.id)

            if self.config.max_concurrency > 1:
                batch_results = await self._run_batch_parallel(batch, state)
            else:
                batch_results = await self._run_batch_sequential(batch, state)

            for node, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    await self.event_bus.emit(
                        AgentErrorEvent(
                            graph_id=graph_id,
                            agent_id=node.id,
                            error=str(result),
                        )
                    )
                    if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
                        stop_execution = True
                        break
                elif isinstance(result, ResultSummary):
                    results[node.id] = result.to_dict()
                    state.mark_completed(node.id, result)

            if stop_execution:
                break

        await self.event_bus.emit(
            GraphCompleteEvent(
                graph_id=graph_id,
                results=results,
            )
        )

        for workspace_handle in state.workspaces.values():
            await workspace_handle.close()

        return results

    async def _run_batch_parallel(
        self,
        batch: list[AgentNode],
        state: ExecutorState,
    ) -> list[Any]:
        semaphore = asyncio.Semaphore(self.config.max_concurrency)

        async def run_with_semaphore(node: AgentNode) -> Any:
            async with semaphore:
                return await self._run_node(node, state)

        tasks = [asyncio.create_task(run_with_semaphore(node)) for node in batch]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_batch_sequential(
        self,
        batch: list[AgentNode],
        state: ExecutorState,
    ) -> list[Any]:
        results = []
        for node in batch:
            try:
                result = await self._run_node(node, state)
                results.append(result)
            except Exception as e:
                results.append(e)
        return results

    async def _run_node(
        self,
        node: AgentNode,
        state: ExecutorState,
    ) -> Any:
        workspace_handle = state.workspaces[node.id]
        graph_id = state.graph_id

        await self.event_bus.emit(
            AgentStartEvent(
                graph_id=graph_id,
                agent_id=node.id,
                node={
                    "name": node.name,
                    "target": str(node.target.file_path),
                },
            )
        )

        try:
            summary = await execute_agent(
                node,
                workspace_handle,
                self.context_builder,
                self.result_handler,
                self.event_bus,
                self.remora_config,
                self.config.max_turns,
            )

            await self.event_bus.emit(
                AgentCompleteEvent(
                    graph_id=graph_id,
                    agent_id=node.id,
                    result=summary.to_dict(),
                )
            )
            self.context_builder.ingest_summary(summary)

            return summary

        except KernelError as exc:
            await self.event_bus.emit(
                AgentErrorEvent(
                    graph_id=graph_id,
                    agent_id=node.id,
                    error=str(exc),
                )
            )
            if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
                raise
            return None
        except Exception as exc:
            await self.event_bus.emit(
                AgentErrorEvent(
                    graph_id=graph_id,
                    agent_id=node.id,
                    error=str(exc),
                )
            )
            if self.config.error_policy == ErrorPolicy.STOP_GRAPH:
                raise
            return None


__all__ = [
    "GraphExecutor",
    "ExecutorState",
    "ExecutionConfig",
    "ErrorPolicy",
    "execute_agent",
]
