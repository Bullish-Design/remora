# Interactive Agent Refactor Concept for Remora

> A comprehensive architectural refactoring plan to support real-time interactive agent workflows with a Datastar-powered web dashboard.

## Executive Summary

This document outlines a principled refactoring of Remora to support **interactive agent workflows** where:
1. Agents can pause and ask the user clarifying questions (Agent-Initiated Inbox)
2. Users can proactively inject context into running agents (User-Initiated Inbox)
3. Real-time UI updates via Server-Sent Events (SSE) and Datastar morphing
4. Hot-reloadable tool bundles for rapid iteration

The refactoring is organized into **five interconnected workstreams** that build upon each other, starting with the foundational event system and culminating in the Datastar web dashboard integration.

---

## Workstream 1: Async Event Bus Foundation

### Problem
Currently, Remora's event system (`events.py`) is designed for **fire-and-forget** JSONL output. The `JsonlEventEmitter` writes to a file, and the `RemoraEventBridge` translates structured-agents events into this format. This works for logging but cannot support:
- Real-time streaming to web clients
- Blocking waits for user input
- Multi-subscriber patterns (log file + SSE + in-memory)

### Proposed Solution: `AsyncEventBus`

Create a new `AsyncEventBus` class that replaces the static `EventEmitter` pattern with an async-native pub/sub system:

```python
# src/remora/events/async_bus.py

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Awaitable
import uuid

class EventType(str, Enum):
    # Core lifecycle
    AGENT_START = "agent_start"
    AGENT_COMPLETE = "agent_complete"
    AGENT_ERROR = "agent_error"
    
    # Inbox interaction (NEW)
    AGENT_BLOCKED = "agent_blocked"
    AGENT_RESUMED = "agent_resumed"
    USER_MESSAGE = "user_message"
    
    # State changes
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TURN_COMPLETE = "turn_complete"

@dataclass
class Event:
    """Immutable event payload."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    type: EventType
    agent_id: str
    node_id: str
    timestamp: datetime = field(default_factory=datetime.now)
    payload: dict[str, Any] = field(default_factory=dict)

EventHandler = Callable[[Event], Awaitable[None]]

class AsyncEventBus:
    """Async-native pub/sub event bus with multiple subscribers."""
    
    def __init__(self):
        self._subscribers: dict[EventType, list[EventHandler]] = {}
        self._all_handlers: list[EventHandler] = []
        self._queue: asyncio.Queue[Event] | None = None
    
    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)
    
    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all events."""
        self._all_handlers.append(handler)
    
    async def publish(self, event: Event) -> None:
        """Publish an event to all subscribers."""
        # Type-specific handlers
        for handler in self._subscribers.get(event.type, []):
            await handler(event)
        
        # Global handlers
        for handler in self._all_handlers:
            await handler(event)
    
    def queue_stream(self) -> asyncio.Queue[Event]:
        """Get a queue for SSE streaming."""
        if self._queue is None:
            self._queue = asyncio.Queue()
        return self._queue
```

### Why This Approach?

1. **Backwards-Compatible Adapter**: The existing `JsonlEventEmitter` can wrap `AsyncEventBus` as a subscriber, preserving existing CLI behavior
2. **First-Class SSE Support**: The queue stream directly feeds FastAPI's `StreamingResponse`
3. **Inbox Integration Point**: New `AGENT_BLOCKED` and `USER_MESSAGE` events are first-class types, not payload hacks
4. **Testability**: Handlers are simple async callables, easy to mock

### Migration Path

1. Create `src/remora/events/async_bus.py` with `AsyncEventBus`
2. Add `EventType` enum with new inbox variants
3. Create `AsyncEventBridge` (mirrors `RemoraEventBridge`) that publishes to the bus
4. Keep `EventEmitter` for CLI compatibility, backed by an async adapter

---

## Workstream 2: Interactive Agent Coordinator

### Problem
The TUI concept requires agents to **pause execution** and wait for user input. Currently:
- External functions in `externals.py` are synchronous-looking but run inside Grail's Python execution environment
- There's no mechanism to suspend a tool and resume it later
- The `KernelRunner` has no awareness of user interaction

### Proposed Solution: `InteractiveAgentCoordinator`

A first-class coordinator that manages the lifecycle of interactive agents:

```python
# src/remora/interactive/coordinator.py

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from enum import Enum

class InteractionMode(str, Enum):
    """How the agent handles user interaction."""
    AUTO = "auto"           # No interaction, run to completion
    ASK_ON_BLOCK = "ask_on_block"  # Pause when tool requests user input
    ALWAYS_ASK = "always_ask"       # Pause at every tool call

@dataclass
class AgentInbox:
    """Per-agent communication channel."""
    agent_id: str
    node_id: str
    
    # For agent-initiated blocking (ask_user)
    _pending_question: asyncio.Future[str] | None = None
    
    # For user-initiated messages (async inbox)
    _message_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)
    
    # State tracking
    is_blocked: bool = False
    blocked_at: datetime | None = None
    blocked_message: str | None = None

class InteractiveAgentCoordinator:
    """Manages interactive agent lifecycles with inbox support."""
    
    def __init__(self, event_bus: AsyncEventBus, mode: InteractionMode = InteractionMode.ASK_ON_BLOCK):
        self._bus = event_bus
        self._mode = mode
        self._inboxes: dict[str, AgentInbox] = {}
        self._global_queue: asyncio.Queue[str] = asyncio.Queue()
        
        # Subscribe to relevant events
        self._bus.subscribe(EventType.AGENT_START, self._on_agent_start)
        self._bus.subscribe(EventType.AGENT_COMPLETE, self._on_agent_complete)
    
    async def _on_agent_start(self, event: Event) -> None:
        """Create inbox when agent starts."""
        self._inboxes[event.agent_id] = AgentInbox(
            agent_id=event.agent_id,
            node_id=event.node_id,
        )
    
    async def _on_agent_complete(self, event: Event) -> None:
        """Cleanup inbox when agent completes."""
        inbox = self._inboxes.pop(event.agent_id, None)
        if inbox and inbox._pending_question and not inbox._pending_question.done():
            inbox._pending_question.cancel()
    
    async def block_agent(
        self, 
        agent_id: str, 
        message: str,
        timeout: float = 300.0
    ) -> str:
        """
        Block an agent until user responds.
        
        Emits AGENT_BLOCKED event, awaits user input, then resumes.
        """
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            raise ValueError(f"No inbox for agent {agent_id}")
        
        if self._mode == InteractionMode.AUTO:
            return ""  # No-op in auto mode
        
        loop = asyncio.get_running_loop()
        inbox._pending_question = loop.create_future()
        inbox.is_blocked = True
        inbox.blocked_at = datetime.now()
        inbox.blocked_message = message
        
        # Emit blocked event for UI
        await self._bus.publish(Event(
            type=EventType.AGENT_BLOCKED,
            agent_id=agent_id,
            node_id=inbox.node_id,
            payload={
                "message": message,
                "blocked_at": inbox.blocked_at.isoformat(),
            }
        ))
        
        try:
            # Wait for user response (with timeout)
            result = await asyncio.wait_for(
                inbox._pending_question,
                timeout=timeout
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"User did not respond within {timeout}s") from None
        finally:
            inbox.is_blocked = False
            inbox.blocked_at = None
            inbox.blocked_message = None
            inbox._pending_question = None
            
            # Emit resumed event for UI
            await self._bus.publish(Event(
                type=EventType.AGENT_RESUMED,
                agent_id=agent_id,
                node_id=inbox.node_id,
                payload={"response": result}
            ))
        
        return result
    
    async def send_user_message(self, agent_id: str, message: str) -> None:
        """
        Queue a user message for a running agent.
        
        The agent will receive this message on its next context poll.
        """
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            raise ValueError(f"No active agent with ID {agent_id}")
        
        await inbox._message_queue.put(message)
        
        await self._bus.publish(Event(
            type=EventType.USER_MESSAGE,
            agent_id=agent_id,
            node_id=inbox.node_id,
            payload={"message": message, "queued_at": datetime.now().isoformat()}
        ))
    
    async def drain_inbox(self, agent_id: str) -> list[str]:
        """Get all queued messages for an agent."""
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            return []
        
        messages = []
        while not inbox._message_queue.empty():
            messages.append(await inbox._message_queue.get())
        return messages
    
    def get_inbox_status(self, agent_id: str) -> dict[str, Any]:
        """Get current inbox state for UI."""
        inbox = self._inboxes.get(agent_id)
        if not inbox:
            return {"exists": False}
        
        return {
            "exists": True,
            "is_blocked": inbox.is_blocked,
            "blocked_message": inbox.blocked_message,
            "message_count": inbox._message_queue.qsize(),
        }
```

