# Implementation Guide: Step 12 - Dashboard Package

## Overview

This step extracts and refactors the web dashboard code from `src/remora/hub/` into a focused `remora/dashboard/` package. This implements **Idea 3** from the design document: splitting the Hub into independent Indexer and Dashboard packages.

## Contract Touchpoints
- Dashboard streams events via `EventBus.stream()` and renders graph + kernel events.
- `/answer` endpoint emits `HumanInputResponseEvent` for `ask_user` requests.

## Done Criteria
- [ ] SSE endpoint streams `RemoraEvent` payloads end-to-end.
- [ ] Human input requests/responses flow through EventBus without polling.
- [ ] Dashboard reads node metadata from `NodeStateStore` only.

## What You're Creating

A focused dashboard package that provides:
- Web UI with real-time SSE updates via datastar-py
- Graph execution trigger endpoints
- Human-in-the-loop integration for blocked agents

## What You're Replacing

From the current codebase, extract these components:
- `src/remora/hub/server.py` - HubServer with Starlette
- `src/remora/hub/views.py` - datastar views  
- `src/remora/hub/state.py` - Dashboard state (will become `dashboard/state.py`)
- `src/remora/frontend/state.py` - Frontend state management
- `src/remora/hub/registry.py` - Workspace registry

**Leave behind** (goes to indexer package):
- `src/remora/hub/daemon.py`
- `src/remora/hub/watcher.py`
- `src/remora/hub/indexer.py`
- `src/remora/hub/store.py`
- `src/remora/hub/models.py`
- `src/remora/hub/rules.py`
- `src/remora/hub/call_graph.py`

## Implementation Steps

### Step 1: Create Package Structure

Create the directory structure:

```
src/remora/dashboard/
  __init__.py
  app.py
  views.py
  state.py
  cli.py
```

### Step 2: Create `__init__.py`

```python
"""Remora Dashboard Package.

Provides the web dashboard for monitoring agent execution and triggering graphs.
"""

from remora.dashboard.app import create_app
from remora.dashboard.state import DashboardState

__all__ = ["create_app", "DashboardState"]
```

### Step 3: Create `state.py`

This is adapted from `hub/state.py` and `frontend/state.py`:

```python
"""Dashboard state management - tracks agent events and UI state."""

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from remora.events import RemoraEvent

MAX_EVENTS = 200


@dataclass
class DashboardState:
    """Runtime state for the dashboard - rebuilt from events via EventBus."""
    
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0

    def record(self, event: RemoraEvent) -> None:
        """Process event and update state."""
        from remora.events import (
            AgentStartEvent,
            AgentCompleteEvent,
            AgentErrorEvent,
            HumanInputRequestEvent,
            HumanInputResponseEvent,
        )
        
        event_dict = {
            "event_type": type(event).__name__,
            "graph_id": getattr(event, "graph_id", ""),
            "agent_id": getattr(event, "agent_id", ""),
            "timestamp": getattr(event, "timestamp", 0),
        }
        self.events.append(event_dict)
        
        if isinstance(event, AgentStartEvent):
            self.agent_states[event.agent_id] = {
                "state": "started",
                "name": event.agent_id,
            }
            self.total_agents += 1
        
        elif isinstance(event, HumanInputRequestEvent):
            key = event.request_id
            self.blocked[key] = {
                "agent_id": event.agent_id,
                "question": event.question,
                "options": getattr(event, "options", []),
                "request_id": event.request_id,
            }
        
        elif isinstance(event, HumanInputResponseEvent):
            self.blocked.pop(event.request_id, None)
        
        elif isinstance(event, (AgentCompleteEvent, AgentErrorEvent)):
            if event.agent_id in self.agent_states:
                state_map = {
                    AgentCompleteEvent: "completed",
                    AgentErrorEvent: "failed",
                }
                self.agent_states[event.agent_id]["state"] = state_map[type(event)]
                if isinstance(event, AgentCompleteEvent):
                    self.completed_agents += 1
        
        if isinstance(event, AgentCompleteEvent):
            self.results.insert(
                0,
                {
                    "agent_id": event.agent_id,
                    "content": str(getattr(event, "result", "")),
                    "timestamp": getattr(event, "timestamp", 0),
                },
            )
            if len(self.results) > 50:
                self.results.pop()


    def get_view_data(self) -> dict[str, Any]:
        """Data needed to render the dashboard view."""
        return {
            "events": list(self.events),
            "blocked": list(self.blocked.values()),
            "agent_states": self.agent_states,
            "progress": {"total": self.total_agents, "completed": self.completed_agents},
            "results": self.results[:10],
        }
```

