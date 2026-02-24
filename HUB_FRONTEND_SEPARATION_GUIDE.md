# REMORA HUB + FRONTEND SEPARATION GUIDE

> **Final Version**: Using datastar-py (Starlette) for Hub + Stario for Frontend

---

## Python Version Compatibility

| Component | Framework | Python Version |
|-----------|-----------|---------------|
| Hub (Agent/Backend) | datastar-py + Starlette | 3.10+ (compatible with 3.13) |
| Frontend (UI) | Stario | 3.14+ |

---

## Architecture Overview

### The Complete Agent Interaction Flow

Understanding how Remora handles agent interaction is critical:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AGENT EXECUTION FLOW                              │
└─────────────────────────────────────────────────────────────────────────────────┘

1. Agent starts → register_agent_workspace(agent_id, workspace)
   → WorkspaceRegistry maps agent_id → GraphWorkspace

2. Agent blocks → writes to workspace KV:
   → key: "outbox:question:{msg_id}"
   → value: {"question": "...", "options": [...], "status": "pending", ...}

3. WorkspaceInboxCoordinator polls workspace.kv.list("outbox:question:")
   → finds pending questions
   → publishes Event.agent_blocked(agent_id, question, msg_id)

4. Frontend receives event → displays blocked question with response form

5. User responds → POST /agent/{agent_id}/respond
   → WorkspaceInboxCoordinator.respond(agent_id, msg_id, answer)
   → writes to workspace KV: key: "inbox:response:{msg_id}"

6. Agent reads response → workspace.kv.get("inbox:response:{msg_id}")
   → resumes execution
```

### Hub + Frontend Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              REMORA HUB (Server)                               │
│                           Python 3.10+ (Starlette)                            │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │ GraphWorkspace (Fsdantic)                                              │   │
│  │   - .kv → WorkspaceKV for agent↔frontend IPC                          │   │
│  │   - .agent_space(agent_id) → per-agent directories                    │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
│                                    ▲                                           │
│                                    │                                           │
│  ┌────────────┐    ┌─────────────┐│    ┌─────────────────────────────┐     │
│  │ EventBus   │◀──▶│ AgentGraph  ││    │ WorkspaceInboxCoordinator  │     │
│  │            │    │             ││    │ (polls KV, publishes      │     │
│  │            │    │             ││    │  agent_blocked events)    │     │
│  └─────┬──────┘    └─────────────┘│    └──────────────┬────────────┘     │
│        │                            │                     │                  │
│        │  /subscribe endpoint      │                     │                  │
│        │  → DatastarResponse      │                     │                  │
│        │  → SSE.patch_elements() │                     │                  │
│        │  = HTML snapshots       │                     │                  │
│        │                            │                     │                  │
│        │  POST /graph/execute     │                     │                  │
│        │  POST /agent/{id}/respond│                     │                  │
└────────┼────────────────────────────┼─────────────────────┼──────────────────┘
         │                            │                     │
         │ SSE (Datastar format)     │ HTTP POST           │
         │ over Tailscale           │ over Tailscale      │
         │                            │                     │
         ▼                            ▼                     ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (Laptop)                                      │
│                            Python 3.14+ (Stario)                               │
│                                                                               │
│  ┌───────────────────────────────────────────────────────────────────────┐   │
│  │ Stario + Datastar SPA                                                 │   │
│  │                                                                       │   │
│  │  GET /                     → serves SPA                               │   │
│  │  GET /subscribe            → proxies hub's SSE (pass-through)         │   │
│  │  POST /graph/execute      → proxy to hub                             │   │
│  │  POST /agent/{id}/respond → proxy to hub (user responds to agent)   │   │
│  │                                                                       │   │
│  │  Key UI Components:                                                  │   │
│  │  - Blocked agents list with response forms                           │   │
│  │  - Events stream viewer                                              │   │
│  │  - Agent status/status                                              │   │
│  │  - Results display                                                  │   │
│  └───────────────────────────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## PHASE 1: Hub Server (datastar-py + Starlette)

### 1.1 Key Components

The hub must correctly implement:

1. **GraphWorkspace** - Each graph gets a workspace with KV store
2. **WorkspaceRegistry** - Maps agent_ids → workspaces  
3. **WorkspaceInboxCoordinator** - Polls KV, publishes blocked events, writes responses
4. **EventBus** - Central event system

### 1.2 State Management

```python
# File: remora/hub/state.py

