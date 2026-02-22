"""Orchestration layer for Remora."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import suppress
from enum import Enum
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field, field_validator

from remora.config import RemoraConfig
from remora.discovery import CSTNode
from remora.events import (
    CompositeEventEmitter,
    EventEmitter,
    EventStreamController,
    build_event_emitter,
)
from remora.kernel_runner import KernelRunner
from remora.llm_logger import LlmConversationLogger
from remora.results import AgentResult, AgentStatus, NodeResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Remora Agent State & Context (inspired by cairn.runtime.agent)
# ---------------------------------------------------------------------------


class RemoraAgentState(str, Enum):
    """Agent lifecycle states for Remora's orchestration."""

    QUEUED = "queued"
    EXECUTING = "executing"
    COMPLETED = "completed"
    ERRORED = "errored"


class RemoraAgentContext(BaseModel):
    """Structured runtime context for a single agent task.

    Args:
        agent_id: Unique identifier for the agent run.
        task: Human-readable task name.
        operation: Operation name being executed.
        node_id: CST node identifier.
    """

    agent_id: str
    task: str
    operation: str
    node_id: str
    state: RemoraAgentState = RemoraAgentState.QUEUED
    created_at: float = Field(default_factory=time.monotonic)
    state_changed_at: float = Field(default_factory=time.monotonic)

    @field_validator("agent_id")
    @classmethod
    def validate_agent_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("agent_id must be non-empty")
        return value

    def transition(self, new_state: RemoraAgentState) -> None:
        """Move to a new state and update timestamps.

        Args:
            new_state: The new lifecycle state.
        """
        self.state = new_state
        self.state_changed_at = time.monotonic()


# ---------------------------------------------------------------------------
# Phase normalisation helper
# ---------------------------------------------------------------------------


def _normalize_phase(phase: str) -> tuple[str, str | None]:
    """Normalize phase names for event payloads.

    Args:
        phase: Raw phase label.

    Returns:
        Tuple of normalized phase and optional subphase.
    """
    if phase in {"discovery", "grail_check", "execution", "submission"}:
        return phase, None
    if phase in {"merge"}:
        return "submission", phase
    return "execution", phase


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


from cairn.orchestrator.queue import TaskPriority
from cairn.runtime.workspace_cache import WorkspaceCache


PRIORITY_MAP = {
    "low": TaskPriority.LOW,
    "normal": TaskPriority.NORMAL,
    "high": TaskPriority.HIGH,
}