### Step 4: Create `views.py`

This is adapted from `hub/views.py`. The key changes:
- Use the new event types from `remora.events`
- Remove workspace management (that goes to indexer/executor)
- Keep the datastar-powered UI rendering

```python
"""Dashboard views - Datastar-powered web UI."""

import html
import json

from datastar_py import attribute_generator as data
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse


def render_tag(tag, content="", **attrs):
    """Simple HTML tag renderer."""
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items() if v)
    if content:
        return f"<{tag} {attr_str}>{content}</{tag}>" if attr_str else f"<{tag}>{content}</{tag}>"
    return f"<{tag} {attr_str}/>" if attr_str else f"<{tag}/>"


def page(title="Remora Dashboard", *body_content):
    """Base HTML shell with Datastar loaded."""
    body_attrs = data.init("@get('/subscribe')")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <style>
        body {{ font-family: system-ui, sans-serif; margin: 0; padding: 20px; background: #f5f5f5; }}
        .header {{ background: #333; color: white; padding: 20px; margin: -20px -20px 20px -20px; display: flex; justify-content: space-between; }}
        .card {{ background: white; border-radius: 8px; padding: 16px; margin-bottom: 16px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        .events-list, .blocked-agents, .agent-status, .results {{ max-height: 300px; overflow-y: auto; }}
        .event {{ padding: 8px; border-bottom: 1px solid #eee; font-size: 13px; }}
        .event-time {{ color: #666; margin-right: 8px; }}
        .event-type {{ background: #e0e0e0; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
        .blocked-agent {{ background: #fff3cd; padding: 12px; border-radius: 4px; margin-bottom: 8px; }}
        .agent-id {{ font-weight: bold; color: #856404; }}
        .question {{ margin: 8px 0; }}
        .response-form {{ display: flex; gap: 8px; }}
        .response-form input, .response-form select {{ flex: 1; padding: 8px; border: 1px solid #ddd; border-radius: 4px; }}
        .response-form button {{ padding: 8px 16px; background: #007bff; color: white; border: none; border-radius: 4px; cursor: pointer; }}
        .state-indicator {{ display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; }}
        .state-indicator.started {{ background: #28a745; }}
        .state-indicator.completed {{ background: #17a2b8; }}
        .state-indicator.failed {{ background: #dc3545; }}
        .state-indicator.blocked {{ background: #ffc107; }}
        .empty-state {{ color: #999; text-align: center; padding: 20px; }}
        .progress-bar {{ height: 20px; background: #e0e0e0; border-radius: 10px; overflow: hidden; }}
        .progress-fill {{ height: 100%; background: #28a745; transition: width 0.3s; }}
        .main {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        @media (max-width: 768px) {{ .main {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body {body_attrs}>
    {"".join(body_content)}
</body>
</html>"""


def event_item_view(event: dict) -> str:
    """Single event in the stream."""
    timestamp = event.get("timestamp", 0)
    if timestamp:
        import time
        timestamp = time.strftime("%H:%M:%S", time.localtime(timestamp))
    else:
        timestamp = "--:--:--"
    
    event_type = event.get("event_type", "")
    agent_id = event.get("agent_id", "")

    return render_tag(
        "div",
        content=(
            render_tag("span", content=timestamp, class_="event-time")
            + render_tag("span", content=event_type, class_="event-type")
            + (render_tag("span", content=f"@{agent_id}", class_="event-agent") if agent_id else "")
        ),
        class_="event",
    )


def events_list_view(events: list[dict]) -> str:
    """List of events."""
    if not events:
        return render_tag(
            "div",
            id="events-list",
            class_="events-list",
            content=render_tag("div", content="No events yet", class_="empty-state"),
        )

    events_html = "".join(event_item_view(e) for e in reversed(events[-50:]))
    return render_tag("div", id="events-list", class_="events-list", content=events_html)


def blocked_card_view(blocked: dict) -> str:
    """Blocked agent card - shows question and input for human response."""
    agent_id = blocked.get("agent_id", "")
    question = blocked.get("question", "")
    options = blocked.get("options", [])
    request_id = blocked.get("request_id", "")

    key = f"{agent_id}:{question}".replace(":", "_").replace(" ", "_")

    if options and len(options) > 0:
        options_html = "".join(render_tag("option", content=opt, value=opt) for opt in options)
        input_html = render_tag(
            "select", id=f"answer-{key}", content=options_html, **{"data-bind": f"responseDraft.{key}"}
        )
    else:
        input_html = render_tag(
            "input",
            id=f"answer-{key}",
            type="text",
            placeholder="Your response...",
            autocomplete="off",
            **{"data-bind": f"responseDraft.{key}"},
        )

    button = render_tag(
        "button",
        content="Send",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": f"""
                const draft = $responseDraft?.{key};
                if (draft?.trim()) {{
                    @post('/input', {{request_id: '{request_id}', response: draft}});
                    $responseDraft.{{key}} = '';
                }}
            """,
        },
    )

    form = render_tag("div", id=f"form-{key}", class_="response-form", content=input_html + button)

    return render_tag(
        "div",
        class_="blocked-agent",
        content=(
            render_tag("div", content=f"@{agent_id}", class_="agent-id")
            + render_tag("div", content=question, class_="question")
            + form
        ),
    )


def blocked_list_view(blocked: list[dict]) -> str:
    """List of blocked agents waiting for response."""
    if not blocked:
        return render_tag(
            "div",
            id="blocked-agents",
            class_="blocked-agents",
            content=render_tag("div", content="No agents waiting for input", class_="empty-state"),
        )

    cards = "".join(blocked_card_view(b) for b in blocked)
    return render_tag("div", id="blocked-agents", class_="blocked-agents", content=cards)


def graph_launcher_card_view() -> str:
    """Card that lets users configure and start a graph."""
    defaults = {
        "graphLauncher": {
            "target_path": "",
            "bundle": "lint",
        }
    }
    signals_attr = html.escape(json.dumps(defaults), quote=True)

    target_input = render_tag(
        "input",
        placeholder="Target path (file or directory)",
        type="text",
        **{"data-bind": "graphLauncher.target_path"},
    )
    bundle_input = render_tag(
        "input",
        placeholder="Bundle name (e.g., lint, docstring)",
        type="text",
        **{"data-bind": "graphLauncher.bundle"},
    )

    button = render_tag(
        "button",
        content="Run Graph",
        type="button",
        **{
            "data-on": "click",
            "data-on-click": """
                const target = $graphLauncher?.target_path?.trim();
                const bundle = $graphLauncher?.bundle?.trim() || 'lint';
                if (!target) {
                    alert('Target path is required.');
                    return;
                }
                @post('/run', {target_path: target, bundle: bundle});
            """,
        },
    )

    form = render_tag(
        "div",
        class_="graph-launcher-form",
        content=target_input + bundle_input + button,
    )

    signals_div = render_tag(
        "div",
        **{
            "data-signals__ifmissing": signals_attr,
            "style": "display:none",
        },
    )

    return render_tag(
        "div",
        class_="card graph-launcher-card",
        content=render_tag("div", content="Run Agent Graph") + form + signals_div,
    )


def agent_item_view(agent_id: str, state_info: dict) -> str:
    """Single agent status."""
    state = state_info.get("state", "pending")
    name = state_info.get("name", agent_id)

    return render_tag(
        "div",
        class_="agent-item",
        content=(
            render_tag("span", class_=f"state-indicator {state}")
            + render_tag("span", content=name, class_="agent-name")
            + render_tag("span", content=state, class_="agent-state")
        ),
    )


def agent_status_view(agent_states: dict) -> str:
    """All agent statuses."""
    if not agent_states:
        return render_tag(
            "div",
            id="agent-status",
            class_="agent-status",
            content=render_tag("div", content="No agents running", class_="empty-state"),
        )

    items = "".join(agent_item_view(aid, info) for aid, info in agent_states.items())
    return render_tag("div", id="agent-status", class_="agent-status", content=items)


def result_item_view(result: dict) -> str:
    """Single result."""
    agent_id = result.get("agent_id", "")
    content = result.get("content", "")

    return render_tag(
        "div",
        class_="result-item",
        content=(
            render_tag("div", content=f"@{agent_id}", class_="result-agent")
            + render_tag("div", content=content, class_="result-content")
        ),
    )


def results_view(results: list[dict]) -> str:
    """List of results."""
    if not results:
        return render_tag(
            "div",
            id="results",
            class_="results",
            content=render_tag("div", content="No results yet", class_="empty-state"),
        )

    items = "".join(result_item_view(r) for r in results)
    return render_tag("div", id="results", class_="results", content=items)


def progress_bar_view(total: int, completed: int) -> str:
    """Progress bar."""
    percent = int((completed / total) * 100) if total > 0 else 0

    return render_tag(
        "div",
        id="execution-progress",
        content=(
            render_tag(
                "div",
                class_="progress-bar",
                content=render_tag(
                    "div", id="progress-fill", class_="progress-fill", **{"style": f"width: {percent}%"}
                ),
            )
            + render_tag("div", content=f"{completed}/{total} agents completed", class_="progress-text")
        ),
    )


def dashboard_view(view_data: dict) -> str:
    """Main dashboard view - complete HTML snapshot."""
    events = view_data.get("events", [])
    blocked = view_data.get("blocked", [])
    agent_states = view_data.get("agent_states", {})
    progress = view_data.get("progress", {"total": 0, "completed": 0})
    results = view_data.get("results", [])

    header = render_tag(
        "div",
        class_="header",
        content=render_tag("div", content="Remora Dashboard")
        + render_tag("div", content=f"Agents: {progress['completed']}/{progress['total']}", class_="status"),
    )

    events_panel = render_tag(
        "div",
        id="events-panel",
        content=render_tag("div", id="events-header", content="Events Stream") + events_list_view(events),
    )

    graph_launcher_card = graph_launcher_card_view()

    blocked_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Blocked Agents") + blocked_list_view(blocked)
    )

    status_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Agent Status") + agent_status_view(agent_states)
    )

    results_card = render_tag(
        "div", class_="card", content=render_tag("div", content="Results") + results_view(results)
    )

    progress_card = render_tag(
        "div",
        class_="card",
        content=render_tag("div", content="Graph Execution")
        + progress_bar_view(progress["total"], progress["completed"]),
    )

    main_panel = render_tag(
        "div",
        id="main-panel",
        content=graph_launcher_card + blocked_card + status_card + results_card + progress_card,
    )

    main = render_tag("div", class_="main", content=events_panel + main_panel)

    return page(header + main)


async def index(request: Request) -> HTMLResponse:
    """Main dashboard page."""
    state = request.app.state.dashboard_state
    view_data = state.get_view_data()
    html = dashboard_view(view_data)
    return HTMLResponse(html)
```

