"""Grail tool implementation."""

from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any

import grail
from structured_agents.types import ToolCall, ToolSchema, ToolResult

logger = logging.getLogger(__name__)


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
    """A tool backed by a .pym script."""

    def __init__(self, script: grail.GrailScript, limits: grail.Limits | None = None):
        self._script = script
        self._limits = limits
        self._schema = ToolSchema(
            name=script.name,
            description=f"Tool: {script.name}",
            parameters=_build_parameters(script),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(
        self, arguments: dict[str, Any], context: ToolCall | None
    ) -> ToolResult:
        call_id = context.id if context else "unknown"
        try:
            result = await self._script.run(inputs=arguments, limits=self._limits)
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(
                call_id=call_id,
                name=self._script.name,
                output=output,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._script.name,
                output=str(e),
                is_error=True,
            )


def discover_tools(
    agents_dir: str, limits: grail.Limits | None = None
) -> list[GrailTool]:
    """Discover and load .pym tools from a directory."""
    tools: list[GrailTool] = []
    agents_path = Path(agents_dir)

    if not agents_path.exists():
        logger.warning("Agents directory does not exist: %s", agents_dir)
        return tools

    for pym_file in sorted(agents_path.glob("*.pym")):
        try:
            script = grail.load(str(pym_file), grail_dir=None)
            tools.append(GrailTool(script, limits=limits))
            logger.debug("Loaded tool: %s from %s", script.name, pym_file)
        except Exception as e:
            logger.warning("Failed to load %s: %s", pym_file, e)
            continue

    return tools
