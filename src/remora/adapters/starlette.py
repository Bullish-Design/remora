"""Starlette adapter for the Remora service API."""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from datastar_py.starlette import DatastarResponse
from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse
from starlette.routing import Route

from remora.models import PlanRequest, RunRequest
from remora.service.api import RemoraService


def create_app(service: RemoraService | None = None) -> Starlette:
    service = service or RemoraService.create_default()

    async def index(_request: Request) -> HTMLResponse:
        return HTMLResponse(service.index_html())

    async def subscribe(_request: Request) -> DatastarResponse:
        return DatastarResponse(service.subscribe_stream())

    async def events(_request: Request) -> StreamingResponse:
        return _sse_response(service.events_stream())

    async def run(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        run_request = RunRequest.from_dict(payload)
        try:
            response = await service.run(run_request)
        except ValueError as exc:
            return _error(str(exc), status_code=400)
        return JSONResponse(response.to_dict())

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

    async def plan(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        plan_request = PlanRequest.from_dict(payload)
        try:
            response = await service.plan(plan_request)
        except ValueError as exc:
            return _error(str(exc), status_code=400)
        return JSONResponse(response.to_dict())

    async def config(_request: Request) -> JSONResponse:
        return JSONResponse(service.config_snapshot().to_dict())

    async def snapshot(_request: Request) -> JSONResponse:
        return JSONResponse(service.ui_snapshot())

    routes = [
        Route("/", index),
        Route("/subscribe", subscribe),
        Route("/events", events),
        Route("/run", run, methods=["POST"]),
        Route("/input", submit_input, methods=["POST"]),
        Route("/plan", plan, methods=["POST"]),
        Route("/config", config),
        Route("/snapshot", snapshot),
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
