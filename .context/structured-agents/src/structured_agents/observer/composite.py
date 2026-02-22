"""Composite observer for fan-out to multiple observers."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.observer.protocol import Observer

logger = logging.getLogger(__name__)


class CompositeObserver:
    """Fan-out observer that forwards events to multiple child observers.

    If a child observer raises an exception, it is logged but does not
    prevent other observers from receiving the event.
    """

    def __init__(self, observers: Sequence[Observer]):
        self._observers = list(observers)

    async def _notify_all(
        self, method_name: str, *args: object, **kwargs: object
    ) -> None:
        """Call a method on all observers, catching exceptions."""
        tasks = []
        for obs in self._observers:
            method = getattr(obs, method_name, None)
            if method:
                tasks.append(method(*args, **kwargs))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        "Observer %s.%s raised %s: %s",
                        self._observers[i].__class__.__name__,
                        method_name,
                        type(result).__name__,
                        result,
                    )

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        await self._notify_all("on_kernel_start", event)

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        await self._notify_all("on_model_request", event)

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        await self._notify_all("on_model_response", event)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        await self._notify_all("on_tool_call", event)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        await self._notify_all("on_tool_result", event)

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        await self._notify_all("on_turn_complete", event)

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        await self._notify_all("on_kernel_end", event)

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        await self._notify_all("on_error", error, context)