### Integration with `KernelRunner`

The coordinator hooks into the kernel via the `context_provider` mechanism:

```python
# In KernelRunner._provide_context()

async def _provide_context(self) -> dict[str, Any]:
    # ... existing context building ...
    
    # NEW: Check for user messages
    if self._interactive_coordinator:
        messages = await self._interactive_coordinator.drain_inbox(self.ctx.agent_id)
        if messages:
            prompt_ctx["user_inbox_messages"] = messages
            # Inject into conversation as a system message
            prompt_ctx["inject_message"] = (
                "User has sent additional context:\n" + 
                "\n".join(f"- {m}" for m in messages)
            )
    
    return prompt_ctx
```

---

## Workstream 3: Native `ask_user` External Function

### Problem
The TUI concept requires agents to be able to call `ask_user("question?")` from within a `.pym` tool and have it actually pause execution. Currently, external functions in Remora are fire-and-forget.

### Proposed Solution: First-Class Interactive External

Add `ask_user` as a proper external function that integrates with the coordinator:

```python
# src/remora/externals.py additions

from remora.interactive.coordinator import InteractiveAgentCoordinator

# Global coordinator instance (set by KernelRunner initialization)
_interactive_coordinator: InteractiveAgentCoordinator | None = None

def set_interactive_coordinator(coordinator: InteractiveAgentCoordinator) -> None:
    """Configure the global interactive coordinator."""
    global _interactive_coordinator
    _interactive_coordinator = coordinator

async def ask_user(message: str) -> str:
    """
    Ask the user a question and wait for their response.
    
    This function suspends agent execution until the user replies
    via the web dashboard or API.
    
    Args:
        message: The question to ask the user.
        
    Returns:
        The user's response string.
        
    Raises:
        TimeoutError: If the user doesn't respond within the timeout.
    """
    global _interactive_coordinator
    
    if _interactive_coordinator is None:
        # Fallback for non-interactive mode
        return ""
    
    # Extract agent_id from Grail's context (passed via thread-local or similar)
    # For now, we assume it's available via grail_context
    agent_id = _get_current_agent_id()
    
    return await _interactive_coordinator.block_agent(
        agent_id=agent_id,
        message=message,
        timeout=300.0  # 5 minute default
    )

def _get_current_agent_id() -> str:
    """Get the current agent ID from Grail execution context."""
    import contextvars
    current_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_agent_id")
    return current_agent_id.get()
```

### Tool Integration

The `ask_user` function can now be used directly in `.pym` tools:

```python
# agents/docstring/docstring.pym (example)

tool ask_for_format {
    input {
        String target_file
    }
    
    async fn execute() {
        # Ask user for their preference
        let format = ask_user("Which docstring format do you prefer? (google/numpy/epydoc)")
        
        # Continue with the chosen format
        ...
    }
}
```

---

## Workstream 4: Dynamic Bundle Management & Hot Reload

### Problem
The TUI concept mentions editing tools and prompts "live" from the dashboard. Currently:
- Bundles are loaded once per `KernelRunner` instantiation
- There's no file watching mechanism
- Changes require restart

### Proposed Solution: `BundleManager`

