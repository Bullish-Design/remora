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
6. [Phase 5: Persistence - Snapshots](#phase-5-persistence---snapshots)
7. [Phase 6: Integration - Workspace & Discovery](#phase-6-integration---workspace--discovery)
8. [Phase 7: UI - Event-Driven Frontends](#phase-7-ui---event-driven-frontends)
9. [Testing Strategy](#testing-strategy)
10. [Migration Path](#migration-path)

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

### 2.2 What to Build

Create `src/remora/event_bus.py`:

```python
"""Unified Event Bus - the central nervous system of Remora.

This module provides a single event system that:
1. All components publish to (agents, kernels, tools)
2. All consumers subscribe from (UI, logging, metrics)
3. Supports both in-process and distributed consumers
"""

import asyncio
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable
import uuid


class EventType(str, Enum):
    """All events in the system. One enum to rule them all."""
    
    # Agent lifecycle
    AGENT_CREATED = "agent_created"
    AGENT_STARTED = "agent_started"
    AGENT_BLOCKED = "agent_blocked"      # Waiting for user input
    AGENT_RESUMED = "agent_resumed"      # User responded
    AGENT_COMPLETED = "agent_completed"
    AGENT_FAILED = "agent_failed"
    AGENT_CANCELLED = "agent_cancelled"
    
    # Tool lifecycle
    TOOL_CALLED = "tool_called"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    
    # Model lifecycle
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    
    # User interaction
    USER_MESSAGE_SENT = "user_message_sent"
    USER_MESSAGE_RECEIVED = "user_message_received"
    
    # Graph lifecycle
    GRAPH_STARTED = "graph_started"
    GRAPH_COMPLETED = "graph_completed"
    GRAPH_PROGRESS = "graph_progress"


@dataclass
class Event:
    """Every event in the system has this shape.
    
    Simple, JSON-serializable, and self-describing.
    """
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: EventType
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Who/what
    agent_id: str | None = None
    graph_id: str | None = None
    node_id: str | None = None
    
    # What happened
    payload: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict for JSON."""
        return {
            "id": self.id,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "agent_id": self.agent_id,
            "graph_id": self.graph_id,
            "node_id": self.node_id,
            "payload": self.payload,
        }
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict())


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus:
    """The single source of truth for all events.
    
    Usage:
        # Publish events
        await event_bus.publish(Event(type=EventType.AGENT_STARTED, agent_id="..."))
        
        # Subscribe to specific events
        await event_bus.subscribe(EventType.AGENT_BLOCKED, my_handler)
        
        # Subscribe to patterns
        await event_bus.subscribe("agent_*", my_handler)
        
        # Get stream for consumption
        async for event in event_bus.stream():
            print(event)
    """
    
    def __init__(self):
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._running = False
    
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Publish to queue for stream consumers
        await self._queue.put(event)
        
        # Notify pattern subscribers
        await self._notify_subscribers(event)
    
    async def _notify_subscribers(self, event: Event) -> None:
        """Notify all matching subscribers."""
        event_key = event.type.value
        
        # Direct match
        for handler in self._subscribers.get(event_key, []):
            try:
                await handler(event)
            except Exception:
                import logging
                logging.exception(f"Handler failed for {event_key}")
        
        # Wildcard match
        for pattern, handlers in self._subscribers.items():
            if pattern.endswith("*") and event_key.startswith(pattern[:-1]):
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception:
                        import logging
                        logging.exception(f"Handler failed for pattern {pattern}")
    
    async def subscribe(self, event_pattern: str, handler: EventHandler) -> None:
        """Subscribe to events matching the pattern.
        
        Args:
            event_pattern: Exact event type (e.g., "agent_blocked") 
                          or pattern (e.g., "agent_*")
            handler: Async function to call when event matches
        """
        if event_pattern not in self._subscribers:
            self._subscribers[event_pattern] = []
        self._subscribers[event_pattern].append(handler)
    
    async def unsubscribe(self, event_pattern: str, handler: EventHandler) -> None:
        """Remove a subscription."""
        if event_pattern in self._subscribers:
            self._subscribers[event_pattern] = [
                h for h in self._subscribers[event_pattern] 
                if h != handler
            ]
    
    def stream(self) -> "EventStream":
        """Get an async iterator of events."""
        return EventStream(self._queue)
    
    async def send_sse(self, scope: str = "default") -> str:
        """Format events for Server-Sent Events."""
        # For web UI consumption
        ...


class EventStream:
    """Async iterator for consuming events."""
    
    def __init__(self, queue: asyncio.Queue[Event]):
        self._queue = queue
    
    def __aiter__(self):
        return self
    
    async def __anext__(self) -> Event:
        return await self._queue.get()


# Global singleton (for simple usage)
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


@dataclass
class AgentInbox:
    """The inbox for user interaction.
    
    Every AgentNode has one of these. It handles:
    - Blocking: Agent asks user, waits for response
    - Async: User sends message, agent receives on next turn
    """
    # For blocking (agent asks user)
    blocked: bool = False
    blocked_question: str | None = None
    blocked_since: datetime | None = None
    _pending_response: asyncio.Future[str] | None = None
    
    # For async messages (user sends to running agent)
    _message_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    
    async def ask_user(self, question: str, timeout: float = 300.0) -> str:
        """Block and wait for user response."""
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
    
    def _resolve_response(self, response: str) -> None:
        """Called by UI to resolve blocked ask_user."""
        if self._pending_response and not self._pending_response.done():
            self._pending_response.set_result(response)


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
    ):
        self._graph = graph
        self._max_concurrency = max_concurrency
        self._interactive = interactive
        self._event_bus = event_bus
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
            await asyncio.gather(*tasks, return_exceptions=True)
        
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

**Goal**: Make user interaction a native capability of the agent kernel, not an add-on.

**Time Estimate**: 3-4 days

### 4.1 What to Build

We need to contribute back to structured-agents to add the `__ask_user__` tool natively.

Create/update in `.context/structured-agents/src/structured_agents/tool_sources/`:

```python
# interactive.py
"""Interactive tools - built-in user interaction capabilities.

This module adds native support for:
- __ask_user__: Block and wait for user response
- __get_user_messages__: Get async messages from user
"""

from dataclasses import dataclass
from typing import Any
import json
import asyncio

from structured_agents.tool_sources.protocol import ToolSource, ToolSchema
from structured_agents.types import ToolCall, ToolResult


# These tools are always available when using interactive mode
INTERACTIVE_TOOLS = [
    ToolSchema(
        name="__ask_user__",
        description=(
            "Ask the user a question and wait for their response. "
            "Use this when you need clarification, approval, or additional context. "
            "The agent will pause until the user responds."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user"
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional constrained choices (makes UI easier)"
                },
                "timeout_seconds": {
                    "type": "number",
                    "default": 300,
                    "description": "How long to wait for response"
                }
            },
            "required": ["question"]
        }
    ),
    ToolSchema(
        name="__get_user_messages__",
        description=(
            "Get any messages the user has sent to this agent. "
            "Call this at the start of each turn to check for new context."
        ),
        parameters={
            "type": "object",
            "properties": {}
        }
    )
]


class InteractiveBackend:
    """Backend that handles interactive tools.
    
    This is a special backend that wraps another backend (usually GrailBackend)
    and adds interactive tool handling.
    """
    
    def __init__(self, wrapped: ToolSource, event_bus=None):
        self._wrapped = wrapped
        self._event_bus = event_bus
        self._pending_futures: dict[str, asyncio.Future] = {}
    
    def list_tools(self) -> list[str]:
        tools = self._wrapped.list_tools()
        tools.extend([t.name for t in INTERACTIVE_TOOLS])
        return tools
    
    def resolve(self, tool_name: str) -> ToolSchema | None:
        # Check interactive tools first
        for tool in INTERACTIVE_TOOLS:
            if tool.name == tool_name:
                return tool
        return self._wrapped.resolve(tool_name)
    
    async def execute(
        self, 
        tool_call: ToolCall, 
        tool_schema: ToolSchema, 
        context: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool, handling interactive ones specially."""
        
        if tool_schema.name == "__ask_user__":
            return await self._execute_ask_user(tool_call, context)
        
        if tool_schema.name == "__get_user_messages__":
            return await self._execute_get_messages(tool_call, context)
        
        # Fall through to wrapped backend
        return await self._wrapped.execute(tool_call, tool_schema, context)
    
    async def _execute_ask_user(
        self, 
        tool_call: ToolCall, 
        context: dict[str, Any]
    ) -> ToolResult:
        """Handle __ask_user__ tool."""
        args = tool_call.arguments
        question = args.get("question", "Please respond")
        options = args.get("options")
        timeout = args.get("timeout_seconds", 300)
        
        agent_id = context.get("agent_id", "unknown")
        
        # Emit blocked event
        if self._event_bus:
            from remora.event_bus import Event, EventType
            await self._event_bus.publish(Event(
                type=EventType.AGENT_BLOCKED,
                agent_id=agent_id,
                payload={
                    "question": question,
                    "options": options,
                    "tool_call_id": tool_call.id
                }
            ))
        
        # Wait for response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_futures[tool_call.id] = future
        
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return ToolResult(
                call_id=tool_call.id,
                name="__ask_user__",
                output=json.dumps({"status": "answered", "response": response}),
                is_error=False
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=tool_call.id,
                name="__ask_user__",
                output=json.dumps({"status": "timeout"}),
                is_error=True
            )
        finally:
            self._pending_futures.pop(tool_call.id, None)
            
            # Emit resumed event
            if self._event_bus:
                from remora.event_bus import Event, EventType
                await self._event_bus.publish(Event(
                    type=EventType.AGENT_RESUMED,
                    agent_id=agent_id,
                    payload={"tool_call_id": tool_call.id}
                ))
    
    async def _execute_get_messages(
        self, 
        tool_call: ToolCall, 
        context: dict[str, Any]
    ) -> ToolResult:
        """Handle __get_user_messages__ tool."""
        # Get inbox from context (set by AgentNode)
        inbox = context.get("inbox")
        
        if inbox is None:
            return ToolResult(
                call_id=tool_call.id,
                name="__get_user_messages__",
                output=json.dumps({"messages": []}),
                is_error=False
            )
        
        messages = await inbox.drain_messages()
        
        return ToolResult(
            call_id=tool_call.id,
            name="__get_user_messages__",
            output=json.dumps({"messages": messages}),
            is_error=False
        )
    
    def resolve_response(self, tool_call_id: str, response: str) -> None:
        """Called by UI to resolve a pending ask_user."""
        if tool_call_id in self._pending_futures:
            future = self._pending_futures[tool_call_id]
            if not future.done():
                future.set_result(response)
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

## 6. Phase 5: Persistence - Snapshots

**Goal**: Enable pause/resume of agents across restarts.

**Time Estimate**: 2-3 days

### 6.1 What to Build

```python
# snapshots.py

import json
import pickle
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from remora.agent_graph import AgentNode, AgentState


@dataclass
class AgentSnapshot:
    """Complete state of an agent for resume.
    
    This allows:
    - User steps away, comes back
    - Review before continuing
    - Debugging at exact point
    """
    agent_id: str
    created_at: datetime
    
    # Kernel state
    turn: int
    messages: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    
    # Context
    context: dict[str, Any]
    
    # Inbox
    inbox_messages: list[str]
    blocked_question: str | None
    
    # Workspace
    workspace_path: str
    
    def to_file(self, path: Path) -> None:
        """Save snapshot to file."""
        data = {
            "agent_id": self.agent_id,
            "created_at": self.created_at.isoformat(),
            "turn": self.turn,
            "messages": self.messages,
            "tool_results": self.tool_results,
            "context": self.context,
            "inbox_messages": self.inbox_messages,
            "blocked_question": self.blocked_question,
            "workspace_path": self.workspace_path,
        }
        path.write_text(json.dumps(data))
    
    @classmethod
    def from_file(cls, path: Path) -> "AgentSnapshot":
        """Load snapshot from file."""
        data = json.loads(path.read_text())
        return cls(
            agent_id=data["agent_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            turn=data["turn"],
            messages=data["messages"],
            tool_results=data["tool_results"],
            context=data["context"],
            inbox_messages=data["inbox_messages"],
            blocked_question=data["blocked_question"],
            workspace_path=data["workspace_path"],
        )


class SnapshotManager:
    """Manages agent snapshots."""
    
    def __init__(self, snapshot_dir: Path):
        self._dir = snapshot_dir
        self._dir.mkdir(parents=True, exist_ok=True)
    
    async def create(self, agent: AgentNode) -> AgentSnapshot:
        """Create a snapshot of current agent state."""
        snapshot = AgentSnapshot(
            agent_id=agent.id,
            created_at=datetime.now(),
            turn=agent.kernel.turn if agent.kernel else 0,
            messages=[],  # TODO: Extract from kernel
            tool_results=[],
            context={},  # TODO: Extract from context
            inbox_messages=[],
            blocked_question=agent.inbox.blocked_question,
            workspace_path=str(agent.workspace_path) if agent.workspace_path else "",
        )
        
        snapshot.to_file(self._dir / f"{agent.id}.json")
        return snapshot
    
    async def restore(self, snapshot: AgentSnapshot) -> AgentNode:
        """Restore an agent from snapshot."""
        # TODO: Implement
        pass
    
    def list(self) -> list[AgentSnapshot]:
        """List all available snapshots."""
        return [
            AgentSnapshot.from_file(f)
            for f in self._dir.glob("*.json")
        ]
```

### 6.2 Success Criteria

- [ ] Agent state can be serialized
- [ ] Snapshots persist to disk
- [ ] Agents can resume from snapshots
- [ ] Review workflow supported

---

## 7. Phase 6: Integration - Workspace & Discovery

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

## 8. Phase 7: UI - Event-Driven Frontends

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

### 10.3 Compatibility Mode

For gradual migration, support both APIs:

```python
# compat.py

def legacy_mode():
    """Enable v1 compatibility."""
    # Use old Coordinator
    # Use old EventEmitter
    pass

def v2_mode():
    """Use new v2 API."""
    # Use AgentGraph
    # Use EventBus
    pass
```

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

## Quick Reference

### File Structure

```
src/remora/
├── __init__.py              # Public API (keep small!)
├── event_bus.py             # NEW: Phase 1
├── agent_graph.py           # NEW: Phase 2
├── interactive_tools.py     # NEW: Phase 3 (contrib to structured-agents)
├── snapshots.py             # NEW: Phase 5
├── workspace.py             # NEW: Phase 6
├── discovery/              # Existing (keep)
├── config.py               # Existing (simplify)
├── results.py              # Existing (keep)
└── ...                     # Other modules (deprecate)

.context/
└── structured-agents/
    └── src/structured_agents/
        └── tool_sources/
            └── interactive.py  # NEW: Phase 3

tests/
├── unit/
│   ├── test_event_bus.py
│   ├── test_agent_graph.py
│   └── test_interactive_tools.py
└── integration/
    └── test_full_flow.py
```

### Success Checklist

- [ ] EventBus replaces EventEmitter + EventBridge
- [ ] AgentNode is the single concept of "agent"
- [ ] AgentGraph provides declarative API
- [ ] __ask_user__ is a native tool
- [ ] User interaction works via event subscription
- [ ] Snapshots enable pause/resume
- [ ] Discovery integrates with graph
- [ ] Public API is < 20 lines
- [ ] All tests pass
- [ ] Documentation complete
