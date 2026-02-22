from __future__ import annotations

from pathlib import Path
from typing import Any

from structured_agents.backends.protocol import ToolBackend
from structured_agents.types import ToolCall, ToolResult, ToolSchema


class CompositeBackend:
    """Backend that routes execution to appropriate sub-backends."""

    def __init__(self) -> None:
        self._backends: dict[str, ToolBackend] = {}

    def register(self, backend_name: str, backend: ToolBackend) -> None:
        """Register a backend for a given type."""
        self._backends[backend_name] = backend

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute tool using appropriate backend."""
        backend = self._backends.get(tool_schema.backend)

        if not backend:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"No backend registered for: {tool_schema.backend}",
                is_error=True,
            )

        return await backend.execute(tool_call, tool_schema, context)

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Run context providers using Grail backend."""
        grail_backend = self._backends.get("grail")
        if grail_backend:
            return await grail_backend.run_context_providers(providers, context)
        return []