### Step 5: Create `app.py`

This is adapted from `hub/server.py`. The key changes:
- Remove workspace management (goes to executor)
- Remove workspace registry (goes to indexer)
- Remove graph building logic (goes to executor)
- Keep: SSE endpoints, run agent trigger, human input submission

```python
"""Starlette application for the dashboard."""

import asyncio
import logging
from typing import Any

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from remora.dashboard.state import DashboardState
from remora.dashboard import views
from remora.event_bus import get_event_bus
from remora.events import HumanInputResponseEvent

logger = logging.getLogger(__name__)


class DashboardApp:
    """Dashboard Starlette application."""
    
    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._event_bus = get_event_bus()
        self._dashboard_state = DashboardState()
        self._running_tasks: dict[str, asyncio.Task] = {}
        
    @property
    def app(self) -> Starlette:
        """Build the Starlette application."""
        return Starlette(
            routes=[
                Route("/", views.index),
                Route("/subscribe", self.subscribe),
                Route("/events", self.events),
                Route("/run", self.run_agent, methods=["POST"]),
                Route("/input", self.submit_input, methods=["POST"]),
            ],
            debug=self.config.get("debug", False),
        )

    async def subscribe(self, request: Request) -> DatastarResponse:
        """SSE endpoint - streams complete view snapshots via Datastar."""
        
        @datastar_response
        async def event_stream():
            view_data = self._dashboard_state.get_view_data()
            yield SSE.patch_elements(views.dashboard_view(view_data))

            async for _ in self._event_bus.stream():
                view_data = self._dashboard_state.get_view_data()
                yield SSE.patch_elements(views.dashboard_view(view_data))

        return await event_stream()

    async def events(self, request: Request) -> StreamingResponse:
        """Raw SSE endpoint - streams events as JSON for API clients."""
        
        async def event_generator():
            try:
                async for event in self._event_bus.stream():
                    event_type = type(event).__name__
                    data = {
                        "event_type": event_type,
                        "graph_id": getattr(event, "graph_id", ""),
                        "agent_id": getattr(event, "agent_id", ""),
                        "timestamp": getattr(event, "timestamp", 0),
                    }
                    yield f"event: {event_type}\ndata: {data}\n\n"
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error in events stream")
                pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    async def run_agent(self, request: Request) -> JSONResponse:
        """Trigger a graph execution."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        
        target_path = body.get("target_path", "")
        bundle = body.get("bundle", "lint")
        
        if not target_path:
            return JSONResponse(
                {"error": "target_path is required"},
                status_code=400,
            )
        
        graph_id = await self._trigger_graph(target_path, bundle)
        
        return JSONResponse({
            "status": "started",
            "graph_id": graph_id,
        })

    async def _trigger_graph(self, target_path: str, bundle: str) -> str:
        """Trigger graph execution via the executor."""
        from remora.executor import GraphExecutor
        from remora.graph import build_graph
        from remora.discovery import discover, CSTNode
        from pathlib import Path
        
        import uuid
        graph_id = uuid.uuid4().hex[:8]
        
        nodes = discover([Path(target_path)])
        agent_nodes = build_graph(nodes, {bundle: Path(f"agents/{bundle}")})
        
        task = asyncio.create_task(self._execute_graph(graph_id, agent_nodes))
        self._running_tasks[graph_id] = task
        
        return graph_id

    async def _execute_graph(self, graph_id: str, agent_nodes: list) -> None:
        """Execute the graph asynchronously."""
        from remora.executor import GraphExecutor, ExecutorConfig
        from remora.event_bus import get_event_bus
        
        try:
            config = ExecutorConfig(
                max_concurrency=4,
                timeout=300.0,
            )
            executor = GraphExecutor(config=config, event_bus=get_event_bus())
            await executor.run(agent_nodes)
        except Exception as e:
            logger.exception("Graph execution failed")
            await get_event_bus().emit(type("GraphFailedEvent", (), {
                "graph_id": graph_id,
                "error": str(e),
            })())

    async def submit_input(self, request: Request) -> JSONResponse:
        """Submit human input for blocked agent."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)
        
        request_id = body.get("request_id", "")
        response = body.get("response", "")
        
        if not request_id or not response:
            return JSONResponse(
                {"error": "request_id and response are required"},
                status_code=400,
            )
        
        event = HumanInputResponseEvent(
            request_id=request_id,
            response=response,
        )
        await self._event_bus.emit(event)
        
        return JSONResponse({"status": "submitted"})


def create_app(config: dict[str, Any] | None = None) -> Starlette:
    """Create the dashboard Starlette application."""
    dashboard_app = DashboardApp(config)
    return dashboard_app.app
```

