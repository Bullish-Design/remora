"""Simple Python function backend for testing and simple use cases."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

from structured_agents.registries.python import PythonRegistry
from structured_agents.types import ToolCall, ToolResult, ToolSchema


class PythonBackend:
    """Backend that executes Python functions directly.

    This is useful for:
    - Testing without Grail dependencies
    - Simple tools that don't need sandboxing
    - Wrapping existing Python functions as tools
    """

    def __init__(
        self,
        registry: PythonRegistry | None = None,
        handlers: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    ) -> None:
        """Initialize with optional registry and handlers.

        Args:
            registry: Registry providing tool callables.
            handlers: Optional mapping of tool names to async handlers.
        """
        self._registry = registry or PythonRegistry()
        if handlers:
            for name, handler in handlers.items():
                self.register(name, handler)

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        """Register a tool handler.

        Args:
            name: Tool name.
            handler: Async function to handle the tool.
        """
        self._registry.register(name, handler)

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool using the registered handler."""
        handler = self._registry.get_callable(tool_call.name)

        if not handler:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"No handler registered for tool: {tool_call.name}",
                is_error=True,
            )

        try:
            kwargs = {**context, **tool_call.arguments}
            result = handler(**kwargs)
            if inspect.isawaitable(result):
                result = await result

            output = result if isinstance(result, str) else json.dumps(result)

            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"{type(exc).__name__}: {exc}",
                is_error=True,
            )

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Python backend doesn't support context providers."""
        return []
