# Implementation Guide: Remora Web UI

> A step-by-step guide for a junior developer to implement the Remora Web UI as a standalone
> Python 3.14 repository that connects to the remora core library over HTTP.

---

## Table of Contents

1. **Purpose & Scope** — What this guide builds and why it is a separate repo
2. **Architecture Overview** — Two processes, two servers, one browser
3. **Prerequisites** — Software, knowledge, running remora server
4. **Part A: Remora Server-Side Changes** — The five additions required in the remora repo
   - 4.1 CORS Middleware
   - 4.2 Adding `companion_registry` to `RemoraService`
   - 4.3 `GET /graph/data` — Nodes + edges for Cytoscape
   - 4.4 `GET /companion/sidebar/{node_id}` — Markdown sidebar
   - 4.5 `POST /companion/chat` — Chat with a node agent
   - 4.6 `GET /companion/workspace/{node_id}` — Workspace file tree
   - 4.7 Starting companion in the web server process
5. **Part B: New Repository Setup** — Python 3.14 package from scratch
   - 5.1 Directory structure
   - 5.2 `pyproject.toml`
   - 5.3 `devenv.nix` (optional but recommended)
6. **Part C: Python Starlette Server** — The minimal host process
   - 6.1 `config.py`
   - 6.2 `app.py`
   - 6.3 Entry point
7. **Part D: Frontend — HTML Shell** — The single-page application scaffold
8. **Part E: Frontend — CSS** — Layout for graph + sidebar split
9. **Part F: Frontend — JavaScript (main.js)** — Full annotated implementation
   - 9.1 Initialisation sequence
   - 9.2 Loading the graph (Mode 2)
   - 9.3 Cytoscape styles
   - 9.4 Live event pings via EventSource
   - 9.5 Opening the sidebar (Mode 1)
   - 9.6 Chat interaction
   - 9.7 Event log
10. **Phase 0: Static Graph Snapshot** — First working milestone
11. **Phase 1: Live Event Pings** — Nodes flash when events fire
12. **Phase 2: Mode 1 Sidebar Panel** — Click a node, see its agent panel
13. **Phase 3: Chat (non-streaming)** — Send a message, receive a reply
14. **Phase 4: Neovim Cursor Sync → Graph Highlight** — Editor selection shown in browser
15. **Phase 5: EventStore Replay Scrubber** — Scrub backwards through history
16. **Running the Full Stack** — Start order, verification steps
17. **Testing Checklist** — Manual smoke-tests for each phase
18. **Common Pitfalls & FAQ** — The things that will go wrong

---

---

## 1. Purpose & Scope

This guide walks you through building **Remora Web UI** — a browser-based companion to the
remora agent swarm. It replaces nothing in the existing Neovim workflow; it runs alongside it.

### What you will build

Two visual modes in a single HTML page:

- **Mode 2 (default) — Graph View**: Full-screen Cytoscape.js graph of every node (function,
  method, class, module) in the repo. Edges represent calls and containment. Nodes flash with
  colour when events fire on them. A live event log sidebar shows a feed of recent swarm
  activity. Clicking a node switches to Mode 1.

- **Mode 1 — Agent Panel**: A tall, narrow panel (drawer) for a single node agent. Shows the
  agent's markdown sidebar (role, schema, notes, chat history summary, links). Includes a chat
  input so you can talk to the agent. A "back to graph" button returns to Mode 2.

### Why a separate repository?

The remora core library requires **Python ≥ 3.13**.  The `stario` library (a future dependency
for advanced UI features) requires **Python 3.14** and cannot be installed in the same
environment. Therefore this webapp is a separate Python package that connects to remora's
HTTP API — it does **not** import remora directly.

### Scope of this guide

