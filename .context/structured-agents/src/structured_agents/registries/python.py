from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any, Callable, get_type_hints

from structured_agents.types import ToolSchema


@dataclass
class PythonTool:
    """A registered Python callable as a tool."""

    name: str
    func: Callable[..., Any]
    description: str | None = None


class PythonRegistry:
    """Registry for Python callable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, PythonTool] = {}

    @property
    def name(self) -> str:
        return "python"

    def register(
        self, name: str, func: Callable[..., Any], description: str | None = None
    ) -> None:
        """Register a Python callable as a tool.

        Args:
            name: Tool name.
            func: The callable to register.
            description: Optional description (defaults to docstring).
        """
        self._tools[name] = PythonTool(
            name=name,
            func=func,
            description=description or func.__doc__ or f"Python function: {name}",
        )

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def resolve(self, tool_name: str) -> ToolSchema | None:
        tool = self._tools.get(tool_name)
        if not tool:
            return None
        return self._build_schema(tool)

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        return [
            self._build_schema(self._tools[name])
            for name in tool_names
            if name in self._tools
        ]

    def get_callable(self, tool_name: str) -> Callable[..., Any] | None:
        """Get the registered callable for a tool."""
        tool = self._tools.get(tool_name)
        return tool.func if tool else None

    def _build_schema(self, tool: PythonTool) -> ToolSchema:
        """Build ToolSchema from function signature."""
        sig = inspect.signature(tool.func)
        hints = (
            get_type_hints(tool.func) if hasattr(tool.func, "__annotations__") else {}
        )

        properties: dict[str, Any] = {}
        required: list[str] = []

        for param_name, param in sig.parameters.items():
            if param_name in ("self", "cls"):
                continue

            prop: dict[str, Any] = {
                "type": self._python_type_to_json(hints.get(param_name))
            }

            if param.default is inspect.Parameter.empty:
                required.append(param_name)
            else:
                prop["default"] = param.default

            properties[param_name] = prop

        parameters: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            parameters["required"] = required

        return ToolSchema(
            name=tool.name,
            description=tool.description or "",
            parameters=parameters,
            backend="python",
        )

    def _python_type_to_json(self, python_type: Any) -> str:
        """Convert Python type hint to JSON Schema type."""
        if python_type is None:
            return "string"

        type_map = {
            str: "string",
            int: "integer",
            float: "number",
            bool: "boolean",
            list: "array",
            dict: "object",
        }

        origin = getattr(python_type, "__origin__", python_type)
        return type_map.get(origin, "string")
