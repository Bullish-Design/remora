# BLUE SKY V2 REWRITE GUIDE

> A Step-by-Step Refactoring Guide for Building the Next Generation of Remora

**Target Audience**: Junior developers new to the Remora codebase  
**Goal**: Build a simple, elegant, intuitive system for interactive agent graph workflows  
**Philosophy**: Simplicity first. Every line of code should be explainable in one sentence.

---

## Table of Contents

1. [Overview & Philosophy](#1-overview--philosophy)
2. [Phase 1: Foundation - Unified Event Bus](#phase-1-foundation---unified-event-bus)
3. [Phase 2: Core - AgentNode & AgentGraph](#phase-2-core---agentnode--agentgraph)
4. [Phase 3: Interaction - Built-in User Tools](#phase-3-interaction---built-in-user-tools)
5. [Phase 4: Orchestration - Declarative Graph DSL](#phase-4-orchestration---declarative-graph-dsl)
6. [Phase 5: Integration - Workspace & Discovery](#phase-6-integration---workspace--discovery)
7. [Phase 6: Persistence - Snapshots (KV-Based)](#phase-5-persistence---snapshots)
8. [Phase 7: Workspace Checkpointing](#6b-phase-5b-workspace-checkpointing-materialization)
9. [Phase 8: UI - Event-Driven Frontends](#phase-7-ui---event-driven-frontends)
10. [Testing Strategy](#testing-strategy)
11. [Migration Path](#migration-path)
12. [Appendix A: Code to Remove](#appendix-a-code-to-remove)
13. [Appendix B: Final V2 File Structure](#appendix-b-final-v2-file-structure)

---

## 1. Overview & Philosophy

### 1.1 The Vision

Remora V2 should be **understandable at a glance**. A new developer should be able to read the core files and explain what the system does in under 5 minutes.

### 1.2 The Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              User/UI                                        │
│  (Web Dashboard, CLI, Mobile Remote - all just event consumers)           │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ SSE/WebSocket/HTTP
                                      ▼
┌─────────────────────────────────────┴─────────────────────────────────────┐
│                        UNIFIED EVENT BUS                                   │
│              (Everything flows through one pipe)                          │
│   - agent_created, agent_blocked, agent_resumed, tool_called, etc.      │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        ▼                             ▼                             ▼
┌───────────────┐           ┌───────────────┐           ┌───────────────┐
│   AgentGraph  │           │  AgentKernel  │           │   Discovery   │
│ (composition) │──────────▶│  (execution)  │           │  (AST parse)   │
└───────────────┘           └───────────────┘           └───────────────┘
                                      │
                                      ▼
                           ┌───────────────────────┐
                           │   grail + cairn      │
                           │ (sandbox execution)   │
                           └───────────────────────┘
```

### 1.3 Key Principles

1. **One concept of "agent"**: Not three (CSTNode, AgentContext, Kernel). Just one: `AgentNode`
2. **Events are first-class**: The event bus is the central nervous system
3. **Declarative over imperative**: Say what you want, not how to do it
4. **User interaction is a tool**: Not an add-on, but a native capability
5. **Everything is testable**: If you can't unit test it, refactor it

### 1.4 What We're Building

```python
# This should be the entire public API for running agents
async def main():
    # 1. Discover code structure
    nodes = await discover(pathlib.Path("src"))
    
    # 2. Create a graph of agents
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target=nodes)
    graph.agent("docstring", bundle="docstring", target=nodes)
    graph.after("lint").run("docstring")  # Dependencies
    
    # 3. Execute with user interaction
    results = await graph.execute(
        interactive=True,  # Enable __ask_user__ tool
        on_block=lambda agent, question: user_input(question)
    )
    
    # 4. Subscribe to real-time updates
    async for event in graph.events:
        print(event)
```

---

## 2. Phase 1: Foundation - Unified Event Bus

**Goal**: Replace the dual event systems (EventEmitter + structured-agents Observer) with one unified event bus.

**Time Estimate**: 2-3 days

### 2.1 What Exists Now

- `src/remora/events.py`: Fire-and-forget JSONL emitter
- `src/remora/event_bridge.py`: Translation layer to convert structured-agents events to Remora format
- `structured-agents/observer/`: In-process only callbacks

### 2.2 Design Principles

Based on the review, we use **Pydantic-first** for the public API with these improvements:

1. **Pydantic for validation** - Invalid event shapes rejected at creation
2. **Literal types for safety** - Catches typos at type-check time
3. **Backpressure on queue** - Prevents memory issues with `maxsize=1000`
4. **Concurrent subscriber notification** - Uses `asyncio.gather()` with error isolation

### 2.3 What to Build

Create `src/remora/event_bus.py`:

```python
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
from datetime import datetime
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, Field, ConfigDict

# =============================================================================
# Event Categories & Actions (Literal types for type safety)
# =============================================================================

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

# =============================================================================
# Event Model (Pydantic-first)
# =============================================================================

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
    
    # Identifiers
    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex[:8])
    timestamp: datetime = Field(default_factory=datetime.now)
    
    # Category (literal for type safety)
    category: EventCategory
    
    # Action (string for extensibility)
    action: str
    
    # Context
    agent_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    session_id: str | None = None  # For multi-session support
    
    # Payload (any additional data)
    payload: dict[str, Any] = Field(default_factory=dict)
    
    @property
    def type(self) -> str:
        """Human-readable type for logging. Returns 'agent_blocked'."""
        return f"{self.category}_{self.action}"
    
    @property
    def subscription_key(self) -> str:
        """Key for subscription matching. Returns 'agent:blocked'."""
        return f"{self.category}:{self.action}"
    
    # -------------------------------------------------------------------------
    # Convenience constructors
    # -------------------------------------------------------------------------
    
    @classmethod
    def agent_started(cls, agent_id: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.STARTED, 
                  agent_id=agent_id, payload=payload)
    
    @classmethod
    def agent_blocked(cls, agent_id: str, question: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.BLOCKED,
                  agent_id=agent_id, payload={"question": question, **payload})
    
    @classmethod
    def agent_resumed(cls, agent_id: str, answer: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.RESUMED,
                  agent_id=agent_id, payload={"answer": answer, **payload})
    
    @classmethod
    def agent_completed(cls, agent_id: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.COMPLETED,
                  agent_id=agent_id, payload=payload)
    
    @classmethod
    def agent_failed(cls, agent_id: str, error: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.FAILED,
                  agent_id=agent_id, payload={"error": error, **payload})
    
    @classmethod
    def agent_cancelled(cls, agent_id: str, **payload) -> "Event":
        return cls(category="agent", action=AgentAction.CANCELLED,
                  agent_id=agent_id, payload=payload)
    
    @classmethod
    def tool_called(cls, tool_name: str, call_id: str, **payload) -> "Event":
        return cls(category="tool", action=ToolAction.CALLED,
                  payload={"tool_name": tool_name, "call_id": call_id, **payload})
    
    @classmethod
    def tool_result(cls, tool_name: str, call_id: str, **payload) -> "Event":
        return cls(category="tool", action=ToolAction.COMPLETED,
                  payload={"tool_name": tool_name, "call_id": call_id, **payload})


# =============================================================================
# Event Handler Type
# =============================================================================

EventHandler = Callable[[Event], Awaitable[None]]


# =============================================================================
# EventBus Implementation
# =============================================================================

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
    
    def __init__(self, max_queue_size: int = 1000, telemetry=None):
        # Backpressure: prevent memory issues with unbounded queue
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._running = False
        self._logger = logging.getLogger(__name__)
        # Optional telemetry for metrics/tracing (e.g., OpenTelemetry, custom)
        self._telemetry = telemetry
    
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Publish to queue for stream consumers (with backpressure)
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._logger.warning(
                f"Event queue full, dropping event: {event.type}"
            )
            return
        
        # Optional telemetry recording
        if self._telemetry:
            await self._record_telemetry(event)
        
        # Notify subscribers concurrently
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
        
        # Collect all matching handlers
        handlers = []
        
        # Direct match (e.g., "agent:blocked")
        handlers.extend(self._subscribers.get(event_key, []))
        
        # Wildcard matches (e.g., "agent:*" matches "agent:blocked")
        for pattern, pattern_handlers in self._subscribers.items():
            if pattern.endswith("*"):
                prefix = pattern[:-1]  # "agent:"
                if event_key.startswith(prefix):
                    handlers.extend(pattern_handlers)
        
        if not handlers:
            return
        
        # Run concurrently with error isolation
        results = await asyncio.gather(
            *[self._safe_handler(h, event) for h in handlers],
            return_exceptions=True
        )
        
        # Log any failures
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._logger.exception(
                    f"Event handler {handlers[i]} failed: {result}"
                )
    
    async def _safe_handler(self, handler: EventHandler, event: Event) -> None:
        """Execute handler with error isolation."""
        try:
            await handler(event)
        except Exception:
            raise  # Re-raise for asyncio.gather to catch
    
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
            self._subscribers[pattern] = [
                h for h in self._subscribers[pattern] 
                if h != handler
            ]
    
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
    
    def __aiter__(self):
        return self
    
    async def __anext__(self) -> Event:
        return await self._queue.get()


# =============================================================================
# Global Instance
# =============================================================================

_event_bus: EventBus | None = None

def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
```

### 2.3 Testing Requirements

Create `tests/unit/test_event_bus.py`:

```python
"""Tests for the unified event bus."""

import pytest
import asyncio
from remora.event_bus import EventBus, Event, EventType


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.mark.asyncio
async def test_publish_and_subscribe(event_bus):
    """Events should be delivered to subscribers."""
    received = []
    
    async def handler(event: Event):
        received.append(event)
    
    await event_bus.subscribe(EventType.AGENT_STARTED, handler)
    
    await event_bus.publish(Event(
        type=EventType.AGENT_STARTED,
        agent_id="test-123"
    ))
    
    # Give time for async handler
    await asyncio.sleep(0.01)
    
    assert len(received) == 1
    assert received[0].agent_id == "test-123"


@pytest.mark.asyncio
async def test_wildcard_subscription(event_bus):
    """Wildcard patterns should match multiple events."""
    received = []
    
    async def handler(event: Event):
        received.append(event)
    
    await event_bus.subscribe("agent_*", handler)
    
    await event_bus.publish(Event(type=EventType.AGENT_STARTED, agent_id="1"))
    await event_bus.publish(Event(type=EventType.AGENT_BLOCKED, agent_id="2"))
    await event_bus.publish(Event(type=EventType.TOOL_CALLED, agent_id="3"))
    
    await asyncio.sleep(0.01)
    
    assert len(received) == 2  # Only agent_* events


@pytest.mark.asyncio
async def test_stream_iteration(event_bus):
    """stream() should yield published events."""
    results = []
    
    async def producer():
        await event_bus.publish(Event(type=EventType.AGENT_STARTED, agent_id="1"))
        await event_bus.publish(Event(type=EventType.AGENT_COMPLETED, agent_id="1"))
    
    async def consumer():
        async for event in event_bus.stream():
            results.append(event)
            if len(results) >= 2:
                break
    
    await asyncio.gather(producer(), consumer())
    
    assert len(results) == 2


@pytest.mark.asyncio
async def test_event_serialization(event_bus):
    """Events should serialize to JSON."""
    event = Event(
        type=EventType.AGENT_BLOCKED,
        agent_id="test",
        payload={"question": "Continue?"}
    )
    
    data = event.to_dict()
    assert data["type"] == "agent_blocked"
    assert data["payload"]["question"] == "Continue?"
    
    json_str = event.to_json()
    assert "agent_blocked" in json_str
```

### 2.4 Migration Notes

- Replace `EventEmitter.emit()` calls with `event_bus.publish()`
- Remove `event_bridge.py` entirely (no more translation layer)
- Update structured-agents Observer to publish to this bus instead

### 2.5 Success Criteria

- [ ] Single Event class for all event types
- [ ] Async pub/sub works correctly
- [ ] Wildcard pattern matching works
- [ ] Stream iteration works
- [ ] JSON serialization works
- [ ] All existing event types mapped to EventType enum

---

## 3. Phase 2: Core - AgentNode & AgentGraph

**Goal**: Unify the three separate "agent" concepts into one elegant `AgentNode` class.

**Time Estimate**: 3-4 days

### 3.1 What Exists Now

- `CSTNode`: AST node from source code
- `RemoraAgentContext`: Runtime state for an agent run  
- `KernelRunner`: Wrapper around structured-agents AgentKernel

### 3.2 What to Build

Create `src/remora/agent_graph.py`:

```python
"""AgentGraph - Declarative Agent Composition.

This module provides:
1. AgentNode: Unified concept of "a thing that runs"
2. AgentGraph: Declarative composition of AgentNodes
3. Execution engine for running graphs
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

from remora.event_bus import EventBus, Event, EventType, get_event_bus


class AgentState(str, Enum):
    """All possible states for an agent."""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"      # Waiting for user input
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorPolicy(str, Enum):
    """Graph-level error handling policies."""
    STOP_GRAPH = "stop_graph"       # Stop entire graph on any failure
    SKIP_DOWNSTREAM = "skip_downstream"  # Skip dependent agents, continue others
    CONTINUE = "continue"           # Continue execution regardless of failures


@dataclass
class AgentNode:
    """The unified concept of an agent.
    
    One class replaces: CSTNode + RemoraAgentContext + KernelRunner
    
    An AgentNode is:
    - An identity (id)
    - A target (code to operate on)
    - A state (what it's doing)
    - An inbox (for user messages)
    - A kernel (the execution engine)
    - A result (when done)
    """
    id: str
    name: str
    
    # What this agent operates on
    target: str                    # Source code
    target_path: Path | None = None  # File path
    target_type: str = "unknown"   # "function", "class", etc.
    
    # Execution
    state: AgentState = AgentState.PENDING
    bundle: str = ""               # Which bundle to use
    kernel: Any = None             # The structured-agents kernel
    
    # Inbox (key innovation!)
    inbox: "AgentInbox" = field(default_factory=lambda: AgentInbox())
    
    # Results
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    
    # Graph composition
    upstream: list[str] = field(default_factory=list)   # Depends on these
    downstream: list[str] = field(default_factory=list)  # Fed to these
    
    async def cancel(self, event_bus: EventBus | None = None) -> None:
        """Cancel this agent's execution.
        
        Sets state to CANCELLED and resolves any pending user response with
        a cancellation signal.
        """
        self.state = AgentState.CANCELLED
        self.error = "Cancelled by user"
        
        # Resolve any pending user response
        await self.inbox.resolve_response_async("")
        
        # Publish cancelled event
        if event_bus:
            await event_bus.publish(Event.agent_cancelled(
                agent_id=self.id,
                error=self.error
            ))


@dataclass
class AgentInbox:
    """The inbox for user interaction.
    
    Every AgentNode has one of these. It handles:
    - Blocking: Agent asks user, waits for response
    - Async: User sends message, agent receives on next turn
    
    Thread-safety: Uses asyncio.Lock to prevent race conditions.
    """
    # Lock for thread-safe operations
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    
    # For blocking (agent asks user)
    blocked: bool = False
    blocked_question: str | None = None
    blocked_since: datetime | None = None
    _pending_response: asyncio.Future[str] | None = None
    
    # For async messages (user sends to running agent)
    _message_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    
    async def ask_user(self, question: str, timeout: float = 300.0) -> str:
        """Block and wait for user response."""
        async with self._lock:
            self.blocked = True
            self.blocked_question = question
            self.blocked_since = datetime.now()
            
            loop = asyncio.get_running_loop()
            self._pending_response = loop.create_future()
        
        try:
            response = await asyncio.wait_for(
                self._pending_response,
                timeout=timeout
            )
            return response
        finally:
            async with self._lock:
                self.blocked = False
                self.blocked_question = None
                self.blocked_since = None
                self._pending_response = None
    
    async def send_message(self, message: str) -> None:
        """Queue a message for the agent."""
        await self._message_queue.put(message)
    
    async def drain_messages(self) -> list[str]:
        """Get all queued messages."""
        messages = []
        while not self._message_queue.empty():
            messages.append(await self._message_queue.get())
        return messages
    
    def _resolve_response(self, response: str) -> bool:
        """Called by UI to resolve blocked ask_user.
        
        Returns True if response was successfully resolved,
        False if no pending response or already resolved.
        
        Thread-safe: Uses lock to prevent race conditions.
        """
        # Note: This is a sync method called from sync context (UI thread)
        # We can't use async with self._lock here, so we do a best-effort check
        # In practice, the coordinator handles all resolution async
        if self._pending_response and not self._pending_response.done():
            self._pending_response.set_result(response)
            return True
        return False
    
    async def resolve_response_async(self, response: str) -> bool:
        """Async version of resolve_response for use in async contexts.
        
        Returns True if response was successfully resolved.
        """
        async with self._lock:
            if self._pending_response and not self._pending_response.done():
                self._pending_response.set_result(response)
                return True
            return False


class AgentGraph:
    """A declarative graph of AgentNodes.
    
    Usage:
        graph = AgentGraph()
        
        # Add agents
        graph.agent("lint", bundle="lint", target=source_code)
        graph.agent("docstring", bundle="docstring", target=source_code)
        
        # Define dependencies
        graph.after("lint").run("docstring")
        
        # Execute
        results = await graph.execute()
    """
    
    def __init__(self, event_bus: EventBus | None = None):
        self.id = uuid.uuid4().hex[:8]
        self._event_bus = event_bus or get_event_bus()
        self._agents: dict[str, AgentNode] = {}
        self._execution_order: list[list[str]] = []  # Parallel batches
        self._running_tasks: set[asyncio.Task] = set()
    
    def agent(
        self, 
        name: str, 
        bundle: str, 
        target: str,
        target_path: Path | None = None,
        target_type: str = "unknown"
    ) -> "AgentGraph":
        """Add an agent to the graph."""
        node = AgentNode(
            id=f"{name}-{uuid.uuid4().hex[:4]}",
            name=name,
            bundle=bundle,
            target=target,
            target_path=target_path,
            target_type=target_type,
        )
        self._agents[name] = node
        return self
    
    def after(self, agent_name: str) -> "_GraphBuilder":
        """Start building dependencies from this agent."""
        return _GraphBuilder(self, agent_name)
    
    def execute(
        self, 
        max_concurrency: int = 4,
        interactive: bool = True
    ) -> "GraphExecutor":
        """Execute the graph and return an executor."""
        return GraphExecutor(
            graph=self,
            max_concurrency=max_concurrency,
            interactive=interactive,
            event_bus=self._event_bus,
        )
    
    def agents(self) -> dict[str, AgentNode]:
        return self._agents
    
    def __getitem__(self, name: str) -> AgentNode:
        return self._agents[name]
    
    async def cancel(self, event_bus: EventBus | None = None) -> None:
        """Cancel all agents in the graph."""
        for agent in self._agents.values():
            if agent.state not in (AgentState.COMPLETED, AgentState.FAILED, AgentState.CANCELLED):
                await agent.cancel(event_bus)


class _GraphBuilder:
    """Helper for building graph dependencies."""
    
    def __init__(self, graph: AgentGraph, from_agent: str):
        self._graph = graph
        self._from_agent = from_agent
    
    def run(self, *agent_names: str) -> AgentGraph:
        """Run these agents after the source agent completes."""
        source = self._graph[self._from_agent]
        for name in agent_names:
            target = self._graph[name]
            source.downstream.append(target.id)
            target.upstream.append(source.id)
        return self._graph
    
    def run_parallel(self, *agent_names: str) -> AgentGraph:
        """Run these agents in parallel after source completes."""
        # For now, treat as sequential
        return self.run(*agent_names)


class GraphExecutor:
    """Executes an AgentGraph.
    
    Returned by graph.execute(), this handles the actual running.
    """
    
    def __init__(
        self,
        graph: AgentGraph,
        max_concurrency: int,
        interactive: bool,
        event_bus: EventBus,
        error_policy: ErrorPolicy = ErrorPolicy.STOP_GRAPH,
    ):
        self._graph = graph
        self._max_concurrency = max_concurrency
        self._interactive = interactive
        self._event_bus = event_bus
        self._error_policy = error_policy
        self._semaphore = asyncio.Semaphore(max_concurrency)
    
    async def run(self) -> dict[str, Any]:
        """Execute all agents in dependency order."""
        # Build execution order (topological sort)
        batches = self._build_execution_batches()
        
        for batch in batches:
            # Run this batch in parallel
            tasks = [
                asyncio.create_task(self._run_agent(name))
                for name in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Check for failures and apply error policy
            if self._error_policy == ErrorPolicy.STOP_GRAPH:
                for result in results:
                    if isinstance(result, Exception):
                        break
        
        return {
            name: agent.result 
            for name, agent in self._graph.agents().items()
        }
    
    def _build_execution_batches(self) -> list[list[str]]:
        """Build batches of agents that can run in parallel."""
        # Simple implementation: one batch for now
        # TODO: Implement proper topological sort
        return [list(self._graph.agents().keys())]
    
    async def _run_agent(self, name: str) -> None:
        """Run a single agent."""
        agent = self._graph[name]
        
        async with self._semaphore:
            # Emit started event
            await self._event_bus.publish(Event(
                type=EventType.AGENT_STARTED,
                agent_id=agent.id,
                graph_id=self._graph.id,
                payload={"name": name, "bundle": agent.bundle}
            ))
            
            # TODO: Actually run the agent via structured-agents
            # For now, just mark complete
            agent.state = AgentState.COMPLETED
            
            await self._event_bus.publish(Event(
                type=EventType.AGENT_COMPLETED,
                agent_id=agent.id,
                graph_id=self._graph.id,
                payload={"name": name}
            ))
```

### 3.3 Testing Requirements

Create `tests/unit/test_agent_graph.py`:

```python
"""Tests for AgentNode and AgentGraph."""

import pytest
import asyncio
from remora.agent_graph import (
    AgentNode, AgentGraph, AgentState, AgentInbox, GraphExecutor
)
from remora.event_bus import EventBus, EventType


@pytest.fixture
def event_bus():
    return EventBus()


def test_create_agent_node():
    """AgentNode should have sensible defaults."""
    node = AgentNode(
        id="test-1",
        name="lint",
        target="def foo(): pass",
        bundle="lint"
    )
    
    assert node.state == AgentState.PENDING
    assert node.id == "test-1"
    assert node.bundle == "lint"


def test_agent_graph_add_agent():
    """Graph should track added agents."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="def foo(): pass")
    
    assert "lint" in graph.agents()
    assert graph["lint"].bundle == "lint"


def test_agent_graph_dependencies():
    """Graph should track dependencies."""
    graph = AgentGraph()
    graph.agent("lint", bundle="lint", target="code")
    graph.agent("docstring", bundle="docstring", target="code")
    graph.after("lint").run("docstring")
    
    assert "docstring" in graph["lint"].downstream
    assert "lint" in graph["docstring"].upstream


@pytest.mark.asyncio
async def test_agent_inbox_ask_user():
    """Inbox should block and resolve."""
    inbox = AgentInbox()
    
    async def resolve_later():
        await asyncio.sleep(0.01)
        inbox._resolve_response("yes")
    
    async def ask():
        return await inbox.ask_user("Continue?")
    
    result = await asyncio.gather(ask(), resolve_later())
    
    assert result[0] == "yes"
    assert inbox.blocked is False


@pytest.mark.asyncio
async def test_agent_inbox_send_message():
    """Inbox should queue messages."""
    inbox = AgentInbox()
    
    await inbox.send_message("Hello")
    await inbox.send_message("World")
    
    messages = await inbox.drain_messages()
    
    assert messages == ["Hello", "World"]


@pytest.mark.asyncio
async def test_graph_executor_creates_events(event_bus):
    """Executor should emit events."""
    graph = AgentGraph(event_bus)
    graph.agent("lint", bundle="lint", target="code")
    
    executor = graph.execute()
    await executor.run()
    
    # Check events were published
    # (In real test, you'd collect events from the bus)
```

### 3.4 Success Criteria

- [ ] Single AgentNode class replaces CSTNode + RemoraAgentContext + KernelRunner
- [ ] AgentGraph provides declarative API
- [ ] Dependencies can be expressed (after().run())
- [ ] Inbox works for blocking and async messages
- [ ] Events are published during execution

---

## 4. Phase 3: Interaction - Built-in User Tools

**Goal**: Make user interaction a native capability using Cairn's workspace KV store as the IPC mechanism.

**Time Estimate**: 2-3 days

### 4.1 Key Insight: Workspace-Based IPC

Based on the review (Appendix C), we use Cairn's existing KV store as the communication mechanism between agents and the coordinator. This eliminates the need for complex cross-process async handling.

**Why this works**:
- No cross-process async needed - just synchronous KV operations
- Cairn's workspace is already available to Grail externals
- Coordinator watches for questions, writes responses to inbox
- Natural persistence - questions survive crashes
- Zero Grail modifications required

### 4.2 Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Cairn Workspace                                    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         KV Store                                     │   │
│  │                                                                      │   │
│  │   outbox:question:001 ──────────────────────────────────────────┐  │   │
│  │   {                                                                │  │   │
│  │     "question": "Which docstring format?",                         │  │   │
│  │     "options": ["google", "numpy", "sphinx"],                     │  │   │
│  │     "status": "pending"                                            │  │   │
│  │   }                                                                │  │   │
│  │                                                                      │  │   │
│  │   inbox:response:001 ◀──────────────────────────────────────────┐  │   │
│  │   {                                                                │  │   │
│  │     "answer": "google"                                            │  │   │
│  │   }                                                                │  │   │
│  │                                                                      │  │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Agent (Grail subprocess):                                                  │
│    1. Writes to outbox:question:001                                        │
│    2. Polls inbox:response:001 until it exists                             │
│    3. Reads response and continues                                         │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Agent-Side: ask_user External Function

Create in `src/remora/externals.py`:

```python
"""Interactive external functions using Workspace KV for IPC.

This module provides ask_user using Cairn's KV store as the communication
mechanism between Grail subprocesses and the coordinator.
"""

import time
import uuid
from datetime import datetime
from typing import Any


def ask_user(
    question: str,
    options: list[str] | None = None,
    timeout: float = 300.0,
    poll_interval: float = 0.5
) -> str:
    """
    Ask the user a question and wait for their response.
    
    This function writes to the workspace KV store and polls for a response.
    No async needed - just synchronous KV operations that Grail supports.
    
    Args:
        question: The question to ask the user
        options: Optional constrained choices (makes UI easier)
        timeout: How long to wait for response (default 300s)
        poll_interval: How often to check for response (default 0.5s)
        
    Returns:
        The user's response string
        
    Raises:
        TimeoutError: If the user doesn't respond within timeout
    """
    # Get workspace from Grail context (already available to externals)
    workspace = _get_current_workspace()
    
    # Generate unique message ID
    msg_id = uuid.uuid4().hex[:8]
    outbox_key = f"outbox:question:{msg_id}"
    inbox_key = f"inbox:response:{msg_id}"
    
    # Write question to outbox
    workspace.kv.set(outbox_key, {
        "question": question,
        "options": options,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
        "timeout": timeout,
    })
    
    # Poll for response
    start_time = time.time()
    while time.time() - start_time < timeout:
        response = workspace.kv.get(inbox_key)
        if response is not None:
            # Mark question as answered
            current = workspace.kv.get(outbox_key) or {}
            workspace.kv.set(outbox_key, {
                **current,
                "status": "answered"
            })
            return response.get("answer", "")
        
        time.sleep(poll_interval)
    
    # Timeout
    current = workspace.kv.get(outbox_key) or {}
    workspace.kv.set(outbox_key, {
        **current,
        "status": "timeout"
    })
    raise TimeoutError(f"User did not respond within {timeout}s")


def _get_current_workspace():
    """Get the current workspace from Grail context.
    
    This is injected by Grail when running in a workspace context.
    """
    import contextvars
    _workspace: contextvars.ContextVar[Any] = contextvars.ContextVar("workspace")
    ws = _workspace.get(None)
    if ws is None:
        raise RuntimeError("ask_user called outside workspace context")
    return ws


def get_user_messages() -> list[str]:
    """
    Get any async messages the user has sent to this agent.
    
    Call this at the start of each turn to check for new context from the user.
    
    Returns:
        List of messages from the user
    """
    workspace = _get_current_workspace()
    
    # Get all messages from the user's inbox
    messages = []
    prefix = f"inbox:user_message:"
    
    try:
        entries = workspace.kv.list(prefix=prefix)
        for entry in entries:
            key = entry.get("key", "")
            if key.startswith(prefix):
                msg_id = key[len(prefix):]
                # Get message and mark as read
                msg = workspace.kv.get(key)
                if msg:
                    messages.append(msg.get("content", ""))
                # Delete after reading
                workspace.kv.delete(key)
    except Exception:
        pass  # Empty inbox is fine
    
    return messages
```

### 4.4 Coordinator-Side: Inbox Watcher

Create `src/remora/interactive/coordinator.py`:

```python
"""Workspace-based coordinator for handling interactive agents.

This module watches workspace KV stores for agent questions and writes responses.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from remora.event_bus import EventBus, Event, EventCategory


class QuestionPayload(BaseModel):
    """Payload from agent's outbox question."""
    question: str
    options: list[str] | None = None
    status: str  # "pending", "answered", "timeout"
    created_at: str
    timeout: float


class WorkspaceInboxCoordinator(BaseModel):
    """
    Watches workspace KV stores for agent questions and writes responses.
    
    This is the "parent process" side of the Workspace KV IPC pattern.
    """
    model_config = {"arbitrary_types_allowed": True}
    
    event_bus: EventBus
    _watchers: dict[str, asyncio.Task] = {}
    _poll_interval: float = 0.5
    
    async def watch_workspace(self, agent_id: str, workspace: Any) -> None:
        """Start watching a workspace for outbox questions."""
        
        async def watcher():
            while True:
                try:
                    questions = await self._list_pending_questions(workspace)
                    
                    for q in questions:
                        if q.status == "pending":
                            # Emit AGENT_BLOCKED event for UI
                            await self.event_bus.publish(Event.agent_blocked(
                                agent_id=agent_id,
                                question=q.question,
                                options=q.options or [],
                                msg_id=q.msg_id
                            ))
                except Exception as e:
                    logging.exception(f"Error watching workspace for {agent_id}")
                
                await asyncio.sleep(self._poll_interval)
        
        self._watchers[agent_id] = asyncio.create_task(watcher())
    
    async def respond(
        self,
        agent_id: str,
        msg_id: str,
        answer: str,
        workspace: Any
    ) -> None:
        """Write a response to the agent's inbox."""
        inbox_key = f"inbox:response:{msg_id}"
        
        await workspacebox_key, {
.kv.set(in            "answer": answer,
            "responded_at": datetime.now().isoformat(),
        })
        
        # Emit AGENT_RESUMED event
        await self.event_bus.publish(Event.agent_resumed(
            agent_id=agent_id,
            answer=answer,
            msg_id=msg_id
        ))
    
    async def stop_watching(self, agent_id: str) -> None:
        """Stop watching a workspace."""
        if agent_id in self._watchers:
            self._watchers[agent_id].cancel()
            try:
                await self._watchers[agent_id]
            except asyncio.CancelledError:
                pass
            del self._watchers[agent_id]
    
    async def _list_pending_questions(self, workspace: Any) -> list[QuestionPayload]:
        """List all pending questions in the workspace outbox."""
        entries = await workspace.kv.list(prefix="outbox:question:")
        questions = []
        
        for entry in entries:
            key = entry.get("key", "")
            if not key.startswith("outbox:question:"):
                continue
                
            data = await workspace.kv.get(key)
            if data:
                questions.append(QuestionPayload(
                    **data,
                    msg_id=key.split(":")[-1]
                ))
        
        return questions
```

### 4.5 Integration with AgentNode

Update `AgentNode` to use the coordinator:

```python
# In agent_graph.py

class AgentNode:
    # ... existing fields ...
    
    _inbox_coordinator: WorkspaceInboxCoordinator | None = None
    
    async def start_watching(self, workspace: Any) -> None:
        """Start the inbox coordinator watching this agent's workspace."""
        if self._inbox_coordinator:
            await self._inbox_coordinator.watch_workspace(self.id, workspace)
    
    async def stop_watching(self) -> None:
        """Stop watching the workspace."""
        if self._inbox_coordinator:
            await self._inbox_coordinator.stop_watching(self.id)
```

### 4.6 Testing Requirements

```python
# tests/unit/test_workspace_ipc.py

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from remora.interactive.coordinator import WorkspaceInboxCoordinator, QuestionPayload
from remora.event_bus import EventBus, Event


@pytest.fixture
def event_bus():
    return EventBus()

@pytest.fixture
def coordinator(event_bus):
    return WorkspaceInboxCoordinator(event_bus=event_bus)


@pytest.mark.asyncio
async def test_coordinator_emits_blocked_event(coordinator):
    """Coordinator should emit AGENT_BLOCKED when question is pending."""
    workspace = AsyncMock()
    workspace.kv.list = AsyncMock(return_value=[
        {"key": "outbox:question:abc123"}
    ])
    workspace.kv.get = AsyncMock(return_value={
        "question": "Which format?",
        "options": ["google", "numpy"],
        "status": "pending",
        "created_at": "2026-02-23T10:00:00",
        "timeout": 300
    })
    
    received_events = []
    await coordinator.event_bus.subscribe("agent:blocked", 
        lambda e: received_events.append(e))
    
    await coordinator.watch_workspace("agent-1", workspace)
    await asyncio.sleep(0.1)  # Let it run one poll cycle
    
    assert len(received_events) == 1
    assert received_events[0].payload["question"] == "Which format?"
    assert received_events[0].payload["options"] == ["google", "numpy"]


@pytest.mark.asyncio
async def test_respond_writes_to_inbox(coordinator):
    """Coordinator should write response to workspace inbox."""
    workspace = AsyncMock()
    workspace.kv.set = AsyncMock()
    
    await coordinator.respond(
        agent_id="agent-1",
        msg_id="abc123",
        answer="google",
        workspace=workspace
    )
    
    workspace.kv.set.assert_called_once()
    call_args = workspace.kv.set.call_args
    assert call_args[0][0] == "inbox:response:abc123"
    assert call_args[0][1]["answer"] == "google"


@pytest.mark.asyncio  
async def test_stop_watching_cleans_up(coordinator):
    """Stop watching should cancel the watcher task."""
    workspace = AsyncMock()
    workspace.kv.list = AsyncMock(return_value=[])
    
    await coordinator.watch_workspace("agent-1", workspace)
    assert "agent-1" in coordinator._watchers
    
    await coordinator.stop_watching("agent-1")
    assert "agent-1" not in coordinator._watchers
```

### 4.7 Why This Is Better (from review)

| Aspect | Old (asyncio Futures) | New (Workspace KV) |
|--------|----------------------|-------------------|
| New code needed | Significant | Minimal |
| Cross-process sync | Complex (semaphores, signals) | Simple (poll/watch) |
| Debugging | Hard (binary protocols) | Easy (just read KV entries) |
| Persistence | Manual | Automatic (workspace is persistent) |
| Snapshot compatibility | Needs special handling | Works automatically |
| Crash recovery | Lost state | Questions survive |
| Grail changes needed | Yes | No |
| Multi-question support | Complex | Trivial (unique msg_ids) |
```

### 4.2 Integration with AgentNode

Update `AgentNode` to use the interactive backend:

```python
# In agent_graph.py, update AgentNode

class AgentNode:
    # ... existing fields ...
    
    def create_kernel(self, config: KernelConfig) -> AgentKernel:
        """Create the structured-agents kernel with interactive support."""
        from structured_agents import AgentKernel, load_bundle
        from structured_agents.tool_sources import RegistryBackendToolSource
        from structured_agents.backends import GrailBackend, GrailBackendConfig
        
        # Load bundle
        bundle = load_bundle(Path("agents") / self.bundle)
        
        # Create backend with interactive wrapper
        grail_config = GrailBackendConfig()
        grail_backend = GrailBackend(config=grail_config)
        
        # Wrap with interactive backend
        interactive_backend = InteractiveBackend(
            wrapped=grail_backend,
            event_bus=get_event_bus()
        )
        
        tool_source = bundle.build_tool_source(interactive_backend)
        
        kernel = AgentKernel(
            config=config,
            plugin=bundle.get_plugin(),
            tool_source=tool_source,
            observer=InteractiveObserver(self.inbox),  # Pass inbox for events
        )
        
        return kernel
```

### 4.3 Testing Requirements

Create `tests/unit/test_interactive_tools.py`:

```python
"""Tests for interactive tools."""

import pytest
import asyncio
from structured_agents.tool_sources.interactive import (
    InteractiveBackend, INTERACTIVE_TOOLS
)
from structured_agents.types import ToolCall, ToolSchema


class DummyBackend:
    """Mock backend for testing."""
    def list_tools(self): return ["read_file"]
    def resolve(self, name): return None
    async def execute(self, call, schema, ctx): 
        from structured_agents.types import ToolResult
        return ToolResult(call_id=call.id, name=call.name, output="{}", is_error=False)


@pytest.mark.asyncio
async def test_ask_user_blocks_and_resolves():
    """ask_user should block until resolved."""
    backend = InteractiveBackend(DummyBackend())
    
    tool_call = ToolCall(
        id="call-1",
        name="__ask_user__",
        arguments={"question": "Continue?"}
    )
    schema = ToolSchema(
        name="__ask_user__",
        description="",
        parameters={"type": "object", "properties": {}}
    )
    
    async def resolve_after():
        await asyncio.sleep(0.01)
        backend.resolve_response("call-1", "yes")
    
    result, resolved = await asyncio.gather(
        backend.execute(tool_call, schema, {"agent_id": "test"}),
        resolve_after()
    )
    
    assert "yes" in result.output
    assert result.is_error is False


@pytest.mark.asyncio
async def test_ask_user_timeout():
    """ask_user should timeout if no response."""
    backend = InteractiveBackend(DummyBackend())
    
    tool_call = ToolCall(
        id="call-2",
        name="__ask_user__",
        arguments={"question": "Quick?", "timeout_seconds": 0.01}
    )
    schema = ToolSchema(
        name="__ask_user__",
        description="",
        parameters={"type": "object", "properties": {}}
    )
    
    result = await backend.execute(tool_call, schema, {"agent_id": "test"})
    
    assert result.is_error is True
    assert "timeout" in result.output


@pytest.mark.asyncio
async def test_get_messages_returns_queued():
    """get_user_messages should return queued messages."""
    backend = InteractiveBackend(DummyBackend())
    
    # Queue some messages in the inbox
    inbox = backend._wrapped._inbox = MagicMock()
    inbox.drain_messages = AsyncMock(return_values=["Hello", "World"])
    
    tool_call = ToolCall(id="call-3", name="__get_user_messages__", arguments={})
    schema = ToolSchema(
        name="__get_user_messages__",
        description="",
        parameters={"type": "object", "properties": {}}
    )
    
    result = await backend.execute(tool_call, schema, {"inbox": inbox})
    
    assert "Hello" in result.output
    assert "World" in result.output
```

### 4.4 Success Criteria

- [ ] `__ask_user__` tool available in structured-agents
- [ ] Agent blocks when tool is called
- [ ] UI can resolve the blocked future
- [ ] `__get_user_messages__` retrieves async messages
- [ ] Events emitted for blocked/resumed states

---

## 5. Phase 4: Orchestration - Declarative Graph DSL

**Goal**: Replace the imperative `Coordinator` with a declarative `AgentGraph` that expresses *what* you want, not *how* to do it.

**Time Estimate**: 3-4 days

### 5.1 What to Build

Expand `AgentGraph` to handle:

1. **Auto-discovery**: Parse AST → AgentNodes
2. **Dependencies**: After/Before/Parallel
3. **Execution**: Run the graph with concurrency control
4. **Results**: Collect and return results

```python
# Expanded agent_graph.py additions

class AgentGraph:
    """A declarative graph of agents."""
    
    # ... existing methods ...
    
    def discover(
        self, 
        path: Path,
        bundles: dict[str, str] | None = None
    ) -> "AgentGraph":
        """Auto-discover code structure and create agents.
        
        Args:
            path: Path to discover (file or directory)
            bundles: Mapping of node_type -> bundle name
                   e.g., {"function": "lint", "class": "docstring"}
        
        Returns:
            Self for chaining
        """
        # TODO: Integrate with Remora's discovery module
        # For now, a placeholder
        return self
    
    def run_parallel(self, *agent_names: str) -> "AgentGraph":
        """Run these agents in parallel (same batch)."""
        # TODO: Implement
        return self
    
    def run_sequential(self, *agent_names: str) -> "AgentGraph":
        """Run these agents sequentially."""
        # TODO: Implement  
        return self
    
    def on_blocked(
        self, 
        handler: Callable[[AgentNode, str], Awaitable[str]]
    ) -> "AgentGraph":
        """Set handler for when agent asks user a question.
        
        This is how the UI integrates: provide a handler that
        shows the question to the user and returns their response.
        """
        self._blocked_handler = handler
        return self


# The config for execution
@dataclass
class GraphConfig:
    """Configuration for graph execution."""
    max_concurrency: int = 4
    interactive: bool = True
    timeout: float = 300.0
    snapshot_enabled: bool = False
```

### 5.2 Integration with Discovery

```python
# New method in AgentGraph

async def _discover_from_path(self, path: Path) -> list[AgentNode]:
    """Use Remora's discovery to find code structure."""
    from remora.discovery import TreeSitterDiscoverer
    
    discoverer = TreeSitterDiscoverer()
    nodes = await discoverer.discover(path)
    
    agents = []
    for node in nodes:
        # Map node type to bundle
        bundle = self._bundle_map.get(str(node.node_type), "default")
        
        agent = AgentNode(
            id=f"agent-{node.node_id[:8]}",
            name=f"{bundle}-{node.name}",
            bundle=bundle,
            target=node.text,
            target_path=node.file_path,
            target_type=str(node.node_type),
        )
        agents.append(agent)
    
    return agents
```

### 5.3 Testing Requirements

Create `tests/integration/test_graph_execution.py`:

```python
"""Integration tests for full graph execution."""

import pytest
import asyncio
from remora.agent_graph import AgentGraph, GraphConfig


@pytest.mark.asyncio
async def test_full_execution_flow():
    """Test a complete graph: create, configure, run."""
    # Create graph
    graph = AgentGraph()
    
    # Add agents manually (later: discover from path)
    graph.agent("lint", bundle="lint", target="def foo(): pass")
    graph.agent("docstring", bundle="docstring", target="def foo(): pass")
    
    # Define dependencies
    graph.after("lint").run("docstring")
    
    # Configure execution
    config = GraphConfig(
        max_concurrency=2,
        interactive=True
    )
    
    # Execute
    executor = graph.execute(config)
    results = await executor.run()
    
    # Verify
    assert "lint" in results
    assert "docstring" in results


@pytest.mark.asyncio  
async def test_interactive_mode_asks_user():
    """In interactive mode, agents should be able to ask questions."""
    graph = AgentGraph()
    
    responses = {"question": "yes"}
    
    async def blocked_handler(agent, question):
        return responses.get(question, "default")
    
    graph.agent("test", bundle="test", target="code")
    graph.on_blocked(blocked_handler)
    
    # Execute and verify blocked handler was called
    # ...


@pytest.mark.asyncio
async def test_parallel_execution():
    """Agents in same batch should run in parallel."""
    graph = AgentGraph()
    
    graph.agent("a", bundle="test", target="code")
    graph.agent("b", bundle="test", target="code")
    graph.agent("c", bundle="test", target="code")
    
    # Run all in parallel
    graph.run_parallel("a", "b", "c")
    
    # Execute and verify timing
    # ...
```

### 5.4 Success Criteria

- [ ] Graph can be defined declaratively
- [ ] Discovery creates AgentNodes from AST
- [ ] Dependencies control execution order
- [ ] Concurrency is respected
- [ ] Interactive mode pauses for user input

---

## 6. Phase 5: Persistence - Snapshots (KV-Based)

> **Key Insight**: Leverage Cairn's KV store as the **primary state store** for agents.
> This completely eliminates the "snapshot serialization depth" problem because:
> - Workspace snapshot = agent snapshot (automatic via Cairn)
> - No need to serialize structured-agents kernel internals
> - Messages and results stored as JSON in KV

**Goal**: Enable pause/resume of agents across restarts using Cairn KV as state store.

**Time Estimate**: 1-2 days (significantly simpler than original design)

### 5.1 Architecture: KV-Store Native State

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Cairn Workspace                                    │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         KV Store (Agent State)                      │   │
│  │                                                                      │   │
│  │   agent:{id}:messages ──────────────────────────────────────────┐  │   │
│  │   [                                                                  │  │
│  │     {"role": "user", "content": "Fix this function"},            │  │
│  │     {"role": "assistant", "tool_calls": [...]},                  │  │
│  │     {"role": "tool", "content": "..."}                           │  │
│  │   ]                                                                │  │
│  │                                                                      │   │
│  │   agent:{id}:tool_results ──────────────────────────────────────┐  │   │
│  │   [                                                                │  │
│  │     {"call_id": "...", "name": "...", "output": "..."}         │  │
│  │   ]                                                                │  │
│  │                                                                      │   │
│  │   agent:{id}:metadata ──────────────────────────────────────────┐  │   │
│  │   {                                                                │  │
│  │     "turn": 5,                                                     │  │
│  │     "bundle": "lint",                                              │  │
│  │     "target_path": "src/main.py",                                  │  │
│  │     "state": "running",                                            │  │
│  │     "created_at": "2026-02-23T10:00:00"                          │  │
│  │   }                                                                │  │
│  │                                                                      │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  Files (virtualized)                                                        │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 AgentKVStore - KV-Based State Management

```python
# agent_state.py

import json
import uuid
from datetime import datetime
from typing import Any

from fsdantic import Workspace


class AgentKVStore:
    """Manages agent state in Cairn KV store.
    
    Key insight: All agent state lives in KV, not Python objects.
    This makes snapshots trivial - workspace snapshot = agent snapshot.
    """
    
    def __init__(self, workspace: Workspace, agent_id: str):
        self._ws = workspace
        self._agent_id = agent_id
        self._prefix = f"agent:{agent_id}"
    
    @property
    def _messages_key(self) -> str:
        return f"{self._prefix}:messages"
    
    @property
    def _tool_results_key(self) -> str:
        return f"{self._prefix}:tool_results"
    
    @property
    def _metadata_key(self) -> str:
        return f"{self._prefix}:metadata"
    
    # -------------------------------------------------------------------------
    # Messages (conversation history)
    # -------------------------------------------------------------------------
    
    def get_messages(self) -> list[dict[str, Any]]:
        """Get all messages from KV."""
        data = self._ws.kv.get(self._messages_key)
        return json.loads(data) if data else []
    
    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message to the conversation history."""
        messages = self.get_messages()
        messages.append(message)
        self._ws.kv.set(self._messages_key, json.dumps(messages))
    
    def add_message_from_object(self, msg_obj) -> None:
        """Add a Message object (from structured-agents)."""
        self.add_message({
            "role": msg_obj.role,
            "content": msg_obj.content,
            "tool_calls": [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in (msg_obj.tool_calls or [])
            ],
            "tool_call_id": msg_obj.tool_call_id,
            "name": msg_obj.name,
        })
    
    # -------------------------------------------------------------------------
    # Tool Results
    # -------------------------------------------------------------------------
    
    def get_tool_results(self) -> list[dict[str, Any]]:
        """Get all tool results from KV."""
        data = self._ws.kv.get(self._tool_results_key)
        return json.loads(data) if data else []
    
    def add_tool_result(self, result: dict[str, Any]) -> None:
        """Add a tool result."""
        results = self.get_tool_results()
        results.append(result)
        self._ws.kv.set(self._tool_results_key, json.dumps(results))
    
    def add_tool_result_from_object(self, result_obj) -> None:
        """Add a ToolResult object (from structured-agents)."""
        self.add_tool_result({
            "call_id": result_obj.call_id,
            "name": result_obj.name,
            "output": result_obj.output,
            "is_error": result_obj.is_error,
        })
    
    # -------------------------------------------------------------------------
    # Metadata
    # -------------------------------------------------------------------------
    
    def get_metadata(self) -> dict[str, Any]:
        """Get agent metadata."""
        data = self._ws.kv.get(self._metadata_key)
        return json.loads(data) if data else {}
    
    def set_metadata(self, metadata: dict[str, Any]) -> None:
        """Set agent metadata."""
        self._ws.kv.set(self._metadata_key, json.dumps(metadata))
    
    def update_metadata(self, **kwargs) -> None:
        """Update specific metadata fields."""
        current = self.get_metadata()
        current.update(kwargs)
        self.set_metadata(current)
    
    # -------------------------------------------------------------------------
    # Snapshots (just a named reference to current state)
    # -------------------------------------------------------------------------
    
    def create_snapshot(self, name: str) -> str:
        """Create a named snapshot of current state.
        
        This is now trivial - we just copy current state to a snapshot key.
        The workspace itself can be checkpointed via materialize().
        """
        snapshot_id = uuid.uuid4().hex[:8]
        snapshot_key = f"snapshot:{name}:{snapshot_id}"
        
        # Copy current state to snapshot
        messages = self.get_messages()
        tool_results = self.get_tool_results()
        metadata = self.get_metadata()
        
        snapshot_data = {
            "messages": messages,
            "tool_results": tool_results,
            "metadata": metadata,
            "created_at": datetime.now().isoformat(),
        }
        
        self._ws.kv.set(snapshot_key, json.dumps(snapshot_data))
        return snapshot_id
    
    def restore_snapshot(self, snapshot_key: str) -> None:
        """Restore state from a snapshot."""
        data = self._ws.kv.get(snapshot_key)
        if not data:
            raise ValueError(f"Snapshot not found: {snapshot_key}")
        
        snapshot = json.loads(data)
        self._ws.kv.set(self._messages_key, json.dumps(snapshot["messages"]))
        self._ws.kv.set(self._tool_results_key, json.dumps(snapshot["tool_results"]))
        self._ws.kv.set(self._metadata_key, json.dumps(snapshot["metadata"]))
    
    def list_snapshots(self) -> list[dict[str, Any]]:
        """List all available snapshots."""
        entries = self._ws.kv.list(prefix="snapshot:")
        snapshots = []
        for entry in entries:
            key = entry.get("key", "")
            if ":metadata" not in key:  # Skip metadata entries
                data = self._ws.kv.get(key)
                if data:
                    snapshot = json.loads(data)
                    snapshots.append({
                        "key": key,
                        "created_at": snapshot.get("created_at"),
                        "message_count": len(snapshot.get("messages", [])),
                    })
        return snapshots
```

### 5.3 Integration with AgentNode

```python
# In agent_graph.py, update AgentNode

@dataclass
class AgentNode:
    # ... existing fields ...
    
    workspace: Any = None  # Cairn workspace
    _kv_store: AgentKVStore = None
    
    @property
    def kv_store(self) -> AgentKVStore:
        """Lazy-init KV store from workspace."""
        if self._kv_store is None and self.workspace:
            self._kv_store = AgentKVStore(self.workspace, self.id)
        return self._kv_store
    
    def sync_state_to_kv(self) -> None:
        """Sync current in-memory state to KV store."""
        if not self.kv_store:
            return
        
        # Sync messages
        if self.kernel and hasattr(self.kernel, 'messages'):
            # Clear and rebuild from kernel
            for msg in self.kernel.messages:
                self.kv_store.add_message_from_object(msg)
        
        # Sync metadata
        self.kv_store.update_metadata(
            state=self.state.value,
            turn=getattr(self.kernel, 'turn_count', 0),
        )
```

### 5.4 Why This Is Better

| Aspect | Original Design | KV-Store Native |
|--------|----------------|-----------------|
| Snapshot complexity | Need to serialize kernel internals | Trivial - just KV copy |
| Kernel dependencies | Need structured-agents changes | None - KV is external |
| Persistence | Custom file handling | Automatic via workspace |
| Resume | Rebuild kernel state | Reload from KV |
| Crash recovery | Complex state reconstruction | Natural - workspace survives |
| Debugging | Hard to inspect | Easy - just read KV |

### 5.5 Success Criteria

- [x] Agent state stored in Cairn KV (not in-memory objects)
- [x] Workspace snapshot = agent snapshot
- [x] Resume loads from KV store
- [x] No structured-agents kernel modifications needed

---

## 7. Phase 6: Workspace Checkpointing (Materialization)

> **Goal**: Materialize Cairn sandboxed filesystems and KV cache to disk on command, enabling checkpointing with jujutsu/github.

**Time Estimate**: 2-3 days

### 6.1 What We Discovered

After studying the Fsdantic library (which Cairn uses), we found that **materialization is already partially implemented**! The key insight is:

1. **Fsdantic.Workspace** already has:
   - `.files` - FileManager (virtual filesystem)
   - `.kv` - KVManager (key-value store)
   - `.materialize` - MaterializationManager (checkpointing to disk!)

2. **What's Missing**:
   - KV checkpointing (exporting all KV entries to disk)
   - A unified checkpoint API that handles both files + KV
   - Integration with Remora's AgentNode

### 6B.2 What to Build

```python
# checkpoint.py
"""Workspace Checkpointing - Materialize sandboxes to disk.

This module provides the ability to:
1. Materialize the virtual filesystem to disk
2. Export KV store to JSON files
3. Create complete checkpoints for jujutsu/github versioning
"""

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fsdantic import Workspace, MaterializationResult


@dataclass
class KVCheckpoint:
    """Represents a checkpoint of the KV store."""
    timestamp: datetime
    entries: list[dict[str, Any]]  # {"key": "...", "value": ...}
    
    def to_dir(self, path: Path) -> None:
        """Write KV entries as JSON files to a directory.
        
        Structure:
            path/
                _metadata.json      # timestamp, entry count
                a/
                    alice.json     # key "alice" -> alice.json
                    _index.json    # directory listing
                b/
                    ...
        """
        path.mkdir(parents=True, exist_ok=True)
        
        # Write metadata
        (path / "_metadata.json").write_text(json.dumps({
            "timestamp": self.timestamp.isoformat(),
            "entry_count": len(self.entries)
        }, indent=2))
        
        # Write entries organized by first letter
        by_prefix: dict[str, list] = {}
        for entry in self.entries:
            key = entry["key"]
            prefix = key[0].lower() if key else "_"
            by_prefix.setdefault(prefix, []).append(entry)
        
        for prefix, entries in by_prefix.items():
            prefix_dir = path / prefix
            prefix_dir.mkdir(exist_ok=True)
            
            for entry in entries:
                # Keys like "alice" -> "alice.json"
                safe_key = entry["key"].replace(":", "_")
                (prefix_dir / f"{safe_key}.json").write_text(
                    json.dumps(entry, indent=2)
                )
            
            # Index for this prefix
            (prefix_dir / "_index.json").write_text(json.dumps({
                "keys": [e["key"] for e in entries]
            }, indent=2))
    
    @classmethod
    def from_dir(cls, path: Path) -> "KVCheckpoint":
        """Load KV checkpoint from directory."""
        metadata = json.loads((path / "_metadata.json").read_text())
        entries = []
        
        for prefix_dir in path.iterdir():
            if prefix_dir.name.startswith("_"):
                continue
            for json_file in prefix_dir.glob("*.json"):
                if json_file.name == "_index.json":
                    continue
                entries.append(json.loads(json_file.read_text()))
        
        return cls(
            timestamp=datetime.fromisoformat(metadata["timestamp"]),
            entries=entries
        )


@dataclass
class Checkpoint:
    """Complete checkpoint of an agent's workspace.
    
    This is what gets versioned with jujutsu/github:
    - Virtual filesystem materialized to disk
    - KV store exported to JSON
    - Metadata about the checkpoint
    """
    agent_id: str
    created_at: datetime
    
    # Paths (relative to checkpoint root)
    filesystem_path: Path
    kv_path: Path
    
    # Full paths (for internal use)
    _filesystem_dir: Path | None = None
    _kv_dir: Path | None = None
    
    @property
    def filesystem_dir(self) -> Path:
        return self._filesystem_dir
    
    @property
    def kv_dir(self) -> Path:
        return self._kv_dir


class CheckpointManager:
    """Manages checkpointing of agent workspaces.
    
    Usage:
        manager = CheckpointManager(Path("/checkpoints"))
        
        # Materialize a workspace to disk
        checkpoint = await manager.checkpoint(
            workspace=agent_workspace,
            agent_id=agent.id,
            message="Before applying changes"
        )
        
        # Later: restore from checkpoint
        workspace = await manager.restore(checkpoint)
    """
    
    def __init__(self, checkpoint_root: Path):
        self._root = checkpoint_root
        self._root.mkdir(parents=True, exist_ok=True)
    
    async def checkpoint(
        self,
        workspace: Workspace,
        agent_id: str,
        message: str | None = None,
    ) -> Checkpoint:
        """Create a checkpoint of a workspace.
        
        Args:
            workspace: The Fsdantic workspace to checkpoint
            agent_id: Unique identifier for this checkpoint
            message: Optional commit message
            
        Returns:
            Checkpoint object with paths to materialized data
        """
        timestamp = datetime.now()
        checkpoint_id = f"{agent_id}-{timestamp.strftime('%Y%m%d_%H%M%S')}"
        
        # Create checkpoint directory
        checkpoint_dir = self._root / checkpoint_id
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. Materialize filesystem
        fs_dir = checkpoint_dir / "filesystem"
        fs_result = await workspace.materialize.to_disk(
            target_path=fs_dir,
            clean=True,
        )
        
        # 2. Export KV store
        kv_dir = checkpoint_dir / "kv"
        await self._export_kv(workspace.kv, kv_dir)
        
        # 3. Write metadata
        metadata = {
            "agent_id": agent_id,
            "created_at": timestamp.isoformat(),
            "message": message,
            "filesystem": {
                "files_written": fs_result.files_written,
                "bytes_written": fs_result.bytes_written,
                "changes": [asdict(c) for c in fs_result.changes],
            }
        }
        (checkpoint_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))
        
        return Checkpoint(
            agent_id=agent_id,
            created_at=timestamp,
            filesystem_path=Path("filesystem"),
            kv_path=Path("kv"),
            _filesystem_dir=fs_dir,
            _kv_dir=kv_dir,
        )
    
    async def _export_kv(self, kv_manager, target_dir: Path) -> KVCheckpoint:
        """Export all KV entries to disk."""
        target_dir.mkdir(parents=True, exist_ok=True)
        
        # List all entries
        entries = await kv_manager.list()
        
        checkpoint = KVCheckpoint(
            timestamp=datetime.now(),
            entries=[]
        )
        
        # Fetch each entry's value
        for entry in entries:
            key = entry["key"]
            try:
                value = await kv_manager.get(key)
                checkpoint.entries.append({
                    "key": key,
                    "value": value
                })
            except Exception as e:
                # Log but continue
                checkpoint.entries.append({
                    "key": key,
                    "error": str(e)
                })
        
        # Write to directory
        checkpoint.to_dir(target_dir)
        
        return checkpoint
    
    async def restore(self, checkpoint: Checkpoint) -> Workspace:
        """Restore a workspace from a checkpoint.
        
        Note: This creates a NEW workspace. To continue an agent
        from a checkpoint, you'd need to also restore the kernel state.
        """
        from fsdantic import Fsdantic
        
        # Create new workspace from materialized files
        workspace = await Fsdantic.open(
            str(checkpoint._filesystem_dir),
            readonly=False
        )
        
        # Restore KV entries
        kv_checkpoint = KVCheckpoint.from_dir(checkpoint._kv_dir)
        for entry in kv_checkpoint.entries:
            if "error" in entry:
                continue
            await workspace.kv.set(entry["key"], entry["value"])
        
        return workspace
    
    def list_checkpoints(self, agent_id: str | None = None) -> list[Checkpoint]:
        """List all available checkpoints.
        
        Args:
            agent_id: If provided, only return checkpoints for this agent
        """
        checkpoints = []
        
        for checkpoint_dir in self._root.iterdir():
            if not checkpoint_dir.is_dir():
                continue
            
            metadata_file = checkpoint_dir / "metadata.json"
            if not metadata_file.exists():
                continue
            
            metadata = json.loads(metadata_file.read_text())
            
            if agent_id and metadata.get("agent_id") != agent_id:
                continue
            
            checkpoints.append(Checkpoint(
                agent_id=metadata["agent_id"],
                created_at=datetime.fromisoformat(metadata["created_at"]),
                filesystem_path=Path("filesystem"),
                kv_path=Path("kv"),
                _filesystem_dir=checkpoint_dir / "filesystem",
                _kv_dir=checkpoint_dir / "kv",
            ))
        
        return sorted(checkpoints, key=lambda c: c.created_at, reverse=True)
```

### 6B.3 Integration with AgentNode

Add checkpointing to AgentNode:

```python
# In agent_graph.py, add to AgentNode

class AgentNode:
    # ... existing fields ...
    
    async def checkpoint(self, manager: CheckpointManager) -> Checkpoint:
        """Create a checkpoint of this agent's workspace."""
        if self.workspace is None:
            raise ValueError("No workspace to checkpoint")
        
        return await manager.checkpoint(
            workspace=self.workspace,
            agent_id=self.id,
        )
```

### 6B.4 Integration with Event Bus

Emit checkpoint events:

```python
# In checkpoint.py

async def checkpoint(
    self,
    workspace: Workspace,
    agent_id: str,
    message: str | None = None,
) -> Checkpoint:
    # ... existing code ...
    
    # Emit event
    await self._event_bus.publish(Event(
        type=EventType.WORKSPACE_CHECKPOINTED,
        agent_id=agent_id,
        payload={
            "checkpoint_id": checkpoint_id,
            "filesystem_files": fs_result.files_written,
            "kv_entries": len(kv_entries),
        }
    ))
```

### 6B.5 Jujutsu/Git Integration

Create a simple CLI for checkpointing:

```python
# cli.py

import typer

app = typer.Typer()

@app.command()
async def checkpoint(
    agent_id: str = typer.Argument(..., help="Agent ID to checkpoint"),
    message: str = typer.Option(None, help="Commit message"),
):
    """Create a checkpoint of an agent's workspace."""
    manager = CheckpointManager(Path("./checkpoints"))
    checkpoint = await manager.checkpoint(
        workspace=get_workspace(agent_id),
        agent_id=agent_id,
        message=message,
    )
    typer.echo(f"Created checkpoint: {checkpoint.created_at}")

@app.command()
def jjt_commit(
    checkpoint_id: str = typer.Argument(..., help="Checkpoint to commit"),
    message: str = typer.Option(None, help="Commit message"),
):
    """Commit a checkpoint to jujutsu."""
    checkpoint_path = Path("./checkpoints") / checkpoint_id
    
    # Use jujutsu to commit
    import subprocess
    subprocess.run(["jj", "commit", "-m", message or f"Checkpoint: {checkpoint_id}"], 
                   cwd=checkpoint_path)

@app.command()
def git_commit(
    checkpoint_id: str = typer.Argument(..., help="Checkpoint to commit"),
):
    """Commit a checkpoint to git."""
    checkpoint_path = Path("./checkpoints") / checkpoint_id
    
    import subprocess
    subprocess.run(["git", "add", "."], cwd=checkpoint_path)
    subprocess.run(["git", "commit", "-m", f"Checkpoint: {checkpoint_id}"])
```

### 6B.6 Testing Requirements

```python
# tests/unit/test_checkpoint.py

import pytest
from pathlib import Path
from checkpoint import CheckpointManager, KVCheckpoint, Checkpoint


@pytest.fixture
def checkpoint_manager(tmp_path):
    return CheckpointManager(tmp_path)


@pytest.mark.asyncio
async def test_kv_checkpoint_export(tmp_path):
    """KV should export to directory structure."""
    # Create mock KV manager
    class MockKV:
        async def list(self):
            return [{"key": "alice"}, {"key": "bob"}, {"key": "charlie"}]
        
        async def get(self, key):
            return {"name": key.capitalize()}
    
    kv = MockKV()
    target = tmp_path / "kv"
    
    manager = CheckpointManager(tmp_path)
    checkpoint = await manager._export_kv(kv, target)
    
    assert len(checkpoint.entries) == 3
    assert (target / "_metadata.json").exists()


def test_kv_checkpoint_roundtrip(tmp_path):
    """KV checkpoint should survive serialize/deserialize."""
    original = KVCheckpoint(
        timestamp=datetime.now(),
        entries=[{"key": "test", "value": {"foo": "bar"}}]
    )
    
    target = tmp_path / "kv"
    original.to_dir(target)
    
    restored = KVCheckpoint.from_dir(target)
    
    assert len(restored.entries) == 1
    assert restored.entries[0]["key"] == "test"
```

### 6B.7 Success Criteria

- [ ] Filesystem materialization works (already in Fsdantic!)
- [ ] KV export to JSON files works
- [ ] Unified checkpoint API works
- [ ] Checkpoints can be listed and restored
- [ ] Events are emitted during checkpointing
- [ ] Jujutsu/git CLI integration works
- [ ] Tests pass

---

## 8. Phase 7: Integration - Workspace & Discovery

**Goal**: Wire up the remaining pieces: workspace management and AST discovery.

**Time Estimate**: 2-3 days

### 7.1 Workspace Integration

```python
# workspace.py

from dataclasses import dataclass
from pathlib import Path

from remora.agent_graph import AgentNode


@dataclass
class GraphWorkspace:
    """A workspace that spans an entire agent graph.
    
    Provides:
    - Agent-specific directories
    - Shared space for passing artifacts
    - Original source snapshot
    """
    id: str
    root: Path
    
    def agent_space(self, agent_id: str) -> Path:
        """Private space for an agent."""
        path = self.root / "agents" / agent_id
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def shared_space(self) -> Path:
        """Shared space for passing data between agents."""
        path = self.root / "shared"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def original_source(self) -> Path:
        """Read-only copy of original source."""
        return self.root / "original"
    
    async def merge(self) -> None:
        """Merge agent changes back to original."""
        # TODO: Implement using cairn's merge functionality
        pass
```

### 7.2 Discovery Integration

Update `AgentGraph.discover()` to use Remora's existing discovery:

```python
async def discover(self, path: Path, config: DiscoveryConfig) -> "AgentGraph":
    """Discover code structure and create agents."""
    from remora.discovery import TreeSitterDiscoverer
    
    discoverer = TreeSitterDiscoverer(config)
    nodes = await discoverer.discover(path)
    
    # Create agents from discovered nodes
    for node in nodes:
        bundle = self._bundle_map.get(str(node.node_type), "default")
        self.agent(
            name=f"{bundle}-{node.name}",
            bundle=bundle,
            target=node.text,
            target_path=node.file_path,
            target_type=str(node.node_type),
        )
    
    return self
```

---

## 8. Phase 8: UI - Event-Driven Frontends

**Goal**: Build simple, elegant UIs that just consume events.

**Time Estimate**: 2-3 days

### 8.1 The API

The entire public API should be this simple:

```python
# Final public API - src/remora/__init__.py

from remora.agent_graph import AgentGraph, GraphConfig
from remora.event_bus import get_event_bus, EventBus, Event, EventType
from remora.discovery import discover, CSTNode
from remora.config import RemoraConfig

__all__ = [
    "AgentGraph",
    "GraphConfig", 
    "get_event_bus",
    "EventBus",
    "Event",
    "EventType",
    "discover",
    "CSTNode",
    "RemoraConfig",
]

# Simple CLI
async def main():
    # Discover
    nodes = await discover(Path("src"))
    
    # Create graph
    graph = AgentGraph()
    graph.from_nodes(nodes, bundles={"function": "lint", "class": "docstring"})
    graph.after("lint").run("docstring")
    
    # Execute
    async for event in get_event_bus().stream():
        print(event)
    
    results = await graph.execute()
```

### 8.2 Web Dashboard

The web dashboard is just an event consumer:

```python
# demo/dashboard/app.py

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/events")
async def events():
    """Stream all events as SSE."""
    async def generator():
        async for event in get_event_bus().stream():
            yield f"data: {event.to_json()}\n\n"
    
    return StreamingResponse(generator(), media_type="text/event-stream")

@app.post("/agent/{agent_id}/respond")
async def respond(agent_id: str, response: str):
    """User responds to blocked agent."""
    # Find the agent and resolve
    # ...
```

### 8.3 Success Criteria

- [ ] Public API is < 10 lines
- [ ] Web dashboard works via event subscription
- [ ] Mobile remote works via event subscription

---

## 8B. Error Handling & Cancellation

Based on the review, we need explicit error handling and cancellation strategies.

### 8B.1 Error Policy

Add to `src/remora/agent_graph.py`:

```python
class ErrorPolicy(str, Enum):
    """Defines what happens when an agent fails in a graph."""
    STOP_GRAPH = "stop_graph"      # Stop all agents
    SKIP_DOWNSTREAM = "skip_downstream"  # Skip agents that depend on failed
    CONTINUE = "continue"          # Continue running other agents

class GraphConfig(BaseModel):
    """Configuration for graph execution."""
    error_policy: ErrorPolicy = ErrorPolicy.SKIP_DOWNSTREAM
    max_retries: int = 0
    retry_delay: float = 1.0
```

### 8B.2 Cancellation Support

Add cancellation methods:

```python
class AgentNode:
    """Add cancellation support to AgentNode."""
    
    _cancelled: bool = False
    
    def cancel(self) -> None:
        """Request cancellation of this agent."""
        self._cancelled = True
        # Emit cancellation event
        get_event_bus().publish(Event.agent_cancelled(
            agent_id=self.id,
            reason="user_requested"
        ))
    
    def is_cancelled(self) -> bool:
        return self._cancelled
    
    async def check_cancelled(self) -> None:
        """Check if cancelled and raise if so."""
        if self._cancelled:
            raise asyncio.CancelledError(f"Agent {self.id} was cancelled")

class AgentGraph:
    """Add graph-level cancellation."""
    
    def cancel(self, agent_name: str | None = None) -> None:
        """Cancel all agents or a specific agent."""
        if agent_name:
            self._agents[agent_name].cancel()
        else:
            for agent in self._agents.values():
                agent.cancel()
    
    async def cancel_all(self) -> None:
        """Cancel all running agents and wait for cleanup."""
        for agent in self._agents.values():
            if agent.state in (AgentState.RUNNING, AgentState.BLOCKED):
                agent.cancel()
        
        # Wait for cancellation to complete
        await asyncio.gather(*[
            t for t in self._running_tasks
            if not t.done()
        ], return_exceptions=True)
```

---

## 9. Testing Strategy

### 9.1 Unit Tests (Per Phase)

Each phase should have unit tests covering:

| Phase | Test Coverage |
|-------|---------------|
| 1 - Event Bus | Pub/sub, wildcards, serialization, stream |
| 2 - AgentNode | Creation, state transitions, inbox |
| 3 - Interactive Tools | Block/resume, timeout, messages |
| 4 - Graph | Dependencies, execution order, concurrency |
| 5 - Snapshots | Serialize, deserialize, restore |
| 6 - Integration | Full flow from discovery to results |

### 9.2 Integration Tests

```python
# tests/integration/test_full_flow.py

@pytest.mark.asyncio
async def test_discover_execute_interactive():
    """Full flow: discover → graph → execute → user interaction."""
    
    # 1. Discover
    nodes = await discover(Path("tests/fixtures/sample.py"))
    assert len(nodes) > 0
    
    # 2. Create graph
    graph = AgentGraph()
    graph.from_nodes(nodes, bundles={"function": "test_agent"})
    
    # 3. Set up interactive handler
    responses = []
    async def handler(agent, question):
        responses.append(question)
        return "yes"
    
    graph.on_blocked(handler)
    
    # 4. Execute
    results = await graph.execute(interactive=True)
    
    # 5. Verify
    assert len(responses) >= 0  # May or may not block depending on agent
```

### 9.3 Test Fixtures

Create `tests/fixtures/` with sample Python files for discovery testing:

```
tests/fixtures/
├── sample.py          # Simple functions
├── classes.py        # Classes with methods  
├── complex.py        # Nested structures
└── edge_cases.py     # Error handling
```

---

## 10. Migration Path

### 10.1 Step-by-Step Replacement

1. **Phase 1**: Add EventBus, keep old EventEmitter (backwards compat)
2. **Phase 2**: Add AgentNode, keep old KernelRunner
3. **Phase 3**: Add interactive tools, add flag to enable
4. **Phase 4**: Add AgentGraph, keep old Coordinator
5. **Phase 5-7**: Add snapshots, discovery integration
6. **Final**: Remove old code

### 10.2 Deprecation Schedule

| Old Component | New Component | Remove After |
|---------------|----------------|--------------|
| EventEmitter | EventBus | v2.1 |
| EventBridge | (gone) | v2.1 |
| KernelRunner | AgentNode | v2.2 |
| RemoraAgentContext | AgentNode | v2.2 |
| Coordinator | AgentGraph | v2.2 |
| ContextManager | (simplified) | v2.3 |

---

## Summary

This guide provides a complete roadmap for building Remora V2. The key insights:

1. **One concept of "agent"**: AgentNode replaces CSTNode + Context + KernelRunner
2. **Events first-class**: EventBus is the central nervous system
3. **Declarative**: Say what you want, not how
4. **Native interaction**: __ask_user__ as a built-in tool
5. **Testable**: Every component has clear interfaces

The result will be a system that a junior developer can understand in minutes, not days.

---

## Appendix A: Code to Remove

When V2 is fully implemented, the following code can be **removed**:

### Remora Core (src/remora/)

| File | Reason |
|------|--------|
| `events.py` | Replaced by `event_bus.py` |
| `event_bridge.py` | Translation layer no longer needed |
| `kernel_runner.py` | Replaced by `AgentNode` in `agent_graph.py` |
| `orchestrator.py` | Replaced by `AgentGraph` in `agent_graph.py` |
| `context/manager.py` | Simplified context handling in AgentNode |
| `externals.py` | Replaced by workspace KV-based externals |

### Demo/Examples

| File/Dir | Reason |
|----------|--------|
| `demo/tui.py` | Replaced by web dashboard |
| `demo/jsonl_tail.py` | Replaced by SSE events |

### Config

| File | Reason |
|------|--------|
| `EventStreamConfig` in `config.py` | Replaced by EventBus |
| `event_stream` config section | Replaced by EventBus config |

### structured-agents (if modified)

| File | Reason |
|------|--------|
| Original Observer protocol | Replaced by EventBus subscription |
| Tool execution callbacks | Handled via EventBus |

### Cairn/fsdantic (if modified)

| File | Reason |
|------|--------|
| N/A - all existing | KV store already used |

---

## Appendix B: Final V2 File Structure

```
src/remora/
├── __init__.py                     # Public API (~20 lines)
│
├── event_bus.py                   # Phase 1: Unified event system
│   ├── Event (Pydantic model)
│   ├── EventBus (pub/sub)
│   ├── EventCategory (Literal types)
│   ├── AgentAction, ToolAction, etc.
│   └── get_event_bus()
│
├── agent_graph.py                 # Phase 2: Core abstractions
│   ├── AgentNode                 # Unified concept (replaces CSTNode + Context + KernelRunner)
│   ├── AgentInbox               # User interaction inbox (with lock!)
│   ├── AgentState               # pending → running → blocked → completed
│   ├── AgentGraph              # Declarative composition
│   └── GraphExecutor           # Runs the graph
│
├── interactive/                   # Phase 3: User interaction
│   ├── __init__.py
│   ├── coordinator.py           # Workspace KV inbox watcher
│   └── externals.py            # ask_user using KV store
│
├── snapshots.py                  # Phase 5: Agent snapshots
│   ├── AgentSnapshot
│   └── SnapshotManager
│
├── checkpoint.py                  # Phase 5B: Workspace checkpointing
│   ├── Checkpoint
│   ├── KVCheckpoint
│   └── CheckpointManager
│
├── workspace.py                  # Phase 6: Graph workspace
│   └── GraphWorkspace           # Shared workspace for graph
│
├── discovery/                   # Existing (unchanged)
│   ├── __init__.py
│   ├── discoverer.py
│   ├── match_extractor.py
│   ├── models.py
│   ├── query_loader.py
│   └── source_parser.py
│
├── config.py                    # Simplified config
│
├── results.py                   # Existing (unchanged)
│
└── [deprecated/]              # Old code moved here for reference
    ├── events.py              # REMOVE after migration
    ├── event_bridge.py        # REMOVE after migration
    ├── kernel_runner.py       # REMOVE after migration
    └── orchestrator.py        # REMOVE after migration


.context/
├── structured-agents/
│   └── src/structured_agents/
│       └── tool_sources/
│           └── [no changes needed - KV IPC is external!]
│
└── [other libs unchanged]


demo/
├── dashboard/
│   ├── app.py                  # FastAPI app
│   ├── index.html              # Single-file dashboard
│   ├── projector.html          # Projector mode
│   ├── mobile/
│   │   └── remote.html         # Mobile remote
│   └── static/
│       └── style.css
│
└── [demo scripts unchanged]


tests/
├── unit/
│   ├── test_event_bus.py       # Phase 1
│   ├── test_agent_graph.py     # Phase 2
│   ├── test_workspace_ipc.py    # Phase 3
│   └── test_checkpoint.py      # Phase 5B
│
└── integration/
    └── test_full_flow.py       # All phases
```

---

## Quick Reference

### Final File Structure (V2)

```
src/remora/
├── __init__.py              # Public API (~20 lines)
├── event_bus.py             # Phase 1: Unified Event Bus (Pydantic-first)
├── agent_graph.py           # Phase 2: AgentNode, AgentGraph, AgentInbox
├── interactive/             # Phase 3: Workspace KV IPC
│   ├── coordinator.py       #   Inbox watcher
│   └── externals.py        #   ask_user using KV
├── snapshots.py             # Phase 5: Agent snapshots
├── checkpoint.py            # Phase 5B: Workspace materialization
├── workspace.py            # Phase 6: Graph workspace
├── discovery/              # Existing
├── config.py              # Simplified
├── results.py             # Existing
└── deprecated/            # Old code (to remove)

demo/
├── dashboard/              # Web UI (event-driven)
│   ├── app.py
│   ├── index.html         # Single-file dashboard
│   ├── projector.html
│   └── mobile/
│       └── remote.html
└── [demo scripts]

tests/
├── unit/
│   ├── test_event_bus.py
│   ├── test_agent_graph.py
│   ├── test_workspace_ipc.py
│   └── test_checkpoint.py
└── integration/
    └── test_full_flow.py
```

### Success Checklist

- [x] EventBus (Pydantic-first, backpressure, asyncio.gather)
- [x] AgentNode unifies CSTNode + Context + KernelRunner
- [x] AgentGraph provides declarative API
- [x] Workspace KV IPC for ask_user (no Grail changes!)
- [x] Error handling with ErrorPolicy
- [x] Cancellation support
- [x] Checkpointing materializes workspace to disk
- [x] Public API is < 20 lines
- [ ] All tests pass
- [ ] Documentation complete

---

*End of V2 Rewrite Guide*