- Changes to the remora repo (new HTTP endpoints, CORS, companion wiring) — **Part A**
- The new standalone `remora-ui` repo — **Parts B through F**
- Phase-by-phase build plan from zero to feature-complete — **Sections 10–15**

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────┐
│  Your machine                           │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │ remora (Python 3.13)             │   │
│  │  • LSP server (pygls)            │   │
│  │  • Starlette HTTP :8765          │   │
│  │    GET  /events          (SSE)   │   │
│  │    GET  /graph/data      (JSON)  │   │
│  │    GET  /swarm/agents    (JSON)  │   │
│  │    GET  /companion/sidebar/{id}  │   │
│  │    POST /companion/chat          │   │
│  │    GET  /companion/workspace/{id}│   │
│  │  • EventBus (in-memory)          │   │
│  │  • EventStore (SQLite)           │   │
│  │  • NodeAgentRegistry             │   │
│  └──────────────────────────────────┘   │
│            ▲ HTTP requests              │
│            │                            │
│  ┌──────────────────────────────────┐   │
│  │ remora-ui (Python 3.14)          │   │
│  │  • Starlette HTTP :8766          │   │
│  │    GET  /         → index.html   │   │
│  │    GET  /config.json             │   │
│  │    GET  /static/*                │   │
│  └──────────────────────────────────┘   │
│            ▲ HTTP/SSE (CORS)            │
│            │                            │
│  ┌──────────────────────────────────┐   │
│  │ Browser                          │   │
│  │  • Loads index.html from :8766   │   │
│  │  • Fetches graph data from :8765 │   │
│  │  • EventSource on :8765/events   │   │
│  │  • POSTs chat to :8765           │   │
│  │  • Cytoscape.js (graph canvas)   │   │
│  │  • Datastar (reactive sidebar)   │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### Data flow summary

| Action | Source | Target | Protocol |
|--------|--------|--------|----------|
| Page load | Browser | remora-ui :8766 | HTTP GET |
| Graph snapshot | Browser | remora :8765/graph/data | HTTP GET (CORS) |
| Live events | Browser | remora :8765/events | SSE EventSource (CORS) |
| Open sidebar | Browser | remora :8765/companion/sidebar/{id} | HTTP GET (CORS) |
| Send chat | Browser | remora :8765/companion/chat | HTTP POST (CORS) |
| Cursor sync | Neovim LSP | remora EventBus → :8765/events | SSE push |

The `remora-ui` Python process is deliberately thin: it only serves the static HTML/CSS/JS.
All intelligence lives in the remora process. This means you can iterate on the UI without
touching remora, and vice versa.

---

## 3. Prerequisites

### Software

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.14+ | remora-ui runtime |
| Python | 3.13+ | remora runtime (separate env) |
| `uv` | latest | Package manager |
| `devenv` | latest | Reproducible dev environment (optional) |
| A running remora LSP server | any | Provides nodes, edges, events |
| A modern browser | Chrome/Firefox/Safari | Runs the UI |

### Knowledge assumed

- Basic Python (async functions, Starlette routes, `await`)
- Basic HTML/CSS/JavaScript (DOM manipulation, `fetch`, `EventSource`)
- Familiarity with the remora project structure (read `src/remora/adapters/starlette.py` and
  `src/remora/service/api.py` before starting)

### Verifying remora is running

```bash
curl http://localhost:8765/swarm/agents
# Should return a JSON array of agent objects
curl -N http://localhost:8765/events
# Should stream SSE frames (Ctrl-C to stop)
```

If these commands fail, start remora first:
```bash
# In the remora repo
devenv shell -- python -m remora.lsp.server  # or however you start it
```

---

## 4. Part A: Remora Server-Side Changes

You need to make **five changes** to the remora repo before building the standalone UI.
All changes are in two files: `src/remora/adapters/starlette.py` and `src/remora/service/api.py`.

> **Important**: These changes are additive. No existing routes or behaviour are modified.

### 4.1 CORS Middleware

The browser loads the page from `http://localhost:8766` (remora-ui) but makes API calls to
`http://localhost:8765` (remora). Without CORS headers, browsers block these cross-origin requests.

Edit `src/remora/adapters/starlette.py`. At the top, add the import:

```python
from starlette.middleware.cors import CORSMiddleware
```

At the bottom of `create_app()`, before the `return` statement, add:

```python
    app = Starlette(routes=routes)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:8766", "http://127.0.0.1:8766"],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )
    return app
```

> **Note**: In production, restrict `allow_origins` to the exact origin of remora-ui.
> Using `["*"]` also works during development but is less precise.

The current `return Starlette(routes=routes)` line becomes the `app = Starlette(...)` line
shown above. The full diff for the bottom of `create_app()` is:

```diff
-    return Starlette(routes=routes)
+    app = Starlette(routes=routes)
+    app.add_middleware(
+        CORSMiddleware,
+        allow_origins=["http://localhost:8766", "http://127.0.0.1:8766"],
+        allow_methods=["GET", "POST", "OPTIONS"],
+        allow_headers=["*"],
+    )
+    return app
```

### 4.2 Adding `companion_registry` to `RemoraService`

The `NodeAgentRegistry` (which manages per-node LLM agents) is currently only wired in the
LSP server. To serve companion endpoints from the HTTP server, `RemoraService` must hold a
reference to the registry.

Edit `src/remora/service/api.py`.

**Step 1**: Add `NodeAgentRegistry` to the `__init__` signature (use TYPE_CHECKING to avoid
circular imports):

```python
# At the top of the file, update TYPE_CHECKING imports:
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from remora.companion.registry import NodeAgentRegistry
    from remora.core.events.subscriptions import SubscriptionRegistry
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
```

**Step 2**: Add the parameter to `__init__`:

```python
def __init__(
    self,
    *,
    config: Config,
    project_root: Path,
    event_bus: EventBus,
    event_store: EventStore | None = None,
    projector: UiStateProjector | None = None,
    subscriptions: "SubscriptionRegistry | None" = None,
    workspace_service: "CairnWorkspaceService | None" = None,
    companion_registry: "NodeAgentRegistry | None" = None,   # ADD THIS
) -> None:
    # ... existing body ...
    self._companion_registry = companion_registry             # ADD THIS
```

**Step 3**: Expose it as a property:

```python
@property
def companion_registry(self) -> "NodeAgentRegistry | None":
    return self._companion_registry

def set_companion_registry(self, registry: "NodeAgentRegistry") -> None:
    """Wire in the companion registry after construction (used by LSP server)."""
    self._companion_registry = registry
```

The `set_companion_registry` method is how the LSP server (which creates the registry first)
wires it into the service. The `create_default()` class method does NOT create the registry
automatically — companion startup is expensive (it starts background indexing) and should be
opt-in.

### 4.3 `GET /graph/data`

This endpoint returns all nodes and edges in Cytoscape.js element format.

Nodes come from `EventStore.nodes.list_nodes()` (accessed via `service.list_agents()`).
Edges are derived from two sources on each `AgentNode`:
- `callee_ids` → "calls" directed edges (node calls callee)
- `parent_id` → "parent_of" containment edges (parent contains node)

Add this handler inside `create_app()` in `src/remora/adapters/starlette.py`, before the
`routes = [...]` list:

```python
    async def graph_data(_request: Request) -> JSONResponse:
        if not service.has_event_store:
            return _error("event store not configured", status_code=400)
        agents = await service.list_agents()

        cy_nodes = []
        cy_edges = []
        seen_edges: set[tuple[str, str, str]] = set()

        for agent in agents:
            node_id: str = agent["node_id"]
            parent_id: str | None = agent.get("parent_id")

            cy_nodes.append({
                "data": {
                    "id": node_id,
                    "label": agent.get("name", node_id),
                    "type": agent.get("node_type", "function"),
                    "status": agent.get("status", "idle"),
                    "file_path": agent.get("file_path", ""),
                    "full_name": agent.get("full_name", ""),
                    # "parent" enables Cytoscape compound node grouping
                    **({"parent": parent_id} if parent_id else {}),
                }
            })

            # Directed "calls" edges
            for callee_id in (agent.get("callee_ids") or []):
                key = (node_id, callee_id, "calls")
                if key not in seen_edges:
                    seen_edges.add(key)
                    cy_edges.append({
                        "data": {
                            "id": f"{node_id}--calls--{callee_id}",
                            "source": node_id,
                            "target": callee_id,
                            "type": "calls",
                        }
                    })

        return JSONResponse({"nodes": cy_nodes, "edges": cy_edges})
```

Then add to the routes list:

```python
    routes = [
        # ... existing routes ...
        Route("/graph/data", graph_data),
    ]
```

**Why not include `parent_of` edges separately?**  Cytoscape compound nodes use the `parent`
field on a node's `data` object — not a separate edge — to represent containment. Setting
`parent: parent_id` on child nodes is the correct approach.

### 4.4 `GET /companion/sidebar/{node_id}`

Returns the markdown sidebar for a node agent (composed from the agent's Cairn workspace).

Add the import at the top of `starlette.py`:

```python
from remora.companion.sidebar.composer import compose_sidebar
```

Add the handler inside `create_app()`:

```python
    async def companion_sidebar(request: Request) -> JSONResponse:
        registry = service.companion_registry
        if registry is None:
            return _error("companion not configured — start companion first", status_code=503)
        if service._event_store is None:
            return _error("event store not configured", status_code=400)

        node_id = request.path_params["node_id"]
        node = await service._event_store.nodes.get_node(node_id)
        if node is None:
            return _error(f"node {node_id!r} not found", status_code=404)

        ws_service = service.get_workspace_service()
        if ws_service is None:
            return _error("workspace service not configured", status_code=503)

        workspace = await ws_service.get_agent_workspace(node_id)
        markdown = await compose_sidebar(node, workspace)
        return JSONResponse({"node_id": node_id, "markdown": markdown})
```

Add to routes:

```python
        Route("/companion/sidebar/{node_id}", companion_sidebar),
```

### 4.5 `POST /companion/chat`

Sends a message to a node agent and returns the full response (non-streaming for Phase 3;
streaming is added in Phase 3 as an SSE upgrade).

Add the handler inside `create_app()`:

```python
    async def companion_chat(request: Request) -> JSONResponse:
        registry = service.companion_registry
        if registry is None:
            return _error("companion not configured", status_code=503)
        if service._event_store is None:
            return _error("event store not configured", status_code=400)

        try:
            body = await request.json()
        except Exception:
            return _error("invalid JSON body", status_code=400)

        node_id = str(body.get("node_id", "")).strip()
        message = str(body.get("message", "")).strip()
        if not node_id or not message:
            return _error("node_id and message are required", status_code=400)

        node = await service._event_store.nodes.get_node(node_id)
        if node is None:
            return _error(f"node {node_id!r} not found", status_code=404)

        agent = await registry.get_or_create(node)
        response = await agent.send(message)

        # NodeAgentResponse has a .text attribute
        reply_text = getattr(response, "text", str(response))
        return JSONResponse({"node_id": node_id, "reply": reply_text})
```

Add to routes:

```python
        Route("/companion/chat", companion_chat, methods=["POST"]),
```

### 4.6 `GET /companion/workspace/{node_id}`

Returns a JSON summary of the workspace files for a node agent. Useful for the file tree
display in Mode 1.

```python
    async def companion_workspace(request: Request) -> JSONResponse:
        ws_service = service.get_workspace_service()
        if ws_service is None:
            return _error("workspace service not configured", status_code=503)
        if service._event_store is None:
            return _error("event store not configured", status_code=400)

        node_id = request.path_params["node_id"]
        node = await service._event_store.nodes.get_node(node_id)
        if node is None:
            return _error(f"node {node_id!r} not found", status_code=404)

        workspace = await ws_service.get_agent_workspace(node_id)

        # List the keys/paths that exist in the workspace
        # Cairn workspace supports .list_keys() to enumerate stored files
        try:
            keys = await workspace.list_keys()
        except Exception:
            keys = []

        return JSONResponse({"node_id": node_id, "files": list(keys)})
```

Add to routes:

```python
        Route("/companion/workspace/{node_id}", companion_workspace),
```

> **Note**: `workspace.list_keys()` is the Cairn API for listing stored items. If you get
> an `AttributeError`, check the Cairn library docs for the equivalent method on `Workspace`.

### 4.7 Starting companion in the web server process

The companion registry needs to be started before any companion endpoints are called.
The existing `create_app()` function accepts a `RemoraService` — you can pass a service
that already has the registry wired.

The recommended pattern for starting the server with companion enabled:

```python
# In your server startup script (e.g. scripts/start_webserver.py):
import asyncio
from pathlib import Path
from remora.core.config import load_config
from remora.core.events.event_bus import EventBus
from remora.service.api import RemoraService
from remora.service.handlers import build_default_runtime
from remora.companion.startup import start_companion
from remora.companion.config import CompanionConfig
from remora.adapters.starlette import create_app
import uvicorn


async def main():
    config = load_config()
    project_root = Path.cwd()
    event_bus = EventBus()

    event_store, subscriptions, workspace_service = build_default_runtime(
        config=config,
        project_root=project_root,
        event_bus=event_bus,
    )

    # Start companion (wires NodeAgentRegistry + NodeAgentRouter)
    companion_config = CompanionConfig(
        workspace_path=project_root,
        # Model settings read from CompanionConfig defaults or environment
    )
    registry = await start_companion(
        event_store=event_store,
        event_bus=event_bus,
        cairn_service=workspace_service,
        config=companion_config,
    )

    service = RemoraService(
        config=config,
        project_root=project_root,
        event_bus=event_bus,
        event_store=event_store,
        subscriptions=subscriptions,
        workspace_service=workspace_service,
        companion_registry=registry,
    )

    app = create_app(service)
    config_obj = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="info")
    server = uvicorn.Server(config_obj)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
```

For Phase 0 and 1, companion is not needed. You can run `create_app()` with a default
service and the graph data + events will work. Add companion wiring when you reach Phase 2.

---

## 5. Part B: New Repository Setup

### 5.1 Directory Structure

```
remora-ui/
├── pyproject.toml
├── devenv.nix                   # optional but recommended
├── src/
│   └── remora_ui/
│       ├── __init__.py          # package version
│       ├── config.py            # RemoraUIConfig (base_url, port, host)
│       ├── app.py               # Starlette app factory + CLI entry point
│       └── static/
│           ├── index.html       # Single-page application
│           ├── style.css        # Layout styles
│           └── main.js          # All JavaScript
├── tests/
│   └── test_app.py
└── README.md
```

Create the directory tree:

```bash
mkdir -p remora-ui/src/remora_ui/static
mkdir -p remora-ui/tests
touch remora-ui/src/remora_ui/__init__.py
touch remora-ui/src/remora_ui/config.py
touch remora-ui/src/remora_ui/app.py
touch remora-ui/src/remora_ui/static/index.html
touch remora-ui/src/remora_ui/static/style.css
touch remora-ui/src/remora_ui/static/main.js
```

### 5.2 `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "remora-ui"
version = "0.1.0"
description = "Browser-based web UI for the Remora agent swarm"
requires-python = ">=3.14"
dependencies = [
    "starlette>=0.40",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",          # health-check and optional proxy requests
]

[project.scripts]
remora-ui = "remora_ui.app:main"

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",           # for TestClient
]

[tool.hatch.build.targets.wheel]
packages = ["src/remora_ui"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### 5.3 `devenv.nix` (optional)

```nix
{ pkgs, ... }:
{
  languages.python = {
    enable = true;
    version = "3.14";
    uv = {
      enable = true;
      sync.enable = true;
      sync.allExtras = true;
    };
  };
}
```

After creating this file, run `devenv shell` once to build the environment, then use
`devenv shell -- <command>` for all project commands.

---

## 6. Part C: Python Starlette Server

### 6.1 `config.py`

```python
# src/remora_ui/config.py
"""Configuration for remora-ui."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RemoraUIConfig:
    """Runtime configuration for the remora-ui server."""

    # URL of the running remora HTTP server
    remora_base_url: str = "http://localhost:8765"

    # Host and port for the remora-ui server itself
    host: str = "127.0.0.1"
    port: int = 8766

    @classmethod
    def from_env(cls) -> "RemoraUIConfig":
        """Load config from environment variables (all optional)."""
        import os
        return cls(
            remora_base_url=os.environ.get("REMORA_URL", "http://localhost:8765"),
            host=os.environ.get("REMORA_UI_HOST", "127.0.0.1"),
            port=int(os.environ.get("REMORA_UI_PORT", "8766")),
        )
```

### 6.2 `app.py`

```python
# src/remora_ui/app.py
"""Remora Web UI — standalone Starlette server."""
from __future__ import annotations

from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from remora_ui.config import RemoraUIConfig

STATIC_DIR = Path(__file__).parent / "static"


def create_app(config: RemoraUIConfig | None = None) -> Starlette:
    """Build and return the Starlette application."""
    cfg = config or RemoraUIConfig()

    async def index(_request) -> HTMLResponse:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        # Inject the remora base URL at serve time so the JS can use it
        html = html.replace("__REMORA_BASE_URL__", cfg.remora_base_url)
        return HTMLResponse(html)

    async def api_config(_request) -> JSONResponse:
        """Let the browser confirm which remora server to talk to."""
        return JSONResponse({"remora_base_url": cfg.remora_base_url})

    routes = [
        Route("/", index),
        Route("/config.json", api_config),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
    ]

    return Starlette(routes=routes)


def main() -> None:
    """CLI entry point: `remora-ui`."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Remora Web UI server")
    parser.add_argument(
        "--remora-url",
        default=None,
        help="Base URL of the remora HTTP server (default: from env or http://localhost:8765)",
    )
    parser.add_argument("--host", default=None, help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="Bind port (default: 8766)")
    args = parser.parse_args()

    cfg = RemoraUIConfig.from_env()
    if args.remora_url:
        cfg.remora_base_url = args.remora_url
    if args.host:
        cfg.host = args.host
    if args.port:
        cfg.port = args.port

    app = create_app(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
```

### 6.3 `__init__.py`

```python
# src/remora_ui/__init__.py
"""Remora Web UI."""
__version__ = "0.1.0"
```

---

## 7. Part D: Frontend — HTML Shell

`src/remora_ui/static/index.html`

The `__REMORA_BASE_URL__` placeholder is replaced at serve time by `app.py`.

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Remora — Swarm View</title>

  <!-- Datastar — reactive signals and HTML patching -->
  <script type="module" src="https://cdn.jsdelivr.net/npm/@sudodevnull/datastar@1.0.0-RC.7/dist/datastar.min.js"></script>

  <!-- Cytoscape.js — graph canvas -->
  <script src="https://cdn.jsdelivr.net/npm/cytoscape@3.30.2/dist/cytoscape.min.js"></script>

  <!-- cose-bilkent layout — best for code graphs -->
  <script src="https://cdn.jsdelivr.net/npm/cytoscape-cose-bilkent@4.1.0/cytoscape-cose-bilkent.js"></script>

  <!-- marked.js — render markdown from companion API -->
  <script src="https://cdn.jsdelivr.net/npm/marked@13.0.3/marked.min.js"></script>

  <link rel="stylesheet" href="/static/style.css">
</head>

<body
  data-signals='{
    "selectedNodeId": "",
    "sidebarOpen": false,
    "chatMessage": "",
    "sidebarLoading": false,
    "chatLoading": false
  }'
>
  <!-- Graph canvas (Cytoscape manages this element directly) -->
  <div id="cy"></div>

  <!-- Event log panel (bottom-right overlay) -->
  <div id="event-log">
    <div class="event-log-header">Live Events</div>
    <ul id="event-list"></ul>
  </div>

  <!-- Sidebar (Mode 1) — slide in from the right -->
  <aside id="sidebar" data-show="$sidebarOpen" class="sidebar">
    <div class="sidebar-header">
      <span id="sidebar-node-label">—</span>
      <button id="sidebar-close" title="Back to graph">✕</button>
    </div>

    <!-- Markdown content from /companion/sidebar/{id} -->
    <div id="sidebar-content" data-show="!$sidebarLoading">
      <!-- innerHTML set by JS after fetch -->
    </div>
    <div data-show="$sidebarLoading" class="loading">Loading…</div>

    <!-- Chat area -->
    <div id="chat-area">
      <div id="chat-history"></div>

      <form id="chat-form">
        <input
          id="chat-input"
          type="text"
          data-bind="chatMessage"
          placeholder="Ask the agent…"
          autocomplete="off"
        >
        <button type="submit" data-show="!$chatLoading">Send</button>
        <span data-show="$chatLoading" class="loading">Thinking…</span>
      </form>
    </div>
  </aside>

  <!-- Inject remora base URL for JavaScript -->
  <script>
    window.REMORA_BASE_URL = "__REMORA_BASE_URL__";
  </script>
  <script src="/static/main.js"></script>
</body>
</html>
```

---

## 8. Part E: Frontend — CSS

`src/remora_ui/static/style.css`

```css
/* ── Reset & Base ───────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body {
  height: 100%;
  background: #0f1117;
  color: #e0e0e0;
  font-family: system-ui, -apple-system, sans-serif;
  font-size: 13px;
  overflow: hidden;
}

/* ── Graph canvas fills the viewport ───────────────────── */
#cy {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
}

