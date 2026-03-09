"""Grail tool integration with workspace-backed virtual FS."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Any

import grail
from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.agents.agent_context import AgentContext
from remora.core.tools.swarm import SwarmTool, build_swarm_tools

logger = logging.getLogger(__name__)

FilesProvider = Callable[[], Awaitable[dict[str, str | bytes]]]


def _build_parameters(script: grail.GrailScript) -> dict[str, Any]:
    """Build JSON Schema parameters from script Input() declarations."""
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, spec in script.inputs.items():
        prop: dict[str, Any] = {}
        type_map = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
        }
        type_str = spec.type_annotation
        prop["type"] = type_map.get(type_str, "string")
        properties[name] = prop
        if spec.required:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class GrailTool:
    """Simple Grail tool wrapper for standalone use.

    This is a simpler version of RemoraGrailTool that doesn't require
    workspace context or file providers. Useful for testing and simple
    integrations where externals/files aren't needed.

    Replaces the GrailTool that was removed from structured-agents v0.4.0.
    """

    def __init__(
        self,
        script: grail.GrailScript,
        *,
        limits: grail.Limits | None = None,
    ) -> None:
        self._script = script
        self._limits = limits
        self._schema = ToolSchema(
            name=getattr(script, "name", "grail_tool"),
            description=script.__doc__ or f"Grail tool: {script.name}",
            parameters=_build_parameters(script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        try:
            result = await self._script.run(
                inputs=arguments,
                limits=self._limits,
            )
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )


class RemoraGrailTool:
    """A tool backed by a .pym script with external helpers and virtual FS."""

    def __init__(
        self,
        script_path: Path,
        *,
        externals: dict[str, Any],
        files_provider: FilesProvider,
        limits: grail.Limits | None = None,
        grail_dir: str | Path | None = None,
    ) -> None:
        self._script = grail.load(str(script_path), limits=limits, grail_dir=grail_dir)
        self._externals = externals
        self._files_provider = files_provider
        self._limits = limits
        self._schema = ToolSchema(
            name=getattr(self._script, "name", script_path.stem),
            description=f"Tool: {script_path.stem}",
            parameters=_build_parameters(self._script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        try:
            files = await self._files_provider()
            externals = {name: fn for name, fn in self._externals.items() if name in self._script.externals}
            result = await self._script.run(
                inputs=arguments,
                externals=externals,
                files=files,
                limits=self._limits,
            )
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )


def build_virtual_fs(files: Mapping[str, str | bytes]) -> dict[str, str | bytes]:
    """Normalize file paths for Grail virtual filesystem."""
    virtual_fs: dict[str, str | bytes] = {}
    for path, content in files.items():
        normalized = path.replace("\\", "/").lstrip("/")
        virtual_fs[normalized] = content
    return virtual_fs


def discover_grail_tools(
    agents_dir: Path,
    *,
    context: AgentContext | None = None,
    externals: dict[str, Any] | None = None,
    files_provider: FilesProvider,
    workspace_tools_dir: Path | None = None,
    limits: grail.Limits | None = None,
    grail_dir: str | Path | None = None,
) -> list[RemoraGrailTool | SwarmTool]:
    """Discover and load .pym tools from a directory.

    Bootstrap mode: pass externals=bedrock_dict, context=None.
    V1 mode: pass context=AgentContext, externals=None.
    """
    if externals is not None:
        externals_dict = externals
    elif context is not None:
        externals_dict = context.as_externals()
    else:
        raise ValueError("Either context or externals must be provided")

    tools: list[RemoraGrailTool | SwarmTool] = []
    if not agents_dir.exists():
        logger.warning("Agents directory does not exist: %s", agents_dir)
        return tools

    for pym_file in sorted(agents_dir.glob("*.pym")):
        try:
            tools.append(
                RemoraGrailTool(
                    pym_file,
                    externals=externals_dict,
                    files_provider=files_provider,
                    limits=limits,
                    grail_dir=grail_dir,
                )
            )
            logger.debug("Loaded tool: %s", pym_file.name)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", pym_file, exc)
            continue

    if workspace_tools_dir and workspace_tools_dir.exists():
        system_externals = {
            tool.schema.name: _make_tool_callable(tool)
            for tool in tools
            if isinstance(tool, RemoraGrailTool)
        }
        for pym_file in sorted(workspace_tools_dir.glob("*.pym")):
            try:
                tools.append(
                    RemoraGrailTool(
                        pym_file,
                        externals=system_externals,
                        files_provider=files_provider,
                        limits=limits,
                        grail_dir=grail_dir,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to load workspace tool %s: %s", pym_file, exc)
                continue

    if context is not None:
        tools.extend(build_swarm_tools(context))

    return tools


def _make_tool_callable(tool: RemoraGrailTool) -> Callable[..., Awaitable[str]]:
    """Wrap a tool as an async callable for use as @external in Grail scripts."""

    async def _call(**kwargs: Any) -> str:
        result = await tool.execute(kwargs, context=None)
        return result.output

    return _call


__all__ = ["GrailTool", "RemoraGrailTool", "build_virtual_fs", "discover_grail_tools", "_make_tool_callable"]
