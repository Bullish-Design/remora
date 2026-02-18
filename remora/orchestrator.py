"""Orchestration layer for Remora."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any
from pathlib import Path

from remora.client import build_client
from remora.config import RemoraConfig
from remora.discovery import CSTNode
from remora.events import EventStreamController, build_event_emitter
from remora.results import AgentResult, NodeResult
from remora.runner import AgentError, CairnClient, FunctionGemmaRunner
from remora.subagent import load_subagent_definition


class Coordinator:
    def __init__(
        self,
        config: RemoraConfig,
        cairn_client: CairnClient,
        *,
        event_stream_enabled: bool | None = None,
        event_stream_output: Path | None = None,
    ) -> None:
        self.config = config
        self.cairn_client = cairn_client
        self._http_client = build_client(config.server)
        self._semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)
        self._event_emitter = build_event_emitter(
            config.event_stream,
            enabled_override=event_stream_enabled,
            output_override=event_stream_output,
        )

    async def process_node(self, node: CSTNode, operations: list[str]) -> NodeResult:
        runners: dict[str, FunctionGemmaRunner] = {}
        errors: list[dict] = []
        watch_task: asyncio.Task[None] | None = None

        if isinstance(self._event_emitter, EventStreamController):
            watch_task = asyncio.create_task(self._event_emitter.watch())

        try:
            for operation in operations:
                op_config = self.config.operations.get(operation)
                if not op_config or not op_config.enabled:
                    continue
                definition_path = self.config.agents_dir / op_config.subagent
                try:
                    definition = load_subagent_definition(definition_path, agents_dir=self.config.agents_dir)
                    runners[operation] = FunctionGemmaRunner(
                        definition=definition,
                        node=node,
                        workspace_id=f"{operation}-{node.node_id}",
                        cairn_client=self.cairn_client,
                        server_config=self.config.server,
                        runner_config=self.config.runner,
                        adapter_name=op_config.model_id,
                        http_client=self._http_client,
                        event_emitter=self._event_emitter,
                    )
                except Exception as exc:
                    errors.append({"operation": operation, "phase": "init", "error": str(exc)})
                    self._event_emitter.emit(
                        {
                            "event": "agent_error",
                            "agent_id": f"{operation}-{node.node_id}",
                            "node_id": node.node_id,
                            "operation": operation,
                            "phase": "init",
                            "error": str(exc),
                        }
                    )

            async def run_with_limit(
                operation: str, runner: FunctionGemmaRunner
            ) -> tuple[str, AgentResult | Exception]:
                async with self._semaphore:
                    try:
                        return operation, await runner.run()
                    except Exception as exc:
                        phase = exc.phase if isinstance(exc, AgentError) else "run"
                        error_code = exc.error_code if isinstance(exc, AgentError) else None
                        payload: dict[str, Any] = {
                            "event": "agent_error",
                            "agent_id": runner.workspace_id,
                            "node_id": node.node_id,
                            "operation": operation,
                            "phase": phase,
                            "error": str(exc),
                        }
                        if error_code is not None:
                            payload["error_code"] = error_code
                        self._event_emitter.emit(payload)
                        return operation, exc

            results: dict[str, AgentResult] = {}
            if runners:
                raw = await asyncio.gather(
                    *[run_with_limit(operation, runner) for operation, runner in runners.items()],
                    return_exceptions=True,
                )
                for item in raw:
                    if isinstance(item, BaseException):
                        errors.append({"phase": "run", "error": str(item)})
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
        finally:
            if watch_task is not None:
                watch_task.cancel()
                with suppress(asyncio.CancelledError):
                    await watch_task
            self._event_emitter.close()
