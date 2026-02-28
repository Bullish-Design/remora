import asyncio
import json
import os
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datastar_py.sse import ServerSentEventGenerator
import uvicorn

from remora.core.config import load_config
from remora.core.swarm_state import SwarmState
from remora.core.event_store import EventStore
from remora.core.event_bus import EventBus
from remora.core.events import RemoraEvent

# Initialize Core Remora Services
config = load_config()
db_path = Path(config.swarm_root) / config.swarm_id / "workspace.db"
swarm_state = SwarmState(db_path)
event_bus = EventBus()
event_store = EventStore(db_path, event_bus=event_bus)

app = FastAPI(title="Remora Swarm Dashboard")
templates = Jinja2Templates(directory="src/remora/demo/templates")
SOCKET_PATH = config.nvim_socket or "/tmp/remora.sock"


# ---- Neovim RPC Server (Unix Socket) ----
async def handle_nvim_client(reader, writer):
    try:
        while True:
            line = await reader.readline()
            if not line:
                break

            request = json.loads(line.decode())
            method = request.get("method")
            params = request.get("params", {})
            msg_id = request.get("id")

            if method == "agent.select":
                agent_id = params.get("id")

                # Fetch Real State from Remora SwarmState
                agent_meta = await swarm_state.get_agent(agent_id)
                status = agent_meta.status if agent_meta else "NOT_FOUND"

                # We could fetch real triggers by querying the EventStore in a production app
                response = {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "status": status,
                        "triggers": [],  # Keep MVP simple
                    },
                }
                writer.write(json.dumps(response).encode() + b"\n")
                await writer.drain()
    except Exception as e:
        print(f"RPC Error: {e}")
    finally:
        writer.close()


async def start_rpc_server():
    Path(SOCKET_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(SOCKET_PATH).unlink(missing_ok=True)
    server = await asyncio.start_unix_server(handle_nvim_client, path=SOCKET_PATH)
    async with server:
        await server.serve_forever()


@app.on_event("startup")
async def startup_event():
    # Initialize Databases
    await swarm_state.initialize()
    await event_store.initialize()

    # Start Neovim tracking socket
    asyncio.create_task(start_rpc_server())


# ---- Datastar Web UI Server ----


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    # Pass initial state for the tree. In reality, read from actual projects.
    tree_data = [
        {
            "name": "src",
            "type": "dir",
            "children": [
                {
                    "name": "utils.py",
                    "type": "file",
                    "agents": [{"id": "func_format_date_15", "name": "format_date", "status": "DORMANT"}],
                }
            ],
        }
    ]
    return templates.TemplateResponse("index.html", {"request": request, "tree": tree_data})


@app.get("/stream-events")
async def stream_events(request: Request):
    """Datastar SSE endpoint for real-time updates."""

    async def sse_generator():
        # Yield the initial connection message
        yield ServerSentEventGenerator.merge_fragments(
            fragments='<div id="logs" data-prepend><li>Connected to Swarm EventBus...</li></div>'
        )

        # Subscribe to EventBus to receive all RemoraEvents asynchronously
        queue = asyncio.Queue()

        async def event_handler(event: RemoraEvent):
            await queue.put(event)

        event_bus.subscribe_all(event_handler)

        try:
            while True:
                # Wait for next event from Swarm
                event = await queue.get()

                # Format the log line based on the event type
                event_type = type(event).__name__
                agent_id = getattr(
                    event, "agent_id", getattr(event, "to_agent", getattr(event, "from_agent", "System"))
                )

                html_fragment = f'<div id="logs" data-prepend><li>[{event_type}] {agent_id}</li></div>'

                # Datastar merge_fragments tells the frontend to update specific HTML fragments
                yield ServerSentEventGenerator.merge_fragments(fragments=html_fragment)
        except asyncio.CancelledError:
            event_bus.unsubscribe_all(event_handler)

    return ServerSentEventGenerator(sse_generator())


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
