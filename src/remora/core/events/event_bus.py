"""Unified event bus implementing structured-agents Observer protocol.

The EventBus is the central nervous system for all Remora events.
It implements the Observer protocol from structured-agents, allowing
it to receive kernel events directly.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from structured_agents.events import Event as StructuredEvent

if TYPE_CHECKING:
    from remora.core.events import CoreEvent

# Preserve historical logger name for compatibility with existing tests and tooling.
logger = logging.getLogger("remora.core.events.event_bus")
_NOISY_EVENT_NAMES = frozenset({"NodeDiscoveredEvent", "ScaffoldRequestEvent"})

EventHandler = Callable[[Any], Any]


class EventBus:
    """Unified event dispatch with Observer protocol support.

    Implements structured-agents Observer protocol via emit().
    Provides type-based subscription and async streaming.
    """

    def __init__(self, *, error_policy: str = "log") -> None:
        self._handlers: dict[type[Any], list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._error_policy = error_policy
        self._dispatch_cache: dict[type[Any], tuple[EventHandler, ...]] = {}

    def _invalidate_dispatch_cache(self) -> None:
        self._dispatch_cache.clear()

    def _resolve_handlers(self, event_type: type[Any]) -> tuple[EventHandler, ...]:
        cached = self._dispatch_cache.get(event_type)
        if cached is not None:
            return cached

        resolved: list[EventHandler] = []
        for candidate in event_type.__mro__:
            resolved.extend(self._handlers.get(candidate, []))
        resolved.extend(self._all_handlers)
        result = tuple(resolved)
        self._dispatch_cache[event_type] = result
        return result

    async def emit(self, event: StructuredEvent | CoreEvent) -> None:
        event_type = type(event)
        event_name = event_type.__name__
        agent_id = getattr(event, "agent_id", None) or getattr(event, "to_agent", None)
        log_fn = logger.debug if event_name in _NOISY_EVENT_NAMES else logger.info
        log_fn(f"EventBus.emit: {event_name} agent_id={agent_id}")

        handlers = self._resolve_handlers(event_type)
        log_fn(f"EventBus.emit: {len(handlers)} handlers for {event_name}")

        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                if self._error_policy == "propagate":
                    raise
                logger.warning("Event handler error: %s", exc)

    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            self._invalidate_dispatch_cache()

    def subscribe_all(self, handler: EventHandler) -> None:
        if handler not in self._all_handlers:
            self._all_handlers.append(handler)
            self._invalidate_dispatch_cache()

    def unsubscribe(self, handler: EventHandler) -> None:
        for handlers in self._handlers.values():
            if handler in handlers:
                handlers.remove(handler)
        if handler in self._all_handlers:
            self._all_handlers.remove(handler)
        self._invalidate_dispatch_cache()

    @asynccontextmanager
    async def stream(self, *event_types: type[Any]) -> AsyncIterator[AsyncIterator[StructuredEvent | CoreEvent]]:
        queue: asyncio.Queue[StructuredEvent | CoreEvent] = asyncio.Queue()
        filter_types = set(event_types) if event_types else None

        def enqueue(event: StructuredEvent | CoreEvent) -> None:
            if filter_types is None or any(isinstance(event, et) for et in filter_types):
                queue.put_nowait(event)

        self.subscribe_all(enqueue)

        async def iterate() -> AsyncIterator[StructuredEvent | CoreEvent]:
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
        predicate: Callable[[StructuredEvent | CoreEvent], bool],
        timeout: float = 60.0,
    ) -> StructuredEvent | CoreEvent:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[StructuredEvent | CoreEvent] = loop.create_future()

        def handler(event: StructuredEvent | CoreEvent) -> None:
            try:
                if isinstance(event, event_type) and predicate(event):
                    if not future.done():
                        try:
                            future.set_result(event)
                        except asyncio.InvalidStateError:
                            return
            except Exception as exc:
                if not future.done():
                    try:
                        future.set_exception(exc)
                    except asyncio.InvalidStateError:
                        return

        self.subscribe(event_type, handler)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self.unsubscribe(handler)

    def clear(self) -> None:
        self._handlers.clear()
        self._all_handlers.clear()
        self._dispatch_cache.clear()


__all__ = [
    "EventBus",
    "EventHandler",
]
