"""Unified event bus implementing structured-agents Observer protocol.

The EventBus is the central nervous system for all Remora events.
It implements the Observer protocol from structured-agents, allowing
it to receive kernel events directly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from structured_agents.events import Event as StructuredEvent

from remora.core.events import RemoraEvent

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Any]


class EventBus:
    """Unified event dispatch with Observer protocol support.

    Implements structured-agents Observer protocol via emit().
    Provides type-based subscription and async streaming.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Any], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []

    async def emit(self, event: StructuredEvent | RemoraEvent) -> None:
        event_type = type(event)
        handlers: list[EventHandler] = []

        for registered_type, registered_handlers in self._handlers.items():
            if isinstance(event, registered_type):
                handlers.extend(registered_handlers)

        handlers.extend(self._all_handlers)

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.warning("Event handler error: %s", exc)

    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        if handler not in self._all_handlers:
            self._all_handlers.append(handler)

    def unsubscribe(self, handler: EventHandler) -> None:
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)

    @asynccontextmanager
    async def stream(self, *event_types: type[Any]) -> AsyncIterator[AsyncIterator[StructuredEvent | RemoraEvent]]:
        queue: asyncio.Queue[StructuredEvent | RemoraEvent] = asyncio.Queue()
        filter_types = set(event_types) if event_types else None

        def enqueue(event: StructuredEvent | RemoraEvent) -> None:
            if filter_types is None or any(isinstance(event, et) for et in filter_types):
                queue.put_nowait(event)

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[StructuredEvent | RemoraEvent]:
            while True:
                event = await queue.get()
                yield event

        try:
            yield iterate()
        finally:
            self.unsubscribe(enqueue)

    async def wait_for(
        self,
        event_type: type[Any],
        predicate: Callable[[StructuredEvent | RemoraEvent], bool],
        timeout: float = 60.0,
    ) -> StructuredEvent | RemoraEvent:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[StructuredEvent | RemoraEvent] = loop.create_future()

        def handler(event: StructuredEvent | RemoraEvent) -> None:
            try:
                if isinstance(event, event_type) and predicate(event):
                    if not future.done():
                        future.set_result(event)
            except Exception as exc:
                if not future.done():
                    future.set_exception(exc)

        self.subscribe(event_type, handler)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.unsubscribe(handler)

    def clear(self) -> None:
        self._handlers.clear()
        self._all_handlers.clear()


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def reset_event_bus() -> None:
    global _event_bus
    if _event_bus:
        _event_bus.clear()
    _event_bus = None


__all__ = [
    "EventBus",
    "EventHandler",
    "get_event_bus",
    "reset_event_bus",
]
