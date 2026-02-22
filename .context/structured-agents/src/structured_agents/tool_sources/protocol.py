from __future__ import annotations

from typing import Any, Awaitable, Callable, Protocol

from structured_agents.types import ToolCall, ToolResult, ToolSchema

ContextProvider = Callable[[], Awaitable[dict[str, Any]]]


class ToolSource(Protocol):
    """Protocol for unified tool discovery and execution."""

    def list_tools(self) -> list[str]:
        """List all available tool names."""
        ...

    def resolve(self, tool_name: str) -> ToolSchema | None:
        """Resolve a tool schema by name."""
        ...

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        """Resolve multiple tool schemas by name."""
        ...

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a single tool call."""
        ...

    def context_providers(self) -> list[ContextProvider]:
        """Return async context providers for each turn."""
        ...
