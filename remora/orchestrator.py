"""Orchestration layer for Remora."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import suppress
from enum import Enum
from typing import Any
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

from remora.client import build_client
from remora.config import RemoraConfig, resolve_grail_limits
from remora.discovery import CSTNode
from remora.events import EventStreamController, build_event_emitter, CompositeEventEmitter
from remora.execution import ProcessIsolatedExecutor, SnapshotManager
from remora.results import AgentResult, NodeResult
from remora.runner import AgentError, FunctionGemmaRunner
from remora.subagent import load_subagent_definition
from remora.llm_logger import LlmConversationLogger

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

    Replaces the plain ``workspace_id: str`` with a Pydantic model that tracks
    lifecycle state and timestamps, inspired by Cairn's ``AgentContext``.
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
        """Move to *new_state* and update the lifecycle timestamp."""
        self.state = new_state
        self.state_changed_at = time.monotonic()


# ---------------------------------------------------------------------------
# Phase normalisation helper
# ---------------------------------------------------------------------------


def _normalize_phase(phase: str) -> tuple[str, str | None]:
    if phase in {"discovery", "grail_check", "execution", "submission"}:
        return phase, None
    if phase in {"merge"}:
        return "submission", phase
    return "execution", phase


# ---------------------------------------------------------------------------
# Coordinator
# ---------------------------------------------------------------------------


from cairn.orchestrator.queue import TaskQueue, TaskPriority
from cairn.runtime.workspace_manager import WorkspaceManager
from cairn.runtime.workspace_cache import WorkspaceCache
from fsdantic import Fsdantic


PRIORITY_MAP = {
    "low": TaskPriority.LOW,
    "normal": TaskPriority.NORMAL,
    "high": TaskPriority.HIGH,
}


class Coordinator:
    def __init__(
        self,
        config: RemoraConfig,
        *,
        event_stream_enabled: bool | None = None,
        event_stream_output: Path | None = None,
    ) -> None:
        self.config = config

        self._http_client = build_client(config.server)
        self._queue = TaskQueue(max_size=config.cairn.max_queue_size)
        self._semaphore = asyncio.Semaphore(config.cairn.max_concurrent_agents)
        self._workspace_manager = WorkspaceManager()
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
            self._event_emitter = CompositeEventEmitter(
                emitters=[self._event_emitter, self._llm_logger],
                enabled=True,
                include_payloads=True, # Composite needs payloads to pass them down
            )
        self._watch_task: asyncio.Task[None] | None = None
        self._running_tasks: set[asyncio.Task[Any]] = set()
        self._shutdown_requested: bool = False
        # Phase 1: in-process Grail execution
        self._executor = ProcessIsolatedExecutor(
            max_workers=config.cairn.pool_workers,
            call_timeout=float(config.cairn.timeout),
        )
        self._grail_limits = resolve_grail_limits(config.cairn)
        # Phase 6: Snapshot pause/resume (opt-in)
        self._snapshot_manager: SnapshotManager | None = None
        if config.cairn.enable_snapshots:
            self._snapshot_manager = SnapshotManager(
                max_snapshots=config.cairn.max_snapshots,
                max_resumes=config.cairn.max_resumes_per_script,
            )

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
        await self._workspace_manager.close_all()
        await self._workspace_cache.clear()
        await self._executor.shutdown()
        if self._snapshot_manager is not None:
            self._snapshot_manager.clear()

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
        runners: dict[str, tuple[RemoraAgentContext, FunctionGemmaRunner]] = {}
        errors: list[dict] = []

        for operation in operations:
            if self._shutdown_requested:
                break

            op_config = self.config.operations.get(operation)
            if not op_config or not op_config.enabled:
                continue

            agent_id = f"{operation}-{node.node_id}"
            ctx = RemoraAgentContext(
                agent_id=agent_id,
                task=f"{operation} on {node.name}",
                operation=operation,
                node_id=node.node_id,
            )

            definition_path = self.config.agents_dir / op_config.subagent
            try:
                definition = load_subagent_definition(definition_path, agents_dir=self.config.agents_dir)
                self._event_emitter.emit(
                    {
                        "event": "grail_check",
                        "agent_id": ctx.agent_id,
                        "node_id": node.node_id,
                        "operation": operation,
                        "phase": "grail_check",
                        "status": "ok",
                        "warnings": definition.grail_summary.get("warnings", []),
                    }
                )
                runners[operation] = (
                    ctx,
                    FunctionGemmaRunner(
                        definition=definition,
                        node=node,
                        ctx=ctx,
                        server_config=self.config.server,
                        runner_config=self.config.runner,
                        adapter_name=op_config.model_id,
                        http_client=self._http_client,
                        event_emitter=self._event_emitter,
                        grail_executor=self._executor,
                        grail_dir=self.config.cairn.home or Path.cwd(),
                        grail_limits=self._grail_limits,
                        snapshot_manager=self._snapshot_manager,
                    ),
                )
            except Exception as exc:
                ctx.transition(RemoraAgentState.ERRORED)
                errors.append({"operation": operation, "phase": "init", "error": str(exc)})
                phase, step = _normalize_phase("init")
                payload = {
                    "event": "agent_error",
                    "agent_id": ctx.agent_id,
                    "node_id": node.node_id,
                    "operation": operation,
                    "phase": phase,
                    "error": str(exc),
                }
                if step is not None:
                    payload["step"] = step
                self._event_emitter.emit(payload)

        async def run_with_limit(
            operation: str,
            ctx: RemoraAgentContext,
            runner: FunctionGemmaRunner,
        ) -> tuple[str, AgentResult | Exception]:
            async with self._semaphore:
                try:
                    # Phase 4: Manage workspace lifecycle
                    cache_root = self.config.cairn.home or (Path.home() / ".cache" / "remora")
                    workspace_path = cache_root / "workspaces" / ctx.agent_id
                    workspace_path.mkdir(parents=True, exist_ok=True)

                    runner.workspace_root = workspace_path
                    runner.stable_root = Path.cwd()

                    # Track workspace via cache for lifecycle management
                    cache_key = ctx.agent_id
                    ws = self._workspace_cache.get(cache_key)
                    if ws is None:
                        ws = await Fsdantic.open(path=str(workspace_path))
                        self._workspace_cache.put(cache_key, ws)

                    ctx.transition(RemoraAgentState.EXECUTING)
                    try:
                        result = await runner.run()
                        ctx.transition(RemoraAgentState.COMPLETED)
                        return operation, result
                    except Exception as exc:
                        ctx.transition(RemoraAgentState.ERRORED)
                        raw_phase = getattr(exc, "phase", "run")
                        phase, step = _normalize_phase(raw_phase)
                        error_code = getattr(exc, "error_code", None)
                        payload: dict[str, Any] = {
                            "event": "agent_error",
                            "agent_id": ctx.agent_id,
                            "node_id": node.node_id,
                            "operation": operation,
                            "phase": phase,
                            "error": str(exc),
                        }
                        if step is not None:
                            payload["step"] = step
                        if error_code is not None:
                            payload["error_code"] = error_code
                        self._event_emitter.emit(payload)
                        return operation, exc
                    finally:
                        removed_ws = self._workspace_cache.remove(cache_key)
                        if removed_ws is not None:
                            await removed_ws.close()
                        # Phase 6: Clean up any dangling snapshots for this agent
                        if self._snapshot_manager is not None:
                            self._snapshot_manager.cleanup_agent(ctx.agent_id)
                except Exception as setup_exc:
                    logger.error("Workspace setup failed for %s: %s", ctx.agent_id, setup_exc, exc_info=True)
                    ctx.transition(RemoraAgentState.ERRORED)
                    return operation, setup_exc

        results: dict[str, AgentResult] = {}
        if runners:
            tasks = [asyncio.ensure_future(run_with_limit(op, ctx, runner)) for op, (ctx, runner) in runners.items()]
            self._running_tasks.update(tasks)
            try:
                raw = await asyncio.gather(*tasks, return_exceptions=True)
            finally:
                self._running_tasks.difference_update(tasks)

            for item in raw:
                if isinstance(item, BaseException):
                    if isinstance(item, asyncio.CancelledError):
                        # Genuine shutdown cancellation — skip silently
                        continue
                    # Unexpected exception that escaped run_with_limit
                    logger.error(
                        "Unhandled exception in run_with_limit: %s",
                        item,
                        exc_info=item,
                    )
                    errors.append({
                        "operation": "unknown",
                        "phase": "run",
                        "error": str(item),
                    })
                    continue
                operation, outcome = item
                if isinstance(outcome, Exception):
                    errors.append({"operation": operation, "phase": "run", "error": str(outcome)})
                else:
                    results[operation] = outcome

        return NodeResult(
            node_id=node.node_id,
            node_name=node.name,
            file_path=node.file_path,
            operations=results,
            errors=errors,
        )
