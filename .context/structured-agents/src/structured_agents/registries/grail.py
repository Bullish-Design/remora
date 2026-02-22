from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structured_agents.types import ToolSchema

logger = logging.getLogger(__name__)


@dataclass
class GrailRegistryConfig:
    """Configuration for Grail tool registry."""

    agents_dir: Path = field(default_factory=lambda: Path.cwd() / "agents")
    use_grail_check: bool = False
    cache_schemas: bool = True


class GrailRegistry:
    """Registry that resolves tools from Grail .pym scripts."""

    def __init__(self, config: GrailRegistryConfig | None = None) -> None:
        self._config = config or GrailRegistryConfig()
        self._cache: dict[str, ToolSchema] = {}
        self._scanned = False

    @property
    def name(self) -> str:
        return "grail"

    def list_tools(self) -> list[str]:
        """List all .pym tools in the agents directory."""
        self._scan_if_needed()
        return list(self._cache.keys())

    def resolve(self, tool_name: str) -> ToolSchema | None:
        """Resolve a Grail tool by name."""
        self._scan_if_needed()
        return self._cache.get(tool_name)

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        """Resolve multiple Grail tools."""
        self._scan_if_needed()
        return [self._cache[name] for name in tool_names if name in self._cache]

    def _scan_if_needed(self) -> None:
        """Scan agents directory if not already done."""
        if self._scanned and self._config.cache_schemas:
            return

        self._cache.clear()

        if not self._config.agents_dir.exists():
            logger.warning("Agents directory not found: %s", self._config.agents_dir)
            return

        for pym_path in self._config.agents_dir.rglob("*.pym"):
            try:
                schema = self._load_tool_schema(pym_path)
                if schema:
                    self._cache[schema.name] = schema
            except Exception as exc:
                logger.warning("Failed to load %s: %s", pym_path, exc)

        self._scanned = True

    def _load_tool_schema(self, pym_path: Path) -> ToolSchema | None:
        """Load tool schema from .pym file and its .grail artifacts."""
        tool_name = pym_path.stem

        grail_dir = pym_path.parent / ".grail" / tool_name
        inputs_json = grail_dir / "inputs.json"

        if inputs_json.exists():
            return self._schema_from_inputs_json(tool_name, pym_path, inputs_json)

        if self._config.use_grail_check:
            return self._schema_from_grail_check(tool_name, pym_path)

        return ToolSchema(
            name=tool_name,
            description=f"Grail tool: {tool_name}",
            parameters={"type": "object", "properties": {}},
            script_path=pym_path,
            backend="grail",
        )

    def _schema_from_inputs_json(
        self, tool_name: str, pym_path: Path, inputs_json: Path
    ) -> ToolSchema:
        """Build schema from grail-generated inputs.json."""
        with inputs_json.open() as file_handle:
            inputs = json.load(file_handle)

        properties: dict[str, Any] = {}
        required: list[str] = []

        for input_name, input_spec in inputs.items():
            if input_name.startswith("_"):
                continue

            prop: dict[str, Any] = {}

            if "type" in input_spec:
                prop["type"] = self._grail_type_to_json(input_spec["type"])
            if "description" in input_spec:
                prop["description"] = input_spec["description"]
            if "default" in input_spec:
                prop["default"] = input_spec["default"]
            else:
                required.append(input_name)

            properties[input_name] = prop

        parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            parameters["required"] = required

        return ToolSchema(
            name=tool_name,
            description=inputs.get("_description", f"Grail tool: {tool_name}"),
            parameters=parameters,
            script_path=pym_path,
            backend="grail",
        )

    def _schema_from_grail_check(
        self, tool_name: str, pym_path: Path
    ) -> ToolSchema | None:
        """Run grail check and parse outputs."""
        import subprocess

        try:
            result = subprocess.run(
                ["grail", "check", str(pym_path), "--json"],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            if result.returncode == 0:
                json.loads(result.stdout)
        except Exception as exc:
            logger.warning("grail check failed for %s: %s", pym_path, exc)

        return None

    def _grail_type_to_json(self, grail_type: str) -> str:
        """Convert Grail type annotation to JSON Schema type."""
        type_map = {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
            "list": "array",
            "dict": "object",
        }
        return type_map.get(grail_type, "string")