"""
Hub state management.

datastar-py pattern: Keep minimal server state - only what's needed to render
the next view. Re-render complete snapshots on each event.
"""

from dataclasses import dataclass, field
from typing import Any

from remora.event_bus import Event


@dataclass
class HubState:
    """Runtime state for the hub - kept in memory, rebuilt from events."""
    events: list[dict] = field(default_factory=list)
    blocked: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0

    def record(self, event: Event) -> None:
        """Process event and update state."""
        self.events.append(event.model_dump(mode="json"))
        if len(self.events) > 200:
            self.events = self.events[-200:]

        if event.category == "agent" and event.agent_id:
            agent_id = event.agent_id
            payload = event.payload or {}

            if event.action == "started":
                self.agent_states[agent_id] = {
                    "state": "started",
                    "name": payload.get("name", agent_id),
                    "workspace_id": payload.get("workspace_id"),
                    "parent_id": payload.get("parent_id"),
                }
                self.total_agents += 1

            elif event.action == "blocked":
                # KEY: Store blocked question with msg_id for responding later
                key = f"{agent_id}:{payload.get('question', '')}"
                self.blocked[key] = {
                    "agent_id": agent_id,
                    "question": payload.get("question", ""),
                    "options": payload.get("options", []),
                    "msg_id": payload.get("msg_id", ""),  # Critical for responding!
                    "workspace_id": payload.get("workspace_id", ""),
                }

            elif event.action == "resumed":
                question = payload.get("question", "")
                if question:
                    key = f"{agent_id}:{question}"
                    self.blocked.pop(key, None)

            elif event.action in ("completed", "failed", "cancelled"):
                if agent_id in self.agent_states:
                    self.agent_states[agent_id]["state"] = event.action
                    if event.action == "completed":
                        self.completed_agents += 1

        if event.category == "agent" and event.action == "completed":
            self.results.insert(0, {
                "agent_id": event.agent_id,
                "content": event.payload.get("result", str(event.payload)),
                "timestamp": event.timestamp.isoformat() if event.timestamp else "",
            })
            if len(self.results) > 50:
                self.results = self.results[:50]

    def get_view_data(self) -> dict[str, Any]:
        """Data needed to render the dashboard view."""
        return {
            "events": self.events,
            "blocked": list(self.blocked.values()),
            "agentStates": self.agent_states,
            "progress": {"total": self.total_agents, "completed": self.completed_agents},
            "results": self.results[:10],
        }
```

### 1.3 Server Implementation

```python
# File: remora/hub/server.py

