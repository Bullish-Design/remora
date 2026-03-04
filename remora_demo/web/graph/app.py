"""Stario app factory — wires routes, handlers, bridge, and layout.

This module requires Python 3.14 and the Stario framework.
It will NOT import under Python 3.13 — the view/layout/css/svg modules
are fully testable without it.

Architecture:
- Closure-based DI: each handler factory captures (state, layout, relay)
- Views return plain HTML strings; wrapped in SafeString for w.patch()
- w.html() accepts strings directly for full-page responses
- DB polling bridge runs as a background asyncio task
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from stario import Context, Relay, RichTracer, Stario, Writer
from stario.html import SafeString

from remora_demo.web.graph.bridge import DBBridge
from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphState
from remora_demo.web.graph.views.event_stream import render_event_list
from remora_demo.web.graph.views.graph import render_graph
from remora_demo.web.graph.views.shell import render_shell
from remora_demo.web.graph.views.sidebar import render_sidebar_content

logger = logging.getLogger("remora.graph.app")


# ── Signal schemas ──


@dataclass
class CommandSignals:
    """Signals sent from the command form (chat, approve, reject)."""

    command_type: str = ""
    agent_id: str = ""
    payload: str = ""  # JSON string


# ── Handler factories ──


def index(state: GraphState, layout: ForceLayout):
    """GET / — Serve the full HTML page with initial graph."""

    async def handler(c: Context, w: Writer) -> None:
        snapshot = await asyncio.to_thread(state.read_snapshot)
        layout.set_graph(
            [
                {
                    "id": n.get("remora_id", n.get("id", "")),
                    "node_type": n.get("node_type", "function"),
                }
                for n in snapshot.nodes
            ],
            snapshot.edges,
        )
        layout.step(150)
        positions = layout.get_positions()
        w.html(render_shell(snapshot, positions))

    return handler


def subscribe(state: GraphState, layout: ForceLayout, relay: Relay):
    """GET /subscribe — SSE endpoint. Pushes DOM patches on graph changes."""

    async def handler(c: Context, w: Writer) -> None:
        c("subscribe.connected")

        # Send initial state
        snapshot = await asyncio.to_thread(state.read_snapshot)
        positions = layout.get_positions()
        w.patch(SafeString(render_graph(snapshot, positions)))

        events = await asyncio.to_thread(state.read_recent_events, 30)
        w.patch(SafeString(render_event_list(events)))

        # Stream updates
        async for subject, _change_type in w.alive(relay.subscribe("graph.*")):
            c("subscribe.event", {"subject": subject})

            if subject in ("graph.topology", "graph.status", "graph.cursor"):
                snapshot = await asyncio.to_thread(state.read_snapshot)
                positions = layout.get_positions()
                cf = snapshot.cursor_focus.get("agent_id") if snapshot.cursor_focus else None
                w.patch(SafeString(render_graph(snapshot, positions, cursor_focus=cf)))

            if subject == "graph.events":
                events = await asyncio.to_thread(state.read_recent_events, 30)
                w.patch(SafeString(render_event_list(events)))

        c("subscribe.disconnected")

    return handler


def agent_detail(state: GraphState):
    """GET /agent/* — Sidebar content for a selected node."""

    async def handler(c: Context, w: Writer) -> None:
        agent_id = c.req.tail
        if not agent_id:
            w.html(SafeString(render_sidebar_content(None, [], [], {})))
            return

        node = await asyncio.to_thread(state.read_node, agent_id)
        events = await asyncio.to_thread(state.read_events_for_agent, agent_id) if node else []
        proposals = await asyncio.to_thread(state.read_proposals_for_agent, agent_id) if node else []
        connections = await asyncio.to_thread(state.read_edges_for_node, agent_id) if node else {}
        w.html(SafeString(render_sidebar_content(node, events, proposals, connections)))

    return handler


def event_stream(state: GraphState):
    """GET /events — Returns the recent event list HTML fragment."""

    async def handler(c: Context, w: Writer) -> None:
        events = await asyncio.to_thread(state.read_recent_events, 30)
        w.html(SafeString(render_event_list(events)))

    return handler


def post_command(state: GraphState):
    """POST /command — Queue a command for the LSP server via command_queue."""

    async def handler(c: Context, w: Writer) -> None:
        signals = await c.signals(CommandSignals)

        if not signals.command_type:
            w.json({"error": "command_type required"}, status=400)
            return

        payload = json.loads(signals.payload) if signals.payload else {}
        cmd_id = await asyncio.to_thread(
            state.push_command,
            signals.command_type,
            signals.agent_id or None,
            payload,
        )
        c("command.queued", {"command_id": cmd_id, "type": signals.command_type})
        w.json({"status": "queued", "command_id": cmd_id})

    return handler


# ── App factory ──


def create_app(
    db_path: str = ".remora/indexer.db",
    poll_interval: float = 0.3,
) -> tuple[Stario, DBBridge]:
    """Create the Stario graph viewer app.

    Returns (app, bridge) so the caller can start the bridge as a background task
    before calling app.serve().

    Usage::

        app, bridge = create_app("/path/to/indexer.db")
        asyncio.create_task(bridge.run())
        await app.serve(host="127.0.0.1", port=8080)
    """
    tracer = RichTracer()
    app = Stario(tracer)

    state = GraphState(db_path=db_path)
    layout = ForceLayout(width=900, height=600)
    relay: Relay = Relay()
    bridge = DBBridge(state=state, layout=layout, relay=relay, poll_interval=poll_interval)

    # Routes
    app.get("/", index(state, layout))
    app.get("/subscribe", subscribe(state, layout, relay))
    app.get("/agent/*", agent_detail(state))
    app.get("/events", event_stream(state))
    app.post("/command", post_command(state))

    return app, bridge
