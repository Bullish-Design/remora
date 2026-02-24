# Stario MVP Demo Implementation Plan

## Overview

This plan outlines a step-by-step approach to building a Stario-powered dashboard that replaces the existing FastAPI + WebSocket + JavaScript implementation with Datastar patches. The goal is to prove out the SSE + reactive signal model while reusing existing `EventBus` and `WorkspaceInboxCoordinator` components.

---

## Prerequisites

- Python 3.14+ (already configured in `pyproject.toml`)
- Stario already installed as a dependency (`pyproject.toml:29`)

---

## Phase 1: Project Setup & Core Infrastructure

### Step 1.1: Create Stario Dashboard Module

Create a new directory structure for the Stario dashboard:

```
demo/stario_dashboard/
├── __init__.py
├── main.py              # Entry point
├── views.py            # HTML view functions
├── handlers.py         # Request handlers
├── state.py            # Server-side state aggregation
└── static/
    └── css/
        └── style.css   # Reuse existing dashboard styles
```

### Step 1.2: Define Server-Side State Aggregator

Create `demo/stario_dashboard/state.py` - a singleton that maintains the aggregate state that all SSE clients share:

```python
from dataclasses import dataclass, field
from collections import deque
from remora.event_bus import Event

MAX_EVENTS = 200

@dataclass
class DashboardState:
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict] = field(default_factory=dict)
    agent_states: dict[str, dict] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0
    
    def record(self, event: Event):
        # Update events deque
        self.events.append(event.model_dump())
        
        # Update agent states
        if event.agent_id:
            if event.category == "agent":
                if event.action == "started":
                    self.agent_states[event.agent_id] = {
                        "state": "started",
                        "name": event.payload.get("name", event.agent_id)
                    }
                    self.total_agents += 1
                elif event.action in ("completed", "failed", "cancelled"):
                    if event.agent_id in self.agent_states:
                        self.agent_states[event.agent_id]["state"] = event.action
                        self.completed_agents += 1
                elif event.action == "blocked":
                    key = f"{event.agent_id}:{event.payload.get('question', '')}"
                    self.blocked[key] = {
                        "agent_id": event.agent_id,
                        "question": event.payload.get("question", ""),
                        "options": event.payload.get("options", []),
                        "msg_id": event.payload.get("msg_id", "")
                    }
                elif event.action == "resumed":
                    question = event.payload.get("question", "")
                    if question:
                        key = f"{event.agent_id}:{question}"
                        self.blocked.pop(key, None)
                        
        # Update results
        if event.category == "agent" and event.action == "completed":
            self.results.insert(0, {
                "agent_id": event.agent_id,
                "content": event.payload.get("result", str(event.payload)),
                "timestamp": event.timestamp.isoformat()
            })
            if len(self.results) > 50:
                self.results.pop()
    
    def get_signals(self) -> dict:
        return {
            "events": list(self.events),
            "blocked": list(self.blocked.values()),
            "agentStates": self.agent_states,
            "progress": {
                "total": self.total_agents,
                "completed": self.completed_agents
            },
            "results": self.results[:10]  # Latest 10
        }
```

**Key integration points:**
- Import `Event` from `remora.event_bus`
- Import `get_event_bus()` for the SSE stream

### Step 1.3: Create Global State Instance

Add to `demo/stario_dashboard/__init__.py`:

```python
from .state import DashboardState

dashboard_state = DashboardState()
```

---

## Phase 2: View Functions (HTML Templates)

### Step 2.1: Create Base Page Shell

Create `demo/stario_dashboard/views.py`. Start with the page shell that mirrors `demo/dashboard/static/index.html`:

```python
from stario import asset, at, data
from stario.html import (
    Body, Button, Div, Head, Html, Input, Meta, Option, Select,
    Link, Script, Span, Title,
)

def page():
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1.0"}),
            Title("Remora Dashboard"),
            Link({"rel": "stylesheet", "href": "/static/" + asset("css/style.css")}),
            Script({"type": "module", "src": "/static/" + asset("js/datastar.js")}),
        ),
        Body(),
    )
```

### Step 2.2: Implement Event Log View

Add to `views.py`:

```python
def event_item_view(event: dict) -> Div:
    """Single event row with timestamp, type, agent_id, and payload."""
    timestamp = event.get("timestamp", "")
    if timestamp:
        from datetime import datetime
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        time_str = dt.strftime("%H:%M:%S")
    else:
        time_str = "--:--:--"
    
    category = event.get("category", "")
    action = event.get("action", "")
    agent_id = event.get("agent_id", "")
    payload = event.get("payload", {})
    
    css_class = f"event {category}_{action}"
    
    return Div(
        {"class": css_class},
        Span({"class": "event-time"}, time_str),
        Span({"class": "event-type"}, f"{category}:{action}"),
        Span({"class": "event-agent"}, f"@{agent_id}") if agent_id else "",
        Div({"class": "event-payload"}, str(payload)) if payload else "",
    )

def events_list_view(events: list[dict]) -> Div:
    """Events container with auto-scroll on load."""
    if not events:
        return Div(
            {"id": "events-list", "class": "events-list"},
            Div({"class": "empty-state"}, "No events yet")
        )
    
    return Div(
        {"id": "events-list", "class": "events-list"},
        data.on("load", "setTimeout(() => this.scrollTop = this.scrollHeight, 10)"),
        *[event_item_view(e) for e in reversed(events)],  # newest first
    )
```

### Step 2.3: Implement Blocked Agent Card View

Add to `views.py`:

```python
def blocked_card_view(blocked: dict) -> Div:
    """Single blocked agent card with response form."""
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    msg_id = blocked.get("msg_id", "")
    
    key = f"{agent_id}:{question}".replace(":", "_")
    
    card = Div(
        {"class": "blocked-agent", "data-key": key},
        Div({"class": "agent-id"}, f"@{agent_id}"),
        Div({"class": "question"}, question),
        Div({"class": "response-form"}),
    )
    
    # Add input or select based on options
    if options and len(options) > 0:
        select = Select(
            {"id": f"answer-{key}"},
            data.bind(f"responseDraft.{key}"),
            *[Option({"value": opt}, opt) for opt in options],
        )
        card.children[2].children.append(select)
    else:
        input_elem = Input(
            {
                "id": f"answer-{key}",
                "type": "text",
                "placeholder": "Your response...",
                "autocomplete": "off",
            },
            data.bind(f"responseDraft.{key}"),
        )
        card.children[2].children.append(input_elem)
    
    # Add hidden signals for msg_id and agent_id
    card.children.append(Div({}, data.signals({"msg_id": msg_id, "agent_id": agent_id})))
    
    # Add submit button
    button = Button(
        {"type": "button"},
        data.on(
            "click",
            f"""
            const draft = $responseDraft?.{key};
            if (draft?.trim()) {{
                @post('/agent/$agent_id/respond', {{question: '{question}', answer: draft}});
                $responseDraft.{key} = '';
            }}
            """,
        ),
        "Send",
    )
    card.children[2].children.append(button)
    
    return card

def blocked_list_view(blocked: list[dict]) -> Div:
    """Container for all blocked agent cards."""
    if not blocked:
        return Div(
            {"id": "blocked-agents", "class": "blocked-agents"},
            Div({"class": "empty-state"}, "No agents waiting for input"),
        )
    
    return Div(
        {"id": "blocked-agents", "class": "blocked-agents"},
        *[blocked_card_view(b) for b in blocked],
    )
```

### Step 2.4: Implement Agent Status List View

Add to `views.py`:

```python
def agent_item_view(agent_id: str, state_info: dict) -> Div:
    """Single agent status row."""
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)
    
    return Div(
        {"class": "agent-item"},
        Span({"class": f"state-indicator {state}"}),
        Span({"class": "agent-name"}, name),
        Span({"class": "agent-state"}, state),
    )

def agent_status_view(agent_states: dict) -> Div:
    """Container for all agent status items."""
    if not agent_states:
        return Div(
            {"id": "agent-status", "class": "agent-status"},
            Div({"class": "empty-state"}, "No agents running"),
        )
    
    return Div(
        {"id": "agent-status", "class": "agent-status"},
        *[agent_item_view(aid, info) for aid, info in agent_states.items()],
    )
```

### Step 2.5: Implement Results Feed View

Add to `views.py`:

```python
def result_item_view(result: dict) -> Div:
    """Single result item."""
    agent_id = result.get("agent_id", "")
    content = result.get("content", "")
    timestamp = result.get("timestamp", "")
    
    return Div(
        {"class": "result-item"},
        Div({"class": "result-agent"}, f"@{agent_id}"),
        Div({"class": "result-content"}, content),
    )

def results_view(results: list[dict]) -> Div:
    """Container for result items."""
    if not results:
        return Div(
            {"id": "results", "class": "results"},
            Div({"class": "empty-state"}, "No results yet"),
        )
    
    return Div(
        {"id": "results", "class": "results"},
        *[result_item_view(r) for r in results],
    )
```