"""
Remora Hub Server - Starlette + datastar-py.

Uses datastar-py for Datastar SSE events - Python 3.10+ compatible.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from datastar_py import ServerSentEventGenerator as SSE, attribute_generator as data
from datastar_py.starlette import DatastarResponse, datastar_response, read_signals

from remora.event_bus import Event, EventBus, get_event_bus
from remora.frontend.registry import WorkspaceRegistry, workspace_registry
from remora.frontend.state import DashboardState
from remora.interactive import WorkspaceInboxCoordinator
from remora.workspace import GraphWorkspace, WorkspaceManager

from .state import HubState
from .views import dashboard_view


logger = logging.getLogger(__name__)


class HubServer:
    """The Remora Hub - agent execution server."""

    def __init__(
        self,
        workspace_path: Path,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.workspace_path = workspace_path
        self.host = host
        self.port = port

        # Core Remora components
        self._event_bus: EventBus | None = None
        self._coordinator: WorkspaceInboxCoordinator | None = None
        self._workspace_manager: WorkspaceManager | None = None
        
        # Hub state for rendering
        self._hub_state = HubState()
        
        # Starlette app
        self._app: Starlette | None = None

    async def start(self) -> None:
        """Start the hub server."""
        logger.info(f"Starting Remora Hub at {self.host}:{self.port}")

        # Initialize Remora components
        self._event_bus = get_event_bus()
        self._workspace_manager = WorkspaceManager()
        self._coordinator = WorkspaceInboxCoordinator(self._event_bus)

        # Subscribe to events to update hub state
        await self._event_bus.subscribe("agent:*", self._on_event)

        # Create Starlette app
        self._app = Starlette(
            routes=[
                Route("/", self.home),
                Route("/subscribe", self.subscribe),
                Route("/graph/execute", self.execute_graph, methods=["POST"]),
                Route("/agent/{agent_id}/respond", self.respond, methods=["POST"]),
                Mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"),
            ],
        )

        # Run server
        import uvicorn
        config = uvicorn.Config(self._app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _on_event(self, event: Event) -> None:
        """Handle incoming events - update state."""
        self._hub_state.record(event)

    async def home(self, request: Request) -> HTMLResponse:
        """Serve initial dashboard page."""
        view_data = self._hub_state.get_view_data()
        html = dashboard_view(view_data)
        return HTMLResponse(html)

    async def subscribe(self, request: Request) -> DatastarResponse:
        """
        SSE endpoint - streams complete view snapshots.
        
        Key datastar-py pattern:
        1. Send initial state via SSE.patch_elements()
        2. Loop until disconnect, re-rendering view on each event
        """
        @datastar_response
        async def event_stream():
            # Send initial state
            view_data = self._hub_state.get_view_data()
            yield SSE.patch_elements(dashboard_view(view_data))

            # Stream: on each event, re-render and patch
            async for _ in self._event_bus.stream():
                view_data = self._hub_state.get_view_data()
                yield SSE.patch_elements(dashboard_view(view_data))

        return await event_stream(request)

    async def execute_graph(self, request: Request) -> JSONResponse:
        """Execute an agent graph - starts agents in the graph."""
        signals = await read_signals(request) or {}
        graph_id = signals.get("graph_id", "")

        if not graph_id:
            return JSONResponse({"error": "graph_id required"}, status_code=400)

        # Create workspace for this graph
        workspace = await self._workspace_manager.create(graph_id)

        # Demo agents - in real usage, this would be the actual agent graph
        demo_agents = [
            {"id": "root-1", "name": "Root Analyzer", "parent": None},
            {"id": "root-2", "name": "Root Validator", "parent": None},
            {"id": "branch-a", "name": "Branch A", "parent": "root-1"},
            {"id": "leaf-a1", "name": "Leaf A1", "parent": "branch-a"},
        ]

        for agent in demo_agents:
            agent_id = agent["id"]
            # KEY: Register agent with workspace for KV-based communication
            await workspace_registry.register(agent_id, workspace.id, workspace)
            # Start watching this workspace for blocked questions
            await self._coordinator.watch_workspace(agent_id, workspace)
            # Publish agent started event
            await self._event_bus.publish(Event.agent_started(
                agent_id=agent_id,
                name=agent["name"],
                workspace_id=workspace.id,
                parent_id=agent["parent"],
            ))

        return JSONResponse({
            "status": "started",
            "graph_id": graph_id,
            "agents": len(demo_agents),
            "workspace": workspace.id,
        })

    async def respond(self, request: Request, agent_id: str) -> JSONResponse:
        """
        Handle user response to an agent's blocked question.
        
        This is the KEY endpoint for user interaction:
        1. Find the agent's workspace
        2. Write response to workspace KV (inbox:response:{msg_id})
        3. Coordinator publishes agent_resumed event
        """
        signals = await read_signals(request) or {}
        answer = signals.get("answer", "")
        question = signals.get("question", "")
        
        # Find msg_id - either from signals or from blocked state
        msg_id = signals.get("msg_id", "")
        if not msg_id:
            # Look up from blocked state
            for blocked in self._hub_state.blocked.values():
                if blocked.get("agent_id") == agent_id:
                    msg_id = blocked.get("msg_id", "")
                    if msg_id:
                        break

        if not msg_id:
            return JSONResponse({
                "error": "No pending question found for this agent. Is the agent still running?"
            }, status_code=400)

        # Get agent's workspace
        workspace = workspace_registry.get_workspace(agent_id)
        if not workspace:
            return JSONResponse({
                "error": "No workspace found for agent. Is the agent still running?"
            }, status_code=400)

        # KEY: Write response to workspace KV - this unblocks the agent!
        await self._coordinator.respond(
            agent_id=agent_id,
            msg_id=msg_id,
            answer=answer,
            workspace=workspace,
        )

        return JSONResponse({
            "status": "ok",
            "agent_id": agent_id,
            "msg_id": msg_id,
            "answer": answer,
        })


async def run_hub(
    workspace_path: Path = Path(".remora/hub.workspace"),
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run the Remora Hub server."""
    server = HubServer(workspace_path, host, port)
    await server.start()