```python
# src/remora/interactive/bundle_manager.py

import asyncio
from pathlib import Path
from typing import Any, Protocol
from dataclasses import dataclass, field
import grail

class BundleWatcher(Protocol):
    """Protocol for bundle change watchers."""
    async def on_bundle_changed(self, bundle_name: str) -> None: ...

@dataclass
class BundleCatalog:
    """In-memory catalog of available bundles."""
    bundles: dict[str, "LoadedBundle"] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

@dataclass
class LoadedBundle:
    """A loaded bundle with metadata."""
    name: str
    path: Path
    manifest: Any  # BundleManifest
    tool_schemas: list[dict[str, Any]]
    max_turns: int
    termination_tool: str
    initial_messages: list[dict[str, Any]]
    grail_grammar: Any
    last_loaded: float = field(default_factory=lambda: __import__("time").time())

class BundleManager:
    """Manages dynamic bundle loading with hot reload support."""
    
    def __init__(self, agents_dir: Path):
        self._agents_dir = agents_dir
        self._catalog = BundleCatalog()
        self._watchers: list[BundleWatcher] = []
        self._watch_task: asyncio.Task | None = None
    
    async def get_bundle(self, bundle_name: str) -> LoadedBundle:
        """Get a bundle, loading if necessary."""
        async with self._catalog._lock:
            if bundle_name in self._catalog.bundles:
                return self._catalog.bundles[bundle_name]
            
            bundle = await self._load_bundle(bundle_name)
            self._catalog.bundles[bundle_name] = bundle
            return bundle
    
    async def reload_bundle(self, bundle_name: str) -> LoadedBundle:
        """Force reload a bundle, invalidating cache."""
        async with self._catalog._lock:
            # Invalidate
            if bundle_name in self._catalog.bundles:
                del self._catalog.bundles[bundle_name]
            
            # Reload
            bundle = await self._load_bundle(bundle_name)
            self._catalog.bundles[bundle_name] = bundle
            
            # Notify watchers
            for watcher in self._watchers:
                await watcher.on_bundle_changed(bundle_name)
            
            return bundle
    
    async def _load_bundle(self, bundle_name: str) -> LoadedBundle:
        """Load a bundle from disk."""
        bundle_path = self._agents_dir / bundle_name
        bundle = grail.load_bundle(bundle_path)
        
        return LoadedBundle(
            name=bundle_name,
            path=bundle_path,
            manifest=bundle.manifest,
            tool_schemas=bundle.build_tool_schemas(),
            max_turns=bundle.max_turns,
            termination_tool=bundle.termination_tool,
            initial_messages=bundle.build_initial_messages({}),
            grail_grammar=bundle.get_grammar_config(),
        )
    
    def add_watcher(self, watcher: BundleWatcher) -> None:
        """Add a bundle change watcher."""
        self._watchers.append(watcher)
    
    async def start_watching(self, paths: list[Path] | None = None) -> None:
        """Start file system watching for bundle changes."""
        if self._watch_task:
            return
        
        import watchdog
        
        # Watch agent directories for changes
        paths = paths or [self._agents_dir]
        
        # ... implementation of file watching ...
        pass
```

### Web Dashboard Integration

The dashboard can expose bundle editing:

```python
# demo/api/bundles.py (FastAPI routes)

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/bundles", tags=["bundles"])

class BundleEditRequest(BaseModel):
    content: str
    file_path: str  # e.g., "docstring/docstring.pym"

@router.get("/{bundle_name}")
async def get_bundle(bundle_name: str):
    """Get bundle metadata and tool schemas."""
    bundle = await bundle_manager.get_bundle(bundle_name)
    return {
        "name": bundle.name,
        "tools": bundle.tool_schemas,
        "max_turns": bundle.max_turns,
    }

@router.get("/{bundle_name}/files")
async def list_bundle_files(bundle_name: str):
    """List all files in a bundle."""
    bundle_path = agents_dir / bundle_name
    return [
        {"path": str(p.relative_to(bundle_path)), "type": p.suffix}
        for p in bundle_path.rglob("*") if p.is_file()
    ]

@router.get("/{bundle_name}/file/{file_path:path}")
async def get_bundle_file(bundle_name: str, file_path: str):
    """Get file contents."""
    full_path = agents_dir / bundle_name / file_path
    if not full_path.exists():
        raise HTTPException(404, "File not found")
    return {"content": full_path.read_text()}

@router.put("/{bundle_name}/file/{file_path:path}")
async def update_bundle_file(
    bundle_name: str, 
    file_path: str, 
    request: BundleEditRequest
):
    """Update a file in the bundle."""
    full_path = agents_dir / bundle_name / file_path
    full_path.write_text(request.content)
    
    # Trigger hot reload
    await bundle_manager.reload_bundle(bundle_name)
    
    return {"status": "updated", "reloaded": True}
```

---

---

## Workstream 5A: Zero-Dependency Single-File Dashboard

> The absolute simplest way to demo Remora's interactive capabilities - no FastAPI, no Node.js, no build step. Just open an HTML file.

### The Problem with Full-Stack

The FastAPI + Datastar approach from Workstream 5 is powerful but requires:
- Python environment with FastAPI installed
- Running a separate server process
- Configuring ports, CORS, etc.
- For demos: explaining to people how to set up their environment

What if you could just **double-click an HTML file** and it works?

### Solution: Self-Contained HTML Dashboard

#### Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        User's Machine                            │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    Single HTML File                          │ │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────────────┐  │ │
│  │  │ Inline CSS  │  │ Inline JS   │  │ Datastar (CDN)    │  │ │
│  │  └─────────────┘  └─────────────┘  └────────────────────┘  │ │
│  │         │               │                    │                │ │
│  │         └───────────────┼────────────────────┘                │ │
│  │                         │                                     │ │
│  │                  ┌──────┴──────┐                              │ │
│  │                  │ UI State    │                              │ │
│  │                  │ (in-memory) │                              │ │
│  │                  └─────────────┘                              │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                              │                                    │
│                    Polling /fetch() or SSE                       │
│                              │                                    │
│  ┌──────────────────────────┴──────────────────────────────────┐ │
│  │              Python Backend (http.server)                   │
│  │  - Minimal JSON API                                         │
│  │  - Serves the HTML file                                    │
│  │  - Streams events via SSE                                   │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

#### The HTML File