/* ── Event log — bottom-right overlay ──────────────────── */
#event-log {
  position: fixed;
  bottom: 12px;
  right: 12px;
  width: 300px;
  max-height: 240px;
  background: rgba(15, 17, 23, 0.88);
  border: 1px solid #2a2d3a;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  z-index: 100;
}

.event-log-header {
  padding: 6px 10px;
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #7a8094;
  border-bottom: 1px solid #2a2d3a;
  flex-shrink: 0;
}

#event-list {
  overflow-y: auto;
  flex: 1;
  list-style: none;
  padding: 4px 0;
}

#event-list li {
  padding: 4px 10px;
  font-size: 11px;
  border-bottom: 1px solid #1a1c26;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #9ca3af;
}

#event-list li:last-child { border-bottom: none; }

/* Event type colour coding */
#event-list li.ev-AgentStartEvent    { color: #34d399; }
#event-list li.ev-AgentCompleteEvent { color: #60a5fa; }
#event-list li.ev-AgentErrorEvent    { color: #f87171; }
#event-list li.ev-NodeDiscoveredEvent { color: #a78bfa; }

/* ── Sidebar — slides in from the right ────────────────── */
.sidebar {
  position: fixed;
  top: 0;
  right: 0;
  width: 380px;
  height: 100vh;
  background: #151820;
  border-left: 1px solid #2a2d3a;
  display: flex;
  flex-direction: column;
  z-index: 200;
  transform: translateX(100%);
  transition: transform 0.2s ease;
}