if __name__ == "__main__":
    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_hub())
```

### 1.4 View Functions (Complete with Response Forms)

```python
# File: remora/hub/views.py

"""
Dashboard views - complete HTML with blocked agent response forms.

Uses datastar-py's attribute_generator for data-* attributes.
"""

from datastar_py import attribute_generator as data


def render_tag(tag, content="", **attrs):
    """Simple HTML tag renderer."""
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v)
    if content:
        return f"<{tag} {attr_str}>{content}</{tag}>" if attr_str else f"<{tag}>{content}</{tag}>"
    return f"<{tag} {attr_str}/>" if attr_str else f"<{tag}/>"


def page(title="Remora Hub", *body_content):
    """Base HTML shell with Datastar loaded."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <link rel="stylesheet" href="/static/style.css">
</head>
<body {data.init("@get('/subscribe"))}>
    {''.join(body_content)}
</body>
</html>"""


def event_item_view(event: dict) -> str:
    """Single event in the stream."""
    timestamp = event.get("timestamp", "")[:8] if event.get("timestamp") else "--:--:--"
    category = event.get("category", "")
    action = event.get("action", "")
    agent_id = event.get("agent_id", "")
    payload = event.get("payload", {})
    
    return render_tag("div", class_=f"event {category}_{action}",
        render_tag("span", class_="event-time", content=timestamp) +
        render_tag("span", class_="event-type", content=f"{category}:{action}") +
        (render_tag("span", class_="event-agent", content=f"@{agent_id}") if agent_id else "") +
        (render_tag("div", class_="event-payload", content=str(payload)) if payload else "")
    )


def events_list_view(events: list[dict]) -> str:
    """List of events."""
    if not events:
        return render_tag("div", id="events-list", class_="events-list",
            render_tag("div", class_="empty-state", content="No events yet"))
    
    events_html = ''.join(event_item_view(e) for e in reversed(events[-50:]))
    return render_tag("div", id="events-list", class_="events-list", content=events_html)


def blocked_card_view(blocked: dict) -> str:
    """
    BLOCKED AGENT CARD - This is KEY for user interaction!
    
    Shows:
    - Agent ID and question
    - Options (if multiple choice) OR text input
    - Send button that POSTs to /agent/{agent_id}/respond
    """
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    msg_id = blocked.get("msg_id", "")
    
    key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")
    
    card = render_tag("div", class_="blocked-agent", **{"data-key": key},
        render_tag("div", class_="agent-id", content=f"@{agent_id}") +
        render_tag("div", class_="question", content=question) +
        render_tag("div", class_="response-form", id=f"form-{key}")
    )
    
    # Build response input
    if options and len(options) > 0:
        # Multiple choice - use select
        options_html = ''.join(
            render_tag("option", content=opt, **{"value": opt}) 
            for opt in options
        )
        input_html = render_tag("select", 
            id=f"answer-{key}",
            **{"data-bind": f"responseDraft.{key}"},
            content=options_html
        )
    else:
        # Text input
        input_html = render_tag("input",
            id=f"answer-{key}",
            type="text",
            placeholder="Your response...",
            autocomplete="off",
            **{"data-bind": f"responseDraft.{key}"}
        )
    
    # Send button - posts to /agent/{agent_id}/respond
    button = render_tag("button",
        type="button",
        **{
            "data-on": f"click",
            # Store msg_id in signal, post to respond endpoint
            "data-on-click": f"""
                const draft = $responseDraft?.{key};
                if (draft?.trim()) {{
                    @post('/agent/{agent_id}/respond', {{question: '{question}', answer: draft, msg_id: '{msg_id}'}});
                    $responseDraft.{key} = '';
                }}
            """
        },
        content="Send"
    )
    
    # Assemble the form
    form = render_tag("div", class_="response-form", id=f"form-{key}",
        input_html + button
    )
    
    # Add hidden signals for msg_id and agent_id
    signals = render_tag("div", **{
        "data-signals": f'{{"msg_id": "{msg_id}", "agent_id": "{agent_id}"}}'
    })
    
    return render_tag("div", class_="blocked-agent", **{"data-key": key},
        render_tag("div", class_="agent-id", content=f"@{agent_id}") +
        render_tag("div", class_="question", content=question) +
        form +
        signals
    )