### Step 2.6: Implement Progress Bar View

Add to `views.py`:

```python
def progress_bar_view(total: int, completed: int) -> Div:
    """Progress bar with reactive width binding."""
    percent = int((completed / total) * 100) if total > 0 else 0
    
    return Div(
        {"id": "execution-progress"},
        Div(
            {"class": "progress-bar"},
            Div(
                {"id": "progress-fill", "class": "progress-fill"},
                data.style("width", f"$progress.completed / $progress.total * 100 + '%'"),
            ),
        ),
        Div(
            {"id": "progress-text", "class": "progress-text"},
            data.text(f"$progress.completed + '/' + $progress.total + ' agents completed'"),
        ),
    )
```

### Step 2.7: Compose Main Dashboard View

Add to `views.py`:

```python
def dashboard_view(state: DashboardState) -> Html:
    """Main dashboard page - combines all sections."""
    signals = state.get_signals()
    
    return page_with_content(
        data.signals(signals, ifmissing=True),
        data.init(at.get("/events")),
        
        # Header
        Div(
            {"class": "header"},
            Div({}, "Remora Dashboard"),
            Div({"id": "connection-status", "class": "status connected"}, "Connected"),
        ),
        
        # Main layout
        Div(
            {"class": "main"},
            # Events panel
            Div(
                {"id": "events-panel"},
                Div({"id": "events-header"}, "Events Stream"),
                events_list_view(signals["events"]),
            ),
            
            # Main panel
            Div(
                {"id": "main-panel"},
                # Blocked agents
                Div({"class": "card"},
                    Div({}, "Blocked Agents"),
                    blocked_list_view(signals["blocked"]),
                ),
                # Agent status
                Div({"class": "card"},
                    Div({}, "Agent Status"),
                    agent_status_view(signals["agentStates"]),
                ),
                # Results
                Div({"class": "card"},
                    Div({}, "Results"),
                    results_view(signals["results"]),
                ),
                # Progress
                Div({"class": "card"},
                    Div({}, "Graph Execution"),
                    progress_bar_view(signals["progress"]["total"], signals["progress"]["completed"]),
                ),
            ),
        ),
    )
```

---

## Phase 3: Request Handlers

### Step 3.1: Create Handlers Module

Create `demo/stario_dashboard/handlers.py`:

```python
from dataclasses import dataclass
from stario import Context, Writer
from remora.event_bus import get_event_bus
from . import dashboard_state
from .views import dashboard_view

@dataclass
class RespondSignals:
    agent_id: str = ""
    msg_id: str = ""
    question: str = ""
    answer: str = ""

async def home(c: Context, w: Writer) -> None:
    """Serve initial dashboard page."""
    w.html(dashboard_view(dashboard_state))

async def events(c: Context, w: Writer) -> None:
    """SSE endpoint - streams dashboard patches on each event."""
    event_bus = get_event_bus()
    
    async with w.alive(event_bus.stream()) as stream:
        async for event in stream:
            dashboard_state.record(event)
            w.patch(dashboard_view(dashboard_state))
            w.sync(dashboard_state.get_signals())

async def respond(c: Context, w: Writer, agent_id: str) -> None:
    """Handle user response to blocked agent."""
    signals = await c.signals(RespondSignals)
    
    # Validate
    if not signals.agent_id or not signals.answer:
        w.json({"error": "Missing required fields"}, status=400)
        return
    
    # TODO: Integrate with WorkspaceInboxCoordinator
    # For MVP, use the existing pattern from demo/dashboard/app.py
    # This requires workspace reference - see Integration section below
    
    w.json({"status": "ok", "agent_id": signals.agent_id})
```

---

## Phase 4: Application Setup

### Step 4.1: Create Main Entry Point

Create `demo/stario_dashboard/main.py`:

```python
from stario import Stario
from stario.http.writer import CompressionConfig
from . import dashboard_state
from . import handlers
from . import views

app = Stario(
    tracer=lambda name: {"name": name},  # TODO: proper tracer
    compression=CompressionConfig(),
)

# Routes
app.get("/", handlers.home)
app.get("/events", handlers.events)
app.post("/agent/{agent_id}/respond", handlers.respond)

# Static files (reuse existing dashboard styles)
app.assets("/static", "./static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Step 4.2: Copy Static Assets

Copy `demo/dashboard/static/style.css` to `demo/stario_dashboard/static/css/style.css`

Copy Datastar JS to `demo/stario_dashboard/static/js/datastar.js` (see `stario/examples/chat/app/static/js/datastar.js`)

---

## Phase 5: Integration with Remora Core

### Step 5.1: Connect EventBus

The integration is already defined in `handlers.py`:
```python
from remora.event_bus import get_event_bus
event_bus = get_event_bus()
```

This ensures the Stario dashboard shares the same EventBus as the rest of Remora.

### Step 5.2: Option B - Full Integration with WorkspaceInboxCoordinator

This is the **production-ready** pattern that actually delivers responses to agents. It integrates with the existing `WorkspaceInboxCoordinator` to write responses to the workspace KV store.

#### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              Agent                                       │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ externals.py: ask_user()                                       │    │
│  │   1. Writes to outbox:question:{msg_id}  ─────────────────┐   │    │
│  │   2. Polls inbox:response:{msg_id}  ◄─────────────────────┼───┘    │
│  └─────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ KV reads
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                         Workspace KV Store                              │
│   outbox:question:abc123 ──► {question, options, status: "pending"}    │
│   inbox:response:abc123 ◄── {answer, responded_at}                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ KV writes
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                   WorkspaceInboxCoordinator                            │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │ coordinator.py                                               │    │
│   │   - Polls outbox:question:* for pending questions            │    │
│   │   - Publishes Event.agent_blocked to EventBus                │    │
│   │   - respond(): writes to inbox:response:{msg_id}             │    │
│   └────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ EventBus
                                    │
┌─────────────────────────────────────────────────────────────────────────┐
│                       Stario Dashboard                                  │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │ events handler:                                              │    │
│   │   - Subscribes to EventBus                                    │    │
│   │   - Records events in DashboardState                         │    │
│   │   - Patches view on each event                               │    │
│   └────────────────────────────────────────────────────────────────┘    │
│   ┌────────────────────────────────────────────────────────────────┐    │
│   │ respond handler:                                              │    │
│   │   - Gets msg_id from event payload                           │    │
│   │ - Calls coordinator.respond() to write KV                  │    │
│   └────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

#### Implementation Details

**Step 5.2.1: Create Workspace Registry**

The dashboard needs to track which workspace belongs to which agent. Create `demo/stario_dashboard/workspace_registry.py`:

```python
"""Workspace registry - tracks agent -> workspace mappings."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkspaceInfo:
    """Info about a workspace used by an agent."""
    workspace_id: str
    workspace: Any  # Cairn workspace with .kv attribute
    created_at: float = field(default_factory=lambda: __import__("time").time())


class WorkspaceRegistry:
    """Maps agent_ids to their workspaces.
    
    This is needed because when an agent blocks, we need to know
    which workspace to write the response to.
    
    Usage:
        registry = WorkspaceRegistry()
        
        # Register a workspace for an agent
        await registry.register(agent_id, workspace)
        
        # Get workspace for agent
        workspace = registry.get(agent_id)
        
        # Unregister when agent completes
        registry.unregister(agent_id)
    """
    
    def __init__(self):
        self._agent_workspace: dict[str, WorkspaceInfo] = {}
    
    async def register(self, agent_id: str, workspace_id: str, workspace: Any) -> None:
        """Register a workspace for an agent."""
        self._agent_workspace[agent_id] = WorkspaceInfo(
            workspace_id=workspace_id,
            workspace=workspace,
        )
    
    def get(self, agent_id: str) -> WorkspaceInfo | None:
        """Get workspace info for an agent."""
        return self._agent_workspace.get(agent_id)
    
    def get_workspace(self, agent_id: str) -> Any:
        """Get the actual workspace for an agent."""
        info = self._agent_workspace.get(agent_id)
        return info.workspace if info else None
    
    def unregister(self, agent_id: str) -> None:
        """Remove agent's workspace mapping."""
        self._agent_workspace.pop(agent_id, None)
    
    def list_agents(self) -> list[str]:
        """List all registered agent IDs."""
        return list(self._agent_workspace.keys())