/* Datastar toggles [data-show] via display:none; we also need transform */
.sidebar:not([style*="display: none"]) {
  transform: translateX(0);
}

.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid #2a2d3a;
  flex-shrink: 0;
}

.sidebar-header span {
  font-weight: 600;
  font-size: 13px;
  color: #c9d1e3;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

#sidebar-close {
  background: none;
  border: none;
  color: #7a8094;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 2px 6px;
}

#sidebar-close:hover { color: #e0e0e0; }

/* Markdown content area */
#sidebar-content {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  line-height: 1.6;
}

#sidebar-content h1, #sidebar-content h2, #sidebar-content h3 {
  color: #c9d1e3;
  margin: 12px 0 6px;
}

#sidebar-content code {
  background: #1e2130;
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 11px;
  font-family: "JetBrains Mono", monospace;
}

#sidebar-content pre {
  background: #1e2130;
  padding: 10px;
  border-radius: 4px;
  overflow-x: auto;
  margin: 8px 0;
}

#sidebar-content pre code { background: none; padding: 0; }

/* Chat area */
#chat-area {
  border-top: 1px solid #2a2d3a;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  max-height: 280px;
}

#chat-history {
  flex: 1;
  overflow-y: auto;
  padding: 8px 14px;
}

.chat-msg {
  margin-bottom: 10px;
  line-height: 1.5;
}

.chat-msg.user { color: #a5f3fc; }
.chat-msg.agent { color: #e0e0e0; }
.chat-msg .role {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: #7a8094;
  margin-bottom: 2px;
}

#chat-form {
  display: flex;
  gap: 6px;
  padding: 8px 14px;
  border-top: 1px solid #2a2d3a;
}

#chat-input {
  flex: 1;
  background: #1e2130;
  border: 1px solid #2a2d3a;
  border-radius: 4px;
  color: #e0e0e0;
  padding: 6px 10px;
  font-size: 12px;
}

#chat-input:focus { outline: none; border-color: #4a9eff; }

#chat-form button {
  background: #2563eb;
  border: none;
  border-radius: 4px;
  color: #fff;
  cursor: pointer;
  padding: 6px 14px;
  font-size: 12px;
}

#chat-form button:hover { background: #1d4ed8; }

/* ── Utilities ──────────────────────────────────────────── */
.loading { color: #7a8094; font-style: italic; padding: 8px 14px; }

[data-show="false"], [data-show="0"] { display: none !important; }
```

---

## 9. Part F: Frontend — JavaScript

`src/remora_ui/static/main.js`

This is the complete, fully-annotated JavaScript implementation. Read through it before
starting Phase 0 — understanding the full picture first prevents confusion.

```javascript
// ═══════════════════════════════════════════════════════════
// main.js — Remora Web UI
//
// Responsibilities:
//   • Load graph from remora /graph/data and render in Cytoscape
//   • Subscribe to /events SSE and flash graph nodes on events
//   • Add events to the live event log
//   • Open Mode 1 sidebar when a node is clicked
//   • Send chat messages to /companion/chat
//   • Datastar handles signal state ($sidebarOpen, etc.)
// ═══════════════════════════════════════════════════════════

"use strict";

// ── Configuration ────────────────────────────────────────────────────────────
// window.REMORA_BASE_URL is injected by the server into index.html
const REMORA = window.REMORA_BASE_URL || "http://localhost:8765";

// Maximum events shown in the event log
const MAX_LOG_EVENTS = 50;

// How long (ms) a flash class stays on a node
const FLASH_DURATION = 900;

// ── State ─────────────────────────────────────────────────────────────────────
let cy = null;             // Cytoscape instance
let eventSource = null;    // SSE EventSource

// ── Entry Point ───────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  initCytoscape();
  attachSidebarClose();
  attachChatForm();
  await loadGraph();
  startEventStream();
});

// ═══════════════════════════════════════════════════════════
// Section 9.1 — Cytoscape Initialisation (Mode 2)
// ═══════════════════════════════════════════════════════════

function initCytoscape() {
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: [],           // populated by loadGraph()
    style: getCyStyles(),
    layout: { name: "preset" },   // overridden after data loads
    userZoomingEnabled: true,
    userPanningEnabled: true,
    boxSelectionEnabled: false,
    minZoom: 0.1,
    maxZoom: 5,
  });

  // ── Click a node → open its sidebar (Mode 1) ──────────────────────────────
  cy.on("tap", "node", (event) => {
    const node = event.target;
    // Ignore compound container nodes (file/class wrappers)
    if (node.isParent()) return;
    openSidebar(node.id(), node.data("label"));
  });

  // ── Double-click background → fit the graph ───────────────────────────────
  cy.on("dblclick", (event) => {
    if (event.target === cy) {
      cy.fit(undefined, 40);
    }
  });
}

// ═══════════════════════════════════════════════════════════
// Section 9.2 — Loading the Graph
// ═══════════════════════════════════════════════════════════