### Step 6: Create `cli.py`

```python
"""Dashboard CLI entry point."""

import logging
from pathlib import Path

import typer

from remora.config import load_config
from remora.dashboard.app import create_app

app = typer.Typer(help="Remora Dashboard - Web UI for agent execution monitoring")

logger = logging.getLogger(__name__)


@app.command()
def run(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8420, help="Port to bind to"),
    debug: bool = typer.Option(False, help="Enable debug mode"),
    config_path: Path = typer.Option(
        Path("remora.yaml"),
        exists=True,
        file_okay=True,
        dir_okay=False,
        help="Path to remora.yaml config file",
    ),
):
    """Run the dashboard web server."""
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    config = load_config(config_path)
    dashboard_config = getattr(config, "dashboard", {})
    
    import uvicorn
    starlette_app = create_app({**dashboard_config, "debug": debug})
    
    logger.info(f"Starting Remora Dashboard at http://{host}:{port}")
    uvicorn.run(starlette_app, host=host, port=port)


if __name__ == "__main__":
    app()
```

## Dependencies

Ensure these are in `pyproject.toml`:

```toml
[dependencies]
starlette = ">=0.27"
datastar-py = ">=1.0"
uvicorn = ">=0.23"
typer = ">=0.9"
```

## Integration Points