# Global registry instance
workspace_registry = WorkspaceRegistry()
```

**Step 5.2.2: Modify Event Recording to Track Workspaces**

Update `state.py` to capture workspace information from events:

```python
# In state.py - add workspace reference tracking
from dataclasses import dataclass, field
from collections import deque
from datetime import datetime
from remora.event_bus import Event

# Import the workspace registry
from .workspace_registry import workspace_registry

MAX_EVENTS = 200


@dataclass
class DashboardState:
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict] = field(default_factory=dict)
    agent_states: dict[str, dict] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0
    
    def record(self, event: Event):
        """Process an event and update state."""
        # Update events deque
        self.events.append(event.model_dump())
        
        if event.category == "agent" and event.agent_id:
            # Handle agent lifecycle events
            if event.action == "started":
                self.agent_states[event.agent_id] = {
                    "state": "started",
                    "name": event.payload.get("name", event.agent_id),
                    # Track workspace_id from payload
                    "workspace_id": event.payload.get("workspace_id"),
                }
                self.total_agents += 1
                
            elif event.action == "blocked":
                key = f"{event.agent_id}:{event.payload.get('question', '')}"
                # Capture msg_id and workspace_id from event
                self.blocked[key] = {
                    "agent_id": event.agent_id,
                    "question": event.payload.get("question", ""),
                    "options": event.payload.get("options", []),
                    "msg_id": event.payload.get("msg_id", ""),
                    "workspace_id": event.payload.get("workspace_id", ""),
                }
                
            elif event.action == "resumed":
                question = event.payload.get("question", "")
                if question:
                    key = f"{event.agent_id}:{question}"
                    self.blocked.pop(key, None)
                    
            elif event.action in ("completed", "failed", "cancelled"):
                if event.agent_id in self.agent_states:
                    self.agent_states[event.agent_id]["state"] = event.action
                    self.completed_agents += 1
                    # Cleanup workspace mapping
                    ws_id = self.agent_states[event.agent_id].get("workspace_id")
                    if ws_id:
                        workspace_registry.unregister(event.agent_id)
        
        # Update results for completed agents
        if event.category == "agent" and event.action == "completed":
            self.results.insert(0, {
                "agent_id": event.agent_id,
                "content": event.payload.get("result", str(event.payload)),
                "timestamp": event.timestamp.isoformat()
            })
            if len(self.results) > 50:
                self.results.pop()
    
    def get_signals(self) -> dict:
        return {
            "events": list(self.events),
            "blocked": list(self.blocked.values()),
            "agentStates": self.agent_states,
            "progress": {
                "total": self.total_agents,
                "completed": self.completed_agents
            },
            "results": self.results[:10]
        }
```

**Step 5.2.3: Update Respond Handler**

Update `handlers.py` to use the coordinator:

```python
from dataclasses import dataclass
from stario import Context, Writer
from remora.event_bus import Event, get_event_bus
from remora.interactive.coordinator import WorkspaceInboxCoordinator

from . import dashboard_state
from .workspace_registry import workspace_registry
from .views import dashboard_view


@dataclass
class RespondSignals:
    agent_id: str = ""
    msg_id: str = ""
    question: str = ""
    answer: str = ""


# Global coordinator instance - inject EventBus
_coordinator: WorkspaceInboxCoordinator | None = None


def get_coordinator() -> WorkspaceInboxCoordinator:
    """Get or create the global coordinator."""
    global _coordinator
    if _coordinator is None:
        event_bus = get_event_bus()
        _coordinator = WorkspaceInboxCoordinator(event_bus)
    return _coordinator


async def home(c: Context, w: Writer) -> None:
    """Serve initial dashboard page."""
    w.html(dashboard_view(dashboard_state))


async def events(c: Context, w: Writer) -> None:
    """SSE endpoint - streams dashboard patches on each event."""
    event_bus = get_event_bus()
    
    async with w.alive(event_bus.stream()) as stream:
        async for event in stream:
            dashboard_state.record(event)
            w.patch(dashboard_view(dashboard_state))
            w.sync(dashboard_state.get_signals())