async function loadGraph() {
  let data;
  try {
    const resp = await fetch(`${REMORA}/graph/data`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    data = await resp.json();
  } catch (err) {
    console.error("Failed to load graph data:", err);
    addEventToLog({ type: "ERROR", summary: `Graph load failed: ${err.message}` });
    return;
  }

  if (!data.nodes?.length) {
    console.warn("No nodes returned from /graph/data — is remora running?");
    return;
  }

  // Add nodes first, then edges (Cytoscape requirement for compound nodes)
  cy.add(data.nodes);
  cy.add(data.edges);

  // Remove any edges that reference nodes that don't exist in the graph
  // (can happen if callee_ids reference undiscovered nodes)
  cy.edges().forEach((edge) => {
    if (!cy.getElementById(edge.data("source")).length ||
        !cy.getElementById(edge.data("target")).length) {
      cy.remove(edge);
    }
  });

  // Run layout after data is loaded
  runLayout();
}

function runLayout() {
  // cose-bilkent is the best general-purpose layout for code graphs.
  // It handles compound nodes and directed edges well.
  const layout = cy.layout({
    name: "cose-bilkent",
    animate: false,
    randomize: true,
    idealEdgeLength: 80,
    nodeRepulsion: 8000,
    gravity: 0.5,
    padding: 30,
  });
  layout.run();
}

// ═══════════════════════════════════════════════════════════
// Section 9.3 — Cytoscape Styles
// ═══════════════════════════════════════════════════════════

function getCyStyles() {
  return [
    // ── Default node ────────────────────────────────────────
    {
      selector: "node",
      style: {
        "background-color": "#2563eb",
        "label": "data(label)",
        "font-size": "9px",
        "text-valign": "bottom",
        "text-halign": "center",
        "color": "#c9d1e3",
        "text-outline-color": "#0f1117",
        "text-outline-width": "2px",
        "width": 22,
        "height": 22,
        "border-width": 0,
      },
    },
    // ── Node type variants ───────────────────────────────────
    {
      selector: "node[type = 'module']",
      style: {
        "background-color": "#1e3a5f",
        "shape": "rectangle",
        "width": 30,
        "height": 30,
        "font-size": "10px",
        "font-weight": "bold",
      },
    },
    {
      selector: "node[type = 'class']",
      style: {
        "background-color": "#4c1d95",
        "shape": "round-rectangle",
        "width": 26,
        "height": 26,
      },
    },
    {
      selector: "node[type = 'method']",
      style: {
        "background-color": "#1a3a4a",
        "width": 18,
        "height": 18,
      },
    },
    // ── Status-based colours ─────────────────────────────────
    {
      selector: "node[status = 'running']",
      style: { "background-color": "#d97706", "border-width": 2, "border-color": "#fbbf24" },
    },
    {
      selector: "node[status = 'error']",
      style: { "background-color": "#b91c1c", "border-width": 2, "border-color": "#ef4444" },
    },
    {
      selector: "node[status = 'pending_approval']",
      style: { "background-color": "#7c3aed", "border-width": 2, "border-color": "#a78bfa" },
    },
    // ── Compound (parent) nodes: file/class containers ───────
    {
      selector: ":parent",
      style: {
        "background-color": "#151820",
        "background-opacity": 0.6,
        "border-color": "#2a2d3a",
        "border-width": 1,
        "font-size": "10px",
        "text-valign": "top",
        "padding": "10px",
      },
    },
    // ── Edges ────────────────────────────────────────────────
    {
      selector: "edge",
      style: {
        "width": 1,
        "line-color": "#374151",
        "target-arrow-color": "#374151",
        "target-arrow-shape": "triangle",
        "curve-style": "bezier",
        "arrow-scale": 0.7,
        "opacity": 0.6,
      },
    },
    // ── Hover / selected ─────────────────────────────────────
    {
      selector: "node:selected",
      style: { "border-width": 2, "border-color": "#60a5fa" },
    },
    // ── Flash classes (added/removed by flashClass()) ────────
    // One class per event type — add more as needed
    { selector: ".flash-AgentStartEvent",     style: { "background-color": "#34d399" } },
    { selector: ".flash-AgentCompleteEvent",  style: { "background-color": "#60a5fa" } },
    { selector: ".flash-AgentErrorEvent",     style: { "background-color": "#f87171" } },
    { selector: ".flash-NodeDiscoveredEvent", style: { "background-color": "#a78bfa" } },
    { selector: ".flash-HumanChatEvent",      style: { "background-color": "#fbbf24" } },
    { selector: ".flash-ContentChangedEvent", style: { "background-color": "#34d399" } },
  ];
}

// ═══════════════════════════════════════════════════════════
// Section 9.4 — Live Event Pings via EventSource
// ═══════════════════════════════════════════════════════════

function startEventStream() {
  if (eventSource) {
    eventSource.close();
  }

  eventSource = new EventSource(`${REMORA}/events`);

  // The remora events stream sends named events (e.g. "AgentStartEvent")
  // AND generic "message" events. We handle both.
  eventSource.onmessage = (event) => {
    handleRawEvent(event.data);
  };

  // Named event handler — remora sends event type as SSE "event:" field
  // Register a catch-all by listening to the open connection
  eventSource.addEventListener("open", () => {
    console.log("SSE connected to", `${REMORA}/events`);
  });

  eventSource.onerror = () => {
    console.warn("SSE disconnected, reconnecting in 3s…");
    eventSource.close();
    setTimeout(startEventStream, 3000);
  };

  // Also listen for named events that remora sends
  // (remora uses "event: <TypeName>" in SSE frames)
  const knownTypes = [
    "AgentStartEvent", "AgentCompleteEvent", "AgentErrorEvent",
    "NodeDiscoveredEvent", "NodeRemovedEvent",
    "HumanChatEvent", "ContentChangedEvent", "FileSavedEvent",
    "CursorFocusEvent", "AgentMessageEvent",
  ];
  for (const evType of knownTypes) {
    eventSource.addEventListener(evType, (event) => {
      handleRawEvent(event.data, evType);
    });
  }
}

function handleRawEvent(rawData, explicitType) {
  let data;
  try {
    data = JSON.parse(rawData);
  } catch {
    return; // ignore malformed frames (e.g. SSE keep-alive comments)
  }

  const eventType = explicitType || data.type || data.kind || "event";
  const agentId   = data.agent_id || data.payload?.agent_id;

  // ── Flash the corresponding Cytoscape node ────────────────
  if (agentId && cy) {
    const cyNode = cy.getElementById(agentId);
    if (cyNode.length) {
      cyNode.flashClass(`flash-${eventType}`, FLASH_DURATION);
    }
  }

  // ── Update node status in graph if provided ───────────────
  if (agentId && data.payload?.status && cy) {
    const cyNode = cy.getElementById(agentId);
    if (cyNode.length) {
      cyNode.data("status", data.payload.status);
    }
  }

  // ── Add to event log ──────────────────────────────────────
  addEventToLog({
    type: eventType,
    agent_id: agentId,
    summary: data.summary || data.payload?.name || "",
    timestamp: data.timestamp,
  });
}

// ═══════════════════════════════════════════════════════════
// Section 9.5 — Sidebar (Mode 1)
// ═══════════════════════════════════════════════════════════

async function openSidebar(nodeId, nodeLabel) {
  // Update Datastar signals (works with data-signals on <body>)
  setSignal("selectedNodeId", nodeId);
  setSignal("sidebarOpen", true);
  setSignal("sidebarLoading", true);

  // Update header label
  const labelEl = document.getElementById("sidebar-node-label");
  if (labelEl) labelEl.textContent = nodeLabel || nodeId;

  // Clear previous content
  const contentEl = document.getElementById("sidebar-content");
  if (contentEl) contentEl.innerHTML = "";

  // Clear chat history
  const historyEl = document.getElementById("chat-history");
  if (historyEl) historyEl.innerHTML = "";

  try {
    const resp = await fetch(`${REMORA}/companion/sidebar/${encodeURIComponent(nodeId)}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();

    // Render markdown using marked.js
    if (contentEl) {
      contentEl.innerHTML = marked.parse(data.markdown || "_No content yet._");
    }
  } catch (err) {
    if (contentEl) {
      contentEl.innerHTML = `<p class="error">Failed to load sidebar: ${err.message}</p>`;
    }
  } finally {
    setSignal("sidebarLoading", false);
  }
}

function attachSidebarClose() {
  const closeBtn = document.getElementById("sidebar-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      setSignal("sidebarOpen", false);
      setSignal("selectedNodeId", "");
    });
  }
}

// ═══════════════════════════════════════════════════════════
// Section 9.6 — Chat
// ═══════════════════════════════════════════════════════════

function attachChatForm() {
  const form = document.getElementById("chat-form");
  if (!form) return;

  form.addEventListener("submit", async (event) => {
    event.preventDefault();

    const input    = document.getElementById("chat-input");
    const message  = (input?.value || "").trim();
    const nodeId   = getSignal("selectedNodeId");

    if (!message || !nodeId) return;

    // Clear input
    if (input) input.value = "";
    setSignal("chatMessage", "");

    // Add user message to history
    appendChatMessage("user", message);
    setSignal("chatLoading", true);

    try {
      const resp = await fetch(`${REMORA}/companion/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_id: nodeId, message }),
      });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      appendChatMessage("agent", data.reply || "(no reply)");
    } catch (err) {
      appendChatMessage("agent", `Error: ${err.message}`);
    } finally {
      setSignal("chatLoading", false);
    }
  });
}

