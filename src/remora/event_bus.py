"""Unified Event Bus - the central nervous system of Remora.

This module provides a single event system that unifies:
1. Remora's graph-level events (AgentStart, AgentComplete, etc.)
2. structured-agents' kernel events (ToolCall, ModelResponse, etc.)

Design:
- Type-based subscription instead of string patterns
- Implements structured-agents Observer protocol
- Supports async streaming and wait_for patterns
- Error isolation: one failing handler doesn't affect others
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from typing_extensions import TypeAlias

from remora.events import RemoraEvent


T = TypeVar("T", bound=RemoraEvent)


EventHandler: TypeAlias = Callable[[RemoraEvent], Awaitable[None]]


@dataclass
class Subscription:
    """Tracks an active subscription for cleanup."""

    event_type: type
    handler: EventHandler


class EventBus:
    """The single source of truth for all events.

    Implements structured-agents' Observer protocol and adds Remora's
    pub/sub features on top.

    Usage:
        # Publish events
        await event_bus.emit(AgentStartEvent(
            graph_id="graph-1",
            agent_id="agent-1",
            node={}
        ))

        # Subscribe to specific types
        async def handle_agent_start(event: AgentStartEvent):
            print(f"Agent {event.agent_id} started")

        event_bus.subscribe(AgentStartEvent, handle_agent_start)

        # Stream filtered events (e.g., for SSE)
        async for event in event_bus.stream(AgentStartEvent, AgentCompleteEvent):
            print(event)

        # Wait for specific event (e.g., human input)
        response = await event_bus.wait_for(
            HumanInputResponseEvent,
            lambda e: e.request_id == request_id,
            timeout=300
        )

    Design:
        - No queue: direct handler invocation for low latency
        - asyncio.gather for concurrent notification
        - Error isolation via try/except in each handler
    """

    def __init__(self):
        self._handlers: dict[type, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._subscriptions: list[Subscription] = []
        self._logger = logging.getLogger(__name__)

    async def emit(self, event: RemoraEvent) -> None:
        """Observer protocol method - receives all events.

        This is the entry point for structured-agents to emit events
        through Remora's EventBus.
        """
        await self._notify_handlers(event)

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Subscribe to a specific event type.

        Args:
            event_type: The event class to subscribe to
            handler: Async function to call when event is emitted
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)  # type: ignore[arg-type]
        self._subscriptions.append(Subscription(event_type, handler))

    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a subscription by handler.

        Args:
            handler: The handler function to remove
        """
        for event_type in self._handlers:
            self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

        self._all_handlers = [h for h in self._all_handlers if h != handler]

        self._subscriptions = [s for s in self._subscriptions if s.handler != handler]

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events.

        Useful for logging, metrics, debugging.
        """
        self._all_handlers.append(handler)

    @asynccontextmanager
    async def _event_queue(self) -> AsyncIterator[asyncio.Queue[RemoraEvent]]:
        """Create a queue for streaming events."""
        queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()
        try:
            yield queue
        finally:
            while not queue.empty():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

    def stream(self, *event_types: type) -> "EventStream":
        """Get an async iterator filtered to specific event types.

        Args:
            event_types: Event types to filter. If empty, yields all events.

        Returns:
            EventStream async iterator
        """
        return EventStream(self, set(event_types) if event_types else None)

    async def wait_for(
        self,
        event_type: type[T],
        predicate: Callable[[T], bool],
        timeout: float = 60.0,
    ) -> T:
        """Wait for an event matching the predicate.

        This is the key primitive for human-in-the-loop IPC:
        1. Agent emits HumanInputRequestEvent
        2. Calls wait_for(HumanInputResponseEvent, lambda e: e.request_id == request_id)
        3. Dashboard receives request via stream, user responds
        4. HumanInputResponseEvent is emitted
        5. wait_for resolves with the response

        Args:
            event_type: The event type to wait for
            predicate: Function that returns True when the desired event arrives
            timeout: Maximum seconds to wait (default 60)

        Returns:
            The matching event

        Raises:
            asyncio.TimeoutError: If timeout expires before matching event
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[T] = loop.create_future()

        async def handler(event: RemoraEvent) -> None:
            try:
                if isinstance(event, event_type) and predicate(event):
                    future.set_result(event)
            except Exception as e:
                future.set_exception(e)

        self.subscribe(event_type, handler)  # type: ignore[arg-type]

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise
        finally:
            self.unsubscribe(handler)  # type: ignore[arg-type]

    async def _notify_handlers(self, event: RemoraEvent) -> None:
        """Notify all matching handlers with error isolation."""
        handlers: list[EventHandler] = []

        event_type = type(event)
        for t, h in self._handlers.items():
            if isinstance(event, t):
                handlers.extend(h)

        handlers.extend(self._all_handlers)

        if not handlers:
            return

        results = await asyncio.gather(*[self._safe_handler(h, event) for h in handlers], return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._logger.exception(f"Event handler {handlers[i]} failed: {result}")

    async def _safe_handler(self, handler: EventHandler, event: RemoraEvent) -> None:
        """Execute handler with error isolation."""
        try:
            await handler(event)
        except Exception:
            raise


class EventStream:
    """Async iterator for consuming events from the bus.

    Supports filtering by event type.
    """

    def __init__(
        self,
        event_bus: EventBus,
        event_types: set[type] | None = None,
    ):
        self._bus = event_bus
        self._types = event_types
        self._queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()
        self._handler: EventHandler | None = None
        self._running = False

    def __aiter__(self) -> "EventStream":
        return self

    async def __anext__(self) -> RemoraEvent:
        if self._handler is None:
            self._handler = self._enqueue
            self._bus.subscribe_all(self._handler)
            self._running = True

        if not self._running:
            raise StopAsyncIteration

        try:
            event = await asyncio.wait_for(self._queue.get(), timeout=1.0)

            if self._types and type(event) not in self._types:
                return await self.__anext__()

            return event
        except asyncio.TimeoutError:
            if not self._running:
                raise StopAsyncIteration
            raise

    async def _enqueue(self, event: RemoraEvent) -> None:
        """Handler that enqueues events for the stream."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._bus._logger.warning("Event stream queue full, dropping event")

    def close(self) -> None:
        """Stop the stream and clean up."""
        self._running = False
        if self._handler:
            self._bus._all_handlers = [h for h in self._bus._all_handlers if h != self._handler]
            self._handler = None


# Backwards compatibility - keep old Event class
from dataclasses import dataclass as _dataclass
import uuid as _uuid
from datetime import datetime as _datetime


@_dataclass
class Event:
    """Backwards compatible Event class."""

    id: str = field(default_factory=lambda: _uuid.uuid4().hex[:8])
    timestamp: _datetime = field(default_factory=_datetime.now)
    category: str = ""
    action: str = ""
    agent_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    session_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str:
        return f"{self.category}_{self.action}"

    @property
    def subscription_key(self) -> str:
        return f"{self.category}:{self.action}"


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus: EventBus) -> None:
    """Set the global event bus instance."""
    global _event_bus
    _event_bus = bus


__all__ = [
    "EventBus",
    "EventStream",
    "Subscription",
    "get_event_bus",
    "set_event_bus",
    "Event",
    "RemoraEvent",
]