async def respond(c: Context, w: Writer, agent_id: str) -> None:
    """Handle user response to blocked agent - writes to workspace KV."""
    signals = await c.signals(RespondSignals)
    
    # Validate required fields
    if not signals.agent_id or not signals.answer:
        w.json({"error": "Missing required fields: agent_id and answer are required"}, status=400)
        return
    
    # Get msg_id - from signals or lookup from blocked
    msg_id = signals.msg_id
    if not msg_id:
        # Try to find msg_id from blocked questions
        for blocked in dashboard_state.blocked.values():
            if blocked.get("agent_id") == signals.agent_id:
                msg_id = blocked.get("msg_id", "")
                if msg_id:
                    break
    
    if not msg_id:
        w.json({"error": "No pending question found for this agent"}, status=400)
        return
    
    # Get workspace for this agent
    workspace = workspace_registry.get_workspace(signals.agent_id)
    if not workspace:
        w.json({"error": "No workspace found for agent. Is the agent still running?"}, status=400)
        return
    
    # Use coordinator to respond - writes to KV and publishes event
    coordinator = get_coordinator()
    try:
        await coordinator.respond(
            agent_id=signals.agent_id,
            msg_id=msg_id,
            answer=signals.answer,
            workspace=workspace,
        )
        w.json({"status": "ok", "agent_id": signals.agent_id, "msg_id": msg_id})
    except Exception as e:
        w.json({"error": f"Failed to send response: {str(e)}"}, status=500)
```

**Step 5.2.4: How Events Must Include Workspace Info**

For Option B to work, the `Event.agent_blocked` must include workspace information. This is already partially implemented in `WorkspaceInboxCoordinator`:

```python
# In coordinator.py - the event publishing already includes msg_id
await self.event_bus.publish(
    Event.agent_blocked(
        agent_id=agent_id, 
        question=q.question, 
        options=q.options or [], 
        msg_id=q.msg_id
    )
)
```

However, to include `workspace_id`, we need to modify the coordinator to include it:

```python
# Updated coordinator.py publish
await self.event_bus.publish(
    Event.agent_blocked(
        agent_id=agent_id, 
        question=q.question, 
        options=q.options or [], 
        msg_id=q.msg_id,
        workspace_id=workspace_id,  # NEW - if we pass workspace to coordinator
    )
)
```

Or alternatively, the Stario dashboard can use a different approach:

**Alternative: Direct KV Access**

Instead of using the coordinator, the dashboard can write directly to KV:

```python
async def respond(c: Context, w: Writer, agent_id: str) -> None:
    signals = await c.signals(RespondSignals)
    
    # Get workspace
    workspace = workspace_registry.get_workspace(agent_id)
    if not workspace:
        w.json({"error": "No workspace found"}, status=400)
        return
    
    # Write directly to KV
    inbox_key = f"inbox:response:{signals.msg_id}"
    await workspace.kv.set(inbox_key, {
        "answer": signals.answer,
        "responded_at": datetime.now().isoformat(),
    })
    
    # Publish resumed event
    event_bus = get_event_bus()
    await event_bus.publish(Event.agent_resumed(
        agent_id=agent_id,
        answer=signals.answer,
        msg_id=signals.msg_id,
    ))
    
    w.json({"status": "ok"})
```

#### Summary: Option B Components

| Component | File | Purpose |
|-----------|------|---------|
| WorkspaceRegistry | `workspace_registry.py` | Maps agent_id → workspace |
| DashboardState | `state.py` | Tracks blocked with workspace_id |
| Coordinator integration | `handlers.py` | Writes to KV via coordinator |
| Event enhancement | `coordinator.py` | Include workspace_id in events |

#### Pros/Cons of Option B

| Pros | Cons |
|------|------|
| Agent receives actual response | Requires workspace lifecycle management |
| Works across process boundaries | Need to pass workspace through event chain |
| Production-ready pattern | More complex than Option A |
| Matches existing architecture | Must handle workspace cleanup |
| Survives dashboard restart | Need to track agent→workspace map |

---

## Phase 6: Testing

### Step 6.1: Smoke Test

Create `tests/test_stario_dashboard.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport
from demo.stario_dashboard.main import app

@pytest.mark.asyncio
async def test_events_endpoint():
    """Test that /events returns SSE stream."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, follow_redirects=True) as client:
        async with client.stream("GET", "/events") as response:
            assert response.status_code == 200
            assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
            
            # Read first chunk
            chunk = await response.aread()
            assert b"datastar-patch-elements" in chunk or b"" == chunk

@pytest.mark.asyncio
async def test_home_page():
    """Test that home page renders."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, follow_redirects=True) as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert b"Remora Dashboard" in response.content

