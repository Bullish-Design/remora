"""Observer protocol definition."""

from __future__ import annotations

from typing import Protocol

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class Observer(Protocol):
    """Protocol for receiving kernel execution events.

    All methods are async to allow for I/O operations (logging, network, etc.).
    Implementations should be fast and non-blocking to avoid slowing the kernel.
    """

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        """Called when kernel.run() begins."""
        ...

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        """Called before each model request."""
        ...

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        """Called after each model response."""
        ...

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        """Called before executing each tool."""
        ...

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Called after each tool execution."""
        ...

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        """Called after each complete turn."""
        ...

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        """Called when kernel.run() completes."""
        ...

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        """Called when an error occurs."""
        ...
