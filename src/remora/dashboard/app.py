"""Starlette application for the dashboard."""

import asyncio
import logging
import uuid
from typing import Any

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from remora.config import load_config
from remora.context import ContextBuilder
from remora.dashboard.state import DashboardState
from remora.dashboard import views
from remora.event_bus import get_event_bus
from remora.events import HumanInputResponseEvent

logger = logging.getLogger(__name__)


class DashboardApp:
    """Dashboard Starlette application."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self._event_bus = get_event_bus()
        self._dashboard_state = DashboardState()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._context_builder = ContextBuilder()
        self._remora_config = load_config()

    @property
    def app(self) -> Starlette:
        """Build the Starlette application."""
        return Starlette(
            routes=[
                Route("/", views.index),
                Route("/subscribe", self.subscribe),
                Route("/events", self.events),
                Route("/run", self.run_agent, methods=["POST"]),
                Route("/input", self.submit_input, methods=["POST"]),
            ],
            debug=self.config.get("debug", False),
        )

    async def subscribe(self, request: Request) -> DatastarResponse:
        """SSE endpoint - streams complete view snapshots via Datastar."""

        @datastar_response
        async def event_stream():
            view_data = self._dashboard_state.get_view_data()
            yield SSE.patch_elements(views.dashboard_view(view_data))

            async for event in self._event_bus.stream():
                self._dashboard_state.record(event)
                view_data = self._dashboard_state.get_view_data()
                yield SSE.patch_elements(views.dashboard_view(view_data))

        return await event_stream()

    async def events(self, request: Request) -> StreamingResponse:
        """Raw SSE endpoint - streams events as JSON for API clients."""

        async def event_generator():
            try:
                async for event in self._event_bus.stream():
                    self._dashboard_state.record(event)
                    event_type = type(event).__name__
                    data = {
                        "event_type": event_type,
                        "graph_id": getattr(event, "graph_id", ""),
                        "agent_id": getattr(event, "agent_id", ""),
                        "timestamp": getattr(event, "timestamp", 0),
                    }
                    yield f"event: {event_type}\ndata: {data}\n\n"
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Error in events stream")
                pass

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    async def run_agent(self, request: Request) -> JSONResponse:
        """Trigger a graph execution."""
        try:
            body = await request.json()
        except Exception:
            body = {}

        target_path = body.get("target_path", "")
        bundle = body.get("bundle", "lint")

        if not target_path:
            return JSONResponse(
                {"error": "target_path is required"},
                status_code=400,
            )

        graph_id = await self._trigger_graph(target_path, bundle)

        return JSONResponse(
            {
                "status": "started",
                "graph_id": graph_id,
            }
        )

    async def _trigger_graph(self, target_path: str, bundle: str) -> str:
        """Trigger graph execution via the executor."""
        from remora.graph import build_graph
        from remora.discovery import discover
        from pathlib import Path

        graph_id = uuid.uuid4().hex[:8]

        try:
            nodes = discover([Path(target_path)])
            metadata = self._remora_config.bundle_metadata
            agent_nodes = build_graph(nodes, metadata, config=self._remora_config)

            if bundle and bundle in metadata:
                bundle_path = metadata[bundle].path
                agent_nodes = [node for node in agent_nodes if node.bundle_path == bundle_path]

            task = asyncio.create_task(self._execute_graph(graph_id, agent_nodes))
            self._running_tasks[graph_id] = task
        except Exception:
            logger.exception("Failed to build graph")
            raise

        return graph_id

    async def _execute_graph(self, graph_id: str, agent_nodes: list) -> None:
        """Execute the graph asynchronously."""
        from remora.executor import GraphExecutor, ExecutionConfig
        from remora.event_bus import get_event_bus

        try:
            config = ExecutionConfig(
                max_concurrency=4,
                timeout=300.0,
            )
            executor = GraphExecutor(
                config=config,
                event_bus=get_event_bus(),
                remora_config=self._remora_config,
                context_builder=self._context_builder,
            )
            await executor.run(agent_nodes, self._remora_config.workspace)
        except Exception:
            logger.exception("Graph execution failed")

    async def submit_input(self, request: Request) -> JSONResponse:
        """Submit human input for blocked agent."""
        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "Invalid JSON"}, status_code=400)

        request_id = body.get("request_id", "")
        response = body.get("response", "")

        if not request_id or not response:
            return JSONResponse(
                {"error": "request_id and response are required"},
                status_code=400,
            )

        event = HumanInputResponseEvent(
            request_id=request_id,
            response=response,
        )
        await self._event_bus.emit(event)

        return JSONResponse({"status": "submitted"})


def create_app(config: dict[str, Any] | None = None) -> Starlette:
    """Create the dashboard Starlette application."""
    dashboard_app = DashboardApp(config)
    return dashboard_app.app
