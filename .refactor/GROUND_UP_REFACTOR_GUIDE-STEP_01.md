# Implementation Guide: Step 1 - Unified Event System

## Overview

This step implements **Idea 5: Unify the Event System** from the design document. It creates the "nervous system" that will connect all components of the refactored Remora application.

## Contract Touchpoints
- EventBus must implement `structured_agents.events.observer.Observer` and re-emit kernel events.
- Human-in-the-loop flows must rely on `HumanInputRequestEvent`/`HumanInputResponseEvent` and `EventBus.wait_for()`.
- Use the structured-agents event classes directly (no production stubs).

## Done Criteria
- [ ] `events.py` exports Remora + structured-agents event types without stub fallbacks.
- [ ] `EventBus` supports `subscribe`, `stream`, and `wait_for` and passes a basic unit test.
- [ ] Kernel events and Remora graph events emit through the same bus instance.

## What You're Building

- **`src/remora/events.py`** — All Remora event types as frozen dataclasses + union type
- **`src/remora/event_bus.py`** — Implements structured-agents' Observer protocol + adds pub/sub

## Prerequisites

- Python 3.13+
- `structured-agents` package available (it's in optional dependencies)

---

## Step 1: Create `src/remora/events.py`

### Purpose
Define all Remora event types and re-export structured-agents events in a single unified taxonomy.

### Implementation

Create `src/remora/events.py` with the following structure. Import structured-agents event classes directly; if the dependency is missing, raise an import error rather than defining stub events.

```python
"""Unified event types for Remora.

This module defines all event types in the Remora ecosystem:
- Graph-level events (start, complete, errors)
- Agent-level events (start, complete, errors, human input)
- Kernel-level events from structured-agents

All events are frozen dataclasses for immutability and hashability.
"""

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Union

# Import structured-agents events
from structured_agents.events import (
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    RestartEvent,
    TurnCompleteEvent,
)


# Conditional import for type hints only
if TYPE_CHECKING:
    from remora.discovery import CSTNode
    from structured_agents import RunResult


# =============================================================================
# Remora Graph Events
# =============================================================================

@dataclass(frozen=True)
class GraphStartEvent:
    """Emitted when a graph execution begins."""
    graph_id: str
    node_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphCompleteEvent:
    """Emitted when a graph execution completes successfully."""
    graph_id: str
    results: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class GraphErrorEvent:
    """Emitted when a graph execution fails."""
    graph_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Agent Events
# =============================================================================

@dataclass(frozen=True)
class AgentStartEvent:
    """Emitted when an agent begins execution.
    
    Note: node field is typed as dict for now to avoid circular imports.
    The actual CSTNode type will be used in production.
    """
    graph_id: str
    agent_id: str
    node: dict[str, Any] = field(default_factory=dict)  # CSTNode as dict
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentCompleteEvent:
    """Emitted when an agent completes successfully."""
    graph_id: str
    agent_id: str
    result: dict[str, Any] = field(default_factory=dict)  # RunResult as dict
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentErrorEvent:
    """Emitted when an agent fails."""
    graph_id: str
    agent_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Human-in-the-Loop Events
# =============================================================================

@dataclass(frozen=True)
class HumanInputRequestEvent:
    """Emitted when an agent requests human input.
    
    The dashboard should display this to the user and wait for response.
    """
    graph_id: str
    agent_id: str
    request_id: str
    question: str
    options: list[str] | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class HumanInputResponseEvent:
    """Emitted when human responds to an input request.
    
    This event resolves the corresponding request's wait_for.
    """
    request_id: str
    response: str
    timestamp: float = field(default_factory=time.time)


# =============================================================================
# Union Type
# =============================================================================

RemoraEvent = Union[
    # Graph events
    GraphStartEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    # Agent events
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    # Human-in-the-loop
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    # structured-agents kernel events
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
]


__all__ = [
    # Remora events
    "GraphStartEvent",
    "GraphCompleteEvent", 
    "GraphErrorEvent",
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    # Re-exported structured-agents events
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    # Union type
    "RemoraEvent",
]
```

### Key Design Decisions

1. **Frozen dataclasses** — All events are immutable for safety in async contexts
2. **Time field default factory** — Automatic timestamp generation
3. **Stub types** — If structured-agents isn't installed, provide stub dataclasses so the module still loads
4. **Dict for complex types** — Use `dict[str, Any]` for `CSTNode` and `RunResult` to avoid circular imports; the actual types are documented in comments

---

## Step 2: Update `src/remora/event_bus.py`

### Purpose
Replace the current string-based EventBus with a type-based system that implements structured-agents' Observer protocol.

### Implementation

Replace the content of `src/remora/event_bus.py` with:

```python
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


# Type variable for wait_for return type
T = TypeVar("T", bound=RemoraEvent)


# Alias for event handlers
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
        self._all_handlers: list[EventHandler] = []  # For "emit to all"
        self._subscriptions: list[Subscription] = []
        self._logger = logging.getLogger(__name__)
    
    # =========================================================================
    # Observer Protocol (for structured-agents integration)
    # =========================================================================
    
    async def emit(self, event: RemoraEvent) -> None:
        """Observer protocol method - receives all events.
        
        This is the entry point for structured-agents to emit events
        through Remora's EventBus.
        """
        await self._notify_handlers(event)
    
    # =========================================================================
    # Pub/Sub API
    # =========================================================================
    
    def subscribe(self, event_type: type[T], handler: Callable[[T], Awaitable[None]]) -> None:
        """Subscribe to a specific event type.
        
        Args:
            event_type: The event class to subscribe to
            handler: Async function to call when event is emitted
            
        Example:
            event_bus.subscribe(AgentStartEvent, async def handler(event):
                print(f"Agent started: {event.agent_id}")
            )
        """
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
        self._subscriptions.append(Subscription(event_type, handler))
    
    def unsubscribe(self, handler: EventHandler) -> None:
        """Remove a subscription by handler.
        
        Args:
            handler: The handler function to remove
        """
        # Remove from type-specific handlers
        for event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]
        
        # Remove from all-handlers
        self._all_handlers = [h for h in self._all_handlers if h != handler]
        
        # Remove from subscriptions tracking
        self._subscriptions = [
            s for s in self._subscriptions if s.handler != handler
        ]
    
    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to ALL events.
        
        Useful for logging, metrics, debugging.
        """
        self._all_handlers.append(handler)
    
    # =========================================================================
    # Streaming API
    # =========================================================================
    
    @asynccontextmanager
    async def _event_queue(self) -> AsyncIterator[asyncio.Queue[RemoraEvent]]:
        """Create a queue for streaming events."""
        queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()
        try:
            yield queue
        finally:
            # Clean up any pending queue items
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
            
        Example:
            async for event in event_bus.stream(AgentStartEvent, AgentCompleteEvent):
                print(event)
        """
        return EventStream(self, set(event_types) if event_types else None)
    
    # =========================================================================
    # Wait For API (for human-in-the-loop)
    # =========================================================================
    
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
            
        Example:
            response = await event_bus.wait_for(
                HumanInputResponseEvent,
                lambda e: e.request_id == request_id,
                timeout=300
            )
        """
        loop = asyncio.get_event_loop()
        future: asyncio.Future[T] = loop.create_future()
        
        def handler(event: RemoraEvent) -> None:
            try:
                if isinstance(event, event_type) and predicate(event):
                    future.set_result(event)
            except Exception as e:
                future.set_exception(e)
        
        # Subscribe temporarily
        self.subscribe(event_type, handler)
        
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            raise
        finally:
            # Always clean up subscription
            self.unsubscribe(handler)
    
    # =========================================================================
    # Internal Methods
    # =========================================================================
    
    async def _notify_handlers(self, event: RemoraEvent) -> None:
        """Notify all matching handlers with error isolation."""
        handlers: list[EventHandler] = []
        
        # Get type-specific handlers
        event_type = type(event)
        for t, h in self._handlers.items():
            if isinstance(event, t):
                handlers.extend(h)
        
        # Add all-handlers
        handlers.extend(self._all_handlers)
        
        if not handlers:
            return
        
        # Notify all concurrently with error isolation
        results = await asyncio.gather(
            *[self._safe_handler(h, event) for h in handlers],
            return_exceptions=True
        )
        
        # Log any errors
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._logger.exception(f"Event handler {handlers[i]} failed: {result}")
    
    async def _safe_handler(self, handler: EventHandler, event: RemoraEvent) -> None:
        """Execute handler with error isolation."""
        try:
            await handler(event)
        except Exception:
            raise  # Let _notify_handlers handle logging


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
        # Lazily start consuming
        if self._handler is None:
            self._handler = self._enqueue
            self._bus.subscribe_all(self._handler)
            self._running = True
        
        if not self._running:
            raise StopAsyncIteration
        
        try:
            event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            
            # Filter by type if specified
            if self._types and type(event) not in self._types:
                # Skip this event, try again
                return await self.__anext__()
            
            return event
        except asyncio.TimeoutError:
            # Check if we should continue
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
            self._bus._all_handlers = [
                h for h in self._bus._all_handlers if h != self._handler
            ]
            self._handler = None


# =============================================================================
# Module-level Instance (for backwards compatibility)
# =============================================================================

_event_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance.
    
    For backwards compatibility with existing code that uses:
        from remora.event_bus import get_event_bus
    """
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus


def set_event_bus(bus: EventBus) -> None:
    """Set the global event bus instance.
    
    Useful for testing or custom configurations.
    """
    global _event_bus
    _event_bus = bus


__all__ = [
    "EventBus",
    "EventStream", 
    "Subscription",
    "get_event_bus",
    "set_event_bus",
    "RemoraEvent",
]
```

### Key Design Decisions

1. **Implements Observer protocol** — `emit()` method matches structured-agents' expected interface
2. **Type-based subscription** — Instead of `"agent:*"` strings, use `AgentStartEvent` class
3. **No queue for low latency** — Direct handler invocation; use `stream()` for buffered consumption
4. **wait_for cleanup** — Uses try/finally to ensure subscription is removed even on timeout
5. **Backwards compatibility** — Keeps `get_event_bus()` for existing code

---

## Step 3: Update Exports in `src/remora/__init__.py`

### Purpose
Export the new event types and EventBus for public API.

### Implementation

Read the current `__init__.py` and add these exports:

```python
# Add to existing exports
from remora.events import (
    # Graph events
    GraphStartEvent,
    GraphCompleteEvent,
    GraphErrorEvent,
    # Agent events
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    # Human-in-the-loop
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    # structured-agents events (re-exported)
    KernelStartEvent,
    KernelEndEvent,
    ToolCallEvent,
    ToolResultEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    # Union type
    RemoraEvent,
)

from remora.event_bus import EventBus, get_event_bus

__all__ = [
    # ... existing exports ...
    # Events
    "GraphStartEvent",
    "GraphCompleteEvent",
    "GraphErrorEvent", 
    "AgentStartEvent",
    "AgentCompleteEvent",
    "AgentErrorEvent",
    "HumanInputRequestEvent",
    "HumanInputResponseEvent",
    "KernelStartEvent",
    "KernelEndEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "RemoraEvent",
    # EventBus
    "EventBus",
    "get_event_bus",
]
```

---

## Step 4: Write Tests

### Purpose
Verify the event system works correctly.

### Implementation

Create `tests/test_events.py`:

```python
"""Tests for the unified event system."""

import asyncio
import pytest

from remora.events import (
    AgentStartEvent,
    AgentCompleteEvent,
    AgentErrorEvent,
    GraphStartEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    RemoraEvent,
)
from remora.event_bus import EventBus, get_event_bus


class TestEventTypes:
    """Test event dataclasses are properly defined."""
    
    def test_graph_start_event(self):
        event = GraphStartEvent(graph_id="test-graph", node_count=5)
        assert event.graph_id == "test-graph"
        assert event.node_count == 5
        assert event.timestamp > 0
    
    def test_agent_events_are_frozen(self):
        """Events should be immutable."""
        event = AgentStartEvent(
            graph_id="g1",
            agent_id="a1",
            node={"name": "test"}
        )
        with pytest.raises(AttributeError):
            event.agent_id = "different"  # type: ignore
    
    def test_human_input_request_with_options(self):
        """Human input can have options."""
        event = HumanInputRequestEvent(
            graph_id="g1",
            agent_id="a1", 
            request_id="req-123",
            question="Which option?",
            options=["option_a", "option_b", "option_c"]
        )
        assert event.options == ["option_a", "option_b", "option_c"]
    
    def test_human_input_request_without_options(self):
        """Human input can be free-form (no options)."""
        event = HumanInputRequestEvent(
            graph_id="g1",
            agent_id="a1",
            request_id="req-456", 
            question="What should I do?"
        )
        assert event.options is None


class TestEventBus:
    """Test EventBus functionality."""
    
    @pytest.fixture
    def bus(self):
        """Fresh EventBus for each test."""
        return EventBus()
    
    @pytest.mark.asyncio
    async def test_subscribe_and_emit(self, bus):
        """Basic subscribe/emit works."""
        received = []
        
        async def handler(event: AgentStartEvent):
            received.append(event)
        
        bus.subscribe(AgentStartEvent, handler)
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        assert len(received) == 1
        assert received[0].agent_id == "a1"
    
    @pytest.mark.asyncio
    async def test_unsubscribe(self, bus):
        """Unsubscribe removes handler."""
        received = []
        
        async def handler(event: AgentStartEvent):
            received.append(event)
        
        bus.subscribe(AgentStartEvent, handler)
        bus.unsubscribe(handler)
        
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        assert len(received) == 0
    
    @pytest.mark.asyncio
    async def test_multiple_handlers_same_type(self, bus):
        """Multiple handlers can subscribe to same event type."""
        received1 = []
        received2 = []
        
        async def handler1(event: AgentStartEvent):
            received1.append(event)
        
        async def handler2(event: AgentStartEvent):
            received2.append(event)
        
        bus.subscribe(AgentStartEvent, handler1)
        bus.subscribe(AgentStartEvent, handler2)
        
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        assert len(received1) == 1
        assert len(received2) == 1
    
    @pytest.mark.asyncio
    async def test_subscribe_all(self, bus):
        """subscribe_all receives all events."""
        received = []
        
        async def all_handler(event: RemoraEvent):
            received.append(event)
        
        bus.subscribe_all(all_handler)
        
        await bus.emit(GraphStartEvent(graph_id="g1", node_count=1))
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        assert len(received) == 2
    
    @pytest.mark.asyncio
    async def test_emit_error_isolation(self, bus):
        """One failing handler doesn't affect others."""
        good_received = []
        
        async def good_handler(event: AgentStartEvent):
            good_received.append(event)
        
        async def bad_handler(event: AgentStartEvent):
            raise ValueError("Handler error")
        
        bus.subscribe(AgentStartEvent, bad_handler)
        bus.subscribe(AgentStartEvent, good_handler)
        
        # Should not raise
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        # Good handler should have received the event
        assert len(good_received) == 1


class TestEventStream:
    """Test event streaming."""
    
    @pytest.mark.asyncio
    async def test_stream_filtered(self):
        """Stream can filter by event type."""
        bus = EventBus()
        
        # Start streaming in background
        stream_task = asyncio.create_task(self._collect_stream(
            bus.stream(AgentStartEvent)
        ))
        
        # Emit different event types
        await bus.emit(GraphStartEvent(graph_id="g1", node_count=1))
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        await bus.emit(AgentCompleteEvent(graph_id="g1", agent_id="a1", result={}))
        
        # Give stream time to process
        await asyncio.sleep(0.1)
        
        # Cancel and check
        stream_task.cancel()
        try:
            events = await stream_task
        except asyncio.CancelledError:
            events = stream_task.result() if stream_task.done() else []
        
        # Should only have AgentStartEvent (filtered)
        assert all(isinstance(e, AgentStartEvent) for e in events)
        assert len(events) == 1
    
    @pytest.mark.asyncio
    async def test_stream_all_types(self):
        """Stream with no filter gets all events."""
        bus = EventBus()
        
        stream_task = asyncio.create_task(self._collect_stream(bus.stream()))
        
        await bus.emit(GraphStartEvent(graph_id="g1", node_count=1))
        await bus.emit(AgentStartEvent(graph_id="g1", agent_id="a1", node={}))
        
        await asyncio.sleep(0.1)
        stream_task.cancel()
        
        try:
            events = await stream_task
        except asyncio.CancelledError:
            events = stream_task.result() if stream_task.done() else []
        
        assert len(events) == 2
    
    async def _collect_stream(self, stream, max_events=10):
        """Helper to collect events from a stream."""
        events = []
        async for event in stream:
            events.append(event)
            if len(events) >= max_events:
                break
        return events


class TestWaitFor:
    """Test wait_for functionality."""
    
    @pytest.mark.asyncio
    async def test_wait_for_resolves(self):
        """wait_for resolves when matching event emitted."""
        bus = EventBus()
        
        async def emitter():
            await asyncio.sleep(0.1)
            await bus.emit(HumanInputResponseEvent(
                request_id="req-123",
                response="my answer"
            ))
        
        # Start emitter in background
        asyncio.create_task(emitter())
        
        # Wait for the response
        result = await bus.wait_for(
            HumanInputResponseEvent,
            lambda e: e.request_id == "req-123",
            timeout=5.0
        )
        
        assert result.response == "my answer"
    
    @pytest.mark.asyncio
    async def test_wait_for_timeout(self):
        """wait_for raises TimeoutError on timeout."""
        bus = EventBus()
        
        with pytest.raises(asyncio.TimeoutError):
            await bus.wait_for(
                HumanInputResponseEvent,
                lambda e: e.request_id == "nonexistent",
                timeout=0.1
            )
    
    @pytest.mark.asyncio
    async def test_wait_for_predicate_filter(self):
        """wait_for only resolves when predicate matches."""
        bus = EventBus()
        
        async def emitter():
            await asyncio.sleep(0.05)
            await bus.emit(HumanInputResponseEvent(
                request_id="req-1",  # Wrong ID
                response="wrong"
            ))
            await asyncio.sleep(0.05)
            await bus.emit(HumanInputResponseEvent(
                request_id="req-2",  # Right ID
                response="right"
            ))
        
        asyncio.create_task(emitter())
        
        result = await bus.wait_for(
            HumanInputResponseEvent,
            lambda e: e.request_id == "req-2",
            timeout=5.0
        )
        
        assert result.request_id == "req-2"
        assert result.response == "right"
    
    @pytest.mark.asyncio
    async def test_wait_for_cleans_up_subscription(self):
        """Subscription is removed after wait_for completes."""
        bus = EventBus()
        
        # Emit after a delay so wait_for times out
        async def late_emit():
            await asyncio.sleep(0.2)
            await bus.emit(HumanInputResponseEvent(
                request_id="req-late",
                response="late"
            ))
        
        asyncio.create_task(late_emit())
        
        with pytest.raises(asyncio.TimeoutError):
            await bus.wait_for(
                HumanInputResponseEvent,
                lambda e: e.request_id == "req-early",
                timeout=0.1
            )
        
        # Subscription should be cleaned up - emit should not fail
        await bus.emit(HumanInputResponseEvent(
            request_id="req-late",
            response="late"
        ))


class TestObserverProtocol:
    """Test structured-agents Observer protocol compatibility."""
    
    @pytest.mark.asyncio
    async def test_emit_is_observer_protocol(self):
        """EventBus.emit() matches Observer protocol."""
        bus = EventBus()
        received = []
        
        async def handler(event: RemoraEvent):
            received.append(event)
        
        bus.subscribe(GraphStartEvent, handler)
        
        # This is how structured-agents calls the observer
        await bus.emit(GraphStartEvent(graph_id="g1", node_count=5))
        
        assert len(received) == 1


class TestBackwardsCompatibility:
    """Test backwards compatibility with existing code."""
    
    def test_get_event_bus_singleton(self):
        """get_event_bus returns singleton instance."""
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        assert bus1 is bus2
    
    @pytest.mark.asyncio
    async def test_global_bus_works(self):
        """Global event bus can be used directly."""
        from remora.event_bus import _event_bus
        
        # Reset global
        import remora.event_bus
        remora.event_bus._event_bus = None
        
        bus = get_event_bus()
        
        received = []
        async def handler(event):
            received.append(event)
        
        bus.subscribe(GraphStartEvent, handler)
        await bus.emit(GraphStartEvent(graph_id="g1", node_count=1))
        
        assert len(received) == 1
```

---

## Step 5: Verification

### Run Basic Import Test
```bash
cd /home/andrew/Documents/Projects/remora
python -c "from remora import EventBus, RemoraEvent; print('Import OK')"
```

### Run Tests
```bash
cd /home/andrew/Documents/Projects/remora
python -m pytest tests/test_events.py -v
```

### Expected Output
All tests should pass. If structured-agents isn't installed, the stub types will be used and tests will still work.

---

## Common Pitfalls to Avoid

1. **wait_for cleanup** — Always use try/finally to unsubscribe, even on timeout
2. **Circular imports** — Use `dict[str, Any]` for CSTNode/RunResult in events, not direct type references
3. **Type hints** — Use `TypeAlias` for complex union types to help type checkers
4. **Error isolation** — Use `asyncio.gather(return_exceptions=True)` so one handler failure doesn't break others
5. **Queue overflow** — In stream(), handle QueueFull gracefully (drop oldest or warn)

---

## Files Created/Modified Summary

| File | Action | Description |
|------|--------|-------------|
| `src/remora/events.py` | CREATE | ~120 lines - All event types + union |
| `src/remora/event_bus.py` | MODIFY | ~200 lines - New EventBus implementation |
| `src/remora/__init__.py` | MODIFY | Add event exports |
| `tests/test_events.py` | CREATE | ~250 lines - Comprehensive tests |

---

## Next Step

After this step is complete and verified, proceed to **Step 2: Discovery Module** (Idea 9) which consolidates the 5 discovery files into one.
