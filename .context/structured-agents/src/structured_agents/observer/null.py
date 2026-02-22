"""Null observer implementation (no-op)."""

from __future__ import annotations

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class NullObserver:
    """Observer that does nothing. Used as default."""

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        pass

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        pass

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        pass

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        pass

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        pass

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        pass

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        pass

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        pass