def blocked_list_view(blocked: list[dict]) -> str:
    """List of blocked agents waiting for response."""
    if not blocked:
        return render_tag("div", id="blocked-agents", class_="blocked-agents",
            render_tag("div", class_="empty-state", content="No agents waiting for input"))
    
    cards = ''.join(blocked_card_view(b) for b in blocked)
    return render_tag("div", id="blocked-agents", class_="blocked-agents", content=cards)


def agent_item_view(agent_id: str, state_info: dict) -> str:
    """Single agent status."""
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)
    
    return render_tag("div", class_="agent-item",
        render_tag("span", class_=f"state-indicator {state}") +
        render_tag("span", class_="agent-name", content=name) +
        render_tag("span", class_="agent-state", content=state)
    )


def agent_status_view(agent_states: dict) -> str:
    """All agent statuses."""
    if not agent_states:
        return render_tag("div", id="agent-status", class_="agent-status",
            render_tag("div", class_="empty-state", content="No agents running"))
    
    items = ''.join(agent_item_view(aid, info) for aid, info in agent_states.items())
    return render_tag("div", id="agent-status", class_="agent-status", content=items)


def result_item_view(result: dict) -> str:
    """Single result."""
    agent_id = result.get("agent_id", "")
    content = result.get("content", "")
    
    return render_tag("div", class_="result-item",
        render_tag("div", class_="result-agent", content=f"@{agent_id}") +
        render_tag("div", class_="result-content", content=content)
    )


def results_view(results: list[dict]) -> str:
    """List of results."""
    if not results:
        return render_tag("div", id="results", class_="results",
            render_tag("div", class_="empty-state", content="No results yet"))
    
    items = ''.join(result_item_view(r) for r in results)
    return render_tag("div", id="results", class_="results", content=items)


def progress_bar_view(total: int, completed: int) -> str:
    """Progress bar."""
    percent = int((completed / total) * 100) if total > 0 else 0
    
    return render_tag("div", id="execution-progress",
        render_tag("div", class_="progress-bar",
            render_tag("div", id="progress-fill", class_="progress-fill",
                **{"style": f"width: {percent}%"},
                content=""
            )
        ) +
        render_tag("div", id="progress-text", class_="progress-text",
            content=f"{completed}/{total} agents completed"
        )
    )


def dashboard_view(view_data: dict) -> str:
    """
    Main dashboard view - complete HTML snapshot.
    
    This is called on initial load AND on every SSE patch.
    Datastar matches elements by ID and morphs the DOM.
    """
    events = view_data.get("events", [])
    blocked = view_data.get("blocked", [])
    agent_states = view_data.get("agentStates", {})
    progress = view_data.get("progress", {"total": 0, "completed": 0})
    results = view_data.get("results", [])

    return page(
        # Header
        render_tag("div", class_="header",
            render_tag("div", content="Remora Hub") +
            render_tag("div", class_="status",
                      content=f"Agents: {progress['completed']}/{progress['total']}")
        ),

        # Main layout
        render_tag("div", class_="main",
            # Events panel
            render_tag("div", id="events-panel",
                render_tag("div", id="events-header", content="Events Stream") +
                events_list_view(events)
            ),
            
            # Main panel
            render_tag("div", id="main-panel",
                # Blocked agents - KEY for interaction!
                render_tag("div", class_="card",
                    render_tag("div", content="Blocked Agents") +
                    blocked_list_view(blocked)
                ),
                
                # Agent status
                render_tag("div", class_="card",
                    render_tag("div", content="Agent Status") +
                    agent_status_view(agent_states)
                ),
                
                # Results
                render_tag("div", class_="card",
                    render_tag("div", content="Results") +
                    results_view(results)
                ),
                
                # Progress
                render_tag("div", class_="card",
                    render_tag("div", content="Graph Execution") +
                    progress_bar_view(progress["total"], progress["completed"])
                )
            )
        )
    )
```

### 1.5 CLI Command

```python
# File: remora/hub/cli.py

import logging
from pathlib import Path

import click


@click.group()
def cli():
    """Remora Hub commands."""
    pass


@cli.command()
@click.option("--workspace", type=click.Path(path_type=Path), default=".remora/hub")
@click.option("--host", default="0.0.0.0")
@click.option("--port", default=8000, type=int)
def serve(workspace: Path, host: str, port: int):
    """Start the Remora Hub server."""
    from remora.hub.server import run_hub

    logging.basicConfig(level=logging.INFO)
    import asyncio
    asyncio.run(run_hub(workspace, host, port))
