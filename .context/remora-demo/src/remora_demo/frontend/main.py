"""
Remora Frontend - Stario app that proxies to hub.

This is a minimal Stario app that:
1. Serves the SPA on /
2. Proxies /subscribe to hub's SSE (pass-through)
3. Proxies API calls to hub
"""

import logging
from dataclasses import dataclass

import aiohttp

from stario import Context, RichTracer, Stario, Writer
from stario.http.writer import CompressionConfig

from .views import render_home

HUB_URL = "http://localhost:8000"

logger = logging.getLogger(__name__)


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
    html_content = render_home()
    w.respond(html_content.encode(), b"text/html; charset=utf-8", 200)


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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{HUB_URL}/subscribe") as resp:
                async for chunk in resp.content.iter_any():
                    w.write(chunk)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to connect to hub: {e}")
        w.write(b"")


async def execute_graph(c: Context, w: Writer) -> None:
    """Proxy graph execution to hub."""
    signals = await c.signals(ExecuteSignals)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{HUB_URL}/graph/execute", json={"graph_id": signals.graph_id}) as resp:
                result = await resp.json()
                w.json(result)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to execute graph: {e}")
        w.json({"error": str(e)})


async def respond(c: Context, w: Writer) -> None:
    """Proxy agent response to hub - user responds to blocked agent."""
    # Extract agent_id from the tail path (e.g., /agent/agent-1/respond -> agent_id = agent-1)
    tail = c.req.tail or ""
    parts = tail.strip("/").split("/")
    agent_id = parts[0] if parts else ""

    signals = await c.signals(RespondSignals)

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{HUB_URL}/agent/{agent_id}/respond",
                json={
                    "msg_id": signals.msg_id,
                    "question": signals.question,
                    "answer": signals.answer,
                },
            ) as resp:
                result = await resp.json()
                w.json(result)
    except aiohttp.ClientError as e:
        logger.error(f"Failed to send response: {e}")
        w.json({"error": str(e)})


async def run_app() -> None:
    """Run the Remora Frontend server."""
    tracer = RichTracer()

    with tracer:
        app = Stario(tracer, compression=CompressionConfig())

        app.assets("/static", "src/remora_demo/static")

        app.get("/", home)
        app.get("/subscribe", subscribe)
        app.post("/graph/execute", execute_graph)
        app.post("/agent/*", respond)

        await app.serve(host="0.0.0.0", port=8001)


def main() -> None:
    """Entry point for the remora-frontend script."""
    logging.basicConfig(level=logging.INFO)
    import asyncio

    asyncio.run(run_app())


if __name__ == "__main__":
    main()
