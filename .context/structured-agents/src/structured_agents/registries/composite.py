from __future__ import annotations

from structured_agents.registries.protocol import ToolRegistry
from structured_agents.types import ToolSchema


class CompositeRegistry:
    """Registry that combines multiple registries."""

    def __init__(self, registries: list[ToolRegistry] | None = None) -> None:
        self._registries: list[ToolRegistry] = registries or []

    @property
    def name(self) -> str:
        return "composite"

    def add(self, registry: ToolRegistry) -> None:
        """Add a registry to the composite."""
        self._registries.append(registry)

    def list_tools(self) -> list[str]:
        """List all tools from all registries."""
        tools: list[str] = []
        seen: set[str] = set()

        for registry in self._registries:
            for tool_name in registry.list_tools():
                if tool_name not in seen:
                    tools.append(tool_name)
                    seen.add(tool_name)

        return tools

    def resolve(self, tool_name: str) -> ToolSchema | None:
        """Resolve from first registry that has the tool."""
        for registry in self._registries:
            schema = registry.resolve(tool_name)
            if schema:
                return schema
        return None

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        """Resolve all tools, preferring earlier registries."""
        resolved: dict[str, ToolSchema] = {}

        for name in tool_names:
            if name not in resolved:
                schema = self.resolve(name)
                if schema:
                    resolved[name] = schema

        return [resolved[name] for name in tool_names if name in resolved]