```

---

## PHASE 2: Frontend (Stario)

The frontend is a minimal proxy that:
1. Serves the SPA
2. Proxies SSE from hub (pass-through)
3. Proxies API calls to hub

```python
# File: remora_frontend/main.py

"""
Remora Frontend - Stario app that proxies to hub.

This is a minimal Stario app that:
1. Serves the SPA on /
2. Proxies /subscribe to hub's SSE (pass-through)
3. Proxies API calls to hub
"""

import asyncio
from dataclasses import dataclass
from pathlib import Path

import aiohttp

from stario import Context, RichTracer, Stario, Writer, at, data
from stario.html import Body, Div, Head, Html, Link, Meta, Script, Title
from stario.http.writer import CompressionConfig


# Configuration - Tailscale hostname of hub
HUB_URL = "http://localhost:8000"


# =============================================================================
# Views (Stario - same as hub views but using Stario HTML helpers)
# =============================================================================

def page(*children):
    """Base HTML shell with Datastar loaded."""
    return Html(
        {"lang": "en"},
        Head(
            Meta({"charset": "UTF-8"}),
            Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            Title("Remora"),
            Link({"rel": "stylesheet", "href": "/static/" + "style.css"}),
            Script({
                "type": "module",
                "src": "/static/" + "datastar.js",
            }),
        ),
        Body(*children),
    )


def home_view() -> Html:
    """
    Home page - initializes Datastar signals and subscribes to hub.
    
    The view structure must match the hub's dashboard_view for Datastar
    to correctly morph DOM elements by ID.
    """
    return page(
        data.signals({
            "selectedAgent": None,
            "events": [],
            "blocked": [],
            "agentStates": {},
            "progress": {"total": 0, "completed": 0},
            "results": [],
        }, ifmissing=True),
        
        # Connect to local /subscribe, which proxies to hub
        data.init(at.get("/subscribe")),

        # Header
        Div({"class": "header"},
            Div({}, "Remora Dashboard"),
            Div({"class": "status connected"}, f"Connected to {HUB_URL}")),

        # Main layout - IDs must match hub's view!
        Div({"class": "main"},
            Div({"id": "events-panel"},
                Div({"id": "events-header"}, "Events Stream"),
                # ID: events-list - updated via SSE
                Div({"id": "events-list"}, "Loading...")),
            
            Div({"id": "main-panel"},
                # ID: blocked-agents - KEY for user interaction!
                Div({"class": "card"},
                    Div({}, "Blocked Agents"),
                    Div({"id": "blocked-agents"}, "No agents waiting")),
                
                # ID: agent-status
                Div({"class": "card"},
                    Div({}, "Agent Status"),
                    Div({"id": "agent-status"}, "No agents running")),
                
                # ID: results
                Div({"class": "card"},
                    Div({}, "Results"),
                    Div({"id": "results"}, "No results yet")),
                
                # ID: execution-progress
                Div({"class": "card"},
                    Div({}, "Graph Execution"),
                    Div({"id": "execution-progress"}, "No execution")))),
    )


# =============================================================================
# Handlers
# =============================================================================

@dataclass
class ExecuteSignals:
    graph_id: str = ""


@dataclass
class RespondSignals:
    agent_id: str = ""
    msg_id: str = ""
    question: str = ""
    answer: str = ""


async def home(c: Context, w: Writer) -> None:
    """Serve the SPA."""
    w.html(home_view())


async def subscribe(c: Context, w: Writer) -> None:
    """
    Proxy SSE from hub to browser.
    
    This is a STREAMING proxy:
    1. Connect to hub's /subscribe
    2. Pass through chunks as they arrive
    3. Datastar on the browser understands these as SSE events
    
    Key: We're not transforming the data, just passing it through.
    The hub already sends correct Datastar-formatted SSE patches.
    """
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{HUB_URL}/subscribe") as resp:
            async for chunk in resp.content.iter_any():
                # Pass through raw - Datastar understands SSE format
                w.write(chunk)


async def execute_graph(c: Context, w: Writer) -> None:
    """Proxy graph execution to hub."""
    signals = await c.signals(ExecuteSignals)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{HUB_URL}/graph/execute",
            json={"graph_id": signals.graph_id}
        ) as resp:
            result = await resp.json()
            w.json(result)


