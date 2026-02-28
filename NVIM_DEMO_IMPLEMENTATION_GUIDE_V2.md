# Remora Neovim + Web UI Demo: Implementation Guide V2

This guide provides step-by-step instructions to implement the full reactive demo of Remora. By the end, you'll have:

- **Neovim sidebar** that streams a live "play-by-play" of the agent under your cursor
- **Push-based reactivity** where the daemon pushes events to Neovim in real-time
- **On-demand agent discovery** that registers agents when you open a Python file
- **Real LLM execution** via vLLM running Qwen3-4B
- **Hierarchical Web UI** showing all agents in a file→class→function tree
- **Agent interaction** via chat in both Neovim and Web UI

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [Phase 1: Push-Based Notifications](#3-phase-1-push-based-notifications)
4. [Phase 2: On-Demand Agent Discovery](#4-phase-2-on-demand-agent-discovery)
5. [Phase 3: Streaming Sidepanel](#5-phase-3-streaming-sidepanel)
6. [Phase 4: Chat with Agents](#6-phase-4-chat-with-agents)
7. [Phase 5: AgentRunner Integration](#7-phase-5-agentrunner-integration)
8. [Phase 6: Web UI - Dynamic Agent Tree](#8-phase-6-web-ui-dynamic-agent-tree)
9. [Phase 7: Web UI - Agent Detail Panel](#9-phase-7-web-ui-agent-detail-panel)
10. [Running the Demo](#10-running-the-demo)
11. [Testing & Verification](#11-testing--verification)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         REACTIVE DEMO ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────────┐         ┌──────────────────────────────────────────┐  │
│  │     NEOVIM       │         │              PYTHON DAEMON                │  │
│  │                  │         │                                          │  │
│  │  ┌────────────┐  │  Unix   │  ┌─────────────┐    ┌─────────────────┐  │  │
│  │  │ bridge.lua │◄─┼─Socket──┼─►│ RPC Server  │    │   FastAPI       │  │  │
│  │  └─────┬──────┘  │         │  └──────┬──────┘    │   (Web UI)      │  │  │
│  │        │         │         │         │           └────────┬────────┘  │  │
│  │  ┌─────▼──────┐  │         │  ┌──────▼──────┐             │           │  │
│  │  │ sidepanel  │  │         │  │ ClientMgr   │    ┌────────▼────────┐  │  │
│  │  │ (streaming)│  │         │  │ (tracks     │    │  SSE Endpoint   │  │  │
│  │  └────────────┘  │         │  │  subscribed │    │  /stream-events │  │  │
│  │                  │         │  │  agents)    │    └────────┬────────┘  │  │
│  │  ┌────────────┐  │         │  └──────┬──────┘             │           │  │
│  │  │ navigation │  │         │         │                    │           │  │
│  │  │ (cursor)   │  │         │  ┌──────▼────────────────────▼────────┐  │  │
│  │  └────────────┘  │         │  │            EventBus                │  │  │
│  │                  │         │  │  (all events flow through here)    │  │  │
│  └──────────────────┘         │  └──────┬────────────────────┬────────┘  │  │
│                               │         │                    │           │  │
│                               │  ┌──────▼──────┐    ┌────────▼────────┐  │  │
│                               │  │ AgentRunner │    │   EventStore    │  │  │
│                               │  │ (executes   │    │   (persists)    │  │  │
│                               │  │  turns)     │    └─────────────────┘  │  │
│                               │  └──────┬──────┘                         │  │
│                               │         │                                │  │
│                               │  ┌──────▼──────┐                         │  │
│                               │  │   vLLM      │                         │  │
│                               │  │ (Qwen3-4B)  │                         │  │
│                               │  └─────────────┘                         │  │
│                               └──────────────────────────────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Key Data Flows

1. **Buffer Opened**: Neovim → `buffer.opened(path)` → Daemon parses file → Registers agents in SwarmState
2. **Cursor Moved**: Neovim → `agent.subscribe(id)` → Daemon tracks subscription → Pushes events for that agent
3. **User Chats**: Neovim → `agent.chat(id, msg)` → AgentMessageEvent → Subscription matches → AgentRunner executes → Events pushed back
4. **Agent Executes**: AgentRunner → LLM calls → ToolCallEvent, ModelResponseEvent → EventBus → Push to subscribed Neovim clients

---

## 2. Prerequisites

### 2.1 Verify Existing Files

Ensure these files exist from MVP implementation:

```
remora/
├── lua/remora_nvim/
│   ├── init.lua
│   ├── bridge.lua
│   ├── navigation.lua
│   └── sidepanel.lua
├── plugin/
│   └── remora_nvim.lua
├── src/remora/demo/
│   ├── nvim_server.py
│   └── templates/
│       └── index.html
└── src/remora/core/
    ├── discovery.py
    ├── events.py
    ├── event_bus.py
    ├── event_store.py
    ├── swarm_state.py
    ├── subscriptions.py
    ├── agent_runner.py
    └── agent_state.py
```

### 2.2 Verify vLLM Access

```bash
curl http://remora-server:8000/v1/models
# Should return model list including Qwen/Qwen3-4B-Instruct-2507-FP8
```

---

## 3. Phase 1: Push-Based Notifications

The daemon needs to track which Neovim clients are subscribed to which agents, and push events to them in real-time.

### 3.1 Create Client Manager

**File: `src/remora/demo/client_manager.py`**

```python
"""Manages connected Neovim clients and their subscriptions."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora.core.events import RemoraEvent

logger = logging.getLogger(__name__)


@dataclass
class NvimClient:
    """A connected Neovim client with its subscriptions."""

    writer: asyncio.StreamWriter
    subscribed_agents: set[str] = field(default_factory=set)
    client_id: str = ""

    def __post_init__(self):
        if not self.client_id:
            self.client_id = f"nvim_{id(self)}"


class ClientManager:
    """Manages all connected Neovim clients."""

    def __init__(self):
        self._clients: dict[str, NvimClient] = {}
        self._lock = asyncio.Lock()

    async def register(self, writer: asyncio.StreamWriter) -> NvimClient:
        """Register a new Neovim client."""
        client = NvimClient(writer=writer)
        async with self._lock:
            self._clients[client.client_id] = client
        logger.info(f"Client {client.client_id} connected")
        return client

    async def unregister(self, client: NvimClient) -> None:
        """Unregister a disconnected client."""
        async with self._lock:
            self._clients.pop(client.client_id, None)
        logger.info(f"Client {client.client_id} disconnected")

    async def subscribe(self, client: NvimClient, agent_id: str) -> None:
        """Subscribe a client to an agent's events."""
        async with self._lock:
            # Clear previous subscriptions (one agent at a time for cursor tracking)
            client.subscribed_agents.clear()
            client.subscribed_agents.add(agent_id)
        logger.debug(f"Client {client.client_id} subscribed to {agent_id}")

    async def notify_event(self, event: RemoraEvent) -> None:
        """Push an event to all clients subscribed to the relevant agent."""
        # Determine which agent this event is about
        agent_id = (
            getattr(event, "agent_id", None) or
            getattr(event, "to_agent", None) or
            getattr(event, "from_agent", None)
        )

        if not agent_id:
            return

        # Build JSON-RPC notification
        notification = {
            "jsonrpc": "2.0",
            "method": "event.push",
            "params": {
                "agent_id": agent_id,
                "event_type": type(event).__name__,
                "timestamp": getattr(event, "timestamp", None),
                "data": self._serialize_event(event),
            }
        }
        msg = json.dumps(notification).encode() + b"\n"

        # Send to subscribed clients
        async with self._lock:
            clients_to_notify = [
                c for c in self._clients.values()
                if agent_id in c.subscribed_agents
            ]

        for client in clients_to_notify:
            try:
                client.writer.write(msg)
                await client.writer.drain()
            except Exception as e:
                logger.warning(f"Failed to push to {client.client_id}: {e}")

    def _serialize_event(self, event: RemoraEvent) -> dict:
        """Convert event to JSON-serializable dict."""
        from dataclasses import asdict, is_dataclass

        if is_dataclass(event):
            return asdict(event)
        elif hasattr(event, "__dict__"):
            return dict(vars(event))
        else:
            return {"value": str(event)}


# Global instance
client_manager = ClientManager()
```

### 3.2 Update Daemon to Use Client Manager

**File: `src/remora/demo/nvim_server.py`** (replace entire file)

```python
"""Remora Demo Server - FastAPI + Neovim RPC with push notifications."""

import asyncio
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from remora.core.config import load_config
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore
from remora.core.events import RemoraEvent, AgentMessageEvent
from remora.core.swarm_state import SwarmState
from remora.core.subscriptions import SubscriptionRegistry
from remora.demo.client_manager import ClientManager, NvimClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# Initialize Core Services
# ============================================================================

config = load_config()
db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"

swarm_state = SwarmState(db_path)
event_bus = EventBus()
subscriptions = SubscriptionRegistry(db_path)
event_store = EventStore(db_path, subscriptions=subscriptions, event_bus=event_bus)

# Client manager for push notifications
client_manager = ClientManager()

app = FastAPI(title="Remora Swarm Dashboard")
templates = Jinja2Templates(directory="src/remora/demo/templates")

SOCKET_PATH = getattr(config, "nvim_socket", "/run/user/1000/remora.sock")

# ============================================================================
# EventBus Integration - Push events to Neovim clients
# ============================================================================

async def push_to_clients(event: RemoraEvent) -> None:
    """Forward events from EventBus to subscribed Neovim clients."""
    await client_manager.notify_event(event)

# ============================================================================
# Neovim RPC Server
# ============================================================================

async def handle_nvim_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a connected Neovim client."""
    client = await client_manager.register(writer)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                request = json.loads(line.decode())
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from {client.client_id}: {e}")
                continue

            method = request.get("method", "")
            params = request.get("params", {})
            msg_id = request.get("id")

            # Handle RPC methods
            result = await handle_rpc_method(client, method, params)

            # Send response if request had an ID
            if msg_id is not None:
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                }
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"RPC error for {client.client_id}: {e}")
    finally:
        await client_manager.unregister(client)
        writer.close()
        await writer.wait_closed()


async def handle_rpc_method(client: NvimClient, method: str, params: dict) -> dict:
    """Dispatch RPC method calls."""

    if method == "agent.select":
        # Legacy: just get agent state
        return await rpc_agent_select(params)

    elif method == "agent.subscribe":
        # Subscribe to push notifications for an agent
        return await rpc_agent_subscribe(client, params)

    elif method == "agent.chat":
        # Send a message to an agent
        return await rpc_agent_chat(params)

    elif method == "buffer.opened":
        # Parse and register agents from a file
        return await rpc_buffer_opened(params)

    elif method == "agent.get_events":
        # Get recent events for an agent
        return await rpc_get_events(params)

    else:
        return {"error": f"Unknown method: {method}"}


async def rpc_agent_select(params: dict) -> dict:
    """Get agent state for display."""
    agent_id = params.get("id") or params.get("agent_id")

    if not agent_id:
        return {"error": "Missing agent_id"}

    agent = await swarm_state.get_agent(agent_id)

    if not agent:
        return {
            "status": "NOT_REGISTERED",
            "name": agent_id,
            "node_type": "unknown",
        }

    # Get agent's subscriptions
    subs = await subscriptions.get_subscriptions(agent_id)

    return {
        "status": agent.status,
        "name": agent.name,
        "full_name": agent.full_name,
        "node_type": agent.node_type,
        "file_path": agent.file_path,
        "start_line": agent.start_line,
        "end_line": agent.end_line,
        "parent_id": agent.parent_id,
        "subscriptions": [
            {
                "id": s.id,
                "pattern": {
                    "event_types": s.pattern.event_types,
                    "to_agent": s.pattern.to_agent,
                    "path_glob": s.pattern.path_glob,
                },
                "is_default": s.is_default,
            }
            for s in subs
        ],
    }


async def rpc_agent_subscribe(client: NvimClient, params: dict) -> dict:
    """Subscribe client to push notifications for an agent."""
    agent_id = params.get("id") or params.get("agent_id")

    if not agent_id:
        return {"error": "Missing agent_id"}

    await client_manager.subscribe(client, agent_id)

    return {"subscribed": agent_id}


async def rpc_agent_chat(params: dict) -> dict:
    """Send a chat message to an agent."""
    agent_id = params.get("id") or params.get("agent_id")
    message = params.get("message", "")

    if not agent_id or not message:
        return {"error": "Missing agent_id or message"}

    # Emit an AgentMessageEvent that the agent's subscription will match
    event = AgentMessageEvent(
        from_agent="user",
        to_agent=agent_id,
        content=message,
        tags=["user_chat"],
    )

    # This will persist the event and trigger any matching subscriptions
    event_id = await event_store.append(config.swarm_id, event)

    return {"event_id": event_id, "status": "sent"}


async def rpc_buffer_opened(params: dict) -> dict:
    """Parse a file and register its agents."""
    file_path = params.get("path")

    if not file_path:
        return {"error": "Missing path"}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}

    if path.suffix != ".py":
        return {"agents": [], "message": "Only Python files supported"}

    # Use discovery to parse the file
    from remora.core.discovery import parse_file, CSTNode

    try:
        nodes = parse_file(path)
    except Exception as e:
        logger.error(f"Failed to parse {file_path}: {e}")
        return {"error": str(e)}

    # Register each node as an agent
    registered = []
    for node in nodes:
        agent_id = compute_agent_id(node, path)
        parent_id = None
        if node.parent:
            parent_id = compute_agent_id(node.parent, path)

        from remora.core.swarm_state import AgentMetadata

        metadata = AgentMetadata(
            agent_id=agent_id,
            node_type=node.node_type,
            name=node.name,
            full_name=f"{path.stem}.{node.name}",
            file_path=str(path),
            parent_id=parent_id,
            start_line=node.start_line,
            end_line=node.end_line,
            status="active",
        )

        await swarm_state.upsert(metadata)

        # Register default subscriptions
        await subscriptions.register_defaults(agent_id, str(path))

        registered.append({
            "agent_id": agent_id,
            "name": node.name,
            "type": node.node_type,
            "line": node.start_line,
        })

    logger.info(f"Registered {len(registered)} agents from {file_path}")

    return {"agents": registered}


async def rpc_get_events(params: dict) -> dict:
    """Get recent events for an agent."""
    agent_id = params.get("id") or params.get("agent_id")
    limit = params.get("limit", 20)

    if not agent_id:
        return {"error": "Missing agent_id"}

    # Query events where this agent is involved
    events = []
    async for event in event_store.replay(
        config.swarm_id,
        event_types=None,  # All types
    ):
        # Filter for events involving this agent
        if (event.get("to_agent") == agent_id or
            event.get("from_agent") == agent_id or
            event.get("payload", {}).get("agent_id") == agent_id):
            events.append(event)
            if len(events) >= limit:
                break

    return {"events": events[-limit:]}  # Most recent


def compute_agent_id(node, file_path: Path) -> str:
    """Compute a stable agent ID matching Neovim's computation."""
    # Format: nodetype_filename_line
    # e.g., "function_definition_utils_15"
    return f"{node.node_type}_{file_path.stem}_{node.start_line}"


# ============================================================================
# Startup
# ============================================================================

async def start_rpc_server():
    """Start the Unix socket RPC server."""
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SOCKET_PATH).unlink(missing_ok=True)

    server = await asyncio.start_unix_server(handle_nvim_client, path=SOCKET_PATH)
    logger.info(f"Neovim RPC server listening on {SOCKET_PATH}")

    async with server:
        await server.serve_forever()


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    # Initialize databases
    await swarm_state.initialize()
    await subscriptions.initialize()
    await event_store.initialize()

    # Subscribe to EventBus for push notifications
    event_bus.subscribe_all(push_to_clients)

    # Start Neovim RPC server
    asyncio.create_task(start_rpc_server())

    logger.info("Remora Demo Server started")
    logger.info(f"  Web UI: http://localhost:8080")
    logger.info(f"  Neovim socket: {SOCKET_PATH}")


# ============================================================================
# Web UI Endpoints (SSE for Datastar)
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    """Serve the main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/agents")
async def get_agents():
    """Get all registered agents as hierarchical tree."""
    agents = await swarm_state.list_agents(status="active")

    # Build hierarchy
    tree = build_agent_tree(agents)

    return {"agents": tree}


@app.get("/api/agent/{agent_id}")
async def get_agent_detail(agent_id: str):
    """Get detailed info for a single agent."""
    agent = await swarm_state.get_agent(agent_id)
    if not agent:
        return {"error": "Agent not found"}

    subs = await subscriptions.get_subscriptions(agent_id)

    # Get recent events
    events = []
    async for event in event_store.replay(config.swarm_id):
        if (event.get("to_agent") == agent_id or
            event.get("from_agent") == agent_id):
            events.append(event)

    return {
        "agent": {
            "id": agent.agent_id,
            "name": agent.name,
            "full_name": agent.full_name,
            "node_type": agent.node_type,
            "file_path": agent.file_path,
            "start_line": agent.start_line,
            "end_line": agent.end_line,
            "status": agent.status,
        },
        "subscriptions": [
            {"id": s.id, "is_default": s.is_default}
            for s in subs
        ],
        "recent_events": events[-20:],
    }


@app.post("/api/agent/{agent_id}/chat")
async def post_agent_chat(agent_id: str, request: Request):
    """Send a chat message to an agent via Web UI."""
    body = await request.json()
    message = body.get("message", "")

    if not message:
        return {"error": "Missing message"}

    event = AgentMessageEvent(
        from_agent="web_user",
        to_agent=agent_id,
        content=message,
        tags=["user_chat", "web"],
    )

    event_id = await event_store.append(config.swarm_id, event)

    return {"event_id": event_id, "status": "sent"}


@app.get("/stream-events")
async def stream_events(request: Request):
    """SSE endpoint for real-time event streaming to Web UI."""
    from datastar_py.sse import ServerSentEventGenerator

    async def sse_generator():
        # Initial connection message
        yield ServerSentEventGenerator.merge_fragments(
            '<div id="logs" data-prepend><li class="log-entry">Connected to Swarm EventBus...</li></div>'
        )

        # Subscribe to EventBus
        queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()

        async def handler(event: RemoraEvent):
            await queue.put(event)

        event_bus.subscribe_all(handler)

        try:
            while True:
                event = await queue.get()

                event_type = type(event).__name__
                agent_id = (
                    getattr(event, "agent_id", None) or
                    getattr(event, "to_agent", None) or
                    getattr(event, "from_agent", None) or
                    "system"
                )

                # Format based on event type
                if event_type == "ToolCallEvent":
                    tool_name = getattr(event, "tool_name", "unknown")
                    detail = f"Tool: {tool_name}"
                elif event_type == "ModelResponseEvent":
                    content = getattr(event, "content", "")[:50]
                    detail = f"Response: {content}..."
                elif event_type == "AgentMessageEvent":
                    content = getattr(event, "content", "")[:50]
                    detail = f"Message: {content}..."
                else:
                    detail = ""

                html = f'''<div id="logs" data-prepend>
                    <li class="log-entry">
                        <span class="event-type">[{event_type}]</span>
                        <span class="agent-id">{agent_id}</span>
                        <span class="detail">{detail}</span>
                    </li>
                </div>'''

                yield ServerSentEventGenerator.merge_fragments(html)

        except asyncio.CancelledError:
            event_bus.unsubscribe(handler)

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


def build_agent_tree(agents: list) -> list:
    """Build hierarchical tree from flat agent list."""
    # Group by file
    by_file: dict[str, list] = {}
    for agent in agents:
        fp = agent.file_path
        if fp not in by_file:
            by_file[fp] = []
        by_file[fp].append(agent)

    tree = []
    for file_path, file_agents in by_file.items():
        # Build parent-child relationships
        agents_by_id = {a.agent_id: a for a in file_agents}
        children_map: dict[str | None, list] = {None: []}

        for agent in file_agents:
            parent = agent.parent_id
            if parent not in children_map:
                children_map[parent] = []
            children_map[parent].append(agent)

        def build_node(agent):
            children = children_map.get(agent.agent_id, [])
            return {
                "id": agent.agent_id,
                "name": agent.name,
                "type": agent.node_type,
                "line": agent.start_line,
                "children": [build_node(c) for c in sorted(children, key=lambda x: x.start_line)],
            }

        # Root agents (no parent or parent not in this file)
        roots = [a for a in file_agents if a.parent_id is None or a.parent_id not in agents_by_id]

        file_node = {
            "id": f"file_{Path(file_path).stem}",
            "name": Path(file_path).name,
            "type": "file",
            "path": file_path,
            "children": [build_node(r) for r in sorted(roots, key=lambda x: x.start_line)],
        }
        tree.append(file_node)

    return sorted(tree, key=lambda x: x["name"])


# ============================================================================
# Main
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

### 3.3 Update Neovim Bridge for Push Notifications

**File: `lua/remora_nvim/bridge.lua`** (replace entire file)

```lua
-- Remora Bridge: JSON-RPC client with push notification support

local M = {}

M.client = nil
M.callbacks = {}
M.next_id = 1
M.current_subscription = nil
M.notification_handlers = {}

-- ============================================================================
-- Connection Management
-- ============================================================================

function M.setup(socket_path)
    M.client = vim.loop.new_pipe(false)

    M.client:connect(socket_path, function(err)
        if err then
            vim.schedule(function()
                vim.notify("Remora: Failed to connect to " .. socket_path .. ": " .. err, vim.log.levels.ERROR)
            end)
            return
        end

        -- Start reading responses and notifications
        M.client:read_start(function(read_err, data)
            if read_err then
                vim.schedule(function()
                    vim.notify("Remora: Read error: " .. read_err, vim.log.levels.ERROR)
                end)
                return
            end
            if data then
                M.handle_incoming(data)
            end
        end)

        vim.schedule(function()
            vim.notify("Remora: Connected!", vim.log.levels.INFO)
        end)
    end)
end

-- ============================================================================
-- RPC Calls
-- ============================================================================

function M.call(method, params, callback)
    if not M.client then
        vim.notify("Remora: Not connected", vim.log.levels.WARN)
        return
    end

    local id = M.next_id
    M.next_id = M.next_id + 1

    local msg = vim.fn.json_encode({
        jsonrpc = "2.0",
        id = id,
        method = method,
        params = params,
    })

    if callback then
        M.callbacks[id] = callback
    end

    M.client:write(msg .. "\n")
end

-- ============================================================================
-- Handle Incoming Data (Responses + Notifications)
-- ============================================================================

function M.handle_incoming(data)
    for line in data:gmatch("[^\n]+") do
        local ok, msg = pcall(vim.fn.json_decode, line)
        if ok and msg then
            if msg.id and M.callbacks[msg.id] then
                -- This is a response to our request
                vim.schedule(function()
                    M.callbacks[msg.id](msg.result)
                    M.callbacks[msg.id] = nil
                end)
            elseif msg.method then
                -- This is a push notification from the daemon
                vim.schedule(function()
                    M.handle_notification(msg.method, msg.params)
                end)
            end
        end
    end
end

-- ============================================================================
-- Notification Handling
-- ============================================================================

function M.handle_notification(method, params)
    if method == "event.push" then
        -- An event was pushed for an agent we're subscribed to
        local agent_id = params.agent_id
        local event_type = params.event_type
        local event_data = params.data or {}

        -- Notify the sidepanel to update
        require("remora_nvim.sidepanel").on_event_push(agent_id, event_type, event_data)
    end
end

-- ============================================================================
-- Subscription Management
-- ============================================================================

function M.subscribe_to_agent(agent_id)
    if M.current_subscription == agent_id then
        return -- Already subscribed
    end

    M.current_subscription = agent_id

    M.call("agent.subscribe", { agent_id = agent_id }, function(result)
        if result and result.subscribed then
            -- Subscription confirmed
        end
    end)
end

-- ============================================================================
-- Convenience Methods
-- ============================================================================

function M.notify_buffer_opened(file_path)
    M.call("buffer.opened", { path = file_path }, function(result)
        if result and result.agents then
            local count = #result.agents
            if count > 0 then
                vim.notify(string.format("Remora: Registered %d agents from %s", count, vim.fn.fnamemodify(file_path, ":t")), vim.log.levels.INFO)
            end
        elseif result and result.error then
            vim.notify("Remora: " .. result.error, vim.log.levels.WARN)
        end
    end)
end

function M.send_chat(agent_id, message, callback)
    M.call("agent.chat", { agent_id = agent_id, message = message }, callback)
end

function M.get_agent_events(agent_id, callback)
    M.call("agent.get_events", { agent_id = agent_id }, callback)
end

return M
```

---

## 4. Phase 2: On-Demand Agent Discovery

When Neovim opens a Python file, we parse it and register agents.

### 4.1 Update Navigation to Trigger Discovery

**File: `lua/remora_nvim/navigation.lua`** (replace entire file)

```lua
-- Remora Navigation: Treesitter cursor tracking + agent discovery

local M = {}

M.current_agent_id = nil
M.registered_buffers = {}

-- ============================================================================
-- Setup
-- ============================================================================

function M.setup()
    -- Track cursor movement
    vim.api.nvim_create_autocmd("CursorMoved", {
        callback = M.on_cursor_moved,
    })

    -- Discover agents when buffer is opened
    vim.api.nvim_create_autocmd("BufReadPost", {
        pattern = "*.py",
        callback = M.on_buffer_opened,
    })

    -- Also handle already-open buffers
    vim.api.nvim_create_autocmd("BufEnter", {
        pattern = "*.py",
        callback = M.on_buffer_entered,
    })
end

-- ============================================================================
-- Buffer Discovery
-- ============================================================================

function M.on_buffer_opened(ev)
    local bufnr = ev.buf
    local file_path = vim.api.nvim_buf_get_name(bufnr)

    if file_path == "" or M.registered_buffers[file_path] then
        return
    end

    M.registered_buffers[file_path] = true
    require("remora_nvim.bridge").notify_buffer_opened(file_path)
end

function M.on_buffer_entered(ev)
    -- Ensure discovery for buffers opened before plugin loaded
    local bufnr = ev.buf
    local file_path = vim.api.nvim_buf_get_name(bufnr)

    if file_path == "" or M.registered_buffers[file_path] then
        return
    end

    M.registered_buffers[file_path] = true
    require("remora_nvim.bridge").notify_buffer_opened(file_path)
end

-- ============================================================================
-- Cursor Tracking
-- ============================================================================

function M.on_cursor_moved()
    local bufnr = vim.api.nvim_get_current_buf()
    local filetype = vim.bo[bufnr].filetype

    -- Only track in supported files
    if filetype ~= "python" then
        return
    end

    -- Get treesitter parser
    local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
    if not ok or not parser then
        return
    end

    -- Get cursor position
    local cursor = vim.api.nvim_win_get_cursor(0)
    local row = cursor[1] - 1
    local col = cursor[2]

    -- Parse and find node at cursor
    local tree = parser:parse()[1]
    if not tree then return end

    local root = tree:root()
    if not root then return end

    local node = root:named_descendant_for_range(row, col, row, col)

    -- Walk up to find an "agent" node (function/class)
    local target_node = nil
    while node do
        local node_type = node:type()
        if M.is_agent_node_type(node_type) then
            target_node = node
            break
        end
        node = node:parent()
    end

    -- Compute agent ID
    local file_path = vim.api.nvim_buf_get_name(bufnr)
    local file_name = vim.fn.fnamemodify(file_path, ":t:r")

    local agent_id
    local node_type = "file"
    local start_line = 1

    if target_node then
        node_type = target_node:type()
        start_line, _ = target_node:start()
        start_line = start_line + 1  -- Convert to 1-indexed
    end

    -- ID format must match daemon's compute_agent_id()
    agent_id = string.format("%s_%s_%d", node_type, file_name, start_line)

    -- Update if changed
    if agent_id ~= M.current_agent_id then
        M.current_agent_id = agent_id

        -- Subscribe to events for this agent
        require("remora_nvim.bridge").subscribe_to_agent(agent_id)

        -- Update sidepanel
        require("remora_nvim.sidepanel").show_agent(agent_id, file_path, node_type, start_line)
    end
end

function M.is_agent_node_type(node_type)
    local agent_types = {
        "function_definition",
        "async_function_definition",
        "class_definition",
        "decorated_definition",
    }
    return vim.tbl_contains(agent_types, node_type)
end

-- ============================================================================
-- Navigation Helpers
-- ============================================================================

function M.go_to_parent()
    -- Navigate to parent agent
    local bufnr = vim.api.nvim_get_current_buf()
    local cursor = vim.api.nvim_win_get_cursor(0)
    local row = cursor[1] - 1
    local col = cursor[2]

    local ok, parser = pcall(vim.treesitter.get_parser, bufnr)
    if not ok or not parser then return end

    local tree = parser:parse()[1]
    if not tree then return end

    local root = tree:root()
    local node = root:named_descendant_for_range(row, col, row, col)

    -- Find current agent node
    while node and not M.is_agent_node_type(node:type()) do
        node = node:parent()
    end

    if not node then return end

    -- Go to parent agent
    local parent = node:parent()
    while parent and not M.is_agent_node_type(parent:type()) do
        parent = parent:parent()
    end

    if parent then
        local start_row, start_col = parent:start()
        vim.api.nvim_win_set_cursor(0, { start_row + 1, start_col })
    end
end

return M
```

---

## 5. Phase 3: Streaming Sidepanel

The sidepanel shows agent info and streams events in real-time.

### 5.1 Update Sidepanel with Event Log

**File: `lua/remora_nvim/sidepanel.lua`** (replace entire file)

```lua
-- Remora Sidepanel: Agent info + streaming event log

local M = {}

M.win = nil
M.buf = nil
M.current_agent = nil
M.current_state = nil
M.event_log = {}  -- Ring buffer of recent events
M.max_events = 50

-- ============================================================================
-- Setup
-- ============================================================================

function M.setup()
    M.buf = vim.api.nvim_create_buf(false, true)
    vim.api.nvim_buf_set_option(M.buf, "buftype", "nofile")
    vim.api.nvim_buf_set_option(M.buf, "filetype", "remora")
    vim.api.nvim_buf_set_option(M.buf, "modifiable", true)
    vim.api.nvim_buf_set_name(M.buf, "Remora Agent")

    -- Keymaps for sidepanel
    local opts = { buffer = M.buf, noremap = true, silent = true }
    vim.keymap.set("n", "c", function() require("remora_nvim.chat").open() end, opts)
    vim.keymap.set("n", "q", function() M.close() end, opts)
    vim.keymap.set("n", "r", function() M.refresh() end, opts)
end

-- ============================================================================
-- Window Management
-- ============================================================================

function M.toggle()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        M.close()
    else
        M.open()
    end
end

function M.open()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        return
    end

    vim.cmd("vsplit")
    vim.cmd("wincmd L")
    M.win = vim.api.nvim_get_current_win()
    vim.api.nvim_win_set_buf(M.win, M.buf)
    vim.api.nvim_win_set_width(M.win, 45)

    vim.api.nvim_win_set_option(M.win, "number", false)
    vim.api.nvim_win_set_option(M.win, "relativenumber", false)
    vim.api.nvim_win_set_option(M.win, "signcolumn", "no")
    vim.api.nvim_win_set_option(M.win, "winfixwidth", true)
    vim.api.nvim_win_set_option(M.win, "wrap", true)

    -- Return cursor to previous window
    vim.cmd("wincmd p")

    -- Render if we have an agent
    if M.current_agent then
        M.render()
    end
end

function M.close()
    if M.win and vim.api.nvim_win_is_valid(M.win) then
        vim.api.nvim_win_close(M.win, true)
    end
    M.win = nil
end

-- ============================================================================
-- Agent Display
-- ============================================================================

function M.show_agent(agent_id, file_path, node_type, start_line)
    M.current_agent = agent_id
    M.event_log = {}  -- Clear events for new agent

    -- Fetch agent state from daemon
    require("remora_nvim.bridge").call("agent.select", { id = agent_id }, function(state)
        M.current_state = state
        M.render()

        -- Also fetch recent events
        require("remora_nvim.bridge").get_agent_events(agent_id, function(result)
            if result and result.events then
                for _, ev in ipairs(result.events) do
                    M.add_event_to_log(ev.event_type, ev.payload or {})
                end
                M.render()
            end
        end)
    end)
end

function M.refresh()
    if M.current_agent then
        M.show_agent(M.current_agent, nil, nil, nil)
    end
end

-- ============================================================================
-- Event Push Handler
-- ============================================================================

function M.on_event_push(agent_id, event_type, event_data)
    -- Only process events for current agent
    if agent_id ~= M.current_agent then
        return
    end

    M.add_event_to_log(event_type, event_data)
    M.render()
end

function M.add_event_to_log(event_type, event_data)
    local entry = {
        type = event_type,
        data = event_data,
        time = os.time(),
    }

    table.insert(M.event_log, entry)

    -- Keep only recent events
    while #M.event_log > M.max_events do
        table.remove(M.event_log, 1)
    end
end

-- ============================================================================
-- Rendering
-- ============================================================================

function M.render()
    if not M.buf or not vim.api.nvim_buf_is_valid(M.buf) then
        return
    end

    local lines = {}
    local state = M.current_state or {}

    -- Header
    table.insert(lines, "╭───────────────────────────────────────────╮")
    table.insert(lines, string.format("│ Agent: %-35s│", (state.name or M.current_agent or "?"):sub(1, 35)))
    table.insert(lines, string.format("│ Type: %-36s│", (state.node_type or "unknown"):sub(1, 36)))
    table.insert(lines, string.format("│ Status: %-34s│", (state.status or "UNKNOWN"):sub(1, 34)))

    if state.file_path then
        local short_path = vim.fn.fnamemodify(state.file_path, ":t")
        local location = string.format("%s:%d", short_path, state.start_line or 0)
        table.insert(lines, string.format("│ Location: %-32s│", location:sub(1, 32)))
    end

    table.insert(lines, "╰───────────────────────────────────────────╯")
    table.insert(lines, "")

    -- Subscriptions
    table.insert(lines, "SUBSCRIPTIONS")
    table.insert(lines, "───────────────────────────────────────────")
    if state.subscriptions and #state.subscriptions > 0 then
        for _, sub in ipairs(state.subscriptions) do
            local tag = sub.is_default and "[default]" or "[custom]"
            local pattern_desc = M.describe_pattern(sub.pattern)
            table.insert(lines, string.format("├─ %s %s", tag, pattern_desc:sub(1, 30)))
        end
    else
        table.insert(lines, "  (none)")
    end
    table.insert(lines, "")

    -- Event Log (Play-by-Play)
    table.insert(lines, "PLAY-BY-PLAY")
    table.insert(lines, "───────────────────────────────────────────")

    if #M.event_log > 0 then
        -- Show most recent events first
        for i = #M.event_log, math.max(1, #M.event_log - 15), -1 do
            local ev = M.event_log[i]
            local formatted = M.format_event(ev)
            for _, line in ipairs(formatted) do
                table.insert(lines, line)
            end
        end
    else
        table.insert(lines, "  (no events yet)")
        table.insert(lines, "")
        table.insert(lines, "  Press 'c' to chat with this agent")
    end

    table.insert(lines, "")
    table.insert(lines, "───────────────────────────────────────────")
    table.insert(lines, " [c]hat  [r]efresh  [q]uit")

    -- Write to buffer
    vim.api.nvim_buf_set_option(M.buf, "modifiable", true)
    vim.api.nvim_buf_set_lines(M.buf, 0, -1, false, lines)
    vim.api.nvim_buf_set_option(M.buf, "modifiable", false)
end

function M.describe_pattern(pattern)
    if not pattern then return "unknown" end

    if pattern.to_agent then
        return "to_agent: self"
    elseif pattern.path_glob then
        return "path: " .. pattern.path_glob
    elseif pattern.event_types then
        return "events: " .. table.concat(pattern.event_types, ", ")
    else
        return "custom"
    end
end

function M.format_event(ev)
    local lines = {}
    local time_str = os.date("%H:%M:%S", ev.time)
    local icon = M.get_event_icon(ev.type)

    -- Main event line
    table.insert(lines, string.format("├─ %s [%s] %s", icon, time_str, ev.type))

    -- Event-specific details
    if ev.type == "AgentMessageEvent" then
        local content = ev.data.content or ""
        local from = ev.data.from_agent or "?"
        table.insert(lines, string.format("│  From: %s", from:sub(1, 20)))
        -- Wrap long messages
        for _, line in ipairs(M.wrap_text(content, 38)) do
            table.insert(lines, "│  " .. line)
        end

    elseif ev.type == "ToolCallEvent" then
        local tool = ev.data.tool_name or "unknown"
        table.insert(lines, string.format("│  Tool: %s", tool))

    elseif ev.type == "ModelResponseEvent" then
        local content = ev.data.content or ""
        table.insert(lines, "│  Response:")
        for _, line in ipairs(M.wrap_text(content:sub(1, 200), 38)) do
            table.insert(lines, "│  " .. line)
        end

    elseif ev.type == "AgentStartEvent" then
        table.insert(lines, "│  Agent execution started")

    elseif ev.type == "AgentCompleteEvent" then
        local summary = ev.data.result_summary or ""
        table.insert(lines, "│  Completed: " .. summary:sub(1, 30))

    elseif ev.type == "AgentErrorEvent" then
        local err = ev.data.error or "unknown"
        table.insert(lines, "│  Error: " .. err:sub(1, 35))
    end

    table.insert(lines, "│")

    return lines
end

function M.get_event_icon(event_type)
    local icons = {
        AgentMessageEvent = "💬",
        ToolCallEvent = "🔧",
        ToolResultEvent = "📋",
        ModelRequestEvent = "🤖",
        ModelResponseEvent = "💭",
        AgentStartEvent = "▶️",
        AgentCompleteEvent = "✅",
        AgentErrorEvent = "❌",
        ManualTriggerEvent = "👆",
    }
    return icons[event_type] or "📌"
end

function M.wrap_text(text, width)
    local lines = {}
    local line = ""

    for word in text:gmatch("%S+") do
        if #line + #word + 1 <= width then
            line = line == "" and word or (line .. " " .. word)
        else
            if line ~= "" then
                table.insert(lines, line)
            end
            line = word
        end
    end

    if line ~= "" then
        table.insert(lines, line)
    end

    -- Limit to 5 lines
    if #lines > 5 then
        lines = { lines[1], lines[2], lines[3], lines[4], "..." }
    end

    return lines
end

return M
```

---

## 6. Phase 4: Chat with Agents

Add the ability to send messages to agents.

### 6.1 Create Chat Module

**File: `lua/remora_nvim/chat.lua`**

```lua
-- Remora Chat: Send messages to agents

local M = {}

function M.open()
    local sidepanel = require("remora_nvim.sidepanel")
    local bridge = require("remora_nvim.bridge")

    if not sidepanel.current_agent then
        vim.notify("Remora: No agent selected", vim.log.levels.WARN)
        return
    end

    local agent_id = sidepanel.current_agent
    local agent_name = (sidepanel.current_state and sidepanel.current_state.name) or agent_id

    vim.ui.input({
        prompt = string.format("Chat with %s: ", agent_name),
    }, function(input)
        if input and input ~= "" then
            M.send(agent_id, input)
        end
    end)
end

function M.send(agent_id, message)
    local bridge = require("remora_nvim.bridge")
    local sidepanel = require("remora_nvim.sidepanel")

    vim.notify("Remora: Sending message...", vim.log.levels.INFO)

    -- Add user message to local log immediately for responsiveness
    sidepanel.add_event_to_log("AgentMessageEvent", {
        from_agent = "user",
        to_agent = agent_id,
        content = message,
    })
    sidepanel.render()

    -- Send to daemon
    bridge.send_chat(agent_id, message, function(result)
        if result and result.status == "sent" then
            vim.notify("Remora: Message sent, agent triggered", vim.log.levels.INFO)
        elseif result and result.error then
            vim.notify("Remora: " .. result.error, vim.log.levels.ERROR)
        end
    end)
end

return M
```

### 6.2 Update Init to Include Chat Keybinding

**File: `lua/remora_nvim/init.lua`** (replace entire file)

```lua
-- Remora.nvim: Agent-native IDE plugin

local M = {}

function M.setup(config)
    config = config or {}
    local socket_path = config.socket or "/run/user/1000/remora.sock"

    -- Initialize modules
    require("remora_nvim.sidepanel").setup()
    require("remora_nvim.bridge").setup(socket_path)
    require("remora_nvim.navigation").setup()

    -- Setup keymaps
    M.setup_keymaps(config.keymaps or {})

    vim.notify("Remora.nvim initialized", vim.log.levels.INFO)
end

function M.setup_keymaps(user_keymaps)
    local defaults = {
        toggle = "<leader>ra",
        chat = "<leader>rc",
        parent = "[[",
    }

    local keymaps = vim.tbl_extend("force", defaults, user_keymaps)
    local opts = { noremap = true, silent = true }

    -- Toggle sidepanel
    vim.keymap.set("n", keymaps.toggle, function()
        require("remora_nvim.sidepanel").toggle()
    end, opts)

    -- Chat with current agent
    vim.keymap.set("n", keymaps.chat, function()
        require("remora_nvim.chat").open()
    end, opts)

    -- Navigate to parent agent
    vim.keymap.set("n", keymaps.parent, function()
        require("remora_nvim.navigation").go_to_parent()
    end, opts)
end

return M
```

### 6.3 Update Plugin Entry Point

**File: `plugin/remora_nvim.lua`** (replace entire file)

```lua
-- Remora.nvim plugin entry point

if vim.g.loaded_remora_nvim then
    return
end
vim.g.loaded_remora_nvim = true

-- User commands
vim.api.nvim_create_user_command("RemoraToggle", function()
    require("remora_nvim.sidepanel").toggle()
end, { desc = "Toggle Remora sidepanel" })

vim.api.nvim_create_user_command("RemoraConnect", function(opts)
    local socket = opts.args ~= "" and opts.args or nil
    require("remora_nvim").setup({ socket = socket })
end, { nargs = "?", desc = "Connect to Remora daemon" })

vim.api.nvim_create_user_command("RemoraChat", function()
    require("remora_nvim.chat").open()
end, { desc = "Chat with current agent" })

vim.api.nvim_create_user_command("RemoraRefresh", function()
    require("remora_nvim.sidepanel").refresh()
end, { desc = "Refresh current agent" })
```

---

## 7. Phase 5: AgentRunner Integration

Wire up the AgentRunner so agents actually execute with LLM calls.

### 7.1 Update Server to Start AgentRunner

Add to `src/remora/demo/nvim_server.py`, in the startup section:

```python
# Add these imports at the top
from remora.core.agent_runner import AgentRunner

# Add this in startup_event(), after initializing other services:

@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    # Initialize databases
    await swarm_state.initialize()
    await subscriptions.initialize()
    await event_store.initialize()

    # Subscribe to EventBus for push notifications
    event_bus.subscribe_all(push_to_clients)

    # Start AgentRunner for executing agent turns
    runner = AgentRunner(
        event_store=event_store,
        subscriptions=subscriptions,
        swarm_state=swarm_state,
        config=config,
        event_bus=event_bus,
        project_root=Path.cwd(),
    )
    asyncio.create_task(runner.run_forever())

    # Start Neovim RPC server
    asyncio.create_task(start_rpc_server())

    logger.info("Remora Demo Server started")
    logger.info(f"  Web UI: http://localhost:8080")
    logger.info(f"  Neovim socket: {SOCKET_PATH}")
    logger.info(f"  AgentRunner: active")
```

### 7.2 Verify Config Has LLM Settings

Ensure your `remora.yaml` or config has:

```yaml
model:
  base_url: http://remora-server:8000/v1
  api_key: EMPTY
  default_model: Qwen/Qwen3-4B-Instruct-2507-FP8

# Cascade prevention
max_trigger_depth: 10
trigger_cooldown_ms: 100
max_concurrency: 4
```

---

## 8. Phase 6: Web UI - Dynamic Agent Tree

Replace the hardcoded tree with a dynamic one from SwarmState.

### 8.1 Update HTML Template

**File: `src/remora/demo/templates/index.html`** (replace entire file)

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Swarm Dashboard</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-beta.11/bundles/datastar.js"></script>
    <style>
        :root {
            --bg-primary: #1e1e1e;
            --bg-secondary: #252526;
            --bg-tertiary: #2d2d30;
            --text-primary: #d4d4d4;
            --text-secondary: #808080;
            --accent: #4CAF50;
            --accent-dim: #2d5a2e;
            --border: #404040;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'SF Mono', 'Monaco', 'Inconsolata', 'Roboto Mono', monospace;
            font-size: 13px;
            background: var(--bg-primary);
            color: var(--text-primary);
            display: flex;
            height: 100vh;
        }

        /* Sidebar - Agent Tree */
        .sidebar {
            width: 300px;
            background: var(--bg-secondary);
            border-right: 1px solid var(--border);
            display: flex;
            flex-direction: column;
        }

        .sidebar-header {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .sidebar-header::before {
            content: "🐙";
        }

        .agent-tree {
            flex: 1;
            overflow-y: auto;
            padding: 8px 0;
        }

        .tree-node {
            cursor: pointer;
            user-select: none;
        }

        .tree-node-content {
            display: flex;
            align-items: center;
            padding: 4px 8px;
            gap: 6px;
        }

        .tree-node-content:hover {
            background: var(--bg-tertiary);
        }

        .tree-node.selected > .tree-node-content {
            background: var(--accent-dim);
        }

        .tree-icon {
            width: 16px;
            text-align: center;
        }

        .tree-children {
            margin-left: 16px;
        }

        .node-type-file .tree-icon::before { content: "📄"; }
        .node-type-class_definition .tree-icon::before { content: "🔷"; }
        .node-type-function_definition .tree-icon::before { content: "⚡"; }
        .node-type-async_function_definition .tree-icon::before { content: "⚡"; }

        .node-status {
            font-size: 10px;
            padding: 1px 4px;
            border-radius: 3px;
            background: var(--bg-tertiary);
            color: var(--text-secondary);
        }

        .node-status.active {
            background: var(--accent-dim);
            color: var(--accent);
        }

        /* Main Content */
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
        }

        .main-header {
            padding: 12px 16px;
            border-bottom: 1px solid var(--border);
            font-weight: 600;
        }

        /* Agent Detail Panel */
        .detail-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        .detail-header {
            padding: 16px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
        }

        .detail-header h2 {
            font-size: 16px;
            margin-bottom: 8px;
        }

        .detail-meta {
            display: flex;
            gap: 16px;
            color: var(--text-secondary);
            font-size: 12px;
        }

        .detail-body {
            flex: 1;
            display: flex;
            overflow: hidden;
        }

        /* Event Log */
        .event-log {
            flex: 1;
            display: flex;
            flex-direction: column;
            border-right: 1px solid var(--border);
        }

        .event-log-header {
            padding: 8px 16px;
            background: var(--bg-tertiary);
            font-weight: 600;
            font-size: 12px;
        }

        .event-log-content {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }

        .log-entry {
            padding: 6px 8px;
            border-radius: 4px;
            margin-bottom: 4px;
            background: var(--bg-secondary);
            font-size: 12px;
            display: flex;
            gap: 8px;
        }

        .log-entry:hover {
            background: var(--bg-tertiary);
        }

        .event-type {
            color: var(--accent);
            font-weight: 500;
        }

        .agent-id {
            color: var(--text-secondary);
        }

        .detail {
            color: var(--text-primary);
        }

        /* Chat Panel */
        .chat-panel {
            width: 350px;
            display: flex;
            flex-direction: column;
        }

        .chat-header {
            padding: 8px 16px;
            background: var(--bg-tertiary);
            font-weight: 600;
            font-size: 12px;
        }

        .chat-messages {
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }

        .chat-message {
            padding: 8px;
            margin-bottom: 8px;
            border-radius: 4px;
        }

        .chat-message.user {
            background: var(--accent-dim);
            margin-left: 32px;
        }

        .chat-message.agent {
            background: var(--bg-secondary);
            margin-right: 32px;
        }

        .chat-input-container {
            padding: 8px;
            border-top: 1px solid var(--border);
            display: flex;
            gap: 8px;
        }

        .chat-input {
            flex: 1;
            background: var(--bg-tertiary);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 8px 12px;
            color: var(--text-primary);
            font-family: inherit;
            font-size: 13px;
        }

        .chat-input:focus {
            outline: none;
            border-color: var(--accent);
        }

        .chat-send {
            background: var(--accent);
            border: none;
            border-radius: 4px;
            padding: 8px 16px;
            color: white;
            cursor: pointer;
            font-weight: 500;
        }

        .chat-send:hover {
            opacity: 0.9;
        }

        /* Empty State */
        .empty-state {
            display: flex;
            align-items: center;
            justify-content: center;
            height: 100%;
            color: var(--text-secondary);
            text-align: center;
            padding: 32px;
        }

        .loading {
            text-align: center;
            padding: 16px;
            color: var(--text-secondary);
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">Remora Swarm</div>
        <div class="agent-tree" id="agent-tree">
            <div class="loading">Loading agents...</div>
        </div>
    </div>

    <div class="main">
        <div class="detail-panel" id="detail-panel">
            <div class="empty-state">
                <div>
                    <div style="font-size: 48px; margin-bottom: 16px;">🐙</div>
                    <div>Select an agent from the tree to view details</div>
                </div>
            </div>
        </div>
    </div>

    <!-- Datastar initialization -->
    <div data-on-load="@get('/stream-events')"></div>

    <script>
        // Fetch and render agent tree on load
        async function loadAgentTree() {
            try {
                const response = await fetch('/api/agents');
                const data = await response.json();
                renderTree(data.agents);
            } catch (err) {
                document.getElementById('agent-tree').innerHTML =
                    '<div class="loading">Failed to load agents</div>';
            }
        }

        function renderTree(nodes, container = null) {
            if (!container) {
                container = document.getElementById('agent-tree');
                container.innerHTML = '';
            }

            nodes.forEach(node => {
                const div = document.createElement('div');
                div.className = `tree-node node-type-${node.type}`;
                div.dataset.id = node.id;

                div.innerHTML = `
                    <div class="tree-node-content" onclick="selectAgent('${node.id}')">
                        <span class="tree-icon"></span>
                        <span class="tree-name">${node.name}</span>
                        ${node.line ? `<span class="node-status">:${node.line}</span>` : ''}
                    </div>
                `;

                if (node.children && node.children.length > 0) {
                    const childContainer = document.createElement('div');
                    childContainer.className = 'tree-children';
                    renderTree(node.children, childContainer);
                    div.appendChild(childContainer);
                }

                container.appendChild(div);
            });
        }

        async function selectAgent(agentId) {
            // Update selection state
            document.querySelectorAll('.tree-node').forEach(n => n.classList.remove('selected'));
            const selected = document.querySelector(`[data-id="${agentId}"]`);
            if (selected) selected.classList.add('selected');

            // Fetch agent details
            try {
                const response = await fetch(`/api/agent/${encodeURIComponent(agentId)}`);
                const data = await response.json();
                renderAgentDetail(data);
            } catch (err) {
                console.error('Failed to load agent:', err);
            }
        }

        function renderAgentDetail(data) {
            const agent = data.agent;
            const events = data.recent_events || [];

            const panel = document.getElementById('detail-panel');
            panel.innerHTML = `
                <div class="detail-header">
                    <h2>${agent.name}</h2>
                    <div class="detail-meta">
                        <span>Type: ${agent.node_type}</span>
                        <span>File: ${agent.file_path.split('/').pop()}:${agent.start_line}</span>
                        <span>Status: ${agent.status}</span>
                    </div>
                </div>
                <div class="detail-body">
                    <div class="event-log">
                        <div class="event-log-header">Event Log</div>
                        <div class="event-log-content" id="agent-events">
                            ${events.map(ev => `
                                <div class="log-entry">
                                    <span class="event-type">[${ev.event_type}]</span>
                                    <span class="detail">${formatEventDetail(ev)}</span>
                                </div>
                            `).join('')}
                            ${events.length === 0 ? '<div class="loading">No events yet</div>' : ''}
                        </div>
                    </div>
                    <div class="chat-panel">
                        <div class="chat-header">Chat</div>
                        <div class="chat-messages" id="chat-messages"></div>
                        <div class="chat-input-container">
                            <input type="text" class="chat-input" id="chat-input"
                                   placeholder="Send a message..."
                                   onkeydown="if(event.key==='Enter') sendChat('${agent.id}')">
                            <button class="chat-send" onclick="sendChat('${agent.id}')">Send</button>
                        </div>
                    </div>
                </div>
            `;
        }

        function formatEventDetail(ev) {
            const payload = ev.payload || {};
            if (ev.event_type === 'AgentMessageEvent') {
                return `${payload.from_agent}: ${(payload.content || '').substring(0, 50)}`;
            }
            if (ev.event_type === 'ToolCallEvent') {
                return `Tool: ${payload.tool_name}`;
            }
            return JSON.stringify(payload).substring(0, 50);
        }

        async function sendChat(agentId) {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message) return;

            // Add to UI immediately
            const messages = document.getElementById('chat-messages');
            messages.innerHTML += `
                <div class="chat-message user">${message}</div>
            `;
            messages.scrollTop = messages.scrollHeight;
            input.value = '';

            // Send to server
            try {
                await fetch(`/api/agent/${encodeURIComponent(agentId)}/chat`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message }),
                });
            } catch (err) {
                console.error('Failed to send message:', err);
            }
        }

        // Load tree on page load
        loadAgentTree();

        // Refresh tree periodically
        setInterval(loadAgentTree, 30000);
    </script>
</body>
</html>
```

---

## 9. Phase 7: Web UI - Agent Detail Panel

The detail panel is already included in Phase 6. It shows:

1. **Agent header** with name, type, location, status
2. **Event log** showing recent events for this agent
3. **Chat panel** for sending messages

The SSE stream (`/stream-events`) will push new events that update the log in real-time via Datastar's fragment merging.

---

## 10. Running the Demo

### 10.1 Start the Daemon

```bash
cd /path/to/remora
uv run python src/remora/demo/nvim_server.py
```

You should see:
```
INFO:     Remora Demo Server started
INFO:       Web UI: http://localhost:8080
INFO:       Neovim socket: /run/user/1000/remora.sock
INFO:       AgentRunner: active
```

### 10.2 Open Web UI

Navigate to `http://localhost:8080` in your browser.

### 10.3 Connect Neovim

```vim
" Add to runtimepath
:set runtimepath+=/path/to/remora

" Initialize plugin
:lua require('remora_nvim').setup({ socket = '/run/user/1000/remora.sock' })

" Open a Python file
:e src/remora/core/swarm_state.py

" Toggle sidepanel
:RemoraToggle
```

### 10.4 Test the Demo

1. **Move cursor** around Python functions - sidepanel updates
2. **Press `<leader>rc`** to chat with current agent
3. **Type a message** - watch the play-by-play stream events
4. **Check Web UI** - see the tree populate, click an agent, send a chat

---

## 11. Testing & Verification

### 11.1 Verify Agent Discovery

After opening a Python file, you should see:
```
Remora: Registered 5 agents from swarm_state.py
```

### 11.2 Verify Push Notifications

1. Open sidepanel (`:RemoraToggle`)
2. Navigate to a function
3. Chat with it (`<leader>rc`, type "hello")
4. Watch the PLAY-BY-PLAY section stream events:
   - 💬 AgentMessageEvent (your message)
   - ▶️ AgentStartEvent
   - 🤖 ModelRequestEvent
   - 💭 ModelResponseEvent
   - ✅ AgentCompleteEvent

### 11.3 Verify Web UI Updates

1. Open `http://localhost:8080`
2. Check the tree shows agents from opened files
3. Click an agent, verify detail panel shows
4. Watch Live Swarm Logs stream events

### 11.4 Common Issues

| Issue | Solution |
|-------|----------|
| "Failed to connect" | Check daemon is running, socket path matches |
| "No agents registered" | Open a Python file first |
| Events not streaming | Check EventBus subscription in startup |
| LLM errors | Verify vLLM is running at remora-server:8000 |

---

## File Summary

| File | Lines | Purpose |
|------|-------|---------|
| `src/remora/demo/client_manager.py` | ~80 | Manage Neovim client subscriptions |
| `src/remora/demo/nvim_server.py` | ~350 | Main daemon server |
| `src/remora/demo/templates/index.html` | ~350 | Web UI with Datastar |
| `lua/remora_nvim/init.lua` | ~40 | Plugin setup |
| `lua/remora_nvim/bridge.lua` | ~100 | RPC + push notifications |
| `lua/remora_nvim/navigation.lua` | ~120 | Cursor tracking + discovery |
| `lua/remora_nvim/sidepanel.lua` | ~250 | Streaming event display |
| `lua/remora_nvim/chat.lua` | ~45 | Chat input |
| `plugin/remora_nvim.lua` | ~25 | User commands |
| **Total** | **~1360** | |

---

*Document version: 2.0*
*Status: Ready for Implementation*