```html
<!-- demo/dashboard/single_file/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Swarm Dashboard</title>
    
    <!-- Datastar from CDN (single script, ~15KB) -->
    <script src="https://cdn.jsdelivr.net/npm/datastar@0.0.17/bundle.umd.js"></script>
    
    <style>
        /* Inline critical CSS - no external file needed */
        :root {
            --bg-dark: #0f0f14;
            --bg-card: #1a1a24;
            --accent: #6366f1;
            --accent-hover: #818cf8;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
            --success: #22c55e;
            --warning: #f59e0b;
            --error: #ef4444;
            --pending: #3b82f6;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: var(--bg-dark);
            color: var(--text);
            min-height: 100vh;
        }
        
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
            padding-bottom: 20px;
            border-bottom: 1px solid #2a2a3a;
        }
        
        h1 { font-size: 1.5rem; font-weight: 600; }
        
        .btn {
            background: var(--accent);
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.9rem;
            transition: background 0.2s;
        }
        
        .btn:hover { background: var(--accent-hover); }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        
        .stats-bar {
            display: flex;
            gap: 20px;
            margin-bottom: 20px;
        }
        
        .stat-card {
            background: var(--bg-card);
            padding: 15px 25px;
            border-radius: 10px;
            flex: 1;
        }
        
        .stat-value { font-size: 2rem; font-weight: 700; }
        .stat-label { color: var(--text-muted); font-size: 0.85rem; }
        
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 16px;
        }
        
        .node-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 16px;
            border-left: 4px solid var(--pending);
            transition: transform 0.2s, box-shadow 0.2s;
        }
        
        .node-card.status-completed { border-left-color: var(--success); }
        .node-card.status-executing { border-left-color: var(--accent); }
        .node-card.status-error { border-left-color: var(--error); }
        .node-card.status-blocked { border-left-color: var(--warning); }
        
        .node-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }
        
        .node-name {
            font-weight: 600;
            font-size: 0.95rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .badge {
            font-size: 0.7rem;
            padding: 3px 8px;
            border-radius: 4px;
            background: #2a2a3a;
            color: var(--text-muted);
            text-transform: uppercase;
        }
        
        .node-content {
            font-size: 0.85rem;
            color: var(--text-muted);
            line-height: 1.5;
        }
        
        .inbox {
            margin-top: 12px;
            padding: 12px;
            background: #252532;
            border-radius: 8px;
            border: 1px solid var(--warning);
        }
        
        .inbox-message {
            font-size: 0.85rem;
            margin-bottom: 10px;
            color: var(--warning);
        }
        
        .inbox-input {
            display: flex;
            gap: 8px;
        }
        
        .inbox-input input {
            flex: 1;
            background: #1a1a24;
            border: 1px solid #3a3a4a;
            color: var(--text);
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 0.85rem;
        }
        
        .inbox-input input:focus {
            outline: none;
            border-color: var(--accent);
        }
        
        .inbox-input button {
            background: var(--warning);
            color: #000;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
        }
        
        .spinner {
            width: 16px;
            height: 16px;
            border: 2px solid var(--accent);
            border-top-color: transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .empty-state {
            text-align: center;
            padding: 60px 20px;
            color: var(--text-muted);
        }
        
        .empty-state h2 { margin-bottom: 10px; color: var(--text); }
    </style>
</head>
<body>
    <div class="container" id="app">
        <header>
            <h1>🚀 Remora Swarm</h1>
            <button class="btn" 
                    data-on-click="@post('/api/start')"
                    id="start-btn">
                Start Swarm
            </button>
        </header>
        
        <div class="stats-bar">
            <div class="stat-card">
                <div class="stat-value" data-sse="stat-pending" data-merge="text">0</div>
                <div class="stat-label">Pending</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" data-sse="stat-executing" data-merge="text">0</div>
                <div class="stat-label">Executing</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" data-sse="stat-completed" data-merge="text">0</div>
                <div class="stat-label">Completed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" data-sse="stat-blocked" data-merge="text">0</div>
                <div class="stat-label">Waiting for Input</div>
            </div>
        </div>
        
        <div id="agent-grid" 
             data-on-load="@sse('/api/stream')"
             class="grid">
            <div class="empty-state" data-show="agent-grid">
                <h2>No agents running</h2>
                <p>Click "Start Swarm" to begin analysis</p>
            </div>
        </div>
    </div>
    
    <script>
        // Simple state management
        const state = {
            agents: {},
            stats: { pending: 0, executing: 0, completed: 0, blocked: 0 }
        };
        
        // Initialize Datastar
        const ds = new Datastar(document.body);
        
        // Handle SSE events
        ds.on('datastar-morph', (fragment) => {
            // Process incoming HTML fragments
            console.log('Received event:', fragment.substring(0, 100));
        });
        
        // Poll for status updates (fallback if SSE fails)
        async function pollStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                updateStats(data.stats);
            } catch (e) {
                console.log('Polling disabled - using SSE');
            }
        }
        
        function updateStats(stats) {
            // Stats are updated via Datastar's SSE merging
        }
    </script>
</body>
</html>
```

#### Minimal Python Backend

```python
# demo/dashboard/simple_api.py
"""
Minimal HTTP server for the single-file dashboard.
No FastAPI required - uses stdlib http.server!
"""

import json
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import asyncio
import queue

# The event queue - same as before
event_queue = queue.Queue()

class RemoraRequestHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler with SSE support."""
    
    def do_GET(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/':
            self.serve_html()
        elif parsed.path == '/api/stream':
            self.serve_sse()
        elif parsed.path == '/api/status':
            self.serve_status()
        else:
            self.send_error(404)
    
    def do_POST(self):
        parsed = urlparse(self.path)
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        
        if parsed.path == '/api/start':
            self.handle_start()
        elif parsed.path.startswith('/api/agent/') and parsed.path.endswith('/inbox'):
            self.handle_inbox_response(parsed.path, body)
        elif parsed.path.startswith('/api/agent/') and parsed.path.endswith('/send-message'):
            self.handle_send_message(parsed.path, body)
        else:
            self.send_error(404)
    
    def serve_html(self):
        html_path = Path(__file__).parent / 'index.html'
        content = html_path.read_text()
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.end_headers()
        self.wfile.write(content.encode())
    
    def serve_sse(self):
        """Server-Sent Events endpoint."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        
        # Keep connection open and stream events
        while True:
            try:
                event = event_queue.get(timeout=30)
                self.wfile.write(f"event: datastar-morph\ndata: {event}\n\n".encode())
                self.wfile.flush()
            except queue.Empty:
                # Send keep-alive comment
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
    
    def serve_status(self):
        """Return current status as JSON."""
        # Build status from active agents
        status = {'stats': {'pending': 0, 'executing': 0, 'completed': 0, 'blocked': 0}}
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(status).encode())
    
    def handle_start(self):
        """Start the swarm - spawn background task."""
        # This would integrate with Remora's orchestrator
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'started'}).encode())
        
        # TODO: Start Remora swarm in background thread
    
    def handle_inbox_response(self, path: str, body: str):
        """Handle user response to blocked agent."""
        # Extract agent_id from path: /api/agent/{id}/inbox
        parts = path.split('/')
        agent_id = parts[3] if len(parts) > 3 else None
        
        # Parse body (form-encoded or JSON)
        data = parse_qs(body)
        message = data.get('message', [''])[0]
        
        # TODO: Resolve the agent's pending future
        print(f"User response for {agent_id}: {message}")
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'ok'}).encode())
    
    def handle_send_message(self, path: str, body: str):
        """Handle proactive user message to agent."""
        # Similar to inbox response
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'status': 'queued'}).encode())
    
    def log_message(self, format, *args):
        """Custom logging."""
        print(f"[Dashboard] {format % args}")

def run_server(port=8080):
    """Run the dashboard server."""
    server = HTTPServer(('', port), RemoraRequestHandler)
    print(f"🚀 Remora Dashboard: http://localhost:{port}")
    print("   Press Ctrl+C to stop")
    server.serve_forever()

if __name__ == '__main__':
    run_server()
```