async def respond(c: Context, w: Writer, agent_id: str) -> None:
    """Proxy agent response to hub - user responds to blocked agent."""
    signals = await c.signals(RespondSignals)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{HUB_URL}/agent/{agent_id}/respond",
            json={
                "msg_id": signals.msg_id,
                "question": signals.question,
                "answer": signals.answer,
            }
        ) as resp:
            result = await resp.json()
            w.json(result)


# =============================================================================
# App Setup
# =============================================================================

async def main():
    tracer = RichTracer()

    with tracer:
        app = Stario(tracer, compression=CompressionConfig())

        app.assets("/static", Path(__file__).parent / "static")

        app.get("/", home)
        app.get("/subscribe", subscribe)
        app.post("/graph/execute", execute_graph)
        app.post("/agent/{agent_id}/respond", respond)

        await app.serve(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
```

---

## PHASE 3: Usage

### 3.1 On Server (hub.remora)

```bash
# Start the hub (Python 3.10+)
remora-hub serve --workspace .remora/hub --host 0.0.0.0 --port 8000

# Hub runs and listens on port 8000
# Accessible at hub.remora.local:8000 over Tailscale
```

### 3.2 On Laptop (frontend)

```bash
# Start frontend (Python 3.14+)
python -m remora_frontend

# Frontend runs on port 8000
# Open http://localhost:8000 in browser
```

### 3.3 Execute Graph

```bash
# From laptop, trigger graph execution
curl -X POST http://localhost:8000/graph/execute \
  -H "Content-Type: application/json" \
  -d '{"graph_id": "test-1"}'

# Dashboard updates in real-time via SSE
# Agent gets blocked → appears in "Blocked Agents" section
# User types response → clicks Send → agent resumes
```

---

## Key Implementation Details

### Agent Interaction Flow (Critical!)

1. **Agent writes question to workspace KV:**
   ```python
   await workspace.kv.set(f"outbox:question:{msg_id}", {
       "question": "What should I do?",
       "options": ["option1", "option2"],
       "status": "pending",
       "msg_id": msg_id,
   })
   ```

2. **Coordinator polls and publishes event:**
   ```python
   # WorkspaceInboxCoordinator._list_pending_questions()
   entries = await workspace.kv.list(prefix="outbox:question:")
   # Found! Publish:
   await event_bus.publish(Event.agent_blocked(
       agent_id=agent_id,
       question=q.question,
       options=q.options,
       msg_id=q.msg_id,
   ))
   ```

3. **Frontend displays with response form:**
   ```html
   <div class="blocked-agent">
       <div class="question">What should I do?</div>
       <select data-bind="responseDraft.key">
           <option>option1</option>
           <option>option2</option>
       </select>
       <button data-on-click="@post('/agent/agent-1/respond', {...})">Send</button>
   </div>
   ```

4. **User responds → Coordinator writes response:**
   ```python
   # WorkspaceInboxCoordinator.respond()
   await workspace.kv.set(f"inbox:response:{msg_id}", {
       "answer": "option1",
       "responded_at": datetime.now().isoformat(),
   })
   # Publishes Event.agent_resumed(agent_id, answer, msg_id)
   ```

5. **Agent reads response and resumes:**
   ```python
   # Agent code (in structured-agents)
   response = await workspace.kv.get(f"inbox:response:{msg_id}")
   answer = response["answer"]
   # Continue execution with answer
   ```

---

## Testing Checklist

- [ ] Hub starts on Python 3.10+
- [ ] Frontend starts on Python 3.14+
- [ ] Frontend connects to hub over Tailscale
- [ ] Graph execution triggers events on hub
- [ ] Agent appears in "Agent Status" 
- [ ] Agent gets blocked (simulate with KV write)
- [ ] Blocked agent appears in "Blocked Agents" section
- [ ] User can type response and click Send
- [ ] Response is written to workspace KV
- [ ] Agent resumes after response
- [ ] SSE patches flow from hub to frontend
- [ ] All UI elements update in real-time

---

## References

- [datastar-py GitHub](https://github.com/starfederation/datastar-python)
- [datastar-py PyPI](https://pypi.org/project/datastar-py/)
- [Datastar Official](https://data-star.dev)
- [Stario Documentation](https://stario.dev) - For frontend patterns
