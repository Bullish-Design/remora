"""Grail tool integration with workspace-backed virtual FS."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

import grail
from structured_agents.types import ToolCall, ToolSchema, ToolResult

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


def build_virtual_fs(files: dict[str, str | bytes]) -> dict[str, str | bytes]:
    """Normalize file paths for Grail virtual filesystem."""
    virtual_fs: dict[str, str | bytes] = {}
    for path, content in files.items():
        normalized = path.replace("\\", "/").lstrip("/")
        virtual_fs[normalized] = content
        virtual_fs[f"/{normalized}"] = content
    return virtual_fs


def discover_grail_tools(
    agents_dir: Path,
    *,
    externals: dict[str, Any],
    files_provider: FilesProvider,
    limits: grail.Limits | None = None,
    grail_dir: str | Path | None = None,
) -> list[RemoraGrailTool]:
    """Discover and load .pym tools from a directory."""
    tools: list[RemoraGrailTool] = []
    if not agents_dir.exists():
        logger.warning("Agents directory does not exist: %s", agents_dir)
        return tools

    for pym_file in sorted(agents_dir.glob("*.pym")):
        try:
            tools.append(
                RemoraGrailTool(
                    pym_file,
                    externals=externals,
                    files_provider=files_provider,
                    limits=limits,
                    grail_dir=grail_dir,
                )
            )
            logger.debug("Loaded tool: %s", pym_file.name)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", pym_file, exc)
            continue

    return tools


__all__ = ["RemoraGrailTool", "build_virtual_fs", "discover_grail_tools"]
