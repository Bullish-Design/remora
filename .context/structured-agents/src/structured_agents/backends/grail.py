"""Grail .pym script execution backend.

This backend executes tools defined as Grail .pym scripts in isolated
processes. It's the default backend for production use.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from structured_agents.types import ToolCall, ToolResult, ToolSchema


logger = logging.getLogger(__name__)


@dataclass
class GrailBackendConfig:
    """Configuration for the Grail backend."""

    grail_dir: Path = field(default_factory=lambda: Path.cwd() / "agents")
    max_workers: int = 4
    timeout: float = 300.0
    limits: dict[str, Any] = field(
        default_factory=lambda: {
            "max_memory_mb": 512,
            "max_duration_s": 60,
            "max_recursion": 100,
        }
    )


class GrailBackend:
    """Backend that executes Grail .pym scripts in isolated processes.

    This backend:
    - Runs .pym scripts in separate processes for isolation
    - Supports context providers for injecting per-tool context
    - Handles Grail limits (memory, duration, recursion)
    """

    def __init__(
        self,
        config: GrailBackendConfig | None = None,
        externals_factory: Callable[[str, dict[str, Any]], dict[str, Any]]
        | None = None,
    ) -> None:
        """Initialize the Grail backend.

        Args:
            config: Backend configuration.
            externals_factory: Factory function to create Grail externals.
                Signature: (agent_id, context) -> externals_dict
        """
        self._config = config or GrailBackendConfig()
        self._externals_factory = externals_factory
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=self._config.max_workers
        )

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a .pym script for the tool call."""
        if tool_schema.context_providers:
            try:
                context_outputs = await self.run_context_providers(
                    list(tool_schema.context_providers),
                    context,
                )
            except Exception as exc:
                logger.warning("Context provider failed: %s", exc)
                context_outputs = []
        else:
            context_outputs = []

        script_path = tool_schema.script_path
        if not script_path:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"No script path for tool: {tool_call.name}",
                is_error=True,
            )

        inputs = {**context, **tool_call.arguments}

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    _run_grail_script,
                    str(script_path),
                    str(self._config.grail_dir),
                    inputs,
                    self._config.limits,
                    context.get("agent_id"),
                    context.get("workspace_path"),
                    context.get("stable_path"),
                    context.get("node_source"),
                    context.get("node_metadata"),
                    self._externals_factory,
                ),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"Tool execution timed out after {self._config.timeout}s",
                is_error=True,
            )
        except Exception as exc:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"Execution error: {type(exc).__name__}: {exc}",
                is_error=True,
            )

        if result.get("error"):
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=json.dumps(result),
                is_error=True,
            )

        tool_output = result.get("result", {})
        if context_outputs:
            combined = "\n".join(context_outputs)
            if isinstance(tool_output, str):
                combined += "\n" + tool_output
            else:
                combined += "\n" + json.dumps(tool_output)
            output = combined
        else:
            output = (
                tool_output if isinstance(tool_output, str) else json.dumps(tool_output)
            )

        return ToolResult(
            call_id=tool_call.id,
            name=tool_call.name,
            output=output,
            is_error=False,
        )

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Execute context provider scripts."""
        outputs: list[str] = []
        for provider_path in providers:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    _run_grail_script,
                    str(provider_path),
                    str(self._config.grail_dir),
                    context,
                    self._config.limits,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                if not result.get("error"):
                    output = result.get("result", "")
                    if isinstance(output, dict):
                        output = json.dumps(output)
                    outputs.append(str(output))
            except Exception as exc:
                logger.warning("Context provider %s failed: %s", provider_path, exc)

        return outputs

    def shutdown(self) -> None:
        """Shutdown the process pool."""
        self._executor.shutdown(wait=True)


def _run_grail_script(
    pym_path: str,
    grail_dir: str,
    inputs: dict[str, Any],
    limits: dict[str, Any],
    agent_id: str | None,
    workspace_path: str | None,
    stable_path: str | None,
    node_source: str | None,
    node_metadata: dict[str, Any] | None,
    externals_factory: Callable[..., dict[str, Any]] | None,
) -> dict[str, Any]:
    """Execute a .pym script in a child process.

    This function runs in a separate OS process via ProcessPoolExecutor.
    """
    import grail  # type: ignore[import-not-found]

    async def _execute_async() -> dict[str, Any]:
        path = Path(pym_path)
        if not path.exists():
            return {
                "error": True,
                "code": "FILE_NOT_FOUND",
                "message": f".pym file not found: {pym_path}",
            }

        try:
            script = grail.load(pym_path, grail_dir=grail_dir)
        except Exception as exc:
            return {
                "error": True,
                "code": "LOAD_ERROR",
                "message": f"{type(exc).__name__}: {exc}",
            }

        check = script.check()
        if not check.valid:
            errors = [str(err) for err in (check.errors or [])]
            return {"error": True, "code": "GRAIL_CHECK", "message": "; ".join(errors)}

        externals: dict[str, Any] = {}
        if externals_factory and agent_id:
            try:
                externals = externals_factory(
                    agent_id,
                    {
                        "workspace_path": workspace_path,
                        "stable_path": stable_path,
                        "node_source": node_source,
                        "node_metadata": node_metadata,
                    },
                )
            except Exception as exc:
                return {"error": True, "code": "EXTERNALS_ERROR", "message": str(exc)}

        try:
            result = await script.run(inputs=inputs, limits=limits, externals=externals)
            return {"error": False, "result": result}
        except grail.LimitError as exc:
            return {"error": True, "code": "LIMIT", "message": str(exc)}
        except grail.ExecutionError as exc:
            return {"error": True, "code": "EXECUTION", "message": str(exc)}
        except grail.GrailError as exc:
            return {"error": True, "code": "GRAIL", "message": str(exc)}

    return asyncio.run(_execute_async())
