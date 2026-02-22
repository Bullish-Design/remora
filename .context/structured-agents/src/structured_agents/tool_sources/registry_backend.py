from __future__ import annotations

from typing import Any

from structured_agents.backends.protocol import ToolBackend
from structured_agents.registries.protocol import ToolRegistry
from structured_agents.tool_sources.protocol import ContextProvider, ToolSource
from structured_agents.types import ToolCall, ToolResult, ToolSchema


class RegistryBackendToolSource(ToolSource):
    """Tool source that composes a registry with a backend."""

    def __init__(
        self,
        registry: ToolRegistry,
        backend: ToolBackend,
        context_providers: list[ContextProvider] | None = None,
    ) -> None:
        self._registry = registry
        self._backend = backend
        self._context_providers = list(context_providers or [])

    def list_tools(self) -> list[str]:
        return self._registry.list_tools()

    def resolve(self, tool_name: str) -> ToolSchema | None:
        return self._registry.resolve(tool_name)

    def resolve_all(self, tool_names: list[str]) -> list[ToolSchema]:
        return self._registry.resolve_all(tool_names)

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        return await self._backend.execute(tool_call, tool_schema, context)

    def context_providers(self) -> list[ContextProvider]:
        return list(self._context_providers)