### With EventBus

The dashboard subscribes to the EventBus for:
- Real-time state updates (via `stream()`)
- Human input request events (via `HumanInputResponseEvent`)

### With Executor

The `/run` endpoint triggers the `GraphExecutor` which:
- Discovers nodes from the target path
- Builds the agent graph
- Executes agents in dependency order

### With Config

The dashboard reads from `remora.yaml`:

```yaml
dashboard:
  host: "0.0.0.0"
  port: 8420
  debug: false
```

## What to Preserve

- **SSE for real-time updates** - Both `/subscribe` (Datastar patches) and `/events` (raw JSON)
- **Web UI** - All datastar-powered views for events, blocked agents, status, results
- **Graph execution trigger** - `/run` endpoint that starts graph execution
- **Human-in-the-loop** - `/input` endpoint for submitting responses to blocked agents

## What NOT to Include

- **Workspace management** - That goes to the executor via Cairn
- **Filesystem watching** - That goes to the indexer package
- **Node state store** - That's shared with indexer

## Common Pitfalls

1. **Don't mix indexer code** - Keep dashboard focused on presentation only
2. **Event types must match** - Use the new typed events from `remora.events`, not string-based
3. **Async context** - Remember that EventBus operations are async
4. **State immutability** - DashboardState is rebuilt from events, not persisted

## Verification

Run these commands to verify the implementation:

```bash
# Basic import check
python -c "from remora.dashboard import create_app; print('OK')"

# Check the app can be created
python -c "from remora.dashboard.app import create_app; app = create_app({'debug': True}); print(type(app))"

# Check CLI loads
python -m remora.dashboard.cli --help
```

## Files Summary

| File | Purpose | Adapted From |
|------|---------|--------------|
| `__init__.py` | Package exports | New |
| `app.py` | Starlette app factory | `hub/server.py` |
| `views.py` | Datastar HTML views | `hub/views.py` |
| `state.py` | Dashboard state | `hub/state.py`, `frontend/state.py` |
| `cli.py` | CLI entry point | New (split from `hub/cli.py`) |
