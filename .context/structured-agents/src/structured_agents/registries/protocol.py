from __future__ import annotations

from typing import Protocol

from structured_agents.types import ToolSchema


class ToolRegistry(Protocol):
    """Protocol for resolving tool schemas from a source."""

    @property
    def name(self) -> str:
        """Registry identifier."""
        ...

    def list_tools(self) -> list[str]:
        """List all available tool names."""
        ...

    def resolve(self, tool_name: str) -> ToolSchema | None:
        """Resolve a single tool by name.

        Args:
            tool_name: Name of the tool to resolve.

        Returns:
            ToolSchema if found, None otherwise.
        """
        ...

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        """Resolve multiple tools by name.

        Args:
            tool_names: Names of tools to resolve.

        Returns:
            List of resolved ToolSchemas (excludes tools not found).
        """
        ...