function appendChatMessage(role, text) {
  const history = document.getElementById("chat-history");
  if (!history) return;

  const div = document.createElement("div");
  div.className = `chat-msg ${role}`;
  div.innerHTML = `<div class="role">${role === "user" ? "You" : "Agent"}</div>
                   <div>${escapeHtml(text)}</div>`;
  history.appendChild(div);
  history.scrollTop = history.scrollHeight;
}

// ═══════════════════════════════════════════════════════════
// Section 9.7 — Event Log
// ═══════════════════════════════════════════════════════════

function addEventToLog(data) {
  const list = document.getElementById("event-list");
  if (!list) return;

  const li = document.createElement("li");
  li.className = `ev-${data.type || "unknown"}`;

  const parts = [
    data.type || "?",
    data.agent_id ? `· ${data.agent_id.slice(0, 12)}` : "",
    data.summary  ? `· ${data.summary}` : "",
  ].filter(Boolean);
  li.textContent = parts.join(" ");
  li.title = JSON.stringify(data, null, 2);

  list.prepend(li);

  // Trim to max
  while (list.children.length > MAX_LOG_EVENTS) {
    list.removeChild(list.lastChild);
  }
}

// ═══════════════════════════════════════════════════════════
// Utility helpers
// ═══════════════════════════════════════════════════════════

/**
 * Set a Datastar signal value.
 *
 * Datastar exposes `window.__datastar_store` (the reactive store) after
 * DOMContentLoaded. We update it directly so data-show / data-bind attributes
 * respond automatically.
 *
 * If Datastar is not yet ready, this is a no-op — call it after DOMContentLoaded.
 */
function setSignal(name, value) {
  if (window.__datastar_store) {
    window.__datastar_store[name] = value;
  }
}

function getSignal(name) {
  return window.__datastar_store?.[name];
}

