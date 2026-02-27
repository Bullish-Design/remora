"""Minimal Stario frontend that proxies a Remora backend."""

from __future__ import annotations

import asyncio
import os

import httpx
from stario import Context, RichTracer, Stario, Writer, at, data
from stario.html import Body, Div, Head, Html, Script, Title

REMORA_URL = os.environ.get("REMORA_URL", "http://localhost:8420")


def page(*children):
    return Html(
        {"lang": "en"},
        Head(
            Title("Remora (Stario)"),
            Script(
                {
                    "type": "module",
                    "src": "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js",
                }
            ),
        ),
        Body(
            data.init(at.get("/subscribe")),
            *children,
        ),
    )


async def index(_c: Context, w: Writer) -> None:
    w.html(page(Div({"id": "remora-root"}, "Connecting...")))


async def subscribe(_c: Context, w: Writer) -> None:
    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream("GET", f"{REMORA_URL}/subscribe") as response:
            async for chunk in response.aiter_text():
                # Stario supports streaming raw SSE frames; adjust if your Writer API differs.
                w.raw(chunk)


async def run(c: Context, w: Writer) -> None:
    payload = await c.req.json()
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{REMORA_URL}/run", json=payload)
    w.json(response.json())


async def submit_input(c: Context, w: Writer) -> None:
    payload = await c.req.json()
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{REMORA_URL}/input", json=payload)
    w.json(response.json())


async def main() -> None:
    with RichTracer() as tracer:
        app = Stario(tracer)
        app.get("/", index)
        app.get("/subscribe", subscribe)
        app.post("/run", run)
        app.post("/input", submit_input)
        await app.serve(port=9000)


if __name__ == "__main__":
    asyncio.run(main())
