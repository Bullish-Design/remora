"""Orchestration layer for Remora."""

from __future__ import annotations

import asyncio

from remora.client import build_client
from remora.config import RemoraConfig
from remora.discovery import CSTNode
from remora.results import AgentResult, NodeResult
from remora.runner import CairnClient, FunctionGemmaRunner
from remora.subagent import load_subagent_definition


class Coordinator:
    def __init__(self, config: RemoraConfig, cairn_client: CairnClient) -> None:
        self.config = config
        self.cairn_client = cairn_client
        self._http_client = build_client(config.server)
        self._semaphore = asyncio.Semaphore(config.runner.max_concurrent_runners)

    async def process_node(self, node: CSTNode, operations: list[str]) -> NodeResult:
        runners: dict[str, FunctionGemmaRunner] = {}
        errors: list[dict] = []

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
                    adapter_name=op_config.model_id,
                    http_client=self._http_client,
                )
            except Exception as exc:
                errors.append({"operation": operation, "phase": "init", "error": str(exc)})

        async def run_with_limit(operation: str, runner: FunctionGemmaRunner) -> tuple[str, AgentResult | Exception]:
            async with self._semaphore:
                try:
                    return operation, await runner.run()
                except Exception as exc:
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
