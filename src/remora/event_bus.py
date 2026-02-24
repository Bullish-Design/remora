"""Unified Event Bus - the central nervous system of Remora.

This module provides a single event system that:
1. All components publish to (agents, kernels, tools)
2. All consumers subscribe from (UI, logging, metrics)
3. Supports both in-process and distributed consumers

Design:
- Pydantic-first for public API (validation, type safety)
- Category + Action pattern for extensibility
- Backpressure on queue for stability
- Concurrent subscriber notification with error isolation
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EventCategory = Literal["agent", "tool", "model", "user", "graph"]


class AgentAction:
    """Pre-defined agent actions for type safety."""

    STARTED = "started"
    BLOCKED = "blocked"
    RESUMED = "resumed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ToolAction:
    """Pre-defined tool actions."""

    CALLED = "called"
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"


class ModelAction:
    """Pre-defined model actions."""

    REQUEST = "request"
    RESPONSE = "response"


class GraphAction:
    """Pre-defined graph actions."""

    STARTED = "started"
    PROGRESS = "progress"
    COMPLETED = "completed"
    FAILED = "failed"


class Event(BaseModel):
    """Every event in the system has this shape.

    Design decisions:
    - frozen=True: Events are immutable once created
    - Literal category: Type-safe categories
    - action as string: Extensible without enum changes
    - .type property: Human-readable for logging

    Usage:
        # Create events
        event = Event(category="agent", action="blocked", agent_id="123",
                      payload={"question": "Which format?"})

        # Or use convenience constructors
        event = Event.agent_blocked(agent_id="123", question="Which format?")

        # Subscribe to patterns
        await bus.subscribe("agent:blocked", handler)
        await bus.subscribe("tool:*", handler)  # All tool events
    """

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: datetime = Field(default_factory=datetime.now)

    category: EventCategory

    action: str

    agent_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    session_id: str | None = None

    payload: dict[str, Any] = Field(default_factory=dict)

    @property
    def type(self) -> str:
        """Human-readable type for logging. Returns 'agent_blocked'."""
        return f"{self.category}_{self.action}"

    @property
    def subscription_key(self) -> str:
        """Key for subscription matching. Returns 'agent:blocked'."""
        return f"{self.category}:{self.action}"

    @classmethod
    def agent_started(cls, agent_id: str, **payload: Any) -> "Event":
        return cls(category="agent", action=AgentAction.STARTED, agent_id=agent_id, payload=payload)

    @classmethod
    def agent_blocked(cls, agent_id: str, question: str, **payload: Any) -> "Event":
        return cls(
            category="agent", action=AgentAction.BLOCKED, agent_id=agent_id, payload={"question": question, **payload}
        )

    @classmethod
    def agent_resumed(cls, agent_id: str, answer: str, **payload: Any) -> "Event":
        return cls(
            category="agent", action=AgentAction.RESUMED, agent_id=agent_id, payload={"answer": answer, **payload}
        )

    @classmethod
    def agent_completed(cls, agent_id: str, **payload: Any) -> "Event":
        return cls(category="agent", action=AgentAction.COMPLETED, agent_id=agent_id, payload=payload)

    @classmethod
    def agent_failed(cls, agent_id: str, error: str, **payload: Any) -> "Event":
        return cls(category="agent", action=AgentAction.FAILED, agent_id=agent_id, payload={"error": error, **payload})

    @classmethod
    def agent_cancelled(cls, agent_id: str, **payload: Any) -> "Event":
        return cls(category="agent", action=AgentAction.CANCELLED, agent_id=agent_id, payload=payload)

    @classmethod
    def tool_called(cls, tool_name: str, call_id: str, **payload: Any) -> "Event":
        return cls(
            category="tool", action=ToolAction.CALLED, payload={"tool_name": tool_name, "call_id": call_id, **payload}
        )

    @classmethod
    def tool_result(cls, tool_name: str, call_id: str, **payload: Any) -> "Event":
        return cls(
            category="tool",
            action=ToolAction.COMPLETED,
            payload={"tool_name": tool_name, "call_id": call_id, **payload},
        )


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """The single source of truth for all events.

    Usage:
        # Publish events
        await event_bus.publish(Event.agent_blocked(
            agent_id="agent-123",
            question="Which format?"
        ))

        # Subscribe to specific events
        await event_bus.subscribe("agent:blocked", my_handler)

        # Subscribe to patterns
        await event_bus.subscribe("agent:*", all_agent_handler)
        await event_bus.subscribe("tool:*", all_tool_handler)

        # Get stream for consumption (e.g., SSE)
        async for event in event_bus.stream():
            print(event)

    Design:
        - maxsize=1000 on queue for backpressure
        - asyncio.gather() for concurrent subscriber notification
        - Error isolation: one failing handler doesn't affect others
    """

    def __init__(self, max_queue_size: int = 1000, telemetry: Any = None):
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._running = False
        self._logger = logging.getLogger(__name__)
        self._telemetry: Any = telemetry

    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._logger.warning(f"Event queue full, dropping event: {event.type}")
            return

        if self._telemetry:
            await self._record_telemetry(event)

        await self._notify_subscribers(event)

    async def _record_telemetry(self, event: Event) -> None:
        """Record event to telemetry (tokens used, duration, etc.)."""
        try:
            await self._telemetry.record(event)
        except Exception as e:
            self._logger.debug(f"Telemetry recording failed: {e}")

    async def _notify_subscribers(self, event: Event) -> None:
        """Notify all matching subscribers concurrently with error isolation."""
        event_key = event.subscription_key

        handlers = []

        handlers.extend(self._subscribers.get(event_key, []))

        for pattern, pattern_handlers in self._subscribers.items():
            if pattern.endswith("*"):
                prefix = pattern[:-1]
                if event_key.startswith(prefix):
                    handlers.extend(pattern_handlers)

        if not handlers:
            return

        results = await asyncio.gather(*[self._safe_handler(h, event) for h in handlers], return_exceptions=True)

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._logger.exception(f"Event handler {handlers[i]} failed: {result}")

    async def _safe_handler(self, handler: EventHandler, event: Event) -> None:
        """Execute handler with error isolation."""
        try:
            await handler(event)
        except Exception:
            raise

    async def subscribe(self, pattern: str, handler: EventHandler) -> None:
        """Subscribe to events matching the pattern.

        Args:
            pattern: Subscription pattern (e.g., "agent:blocked", "tool:*", "agent:*")
            handler: Async function to call when event matches
        """
        if pattern not in self._subscribers:
            self._subscribers[pattern] = []
        self._subscribers[pattern].append(handler)

    async def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        """Remove a subscription."""
        if pattern in self._subscribers:
            self._subscribers[pattern] = [h for h in self._subscribers[pattern] if h != handler]

    def stream(self) -> "EventStream":
        """Get an async iterator of events for consumption."""
        return EventStream(self._queue)

    async def send_sse(self, event: Event) -> str:
        """Format event for Server-Sent Events."""
        return f"data: {event.model_dump_json()}\n\n"


class EventStream:
    """Async iterator for consuming events from the bus."""

    def __init__(self, queue: asyncio.Queue[Event]):
        self._queue = queue

    def __aiter__(self) -> "EventStream":
        return self

    async def __anext__(self) -> Event:
        return await self._queue.get()


_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
