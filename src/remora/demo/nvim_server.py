"""Remora Demo Server - FastAPI + Neovim RPC with push notifications."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from remora.core.config import load_config
from remora.core.discovery import CSTNode, parse_file
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore
from remora.core.events import RemoraEvent, AgentMessageEvent
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.demo.client_manager import ClientManager, NvimClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

config = load_config()
db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"

swarm_state = SwarmState(db_path)
event_bus = EventBus()
subscriptions = SubscriptionRegistry(db_path)
event_store = EventStore(db_path, subscriptions=subscriptions, event_bus=event_bus)
client_manager = ClientManager()

app = FastAPI(title="Remora Swarm Dashboard")
templates = Jinja2Templates(directory="src/remora/demo/templates")
SOCKET_PATH = getattr(config, "nvim_socket", "/run/user/1000/remora.sock")


async def push_to_clients(event: RemoraEvent) -> None:
    """Forward EventBus events to subscribed Neovim clients."""
    await client_manager.notify_event(event)


async def handle_nvim_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle RPC requests from a connected Neovim client."""
    client = await client_manager.register(writer)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                request = json.loads(line.decode())
            except json.JSONDecodeError as exc:
                logger.warning("Invalid JSON from %s: %s", client.client_id, exc)
                continue

            method = request.get("method", "")
            params = request.get("params", {}) or {}
            msg_id = request.get("id")

            result = await handle_rpc_method(client, method, params)

            if msg_id is not None:
                response = {"jsonrpc": "2.0", "id": msg_id, "result": result}
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()

    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("RPC error for %s: %s", client.client_id, exc)
    finally:
        await client_manager.unregister(client)
        writer.close()
        await writer.wait_closed()


async def handle_rpc_method(client: NvimClient, method: str, params: dict) -> dict:
    """Dispatch JSON-RPC requests from Neovim."""
    if method == "agent.select":
        return await rpc_agent_select(params)
    if method == "agent.subscribe":
        return await rpc_agent_subscribe(client, params)
    if method == "agent.chat":
        return await rpc_agent_chat(params)
    if method == "buffer.opened":
        return await rpc_buffer_opened(params)
    if method == "agent.get_events":
        return await rpc_get_events(params)
    return {"error": f"Unknown method: {method}"}


async def rpc_agent_select(params: dict) -> dict:
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
                "id": sub.id,
                "pattern": {
                    "event_types": sub.pattern.event_types,
                    "to_agent": sub.pattern.to_agent,
                    "path_glob": sub.pattern.path_glob,
                },
                "is_default": sub.is_default,
            }
            for sub in subs
        ],
    }


async def rpc_agent_subscribe(client: NvimClient, params: dict) -> dict:
    agent_id = params.get("id") or params.get("agent_id")
    if not agent_id:
        return {"error": "Missing agent_id"}
    await client_manager.subscribe(client, agent_id)
    return {"subscribed": agent_id}


async def rpc_agent_chat(params: dict) -> dict:
    agent_id = params.get("id") or params.get("agent_id")
    message = params.get("message", "")
    if not agent_id or not message:
        return {"error": "Missing agent_id or message"}

    event = AgentMessageEvent(
        from_agent="user",
        to_agent=agent_id,
        content=message,
        tags=["user_chat"],
    )

    event_id = await event_store.append(config.swarm_id, event)

    return {"event_id": event_id, "status": "sent"}


async def rpc_buffer_opened(params: dict) -> dict:
    file_path = params.get("path")
    if not file_path:
        return {"error": "Missing path"}

    path = Path(file_path)
    if not path.exists():
        return {"error": f"File not found: {file_path}"}
    if path.suffix != ".py":
        return {"agents": [], "message": "Only Python files supported"}

    try:
        nodes = parse_file(path)
    except Exception as exc:
        logger.error("Failed to parse %s: %s", file_path, exc)
        return {"error": str(exc)}

    registered = []
    for node in nodes:
        agent_id = compute_agent_id(node, path)
        metadata = AgentMetadata(
            agent_id=agent_id,
            node_type=node.node_type,
            name=node.name,
            full_name=f"{path.stem}.{node.name}",
            file_path=str(path),
            parent_id=None,
            start_line=node.start_line,
            end_line=node.end_line,
            status="active",
        )

        await swarm_state.upsert(metadata)
        await subscriptions.register_defaults(agent_id, str(path))

        registered.append(
            {
                "agent_id": agent_id,
                "name": node.name,
                "type": node.node_type,
                "line": node.start_line,
            }
        )

    logger.info("Registered %d agents from %s", len(registered), file_path)

    return {"agents": registered}