class Coordinator:
    """Coordinate discovery, execution, and workspace management."""

    def __init__(
        self,
        config: RemoraConfig,
        *,
        event_stream_enabled: bool | None = None,
        event_stream_output: Path | None = None,
    ) -> None:
        self.config = config

        self._semaphore = asyncio.Semaphore(config.cairn.max_concurrent_agents)
        self._workspace_cache = WorkspaceCache(max_size=config.cairn.workspace_cache_size)
        self._event_emitter = build_event_emitter(
            config.event_stream,
            enabled_override=event_stream_enabled,
            output_override=event_stream_output,
        )
        self._llm_logger: LlmConversationLogger | None = None
        if config.llm_log.enabled:
            output_path = config.llm_log.output or (
                (config.cairn.home or Path.home() / ".cache" / "remora") / "llm_conversations.log"
            )
            self._llm_logger = LlmConversationLogger(
                output=output_path,
                include_full_prompts=config.llm_log.include_full_prompts,
                max_content_lines=config.llm_log.max_content_lines,
            )
            emitters = cast(list[EventEmitter], [self._event_emitter, self._llm_logger])
            self._event_emitter = CompositeEventEmitter(
                emitters=emitters,
                enabled=True,
                include_payloads=True,  # Composite needs payloads to pass them down
            )

        self._watch_task: asyncio.Task[None] | None = None
        self._running_tasks: set[asyncio.Task[Any]] = set()
        self._shutdown_requested: bool = False

    async def __aenter__(self) -> "Coordinator":
        if isinstance(self._event_emitter, EventStreamController):
            self._watch_task = asyncio.create_task(self._event_emitter.watch())
        elif isinstance(self._event_emitter, CompositeEventEmitter):
            # Check if one of the children is the controller
            for child in self._event_emitter.emitters:
                if isinstance(child, EventStreamController):
                    self._watch_task = asyncio.create_task(child.watch())

        if self._llm_logger:
            self._llm_logger.open()

        self._setup_signal_handlers()
        return self

    async def __aexit__(self, *_: object) -> None:
        # Cancel any in-progress agent tasks on exit
        for task in self._running_tasks:
            task.cancel()
        if self._running_tasks:
            await asyncio.gather(*self._running_tasks, return_exceptions=True)
        self._running_tasks.clear()
        if self._watch_task is not None:
            self._watch_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._watch_task
        if self._llm_logger:
            self._llm_logger.close()
        self._event_emitter.close()
        await self._workspace_cache.clear()

    # -- Signal handling (graceful shutdown) --------------------------------

    def _setup_signal_handlers(self) -> None:
        """Register OS signal handlers for graceful shutdown.

        On Unix, hooks SIGINT and SIGTERM.  On Windows, ``add_signal_handler``
        is not supported for SIGTERM, so we fall back to SIGINT only (the
        default ``KeyboardInterrupt`` path still works as a last resort).
        """
        import signal

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._request_shutdown)
            except NotImplementedError:
                # Windows: SIGTERM not supported via add_signal_handler
                pass

    def _request_shutdown(self) -> None:
        if self._shutdown_requested:
            return
        logger.info("Shutdown signal received, cancelling running tasks…")
        self._shutdown_requested = True
        for task in self._running_tasks:
            task.cancel()

    # -- Node processing ----------------------------------------------------

    async def process_node(self, node: CSTNode, operations: list[str]) -> NodeResult:
        runners: dict[str, tuple[RemoraAgentContext, KernelRunner]] = {}
        errors: list[dict[str, Any]] = []

        for operation in operations:
            if self._shutdown_requested:
                break

            op_config = self.config.operations.get(operation)
            if not op_config or not op_config.enabled:
                continue

            agent_id = f"{operation}-{node.node_id[:8]}-{uuid.uuid4().hex[:4]}"
            ctx = RemoraAgentContext(
                agent_id=agent_id,
                task=f"{operation} on {node.name}",
                operation=operation,
                node_id=node.node_id,
            )

            bundle_path = self.config.agents_dir / op_config.subagent
            workspace_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
            workspace_path = workspace_root / "workspaces" / agent_id
            workspace_path.mkdir(parents=True, exist_ok=True)

            try:
                runner = KernelRunner(
                    node=node,
                    ctx=ctx,
                    config=self.config,
                    bundle_path=bundle_path,
                    event_emitter=self._event_emitter,
                    workspace_path=workspace_path,
                    stable_path=None,
                )
                runners[operation] = (ctx, runner)
            except Exception as exc:
                ctx.transition(RemoraAgentState.ERRORED)
                errors.append({"operation": operation, "phase": "init", "error": str(exc)})

        async def run_with_limit(
            operation: str,
            ctx: RemoraAgentContext,
            runner: KernelRunner,
        ) -> tuple[str, AgentResult]:
            async with self._semaphore:
                ctx.transition(RemoraAgentState.EXECUTING)
                try:
                    result = await runner.run()
                    ctx.transition(RemoraAgentState.COMPLETED)
                    return operation, result
                except Exception as exc:
                    ctx.transition(RemoraAgentState.ERRORED)
                    logger.exception("Runner failed for %s", operation)
                    return (
                        operation,
                        AgentResult(
                            status=AgentStatus.FAILED,
                            workspace_id=ctx.agent_id,
                            changed_files=[],
                            summary="",
                            details={},
                            error=str(exc),
                        ),
                    )

        results: dict[str, AgentResult] = {}
        if runners:
            tasks = [asyncio.create_task(run_with_limit(op, ctx, runner)) for op, (ctx, runner) in runners.items()]
            self._running_tasks.update(tasks)
            try:
                raw_results = await asyncio.gather(*tasks)
            finally:
                self._running_tasks.difference_update(tasks)

            for operation, outcome in raw_results:
                results[operation] = outcome
                if outcome.status == AgentStatus.FAILED and outcome.error:
                    errors.append({"operation": operation, "phase": "run", "error": outcome.error})

        return NodeResult(
            node_id=node.node_id,
            node_name=node.name,
            file_path=node.file_path,
            operations=results,
            errors=errors,
        )
