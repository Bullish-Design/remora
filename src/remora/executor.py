"""Graph Executor - Runs agents in dependency order using structured-agents."""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from remora.graph import AgentNode


class ErrorPolicy(StrEnum):
    """Graph-level error handling policies."""

    STOP_GRAPH = "stop_graph"
    SKIP_DOWNSTREAM = "skip_downstream"
    CONTINUE = "continue"


class RunResult(Protocol):
    """Protocol for agent execution results."""

    @property
    def final_message(self) -> Any: ...

    @property
    def turn_count(self) -> int: ...

    @property
    def termination_reason(self) -> str: ...


@dataclass
class ExecutorState:
    """Tracks execution state across a graph run."""

    graph_id: str
    nodes: dict[str, "AgentNode"]
    completed: dict[str, Any] = field(default_factory=dict)
    pending: set[str] = field(default_factory=set)
    workspaces: dict[str, Any] = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)

    def get_agent_state(self, agent_id: str) -> str:
        """Get current state of an agent."""
        if agent_id in self.completed:
            result = self.completed[agent_id]
            if result is None or isinstance(result, dict) and result.get("error"):
                return "failed"
            return "completed"
        if agent_id in self.pending:
            return "running"
        return "pending"

    def mark_completed(self, agent_id: str, result: Any) -> None:
        """Mark an agent as completed."""
        self.completed[agent_id] = result
        self.pending.discard(agent_id)

    def mark_started(self, agent_id: str) -> None:
        """Mark an agent as started."""
        self.pending.add(agent_id)


@dataclass
class ExecutionConfig:
    """Configuration for graph execution."""

    max_concurrency: int = 4
    timeout: float = 300.0
    error_policy: ErrorPolicy = ErrorPolicy.STOP_GRAPH

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")


async def execute_agent(
    node: "AgentNode",
    workspace: Any,
    observer: Any,
) -> Any:
    """Execute a single agent using structured-agents."""
    from remora.workspace import CairnDataProvider

    data_provider = CairnDataProvider(workspace)

    prompt = _build_agent_prompt(node)

    return {"status": "not_implemented", "node": node.name}


def _build_agent_prompt(node: "AgentNode") -> str:
    """Build the prompt for an agent from its target node."""
    prompt_parts = []

    prompt_parts.append(f"# Target: {node.name}")
    prompt_parts.append(f"# Type: {node.node_type}")
    if node.target.file_path:
        prompt_parts.append(f"# File: {node.target.file_path}")
    prompt_parts.append("")
    prompt_parts.append(node.target.text)

    return "\n".join(prompt_parts)


class GraphExecutor:
    """Runs agents in dependency order with bounded concurrency."""

    def __init__(self, config: ExecutionConfig, event_bus: Any):
        """Initialize the executor."""
        self.config = config
        self.event_bus = event_bus

    async def run(
        self,
        graph: list["AgentNode"],
        workspace_config: Any,
    ) -> dict[str, Any]:
        """Execute all agents in topological order."""
        from remora.events import (
            GraphStartEvent,
            GraphCompleteEvent,
            AgentStartEvent,
            AgentCompleteEvent,
            AgentErrorEvent,
        )
        from remora.graph import get_execution_batches
        from remora.workspace import create_workspace

        graph_id = uuid.uuid4().hex
        results: dict[str, Any] = {}
        state = ExecutorState(
            graph_id=graph_id,
            nodes={node.id: node for node in graph},
        )

        await self.event_bus.emit(
            GraphStartEvent(
                graph_id=graph_id,
                node_count=len(graph),
            )
        )

        batches = get_execution_batches(graph)

        for batch in batches:
            for node in batch:
                ws = await create_workspace(node.id, workspace_config)
                state.workspaces[node.id] = ws

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
                        break
                else:
                    results[node.id] = result
                    state.mark_completed(node.id, result)

        await self.event_bus.emit(
            GraphCompleteEvent(
                graph_id=graph_id,
                results=results,
            )
        )

        return results

    async def _run_batch_parallel(
        self,
        batch: list["AgentNode"],
        state: ExecutorState,
    ) -> list[Any]:
        """Run a batch of nodes in parallel."""
        semaphore = asyncio.Semaphore(self.config.max_concurrency)

        async def run_with_semaphore(node: "AgentNode") -> Any:
            async with semaphore:
                return await self._run_node(node, state)

        tasks = [asyncio.create_task(run_with_semaphore(node)) for node in batch]
        return await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_batch_sequential(
        self,
        batch: list["AgentNode"],
        state: ExecutorState,
    ) -> list[Any]:
        """Run a batch of nodes sequentially."""
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
        node: "AgentNode",
        state: ExecutorState,
    ) -> Any:
        """Run a single node."""
        from remora.events import AgentStartEvent, AgentCompleteEvent, AgentErrorEvent

        workspace = state.workspaces[node.id]
        graph_id = state.graph_id

        await self.event_bus.emit(
            AgentStartEvent(
                graph_id=graph_id,
                agent_id=node.id,
                node={},
            )
        )

        try:
            result = await execute_agent(node, workspace, self.event_bus)

            await self.event_bus.emit(
                AgentCompleteEvent(
                    graph_id=graph_id,
                    agent_id=node.id,
                    result=result,
                )
            )

            return result

        except Exception as e:
            await self.event_bus.emit(
                AgentErrorEvent(
                    graph_id=graph_id,
                    agent_id=node.id,
                    error=str(e),
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