function escapeHtml(str) {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
```

> **Datastar store access**: The `window.__datastar_store` pattern is the v1.0 RC7 way to
> access reactive signals from vanilla JS. Check the Datastar changelog if the API changes
> in a future release.

---

## 10. Phase 0: Static Graph Snapshot

**Goal**: Open the browser and see a static graph of all nodes and edges. No live events yet.
No companion sidebar yet. Just the graph.

### What to implement

- Part A 4.1 (CORS) in remora  
- Part A 4.3 (`GET /graph/data`) in remora  
- Parts B–C (new repo setup and Starlette app)  
- Part D (index.html without sidebar or chat — see below)  
- Part E (CSS — full version OK)  
- Part F section 9.1, 9.2, 9.3 (Cytoscape init + loadGraph + styles)  

### Minimal `main.js` for Phase 0

```javascript
"use strict";
const REMORA = window.REMORA_BASE_URL || "http://localhost:8765";
let cy = null;

document.addEventListener("DOMContentLoaded", async () => {
  initCytoscape();
  await loadGraph();
});

function initCytoscape() {
  cy = cytoscape({
    container: document.getElementById("cy"),
    elements: [],
    style: getCyStyles(),
    layout: { name: "preset" },
  });
}

async function loadGraph() {
  const resp = await fetch(`${REMORA}/graph/data`);
  const data = await resp.json();
  cy.add(data.nodes);
  cy.add(data.edges);
  cy.layout({ name: "cose-bilkent", animate: false }).run();
}

// Include getCyStyles() from Section 9.3
```

### Verification

1. Start remora: `devenv shell -- python scripts/start_webserver.py` (or equivalent)
2. Start remora-ui: `devenv shell -- remora-ui` (or `python -m remora_ui.app`)
3. Open `http://localhost:8766`
4. You should see a graph with nodes and edges.
5. `curl http://localhost:8765/graph/data` should return a JSON object with `nodes` and
   `edges` arrays.

### Common issues at Phase 0

| Symptom | Likely cause |
|---------|-------------|
| Empty graph (no nodes) | remora EventStore has no data yet — open a Python file in Neovim with remora LSP running |
| CORS errors in console | CORS middleware not added, or wrong origin in `allow_origins` |
| 404 on `/graph/data` | Route not registered in starlette.py |
| Graph renders but no edges | `callee_ids` empty — code discovery hasn't run yet |

---

## 11. Phase 1: Live Event Pings

**Goal**: As the swarm processes events, the corresponding graph nodes flash with colour.
The event log panel fills with recent events.

### What to implement

Add to your Phase 0 `main.js`:
- Section 9.4 (`startEventStream`, `handleRawEvent`)
- Section 9.7 (`addEventToLog`)
- Call `startEventStream()` in the DOMContentLoaded handler after `loadGraph()`

Make sure the flash classes are in your CSS (they're already in Part E above).

### How it works

`handleRawEvent` is called for every SSE frame from `/events`. It:
1. Parses the JSON data
2. Looks up the `agent_id` in the Cytoscape graph
3. Calls `cyNode.flashClass("flash-AgentStartEvent", 900)` — Cytoscape applies the CSS class
   for 900 ms then removes it, creating a colour flash
4. Appends an entry to the `#event-list` log

The `flashClass()` method is built into Cytoscape.js and requires no additional plugins.

### Triggering events to test

From another terminal, send a test event:

```bash
curl -X POST http://localhost:8765/swarm/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "AgentMessageEvent",
       "data": {"from_agent": "test", "to_agent": "<any_node_id>", "content": "hello"}}'
```

Replace `<any_node_id>` with a real node ID from `/swarm/agents`.

You should see the corresponding node flash green-blue and a log entry appear.

### Verification

- [ ] Node flashes when event fires on it
- [ ] Event log shows the event type, truncated node ID, and summary
- [ ] Log is capped at 50 entries (old entries drop off the bottom)
- [ ] EventSource auto-reconnects after the server restarts (wait 3 seconds after restart)

---

## 12. Phase 2: Mode 1 Sidebar Panel

**Goal**: Click a graph node → the sidebar slides in with the node agent's markdown sidebar
content (role, notes, workspace summary, links). No chat yet.

### What to implement

- Part A 4.2 (`companion_registry` on `RemoraService`)
- Part A 4.4 (`GET /companion/sidebar/{node_id}`)
- Part A 4.7 (start companion in the web server)
- Add `data-signals` and sidebar HTML to `index.html` (Part D)
- Section 9.5 (`openSidebar`, `attachSidebarClose`)
- Update `initCytoscape()` to call `openSidebar()` on `tap`

### Companion startup note

The companion system requires a running LLM backend. Set these environment variables (or
update `CompanionConfig` defaults) before starting the web server:

```bash
export REMORA_MODEL_BASE_URL="http://remora-server:8000/v1"   # your local LLM API
export REMORA_MODEL_NAME="Qwen/Qwen3-4B-Instruct-2507-FP8"    # or whatever model
```

Alternatively, you can load the sidebar without an LLM by reading the workspace files
directly — the `compose_sidebar()` function works even if the agent has never sent a message.

### Verifying the sidebar opens

1. Click any node in the graph
2. The sidebar should slide in from the right
3. It should show the node's name in the header
4. The markdown content area should render the agent's workspace (role, notes, etc.)
5. If the agent workspace is empty (new agent), `compose_sidebar` returns a minimal stub

### The `compose_sidebar` output

The markdown is assembled from these workspace files (if they exist):
- `role.md` — the agent's role description
- `schema.yaml` — the node's data schema
- `notes.md` — accumulated agent notes
- `summary.md` — most recent summary
- `todo.md` — open action items
- `log.jsonl` — last 20 log entries
- `tools/*.pym` — available tool files
- `chat/index.json` — recent chat history index
- `links/links.json` — discovered relationships

If none of these files exist yet, the sidebar shows the node identity (name, type, file path,
start/end lines) and a placeholder.

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| `503 companion not configured` | Didn't call `start_companion()` in the startup script |
| `404 node not found` | Node ID in URL doesn't match any node in the EventStore |
| `AttributeError: 'Workspace' has no attribute 'list_keys'` | Check Cairn API — use `await workspace.keys()` or similar |
| Sidebar shows but markdown is empty | Agent workspace not yet populated — this is normal for new agents |

---

## 13. Phase 3: Chat (Non-Streaming)

**Goal**: Type a message in the sidebar chat input, press Send, see the agent's reply.

### What to implement

- Part A 4.5 (`POST /companion/chat`)
- Section 9.6 (`attachChatForm`, `appendChatMessage`)
- Add `#chat-area` HTML to `index.html` (already in Part D)

### How `agent.send()` works

`NodeAgent.send(message: str) -> NodeAgentResponse` is a coroutine that:
1. Appends the message to the agent's history
2. Runs the LLM kernel exchange
3. Runs post-exchange swarms (Summarizer, Categorizer, Linker, Reflection)
4. Returns `NodeAgentResponse` with a `.text` attribute containing the reply

The entire call is synchronous from the HTTP handler's perspective — the response is only
sent when the LLM finishes. For a small model (4B parameters, local), this is typically
2–10 seconds. A loading indicator is shown via the `$chatLoading` Datastar signal.

### Adding streaming (optional upgrade for Phase 3)

If you want token-by-token streaming, the HTTP endpoint needs to return an SSE stream
instead of a JSON response. This requires modifying `NodeAgent.send()` to yield tokens,
which depends on the underlying LLM kernel implementation. Treat this as a future enhancement.

### Verification

1. Open a node sidebar (Phase 2 must be working)
2. Type a message and press Send
3. The input clears, "Thinking…" appears
4. After a few seconds, the agent's reply appears below your message
5. Send a follow-up — the history is preserved within the page session

---

## 14. Phase 4: Neovim Cursor Sync → Graph Highlight

**Goal**: When the cursor moves in Neovim to a function/method node, that node is highlighted
in the browser graph automatically.

### How it works

The Neovim plugin (`src/remora/lsp/nvim/lua/remora/init.lua`) already sends
`$/remora/cursorMoved` notifications on `CursorHold`. The LSP server handles these and emits
a `CursorFocusEvent` on the `EventBus`. This event flows to the browser via the `/events` SSE
stream.

`CursorFocusEvent` has:
- `focused_agent_id: str` — the node ID of the function/method under the cursor
- `file_path: str`
- `line: int`

### What to implement

Add this handler to `handleRawEvent` in `main.js`:

```javascript
// Inside handleRawEvent(), add after the flash logic:
if (eventType === "CursorFocusEvent" && agentId && cy) {
  // Unhighlight previously focused node
  cy.nodes().removeClass("cursor-focused");
  // Highlight the new node
  const cyNode = cy.getElementById(agentId);
  if (cyNode.length) {
    cyNode.addClass("cursor-focused");
    // Pan the graph to centre on the focused node (optional)
    cy.animate({ center: { eles: cyNode }, zoom: Math.max(cy.zoom(), 1.5) }, { duration: 300 });
  }
}
```

Add the CSS class to `getCyStyles()`:

```javascript
{ selector: ".cursor-focused", style: {
    "border-width": 3,
    "border-color": "#fbbf24",
    "background-color": "#78350f",
} },
```

### Verification

1. Phase 1 must be working (SSE connected)
2. Move the cursor in Neovim over a Python function
3. Within ~500 ms, the corresponding node in the browser graph should highlight in amber
4. Moving to another function unhighlights the previous node and highlights the new one

### Troubleshooting

| Symptom | Fix |
|---------|-----|
| No highlight on cursor move | Check that `CursorFocusEvent` appears in the event log |
| Event appears but no highlight | Node ID in event doesn't match graph — check if the file has been indexed |
| Neovim doesn't send events | Ensure `RemoraTogglePanel` has been called, LSP is attached |

---

## 15. Phase 5: EventStore Replay Scrubber

**Goal**: A scrubber control that lets you step backwards through historical events, showing
the graph state at any point in the past.

> **Note**: This is the most complex phase. Implement Phases 0–4 first.

### How the replay endpoint works

`GET /replay?graph_id=<swarm_id>` (already in remora's Starlette adapter) streams historical
events from the EventStore as SSE frames with `event: replay`.

The `graph_id` is the value from `Config.swarm_id` — typically `"swarm"`.

### What to implement

**Add to `index.html`**:

```html
<!-- Add above the event log -->
<div id="replay-controls">
  <button id="replay-play-pause">⏸</button>
  <input id="replay-scrubber" type="range" min="0" max="100" value="100" step="1">
  <span id="replay-timestamp">Live</span>
</div>
```

**Add to `style.css`**:

```css
#replay-controls {
  position: fixed;
  bottom: 12px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
  background: rgba(15, 17, 23, 0.88);
  border: 1px solid #2a2d3a;
  border-radius: 6px;
  padding: 8px 16px;
  z-index: 100;
}
#replay-scrubber { width: 300px; }
```

**Add to `main.js`**:

```javascript
// Replay mode state
let replayEvents = [];      // all events loaded from /replay
let replayIndex = 0;        // current position in replayEvents
let isLive = true;          // true = live mode, false = replay mode

async function loadReplayHistory(graphId) {
  // Load all replay events into memory (one-time snapshot)
  const resp = await fetch(`${REMORA}/replay?graph_id=${encodeURIComponent(graphId)}`);
  // The replay endpoint is SSE — use a text reader
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    // Parse SSE frames from buffer
    const frames = buffer.split("\n\n");
    buffer = frames.pop(); // last may be incomplete
    for (const frame of frames) {
      const dataLine = frame.split("\n").find(l => l.startsWith("data:"));
      if (dataLine) {
        try {
          replayEvents.push(JSON.parse(dataLine.slice(5)));
        } catch {}
      }
    }
  }

  // Update scrubber range
  const scrubber = document.getElementById("replay-scrubber");
  if (scrubber) {
    scrubber.max = replayEvents.length;
    scrubber.value = replayEvents.length;
  }
}

function attachReplayControls(graphId) {
  const scrubber = document.getElementById("replay-scrubber");
  const timestamp = document.getElementById("replay-timestamp");
  const playPause = document.getElementById("replay-play-pause");

  loadReplayHistory(graphId);

  scrubber?.addEventListener("input", () => {
    replayIndex = parseInt(scrubber.value, 10);
    isLive = (replayIndex === replayEvents.length);

    if (isLive) {
      timestamp.textContent = "Live";
      startEventStream();  // re-attach live SSE
    } else {
      // Pause live events, apply snapshot up to replayIndex
      eventSource?.close();
      const event = replayEvents[replayIndex - 1];
      if (event && timestamp) {
        timestamp.textContent = new Date(event.timestamp * 1000).toLocaleTimeString();
      }
      applyReplaySnapshot(replayIndex);
    }
  });

  playPause?.addEventListener("click", () => {
    if (isLive) {
      isLive = false;
      eventSource?.close();
      playPause.textContent = "▶";
    } else {
      isLive = true;
      scrubber.value = replayEvents.length;
      timestamp.textContent = "Live";
      startEventStream();
      playPause.textContent = "⏸";
    }
  });
}

function applyReplaySnapshot(upToIndex) {
  // Reset all node statuses, then replay events up to upToIndex
  cy.nodes().data("status", "idle");

  for (let i = 0; i < upToIndex; i++) {
    const ev = replayEvents[i];
    const agentId = ev.agent_id;
    if (agentId && ev.payload?.status) {
      const node = cy.getElementById(agentId);
      if (node.length) node.data("status", ev.payload.status);
    }
  }
}
```

Then call `attachReplayControls("swarm")` in the DOMContentLoaded handler.

### Verification

1. Run the swarm for a while to accumulate events
2. Open the browser — the scrubber should show a range matching the event count
3. Drag the scrubber left — the replay timestamp updates
4. Node status colouring reflects the historical state at that point
5. Drag back to the rightmost position — live mode resumes

---

## 16. Running the Full Stack

Start services in this order:

```bash
# Terminal 1: Start remora (LSP server + HTTP server)
cd /path/to/remora
devenv shell -- python scripts/start_webserver.py

# Terminal 2: Start remora-ui
cd /path/to/remora-ui
devenv shell -- remora-ui --remora-url http://localhost:8765

# Browser: open
open http://localhost:8766
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `REMORA_URL` | `http://localhost:8765` | remora server URL (for remora-ui) |
| `REMORA_UI_HOST` | `127.0.0.1` | remora-ui bind host |
| `REMORA_UI_PORT` | `8766` | remora-ui bind port |

### Default ports

| Service | Port |
|---------|------|
| remora HTTP | 8765 |
| remora-ui | 8766 |

---

## 17. Testing Checklist

### Phase 0 — Static Graph

- [ ] `curl http://localhost:8765/graph/data` returns `{"nodes": [...], "edges": [...]}`
- [ ] Browser shows graph nodes
- [ ] Nodes have labels (function/class/method names)
- [ ] Compound nodes group methods inside classes
- [ ] Edges show call relationships
- [ ] Zooming and panning work
- [ ] Double-clicking the background fits the graph

### Phase 1 — Live Events

- [ ] Event log panel appears (bottom-right)
- [ ] Sending a test event via `curl` causes a log entry to appear
- [ ] The corresponding node flashes colour
- [ ] Different event types produce different flash colours
- [ ] Event log caps at 50 entries
- [ ] After killing remora and restarting, SSE reconnects within 3 seconds

### Phase 2 — Sidebar

- [ ] Clicking a node opens the sidebar
- [ ] Sidebar header shows the node's name
- [ ] Markdown content renders (headings, code blocks, lists)
- [ ] Closing the sidebar (✕ button) hides it and returns to graph view
- [ ] Clicking a different node while sidebar is open loads the new node's sidebar
- [ ] `503` response handled gracefully (shows error in sidebar content area)

### Phase 3 — Chat

- [ ] Chat input is visible when sidebar is open
- [ ] Submitting a message shows it in the history
- [ ] "Thinking…" indicator appears while waiting
- [ ] Reply appears in the history after agent responds
- [ ] Follow-up messages retain history context
- [ ] Empty message submission does nothing

### Phase 4 — Cursor Sync

- [ ] Moving cursor in Neovim triggers `CursorFocusEvent` in event log
- [ ] The corresponding node highlights in amber
- [ ] Moving cursor to another function updates the highlight
- [ ] Moving cursor off a function/method removes the highlight

### Phase 5 — Replay

- [ ] Scrubber appears at the bottom
- [ ] Scrubber range matches number of historical events
- [ ] Dragging left shows historical timestamp
- [ ] Node colours reflect historical status at that point
- [ ] Dragging back to rightmost position resumes live mode
- [ ] Pause button stops live updates; play button resumes

---

## 18. Common Pitfalls & FAQ

### "The graph is empty even though remora is running"

The `EventStore` nodes table is only populated after code discovery runs. Code discovery
happens when:
1. The LSP server opens a Python file via Neovim
2. A file-save event triggers re-indexing

Try: open any Python file in your project with Neovim (with the remora LSP active), then
reload the browser.

### "CORS error: blocked by CORS policy"

Check that:
1. `CORSMiddleware` was added to `create_app()` in `starlette.py`
2. The `allow_origins` list includes the exact origin (`http://localhost:8766` not
   `http://127.0.0.1:8766` — these are different origins to browsers)
3. You're not using a different port than expected

Quick fix for development: set `allow_origins=["*"]`.

### "`window.__datastar_store` is undefined"

Datastar initialises its store asynchronously after the page loads. If you call `setSignal()`
in a `DOMContentLoaded` handler and Datastar isn't ready yet, the call is silently ignored.

Fix: add a short wait, or gate on store availability:

```javascript
function setSignal(name, value) {
  const store = window.__datastar_store;
  if (store) {
    store[name] = value;
  } else {
    // Retry once Datastar initialises
    requestAnimationFrame(() => setSignal(name, value));
  }
}
```

Check the Datastar docs for the canonical way to access the store in the version you are using.

### "The sidebar shows but the markdown is blank"

The agent's Cairn workspace is empty — it hasn't been used yet. This is normal for a fresh
project. The sidebar will fill up over time as:
- The agent processes events (auto-generates notes/summary)
- You chat with the agent (chat history indexed in `chat/index.json`)
- The agent discovers links (written to `links/links.json`)

You can pre-populate `role.md` by writing it directly to the workspace path:
`.remora/swarm/agents/{id[:2]}/{id}/workspace.db` (it's a Cairn SQLite database — use
`cairn.open_workspace()` to write files programmatically).

### "The cose-bilkent layout crashes or throws"

Ensure the cose-bilkent CDN script loads **after** the cytoscape script. The order in
`index.html` matters.

If the layout fails with a numeric error, it usually means edges reference non-existent
nodes. The `loadGraph()` function in this guide removes those edges before running the
layout.

### "Chat gives `503 companion not configured`"

You started the server with `RemoraService.create_default()` but didn't call
`start_companion()`. Use the startup script from Section 4.7.

### "How do I add more event flash colours?"

In `getCyStyles()`, add a selector for `.flash-MyEventType` with the colour you want.
In `handleRawEvent()`, the class `flash-<eventType>` is automatically applied — no further
change needed.

### "I want to filter the event log to specific event types"

Add a `<select>` element with event type options, and in `addEventToLog()`, skip entries
that don't match the selected filter. This is a good first enhancement once the basics work.

### "How do I make the graph update when a new node is discovered?"

Subscribe to `NodeDiscoveredEvent` in `handleRawEvent`:

```javascript
if (eventType === "NodeDiscoveredEvent" && data.payload) {
  const p = data.payload;
  cy.add({
    data: {
      id: p.node_id,
      label: p.name,
      type: p.node_type,
      status: "idle",
      file_path: p.file_path,
      full_name: p.full_name,
      ...(p.parent_id ? { parent: p.parent_id } : {}),
    }
  });
  // Re-run layout with new node
  runLayout();
}
```

Similarly, handle `NodeRemovedEvent` by calling `cy.getElementById(node_id).remove()`.

---

*End of implementation guide. Build phase by phase, verify each milestone, and refer back
to REPORT.md for architectural context and trade-off rationale.*