async def rpc_get_events(params: dict) -> dict:
    agent_id = params.get("id") or params.get("agent_id")
    limit = params.get("limit", 20)
    if not agent_id:
        return {"error": "Missing agent_id"}

    events: list[dict] = []
    async for event in event_store.replay(config.swarm_id):
        if (
            event.get("to_agent") == agent_id
            or event.get("from_agent") == agent_id
            or event.get("payload", {}).get("agent_id") == agent_id
        ):
            events.append(event)
            if len(events) >= limit:
                break

    return {"events": events[-limit:]}


def compute_agent_id(node: CSTNode, file_path: Path) -> str:
    return f"{node.node_type}_{file_path.stem}_{node.start_line}"


async def start_rpc_server():
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SOCKET_PATH).unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle_nvim_client, path=SOCKET_PATH)
    logger.info("Neovim RPC server listening on %s", SOCKET_PATH)
    async with server:
        await server.serve_forever()


@app.on_event("startup")
async def startup_event():
    await swarm_state.initialize()
    await subscriptions.initialize()
    await event_store.initialize()

    event_bus.subscribe_all(push_to_clients)
    asyncio.create_task(start_rpc_server())

    logger.info("Remora Demo Server started")
    logger.info("  Web UI: http://localhost:8080")
    logger.info("  Neovim socket: %s", SOCKET_PATH)


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/agents")
async def get_agents():
    agents = await swarm_state.list_agents(status="active")
    tree = build_agent_tree(agents)
    return {"agents": tree}


@app.get("/api/agent/{agent_id}")
async def get_agent_detail(agent_id: str):
    agent = await swarm_state.get_agent(agent_id)
    if not agent:
        return {"error": "Agent not found"}

    subs = await subscriptions.get_subscriptions(agent_id)
    events: list[dict] = []
    async for event in event_store.replay(config.swarm_id):
        if event.get("to_agent") == agent_id or event.get("from_agent") == agent_id:
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
        "subscriptions": [{"id": sub.id, "is_default": sub.is_default} for sub in subs],
        "recent_events": events[-20:],
    }


@app.post("/api/agent/{agent_id}/chat")
async def post_agent_chat(agent_id: str, request: Request):
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
    """SSE endpoint for real-time events."""
    from datastar_py.sse import ServerSentEventGenerator

    async def sse_generator():
        yield ServerSentEventGenerator.merge_fragments(
            '<div id="logs" data-prepend><li class="log-entry">Connected to Swarm EventBus...</li></div>'
        )

        queue: asyncio.Queue[RemoraEvent] = asyncio.Queue()

        async def handler(event: RemoraEvent):
            await queue.put(event)

        event_bus.subscribe_all(handler)

        try:
            while True:
                event = await queue.get()
                event_type = type(event).__name__
                agent_id = (
                    getattr(event, "agent_id", None)
                    or getattr(event, "to_agent", None)
                    or getattr(event, "from_agent", None)
                    or "system"
                )

                if event_type == "ToolCallEvent":
                    tool_name = getattr(event, "tool_name", "unknown")
                    detail = f"Tool: {tool_name}"
                elif event_type == "ModelResponseEvent":
                    detail = f"Response: {(getattr(event, 'content', '') or '')[:50]}..."
                elif event_type == "AgentMessageEvent":
                    detail = f"Message: {(getattr(event, 'content', '') or '')[:50]}..."
                else:
                    detail = ""

                html = f'''
                    <div id="logs" data-prepend>
                        <li class="log-entry">
                            <span class="event-type">[{event_type}]</span>
                            <span class="agent-id">{agent_id}</span>
                            <span class="detail">{detail}</span>
                        </li>
                    </div>
                '''

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
        },
    )


def build_agent_tree(agents: list[AgentMetadata]) -> list[dict]:
    by_file: dict[str, list[AgentMetadata]] = {}
    for agent in agents:
        by_file.setdefault(agent.file_path, []).append(agent)

    tree = []
    for file_path, file_agents in by_file.items():
        agents_by_id = {a.agent_id: a for a in file_agents}
        children_map: dict[str | None, list[AgentMetadata]] = {None: []}

        for agent in file_agents:
            parent_id = agent.parent_id
            children_map.setdefault(parent_id, []).append(agent)

        def build_node(agent: AgentMetadata) -> dict:
            children = children_map.get(agent.agent_id, [])
            return {
                "id": agent.agent_id,
                "name": agent.name,
                "type": agent.node_type,
                "line": agent.start_line,
                "children": [build_node(child) for child in sorted(children, key=lambda x: x.start_line)],
            }

        roots = [
            agent
            for agent in file_agents
            if agent.parent_id is None or agent.parent_id not in agents_by_id
        ]

        file_node = {
            "id": f"file_{Path(file_path).stem}",
            "name": Path(file_path).name,
            "type": "file",
            "path": file_path,
            "children": [build_node(r) for r in sorted(roots, key=lambda x: x.start_line)],
        }

        tree.append(file_node)

    return sorted(tree, key=lambda x: x["name"])


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
