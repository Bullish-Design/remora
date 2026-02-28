"""Starlette adapter for the Remora service API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from datastar_py.starlette import DatastarResponse
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from remora.service.api import RemoraService


def create_app(service: RemoraService | None = None) -> Starlette:
    service = service or RemoraService.create_default()

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(service.index_html())

    async def subscribe(_request: Request) -> DatastarResponse:
        return DatastarResponse(service.subscribe_stream())

    async def events(_request: Request) -> StreamingResponse:
        return _sse_response(service.events_stream())

    async def replay(request: Request) -> StreamingResponse | JSONResponse:
        graph_id = request.query_params.get("graph_id")
        if not graph_id:
            return _error("graph_id required", status_code=400)
        if not service.has_event_store:
            return _error("event store not configured", status_code=400)
        follow = request.query_params.get("follow", "").lower() in {"1", "true", "yes"}

        async def generate():
            last_id = 0
            while True:
                emitted = False
                async for event in service.replay_events(graph_id, after_id=last_id):
                    payload = json.dumps(event, default=str)
                    last_id = int(event.get("id", last_id))
                    emitted = True
                    yield f"event: replay\ndata: {payload}\n\n"
                if not follow:
                    break
                if not emitted:
                    yield ": ping\n\n"
                await asyncio.sleep(0.5)

        return _sse_response(generate())

    async def submit_input(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        request_id = str(payload.get("request_id", "")).strip()
        response_text = str(payload.get("response", "")).strip()
        try:
            response = await service.input(request_id, response_text)
        except ValueError as exc:
            return _error(str(exc), status_code=400)
        return JSONResponse(response.to_dict())

    async def config(_request: Request) -> JSONResponse:
        return JSONResponse(service.config_snapshot().to_dict())

    async def snapshot(_request: Request) -> JSONResponse:
        return JSONResponse(service.ui_snapshot())

    async def swarm_agents(_request: Request) -> JSONResponse:
        return JSONResponse(service.list_agents())

    async def swarm_agent(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        try:
            return JSONResponse(service.get_agent(agent_id))
        except ValueError as exc:
            return _error(str(exc), status_code=404)

    async def swarm_events(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        event_type = payload.get("event_type")
        data = payload.get("data", {})
        try:
            result = await service.emit_event(event_type, data)
        except ValueError as exc:
            return _error(str(exc), status_code=400)
        return JSONResponse(result)

    async def swarm_subscriptions(request: Request) -> JSONResponse:
        agent_id = request.path_params["id"]
        try:
            result = await service.get_subscriptions(agent_id)
        except ValueError as exc:
            return _error(str(exc), status_code=404)
        return JSONResponse(result)

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/events", events),
        Route("/replay", replay),
        Route("/input", submit_input, methods=["POST"]),
        Route("/config", config),
        Route("/snapshot", snapshot),
        Route("/swarm/agents", swarm_agents),
        Route("/swarm/agents/{id}", swarm_agent),
        Route("/swarm/events", swarm_events, methods=["POST"]),
        Route("/swarm/subscriptions/{id}", swarm_subscriptions),
    ]

    return Starlette(routes=routes)


def _sse_response(generator: Any) -> StreamingResponse:
    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(generator, media_type="text/event-stream", headers=headers)


def _error(message: str, *, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


__all__ = ["create_app"]