#### How to Use

1. **Just double-click** `index.html` (or right-click → Open With → Browser)
2. Click "Start Swarm" 
3. Watch agents appear in real-time

That's it. No `pip install`, no `npm run`, no configuration.

---

### Mobile Companion Version

For phones/tablets, create a **separate lightweight page** that acts as a remote:

```html
<!-- demo/dashboard/mobile/remote.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Remora Remote</title>
    <script src="https://cdn.jsdelivr.net/npm/datastar@0.0.17/bundle.umd.js"></script>
    <style>
        /* Mobile-optimized styles */
        :root {
            --bg: #0f0f14;
            --card: #1a1a24;
            --accent: #6366f1;
            --warning: #f59e0b;
            --success: #22c55e;
            --text: #e2e8f0;
            --text-muted: #94a3b8;
        }
        
        * { box-sizing: border-box; }
        
        body {
            font-family: -apple-system, sans-serif;
            background: var(--bg);
            color: var(--text);
            padding: 16px;
            margin: 0;
        }
        
        .header {
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 20px;
            text-align: center;
        }
        
        .blocked-agent {
            background: var(--card);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 16px;
            border: 2px solid var(--warning);
        }
        
        .agent-name {
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .question {
            color: var(--warning);
            font-size: 1rem;
            margin-bottom: 16px;
        }
        
        .quick-replies {
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
            margin-bottom: 12px;
        }
        
        .quick-reply {
            background: var(--warning);
            color: #000;
            border: none;
            padding: 10px 16px;
            border-radius: 20px;
            font-size: 0.9rem;
            font-weight: 600;
        }
        
        .custom-input {
            display: flex;
            gap: 8px;
        }
        
        .custom-input input {
            flex: 1;
            background: var(--bg);
            border: 1px solid #3a3a4a;
            color: var(--text);
            padding: 12px;
            border-radius: 8px;
            font-size: 1rem;
        }
        
        .custom-input button {
            background: var(--accent);
            color: white;
            border: none;
            padding: 12px 20px;
            border-radius: 8px;
            font-weight: 600;
        }
        
        .status-bar {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: var(--card);
            padding: 12px;
            display: flex;
            justify-content: space-around;
            font-size: 0.8rem;
        }
        
        .status-item {
            text-align: center;
        }
        
        .status-value {
            font-size: 1.2rem;
            font-weight: 700;
        }
        
        .no-blocked {
            text-align: center;
            color: var(--text-muted);
            padding: 40px;
        }
    </style>
</head>
<body>
    <div class="header">🎛️ Remora Remote</div>
    
    <div id="blocked-agents" 
         data-on-load="@sse('/api/stream')">
        <div class="no-blocked">
            No agents waiting for input
        </div>
    </div>
    
    <div class="status-bar">
        <div class="status-item">
            <div class="status-value" data-sse="stat-active">0</div>
            <div>Active</div>
        </div>
        <div class="status-item">
            <div class="status-value" data-sse="stat-blocked">0</div>
            <div>Waiting</div>
        </div>
        <div class="status-item">
            <div class="status-value" data-sse="stat-completed">0</div>
            <div>Done</div>
        </div>
    </div>
    
    <script>
        const ds = new Datastar(document.body);
        // Mobile-optimized event handling
    </script>
</body>
</html>
```

#### Mobile Connectivity Options

| Option | Pros | Cons |
|--------|------|------|
| **Same WiFi** | Zero config, works instantly | Requires desktop + phone on same network |
| **LAN IP Display** | Shows local IP on desktop, type into phone | Slightly more setup |
| **ngrok/Cloudflare Tunnel** | Works from anywhere | Requires account, more latency |
| **QR Code** | Easiest for non-technical users | Phone needs camera, same network |

**Auto-discovery approach:**
```python
# Add to simple_api.py
def get_local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('10.255.255.255', 1))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'

# Display on dashboard startup
print(f"🌐 Dashboard: http://{get_local_ip()}:8080")
print(f"📱 Mobile Remote: http://{get_local_ip()}:8080/mobile.html")
```

---

## Workstream 5B: Projector Mode (Presentation Dashboard)

> A full-screen, high-impact visualization designed for team demos, standups, and presentations.

### Design Philosophy

Projector Mode is designed for **presentations**, not daily use:
- **Big visuals**: Elements are 2-3x larger than normal
- **High contrast**: Visible from 20+ feet away
- **Minimal text**: Instead of code snippets, show summaries and status
- **Animated**: Smooth transitions keep attention
- **Auto-advancing**: Can run unattended in a loop

### Visual Style

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              REMORA SWARM                                   │
│                          ████████████████ 78%                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐       │
│   │             │  │             │  │             │  │             │       │
│   │   ●██████   │  │   ●████████│  │   ●██████   │  │   ●         │       │
│   │   ███████   │  │   ████████ │  │   ███████   │  │   ██████    │       │
│   │   ███████   │  │   ████████ │  │   ███████   │  │   ██████    │       │
│   │             │  │             │  │             │  │             │       │
│   │  function   │  │  function   │  │   class     │  │   class     │       │
│   │  apply_fix  │  │  get_node_  │  │  Remora     │  │  Analyzer   │       │
│   │             │  │    source    │  │             │  │             │       │
│   └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘       │
│                                                                             │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                        │
│   │             │  │             │  │             │                        │
│   │   ✓██████   │  │   ✓██████   │  │   ⏳         │                        │
│   │   ✓██████   │  │   ✓██████   │  │             │                        │
│   │             │  │             │  │             │                        │
│   │  read_file  │  │ read_docstr │  │   ruff      │                        │
│   │             │  │             │  │   (waiting) │                        │
│   └─────────────┘  └─────────────┘  └─────────────┘                        │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Last update: 2 seconds ago  │  12 agents completed  │  ● Live             │
└─────────────────────────────────────────────────────────────────────────────┘

