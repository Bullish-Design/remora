"""Starlette app for the Remora web graph view.

Routes:
    GET /           -> HTML shell (initial page load)
    GET /subscribe  -> SSE stream (datastar patches on DB changes)
    GET /agent/{id} -> SSE patch with agent detail sidebar
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Route

from remora_demo.web.render import render_agent_detail, render_graph, render_shell
from remora_demo.web.state import GraphState

logger = logging.getLogger("remora.web")


def create_app(db_path: str = ".remora/indexer.db") -> Starlette:
    """Create the Starlette ASGI app for the graph viewer."""
    state = GraphState(db_path=db_path)

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(render_shell())

    async def subscribe(_request: Request) -> DatastarResponse:
        async def stream() -> AsyncIterator[str]:
            # Initial full render
            try:
                snapshot = await asyncio.to_thread(state.read_snapshot)
                yield SSE.patch_elements(render_graph(snapshot))
            except Exception:
                logger.exception("Error reading initial snapshot")
                yield SSE.patch_elements(
                    '<div id="graph-content"><div class="empty-state">Error reading database</div></div>'
                )

            # Stream changes
            async for snapshot in state.changes():
                try:
                    yield SSE.patch_elements(render_graph(snapshot))
                except Exception:
                    logger.debug("Error rendering snapshot", exc_info=True)

        return DatastarResponse(stream())

    async def agent_detail(request: Request) -> DatastarResponse:
        agent_id = request.path_params["id"]

        def _read():
            node = state.read_node(agent_id)
            events = state.read_recent_events(agent_id) if node else []
            return node, events

        node, events = await asyncio.to_thread(_read)

        if not node:
            html = '<div id="agent-detail"><div class="sidebar-empty">Agent not found</div></div>'
        else:
            html = render_agent_detail(node, events)

        return DatastarResponse(SSE.patch_elements(html))

    async def on_shutdown() -> None:
        state.close()

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/agent/{id:path}", agent_detail),
    ]

    return Starlette(
        routes=routes,
        on_shutdown=[on_shutdown],
    )
