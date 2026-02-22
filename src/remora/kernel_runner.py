"""KernelRunner - Remora's wrapper around structured-agents AgentKernel."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from structured_agents import (
    AgentKernel,
    GrailBackend,
    GrailBackendConfig,
    KernelConfig,
    ToolResult,
    load_bundle,
)

from remora.config import RemoraConfig
from remora.context import ContextManager
from remora.context.summarizers import get_default_summarizers
from remora.discovery import CSTNode
from remora.event_bridge import RemoraEventBridge
from remora.events import EventEmitter
from remora.externals import create_remora_externals
from remora.results import AgentResult, AgentStatus

if TYPE_CHECKING:
    from remora.orchestrator import RemoraAgentContext

logger = logging.getLogger(__name__)


class KernelRunner:
    """Remora's wrapper around structured-agents AgentKernel.

    This class:
    1. Loads bundles and configures the kernel
    2. Creates Remora-specific Grail externals
    3. Bridges events to Remora's EventEmitter
    4. Manages ContextManager state
    5. Formats results into Remora's AgentResult
    """

    def __init__(
        self,
        node: CSTNode,
        ctx: RemoraAgentContext,
        config: RemoraConfig,
        bundle_path: Path,
        event_emitter: EventEmitter,
        workspace_path: Path | None = None,
        stable_path: Path | None = None,
        *,
        backend_factory: Callable[[GrailBackendConfig, Callable], GrailBackend] | None = None,
    ):
        self.node = node
        self.ctx = ctx
        self.config = config
        self.bundle_path = bundle_path
        self.event_emitter = event_emitter
        self.workspace_path = workspace_path
        self.stable_path = stable_path

        self.bundle = load_bundle(bundle_path)

        self.context_manager = ContextManager(
            initial_context={
                "agent_id": ctx.agent_id,
                "goal": f"{self.bundle.name} on {node.name}",
                "operation": self.bundle.name,
                "node_id": node.node_id,
                "node_summary": self._summarize_node(),
            },
            summarizers=get_default_summarizers(),
        )

        self._observer = RemoraEventBridge(
            emitter=event_emitter,
            context_manager=self.context_manager,
            agent_id=ctx.agent_id,
            node_id=node.node_id,
            operation=self.bundle.name,
        )

        self._backend: GrailBackend | None = None
        self._backend_factory = backend_factory

        self._kernel = self._build_kernel()

    def _summarize_node(self) -> str:
        """Create a short summary of the target node."""
        lines = self.node.text.split("\n")
        if len(lines) > 5:
            return "\n".join(lines[:3]) + f"\n... ({len(lines)} lines total)"
        return self.node.text

    def _build_kernel(self) -> AgentKernel:
        """Build the structured-agents kernel with Remora configuration."""
        kernel_config = KernelConfig(
            base_url=self.config.server.base_url,
            model=self.bundle.manifest.model.adapter or self.config.server.default_adapter,
            api_key=self.config.server.api_key,
            timeout=float(self.config.server.timeout),
            max_tokens=self.config.runner.max_tokens,
            temperature=self.config.runner.temperature,
            tool_choice=self.config.runner.tool_choice,
        )

        backend_config = GrailBackendConfig(
            grail_dir=self.config.cairn.home or self.config.agents_dir,
            max_workers=self.config.cairn.pool_workers,
            timeout=float(self.config.cairn.timeout),
            limits={
                **(self._get_limits_for_preset(self.config.cairn.limits_preset)),
                **self.config.cairn.limits_override,
            },
        )

        if self._backend_factory:
            self._backend = self._backend_factory(backend_config, self._create_externals)
        else:
            self._backend = GrailBackend(
                config=backend_config,
                externals_factory=self._create_externals,
            )

        tool_source = self.bundle.build_tool_source(self._backend)
        grammar_config = self.bundle.get_grammar_config()
        plugin = self.bundle.get_plugin()

        return AgentKernel(
            config=kernel_config,
            plugin=plugin,
            tool_source=tool_source,
            observer=self._observer,
            grammar_config=grammar_config,
            max_history_messages=self.config.runner.max_history_messages,
        )

    def _get_limits_for_preset(self, preset: str) -> dict[str, Any]:
        """Get Grail limits for a preset name."""
        presets = {
            "strict": {
                "max_memory_mb": 256,
                "max_duration_s": 30,
                "max_recursion": 50,
            },
            "default": {
                "max_memory_mb": 512,
                "max_duration_s": 60,
                "max_recursion": 100,
            },
            "permissive": {
                "max_memory_mb": 1024,
                "max_duration_s": 120,
                "max_recursion": 200,
            },
        }
        return presets.get(preset, presets["default"])

    def _create_externals(
        self,
        agent_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Create Remora-specific Grail external functions.

        The context dict from GrailBackend contains:
        - workspace_path: str | None
        - stable_path: str | None
        - node_source: str | None
        - node_metadata: dict | None
        """
        return create_remora_externals(
            agent_id=agent_id,
            node_source=context.get("node_source") or self.node.text,
            node_metadata=context.get("node_metadata")
            or {
                "name": self.node.name,
                "type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
                "start_line": self.node.start_line,
                "end_line": self.node.end_line,
            },
            workspace_path=context.get("workspace_path") or (str(self.workspace_path) if self.workspace_path else None),
            stable_path=context.get("stable_path") or (str(self.stable_path) if self.stable_path else None),
        )

    async def _provide_context(self) -> dict[str, Any]:
        """Provide per-turn context to the kernel.

        This is called at the start of each turn to inject
        fresh context into tool execution.
        """
        await self.context_manager.pull_hub_context()

        return {
            "node_text": self.node.text,
            "target_file": str(self.node.file_path),
            "workspace_id": self.ctx.agent_id,
            "agent_id": self.ctx.agent_id,
            "workspace_path": str(self.workspace_path) if self.workspace_path else None,
            "stable_path": str(self.stable_path) if self.stable_path else None,
            "node_source": self.node.text,
            "node_metadata": {
                "name": self.node.name,
                "type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
                "node_id": self.node.node_id,
            },
            **self.context_manager.get_prompt_context(),
        }

    async def run(self) -> AgentResult:
        """Execute the agent loop via structured-agents."""
        initial_messages = self.bundle.build_initial_messages(
            {
                "node_text": self.node.text,
                "node_name": self.node.name,
                "node_type": str(self.node.node_type),
                "file_path": str(self.node.file_path),
            }
        )

        def is_termination_tool(result: ToolResult) -> bool:
            return result.name == self.bundle.termination_tool

        try:
            result = await self._kernel.run(
                initial_messages=initial_messages,
                tools=self.bundle.tool_schemas,
                max_turns=self.bundle.max_turns,
                termination=is_termination_tool,
                context_provider=self._provide_context,
            )

            return self._format_result(result)

        except Exception as exc:
            from remora.errors import ExecutionError
            logger.exception("KernelRunner failed for %s", self.node.node_id)
            return AgentResult(
                status=AgentStatus.FAILED,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary=f"KernelRunner failed with {type(exc).__name__}: {str(exc)}",
                details={},
                error=str(exc),
            )

        finally:
            await self._kernel.close()
            if self._backend:
                self._backend.shutdown()

    def _format_result(self, result) -> AgentResult:
        """Convert structured-agents RunResult to Remora's AgentResult."""
        if result.termination_reason == "termination_tool" and result.final_tool_result:
            output = result.final_tool_result.output

            if isinstance(output, str):
                try:
                    output = json.loads(output)
                except json.JSONDecodeError:
                    output = {"summary": output}

            if isinstance(output, dict):
                status_str = output.get("status", "success")
                status = self._parse_status(status_str)

                return AgentResult(
                    status=status,
                    workspace_id=self.ctx.agent_id,
                    changed_files=output.get("changed_files", []),
                    summary=output.get("summary", ""),
                    details=output.get("details", {}),
                    error=output.get("error"),
                )

        if result.termination_reason == "no_tool_calls":
            return AgentResult(
                status=AgentStatus.SUCCESS,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary=result.final_message.content or "Completed without tool calls",
                details={"termination_reason": "no_tool_calls"},
                error=None,
            )

        if result.termination_reason == "max_turns":
            return AgentResult(
                status=AgentStatus.FAILED,
                workspace_id=self.ctx.agent_id,
                changed_files=[],
                summary="",
                details={"termination_reason": "max_turns", "turns": result.turn_count},
                error=f"Reached maximum turns ({result.turn_count})",
            )

        return AgentResult(
            status=AgentStatus.SUCCESS,
            workspace_id=self.ctx.agent_id,
            changed_files=[],
            summary=result.final_message.content or "",
            details={"termination_reason": result.termination_reason},
            error=None,
        )

    def _parse_status(self, status_str: str) -> AgentStatus:
        """Parse status string to AgentStatus enum."""
        status_map = {
            "success": AgentStatus.SUCCESS,
            "skipped": AgentStatus.SKIPPED,
            "failed": AgentStatus.FAILED,
            "error": AgentStatus.FAILED,
            "errored": AgentStatus.FAILED,
        }
        return status_map.get(status_str.lower(), AgentStatus.SUCCESS)
