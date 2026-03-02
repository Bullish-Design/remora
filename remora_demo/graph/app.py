"""Starlette app for the Remora force-directed graph viewer.

Routes:
    GET /            -> HTML shell (initial page load)
    GET /subscribe   -> SSE: patch_signals with graph data
    GET /agent/{id}  -> HTML sidebar fragment for selected node
    POST /command    -> Queue a command for the LSP server
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from remora_demo.graph.shell import render_shell
from remora_demo.graph.sidebar import render_sidebar
from remora_demo.graph.state import GraphState

logger = logging.getLogger("remora.graph")


def create_app(db_path: str = ".remora/indexer.db") -> Starlette:
    """Create the Starlette ASGI app for the graph viewer."""
    state = GraphState(db_path=db_path)

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(render_shell())

    async def subscribe(_request: Request) -> DatastarResponse:
        async def stream() -> AsyncIterator[str]:
            # Initial data push
            try:
                snapshot = await asyncio.to_thread(state.read_snapshot)
                graph_data = _snapshot_to_signals(snapshot)
                yield SSE.patch_signals(json.dumps({"graph": graph_data}))
            except Exception:
                logger.exception("Error reading initial snapshot")

            # Stream changes
            async for snapshot in state.changes():
                try:
                    graph_data = _snapshot_to_signals(snapshot)
                    yield SSE.patch_signals(json.dumps({"graph": graph_data}))
                except Exception:
                    logger.debug("Error streaming snapshot", exc_info=True)

        return DatastarResponse(stream())

    async def agent_detail(request: Request) -> HTMLResponse:
        agent_id = request.path_params["id"]

        def _read():
            node = state.read_node(agent_id)
            events = state.read_events_for_agent(agent_id) if node else []
            proposals = state.read_proposals_for_agent(agent_id) if node else []
            connections = state.read_edges_for_node(agent_id) if node else {}
            return node, events, proposals, connections

        node, events, proposals, connections = await asyncio.to_thread(_read)
        html = render_sidebar(node, events, proposals, connections)
        return HTMLResponse(html)

    async def post_command(request: Request) -> JSONResponse:
        body = await request.json()
        command_type = body.get("command_type", "")
        agent_id = body.get("agent_id")
        payload = body.get("payload", {})

        if not command_type:
            return JSONResponse({"error": "command_type required"}, status_code=400)

        cmd_id = await asyncio.to_thread(state.push_command, command_type, agent_id, payload)
        return JSONResponse({"status": "queued", "command_id": cmd_id})

    async def on_shutdown() -> None:
        state.close()

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/agent/{id:path}", agent_detail),
        Route("/command", post_command, methods=["POST"]),
    ]

    return Starlette(routes=routes, on_shutdown=[on_shutdown])


def _snapshot_to_signals(snapshot) -> dict:
    """Convert a GraphSnapshot to the signal format the client expects."""
    nodes = []
    for n in snapshot.nodes:
        nodes.append(
            {
                "remora_id": n.get("remora_id", ""),
                "name": n.get("name", ""),
                "node_type": n.get("node_type", ""),
                "status": n.get("status", "active"),
                "file_path": n.get("file_path", ""),
            }
        )

    edges = []
    for e in snapshot.edges:
        edges.append(
            {
                "from_id": e.get("from_id", ""),
                "to_id": e.get("to_id", ""),
                "edge_type": e.get("edge_type", ""),
            }
        )

    focus = None
    if snapshot.cursor_focus:
        focus = snapshot.cursor_focus.get("agent_id")

    return {"nodes": nodes, "edges": edges, "focus": focus}