@pytest.mark.asyncio
async def test_respond_endpoint():
    """Test responding to blocked agent."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, follow_redirects=True) as client:
        response = await client.post(
            "/agent/test-agent/respond",
            json={"question": "Test?", "answer": "Test answer"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
```

---

## Phase 7: Running the Demo

### Step 7.1: Start the Server

```bash
cd demo/stario_dashboard
python main.py
```

Or via Remora CLI:

```bash
remora-demo --dashboard stario
```

### Step 7.2: Verify

1. Open `http://localhost:8000` in browser
2. Connection status should show "Connected"
3. Events should stream in real-time
4. Blocked agents should appear and be respondable

---

## Implementation Order Summary

**For Option B (Production-Ready):**

| Phase | Step | Task | File |
|-------|------|------|------|
| 1 | 1.1 | Create module structure | `demo/stario_dashboard/` |
| 1 | 1.2 | Create state aggregator | `state.py` |
| 1 | 1.3 | Create global instance | `__init__.py` |
| 1 | 1.4 | **Create WorkspaceRegistry** | `workspace_registry.py` | NEW |
| 2 | 2.1 | Base page shell | `views.py` |
| 2 | 2.2 | Event log view | `views.py` |
| 2 | 2.3 | Blocked card view | `views.py` |
| 2 | 2.4 | Agent status view | `views.py` |
| 2 | 2.5 | Results view | `views.py` |
| 2 | 2.6 | Progress bar view | `views.py` |
| 2 | 2.7 | Compose main view | `views.py` |
| 3 | 3.1 | Create handlers (with coordinator) | `handlers.py` |
| 4 | 4.1 | Create main.py | `main.py` |
| 4 | 4.2 | Copy static assets | `static/` |
| 5 | 5.1 | Connect EventBus | `handlers.py` |
| 5 | 5.2 | **Integrate WorkspaceInboxCoordinator** | `handlers.py` + `workspace_registry.py` |
| 5 | 5.3 | **Enhance Event.agent_blocked** | `src/remora/interactive/coordinator.py` |
| 6 | 6.1 | Write tests | `tests/test_stario_dashboard.py` |
| 2 | 2.1 | Base page shell | `views.py` |
| 2 | 2.2 | Event log view | `views.py` |
| 2 | 2.3 | Blocked card view | `views.py` |
| 2 | 2.4 | Agent status view | `views.py` |
| 2 | 2.5 | Results view | `views.py` |
| 2 | 2.6 | Progress bar view | `views.py` |
| 2 | 2.7 | Compose main view | `views.py` |
| 3 | 3.1 | Create handlers | `handlers.py` |
| 4 | 4.1 | Create main.py | `main.py` |
| 4 | 4.2 | Copy static assets | `static/` |
| 5 | 5.1 | Connect EventBus | `handlers.py` |
| 5 | 5.2 | Response handling | `handlers.py` + `state.py` |
| 6 | 6.1 | Write tests | `tests/test_stario_dashboard.py` |

---

## Choosing Between Option A and Option B

This plan implements **Option B** (production-ready) as the default since you requested a "fully functional *real* demo".

### Quick Comparison

| Aspect | Option A (In-Memory) | Option B (Coordinator) |
|--------|---------------------|----------------------|
| **Use Case** | Demo/PoC only | Production |
| **Agent receives response** | No | Yes |
| **Complexity** | Low | Medium |
| **Dependencies** | None | WorkspaceRegistry, coordinator |
| **Works remotely** | No | Yes |

### When to Use Each

- **Option A**: Quick demo to prove SSE/patching works, agents run in same process
- **Option B**: Real usage where agents need the response, production deployment

### Converting to Option A (if needed)

If you need to fall back to Option A for simpler testing:
1. Remove `workspace_registry.py`
2. In `handlers.py`, replace KV write with in-memory dict
3. Remove coordinator integration

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Event duplication | Track per-client last_event_id; filter initial events |
| Workspace reference | **Option B solves this** via WorkspaceRegistry |
| Concurrent updates | Use asyncio.Lock in DashboardState if needed |
| Performance | Filter to agent:* and graph:* events only |
| Workspace cleanup | Unregister on agent completed/failed/cancelled |

---

## Success Criteria

- [ ] SSE stream updates view without custom JS DOM logic
- [ ] Blocked agent questions appear and can be answered
- [ ] `agent:resumed` events update the UI
- [ ] Response is written to workspace KV (agent can read it)
- [ ] Event log, status list, and progress bar remain accurate
- [ ] Reuses existing EventBus and WorkspaceInboxCoordinator
- [ ] Tests pass