Legend: ● executing  ✓ completed  ⏳ pending  ⚠ blocked
```

### Implementation

```html
<!-- demo/dashboard/projector.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Swarm - Projector Mode</title>
    <script src="https://cdn.jsdelivr.net/npm/datastar@0.0.17/bundle.umd.js"></script>
    <style>
        /* Projector Mode - Extra Large & High Contrast */
        :root {
            --bg: #000000;
            --card-bg: #0d0d0d;
            --success: #00ff88;
            --executing: #00aaff;
            --pending: #666666;
            --blocked: #ffaa00;
            --error: #ff4444;
            --text: #ffffff;
            --text-dim: #888888;
        }
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        html, body {
            height: 100%;
            background: var(--bg);
            color: var(--text);
            font-family: 'SF Pro Display', -apple-system, sans-serif;
            overflow: hidden;
        }
        
        .fullscreen {
            height: 100vh;
            display: flex;
            flex-direction: column;
            padding: 40px;
        }
        
        /* Header - Extra Large */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 40px;
        }
        
        h1 {
            font-size: 3rem;
            font-weight: 800;
            letter-spacing: -0.02em;
        }
        
        .progress-bar {
            width: 300px;
            height: 40px;
            background: #1a1a1a;
            border-radius: 20px;
            overflow: hidden;
            position: relative;
        }
        
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, var(--executing), var(--success));
            transition: width 0.5s ease;
            display: flex;
            align-items: center;
            justify-content: flex-end;
            padding-right: 15px;
            font-weight: 700;
            font-size: 1.2rem;
        }
        
        /* Grid - 2x larger cards */
        .grid {
            flex: 1;
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 30px;
            align-content: start;
        }
        
        .agent-card {
            background: var(--card-bg);
            border-radius: 24px;
            padding: 30px;
            display: flex;
            flex-direction: column;
            min-height: 200px;
            position: relative;
            overflow: hidden;
        }
        
        .agent-card.status-executing {
            border: 3px solid var(--executing);
            box-shadow: 0 0 40px rgba(0, 170, 255, 0.2);
        }
        
        .agent-card.status-completed {
            border: 3px solid var(--success);
        }
        
        .agent-card.status-blocked {
            border: 3px solid var(--blocked);
            animation: pulse-warning 2s infinite;
        }
        
        @keyframes pulse-warning {
            0%, 100% { box-shadow: 0 0 20px rgba(255, 170, 0, 0.3); }
            50% { box-shadow: 0 0 50px rgba(255, 170, 0, 0.6); }
        }
        
        /* Status indicator */
        .status-dot {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            margin-bottom: 20px;
        }
        
        .status-dot.executing { 
            background: var(--executing); 
            animation: pulse 1.5s infinite;
        }
        .status-dot.completed { background: var(--success); }
        .status-dot.blocked { background: var(--blocked); }
        .status-dot.pending { background: var(--pending); }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.2); opacity: 0.7; }
        }
        
        /* Agent info */
        .agent-type {
            font-size: 1.4rem;
            font-weight: 700;
            text-transform: uppercase;
            color: var(--text-dim);
            margin-bottom: 10px;
        }
        
        .agent-name {
            font-size: 1.8rem;
            font-weight: 600;
            word-break: break-word;
        }
        
        /* Summary - minimal */
        .agent-summary {
            margin-top: auto;
            font-size: 1.1rem;
            color: var(--text-dim);
            line-height: 1.4;
            max-height: 80px;
            overflow: hidden;
        }
        
        /* Blocked inbox - big and obvious */
        .inbox-prompt {
            position: absolute;
            inset: 0;
            background: rgba(0, 0, 0, 0.95);
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 30px;
            text-align: center;
        }
        
        .inbox-prompt.hidden { display: none; }
        
        .inbox-question {
            font-size: 1.8rem;
            font-weight: 600;
            color: var(--blocked);
            margin-bottom: 30px;
        }
        
        .inbox-buttons {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
            justify-content: center;
        }
        
        .inbox-btn {
            padding: 15px 30px;
            font-size: 1.2rem;
            font-weight: 700;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            transition: transform 0.2s;
        }
        
        .inbox-btn:hover { transform: scale(1.05); }
        .inbox-btn.yes { background: var(--success); color: #000; }
        .inbox-btn.no { background: var(--error); color: #fff; }
        .inbox-btn.custom { background: var(--executing); color: #fff; }
        
        /* Footer */
        footer {
            margin-top: 30px;
            display: flex;
            justify-content: space-between;
            font-size: 1.2rem;
            color: var(--text-dim);
        }
        
        .live-indicator {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .live-dot {
            width: 16px;
            height: 16px;
            background: var(--success);
            border-radius: 50%;
            animation: pulse 1s infinite;
        }
    </style>
</head>
<body>
    <div class="fullscreen" 
         id="app"
         data-on-load="@sse('/api/stream')">
        
        <header>
            <h1>🚀 REMORA SWARM</h1>
            <div class="progress-bar">
                <div class="progress-fill" 
                     style="width: 0%" 
                     data-sse="progress-percent">
                    0%
                </div>
            </div>
        </header>
        
        <div class="grid" id="agent-grid">
            <!-- Agent cards morph in here -->
        </div>
        
        <footer>
            <span data-sse="last-update">Last update: just now</span>
            <span data-sse="completed-count">0 completed</span>
            <div class="live-indicator">
                <div class="live-dot"></div>
                LIVE
            </div>
        </footer>
    </div>
    
    <script>
        const ds = new Datastar(document.body);
    </script>
</body>
</html>
```

### Features

1. **Auto-scaling grid**: Adapts to any screen size while maintaining readability
2. **Giant progress bar**: Shows overall completion percentage
3. **Pulsing animations**: Active agents pulse, blocked agents pulse warning orange
4. **Big tap targets**: Buttons are oversized for presenting with clicker/remote
5. **Minimal text**: Just the essentials visible from back of room
6. **Inbox overlay**: When agent is blocked, full-screen prompt appears with quick-reply buttons
7. **Dark mode only**: Maximizes contrast, reduces eye strain in dark rooms

### Quick-Reply Buttons

For demo purposes, the projector mode can include **preset responses**:

```javascript
// When agent blocks with question, show these options:
// "Which format?" → ["Google", "NumPy", "Sphinx", "Skip"]
// "Apply changes?" → ["Yes", "No", "Preview first"]
// "Continue?" → ["Yes", "Stop"]
```

This makes it easy to demonstrate the interactive flow without typing during a presentation.

### Running in Projector Mode

```bash
# Option 1: Just open the HTML file
# File → Open → projector.html

# Option 2: Run server with auto-launch
python -c "
import webbrowser
import subprocess
subprocess.Popen(['python', 'demo/dashboard/simple_api.py'])
webbrowser.open('http://localhost:8080/projector.html')
"

# Option 3: Full screen command (macOS)
open -a "Google Chrome" --args --kiosk http://localhost:8080/projector.html

# Option 4: Presentation mode (F11 in most browsers)
```

---

## Additional MVP Quick-Wins

### Synthetic User (Demo Mode)

For recording videos without a human present:

```python
# demo/dashboard/synthetic_user.py

class SyntheticUser:
    """Auto-responds to agent prompts for demo recording."""
    
    def __init__(self, responses: dict[str, list[str]] = None):
        # Map question patterns to auto-responses
        self.responses = responses or {
            "format": ["google", "numpy", "sphinx"],
            "apply": ["yes", "no"],
            "continue": ["yes"],
            "which": ["first option"],
        }
        self.response_index = {}
    
    def should_respond(self, message: str) -> bool:
        """Determine if we should auto-respond."""
        import random
        # Respond 80% of time, leave some for drama
        return random.random() < 0.8
    
    def get_response(self, message: str) -> str:
        """Get auto-response for message."""
        message_lower = message.lower()
        
        for key, responses in self.responses.items():
            if key in message_lower:
                idx = self.response_index.get(key, 0)
                self.response_index[key] = (idx + 1) % len(responses)
                return responses[idx]
        
        return "yes"  # Default
        
    async def run(self, coordinator: InteractiveAgentCoordinator):
        """Watch for blocked agents and auto-respond."""
        while True:
            await asyncio.sleep(2)
            
            # Check for blocked agents
            for agent_id, status in coordinator.get_all_statuses():
                if status.is_blocked:
                    response = self.get_response(status.blocked_message)
                    print(f"[SyntheticUser] Responding to {agent_id}: {response}")
                    await coordinator.resume_agent(agent_id, response)
```

### Constraint-Based UI

Instead of free text, use constrained options:

```html
<!-- In inbox fragment -->
<div class="constrained-options">
    <button data-on-click="@post('/api/agent/{{id}}/inbox')" 
            data-model='{"message": "google"}'>
        📄 Google
    </button>
    <button data-on-click="@post('/api/agent/{{id}}/inbox')" 
            data-model='{"message": "numpy"}'>
        🔢 NumPy  
    </button>
    <button data-on-click="@post('/api/agent/{{id}}/inbox')" 
            data-model='{"message": "sphinx"}'>
        📖 Sphinx
    </button>
</div>
```

This reduces friction for demos - just click a button instead of typing.

---

## Choosing Your Approach

| Approach | Best For | Setup Time |
|----------|----------|------------|
| **Single HTML** | Quick demos, sharing with colleagues | 0 min |
| **Mobile Remote** | Multi-screen demos, presenting while controlling | 2 min |
| **Projector Mode** | Team presentations, standups | 1 min |
| **Full FastAPI** | Production use, complex features | 30 min |

**Recommendation**: Start with Single HTML + Projector Mode. Add Mobile Remote if you want that "wow" multi-device demo. Only build the full FastAPI version when you need production features.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Browser                                          │
│  ┌─────────────────────────────────────────────────────────────────────────┐ │
│  │  Datastar Frontend                                                      │ │
│  │  - SSE connection for real-time updates                                 │ │
│  │  - Morph fragments for node state changes                              │ │
│  │  - Form handling for user input                                         │ │
│  └─────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────┬────────────────────────────────────────┘
                                      │ SSE + HTTP
┌─────────────────────────────────────┴────────────────────────────────────────┐
│                           FastAPI Server                                     │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐ │
│  │  SSE Endpoint    │  │  Inbox API       │  │  Bundle Editor API          │ │
│  │  /api/stream     │  │  POST/GET inbox  │  │  CRUD for .pym files         │ │
│  └────────┬─────────┘  └────────┬─────────┘  └─────────────┬──────────────┘ │
│           │                     │                          │                 │
│           └─────────────────────┼──────────────────────────┘                 │
│                                 │                                             │
│                    ┌────────────┴────────────┐                                │
│                    │   InteractiveCoordinator  │◄── Inbox futures           │
│                    └────────────┬────────────┘                                │
│                                 │                                             │
└─────────────────────────────────┼─────────────────────────────────────────────┘
                                  │
┌─────────────────────────────────┴─────────────────────────────────────────────┐
│                            Remora Core                                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────────────┐  │
│  │  AsyncEventBus   │  │  KernelRunner   │  │  BundleManager              │  │
│  │  (event stream)  │  │  (agent exec)   │  │  (hot reload)               │  │
│  └──────────────────┘  └──────────────────┘  └──────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────────────────┘
```

### FastAPI Application Structure

```python
# demo/web_app.py

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncio

from remora.events import AsyncEventBus, Event, EventType
from remora.interactive.coordinator import InteractiveAgentCoordinator, InteractionMode
from remora.interactive.bundle_manager import BundleManager

app = FastAPI(title="Remora Dashboard")
templates = Jinja2Templates(directory="demo/templates")

# Core services
event_bus = AsyncEventBus()
interactive_coordinator = InteractiveAgentCoordinator(event_bus, mode=InteractionMode.ASK_ON_BLOCK)
bundle_manager = BundleManager(agents_dir=Path("agents"))

# Subscribe coordinator to events
event_bus.subscribe(EventType.AGENT_START, lambda e: None)  # Auto-created

# --- SSE Endpoint ---

@app.get("/api/stream")
async def stream_events():
    """Server-Sent Events stream for real-time UI updates."""
    queue = event_bus.queue_stream()
    
    async def generate():
        while True:
            event = await queue.get()
            
            # Datastar expects specific SSE format
            if event.type == EventType.AGENT_BLOCKED:
                # Emit fragment with input form
                fragment = render_inbox_fragment(event)
                yield f"event: datastar-morph\ndata: {fragment}\n\n"
            elif event.type == EventType.AGENT_RESUMED:
                # Remove input form, show spinner
                fragment = render_resumed_fragment(event)
                yield f"event: datastar-morph\ndata: {fragment}\n\n"
            else:
                # Standard node state update
                fragment = render_node_fragment(event)
                yield f"event: datastar-morph\ndata: {fragment}\n\n"
    
    return StreamingResponse(generate(), media_type="text/event-stream")

# --- Inbox Endpoints ---

@app.post("/api/agent/{agent_id}/inbox")
async def submit_inbox_response(agent_id: str, request: Request):
    """User submits response to blocked agent."""
    body = await request.json()
    message = body.get("message", "")
    
    # Resolve the pending future
    await interactive_coordinator.resume_agent(agent_id, message)
    
    return HTMLResponse("<div>Message sent. Resuming agent...</div>")

@app.get("/api/agent/{agent_id}/inbox-status")
async def get_inbox_status(agent_id: str):
    """Get current inbox state."""
    return interactive_coordinator.get_inbox_status(agent_id)

@app.post("/api/agent/{agent_id}/send-message")
async def send_async_message(agent_id: Request):
   : str, request message """User proactively sends to running agent."""
    body = await request.json()
    message = body.get("message", "")
    
    await interactive_coordinator.send_user_message(agent_id, message)
    
    return HTMLResponse("<div>Message queued.</div>")

# --- Frontend ---

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
```

### Frontend Templates

```html
<!-- demo/templates/index.html -->

<!DOCTYPE html>
<html>
<head>
    <title>Remora Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/datastar@0.0.17/bundle.umd.js"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body>
    <div id="app">
        <header>
            <h1>Remora Swarm</h1>
            <button data-on-click="@post('/api/start-swarm')">Start Swarm</button>
        </header>
        
        <div id="agent-grid" 
             data-on-load="@sse('/api/stream')">
            <!-- Agent nodes will morph in here -->
        </div>
    </div>
    
    <script>
        // Datastar configuration
        const ds = new Datastar(document.body);
    </script>
</body>
</html>
```

```html
<!-- demo/templates/fragments/node_fragment.html -->

<div id="node-{{ node.node_id }}" 
     class="node-card status-{{ node.status }}">
    <div class="node-header">
        <span class="badge">{{ node.operation }}</span>
        <span class="node-name">{{ node.node_name }}</span>
        
        {% if node.status == "executing" %}
            <span class="spinner"></span>
        {% elif node.status == "completed" %}
            <span class="check-icon">✓</span>
        {% endif %}
    </div>
    
    <div class="node-content">
        {% if node.summary %}
            <div class="summary">{{ node.summary }}</div>
        {% endif %}
    </div>
    
    <!-- Agent Inbox (shows when blocked) -->
    <div class="inbox" {% if not node.is_blocked %}hidden{% endif %}>
        <div class="agent-message">
            <strong>Agent:</strong> {{ node.blocked_message }}
        </div>
        <div class="user-input">
            <input type="text" 
                   data-model="inbox_message_{{ node.node_id }}"
                   placeholder="Your response...">
            <button data-on-click="@post('/api/agent/{{ node.agent_id }}/inbox')">
                Send
            </button>
        </div>
    </div>
    
    <!-- Async Inbox (always available) -->
    <div class="async-inbox">
        <input type="text"
               data-model="async_message_{{ node.node_id }}"
               placeholder="Send note to agent...">
        <button data-on-click="@post('/api/agent/{{ node.agent_id }}/send-message')">
            →
        </button>
    </div>
</div>
```

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
1. Create `AsyncEventBus` with `EventType` enum
2. Add `AGENT_BLOCKED`, `AGENT_RESUMED`, `USER_MESSAGE` event types
3. Create `AsyncEventBridge` adapter
4. Ensure backwards compatibility with `JsonlEventEmitter`

### Phase 2: Coordinator (Week 2)
1. Implement `InteractiveAgentCoordinator`
2. Add `AgentInbox` dataclass with future/queue management
3. Wire coordinator into `KernelRunner`
4. Add context provider integration for inbox draining

### Phase 3: Externals (Week 2-3)
1. Add `ask_user()` to externals
2. Implement thread-local agent ID tracking
3. Add integration tests for blocking behavior
4. Document usage in tool authoring guide

### Phase 4: Bundle Management (Week 3)
1. Implement `BundleManager` with catalog
2. Add file watcher integration
3. Create FastAPI bundle editing endpoints
4. Build simple dashboard UI for tool editing

### Phase 5: Web Dashboard (Week 4)
1. Create FastAPI app structure
2. Implement SSE endpoint
3. Build Datastar templates
4. Integrate all components
5. End-to-end testing

---

## Key Design Decisions

### 1. Async-First Events
The new event system is async-native from the start. This mirrors modern Python patterns and makes SSE streaming trivial.

### 2. Coordinator Pattern
Rather than scattering inbox logic across `KernelRunner`, `externals.py`, and demo scripts, we centralize it in a dedicated coordinator. This:
- Keeps `KernelRunner` focused on execution
- Makes testing easier (mock the coordinator)
- Provides a single point for timeout/error handling

### 3. Backwards Compatibility
Every new component maintains adapters for the existing system:
- `EventEmitter` still works (backed by async bus)
- CLI behavior unchanged
- No breaking changes to tool authors

### 4. Graceful Degradation
If the web dashboard isn't running:
- `InteractionMode.AUTO` skips all blocking
- `ask_user()` returns empty string
- System works as before

---

## File Changes Summary

### New Files
```
src/remora/events/
├── __init__.py          # Updated exports
├── async_bus.py         # NEW: AsyncEventBus
└── types.py             # NEW: EventType enum

src/remora/interactive/
├── __init__.py
├── coordinator.py       # NEW: InteractiveAgentCoordinator
└── bundle_manager.py    # NEW: BundleManager

demo/
├── web_app.py           # FastAPI app (replaces demo/web_events.py)
├── templates/
│   ├── index.html
│   └── fragments/
│       ├── node_fragment.html
│       └── inbox_fragment.html
└── static/
    └── style.css

docs/
└── INTERACTIVE_AGENT_REFACTOR_CONCEPT.md  # This document
```

### Modified Files
```
src/remora/kernel_runner.py     # Add coordinator injection
src/remora/externals.py         # Add ask_user()
src/remora/orchestrator.py      # Add coordinator to Coordinator
src/remora/cli.py               # Add --interactive flag

agents/
└── (bundle files remain unchanged)
```

---

## Open Questions & Future Work

1. **Timeout Strategy**: Should timeouts be configurable per-tool, per-agent, or globally?
2. **Multi-User Support**: Currently single-user. How do we handle multiple dashboard users?
3. **Persistence**: Should inbox messages be persisted to disk for recovery after server restart?
4. **Audit Trail**: Should we log all user-agent interactions?
5. **Permission Model**: Who can edit bundles? Only admins?

---

## Conclusion

This refactoring transforms Remora from a batch-oriented code analysis tool into an **interactive development partner**. The key insight is that the existing architecture—particularly the external function system and context providers—already supports this workflow; we just need to expose the hooks and build the coordination layer.

The five workstreams are independent enough to implement incrementally, and each provides immediate value:
- Phase 1: Better observability (async events)
- Phase 2-3: Interactive agents (the core feature)
- Phase 4: Rapid iteration (hot reload)
- Phase 5: Wow factor (dashboard)
