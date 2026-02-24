import asyncio
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response, read_signals

from remora.event_bus import Event, EventBus, get_event_bus
from remora.frontend.registry import workspace_registry
from remora.interactive import WorkspaceInboxCoordinator
from remora.workspace import GraphWorkspace, WorkspaceManager

from .state import HubState
from .views import dashboard_view


logger = logging.getLogger(__name__)


class HubServer:
    """The Remora Hub - agent execution server."""

    def __init__(
        self,
        workspace_path: Path,
        host: str = "0.0.0.0",
        port: int = 8000,
    ):
        self.workspace_path = workspace_path
        self.host = host
        self.port = port

        self._event_bus: EventBus | None = None
        self._coordinator: WorkspaceInboxCoordinator | None = None
        self._workspace_manager: WorkspaceManager | None = None

        self._hub_state = HubState()

        self._app: Starlette | None = None

    async def start(self) -> None:
        """Start the hub server."""
        logger.info(f"Starting Remora Hub at {self.host}:{self.port}")

        self._event_bus = get_event_bus()
        self._workspace_manager = WorkspaceManager()
        self._coordinator = WorkspaceInboxCoordinator(self._event_bus)

        await self._event_bus.subscribe("agent:*", self._on_event)

        self._app = Starlette(
            routes=[
                Route("/", self.home),
                Route("/subscribe", self.subscribe),
                Route("/graph/execute", self.execute_graph, methods=["POST"]),
                Route("/agent/{agent_id}/respond", self.respond, methods=["POST"]),
                Mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static"),
            ],
        )

        import uvicorn

        config = uvicorn.Config(self._app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    async def _on_event(self, event: Event) -> None:
        """Handle incoming events - update state."""
        self._hub_state.record(event)

    async def home(self, request: Request) -> HTMLResponse:
        """Serve initial dashboard page."""
        view_data = self._hub_state.get_view_data()
        html = dashboard_view(view_data)
        return HTMLResponse(html)

    async def subscribe(self, request: Request) -> DatastarResponse:
        """
        SSE endpoint - streams complete view snapshots.

        Key datastar-py pattern:
        1. Send initial state via SSE.patch_elements()
        2. Loop until disconnect, re-rendering view on each event
        """

        @datastar_response
        async def event_stream():
            view_data = self._hub_state.get_view_data()
            yield SSE.patch_elements(dashboard_view(view_data))

            async for _ in self._event_bus.stream():
                view_data = self._hub_state.get_view_data()
                yield SSE.patch_elements(dashboard_view(view_data))

        return await event_stream(request)

    async def execute_graph(self, request: Request) -> JSONResponse:
        """Execute an agent graph - starts agents in the graph."""
        signals = await read_signals(request) or {}
        graph_id = signals.get("graph_id", "")

        if not graph_id:
            return JSONResponse({"error": "graph_id required"}, status_code=400)

        workspace = await self._workspace_manager.create(graph_id)

        demo_agents = [
            {"id": "root-1", "name": "Root Analyzer", "parent": None},
            {"id": "root-2", "name": "Root Validator", "parent": None},
            {"id": "branch-a", "name": "Branch A", "parent": "root-1"},
            {"id": "leaf-a1", "name": "Leaf A1", "parent": "branch-a"},
        ]

        for agent in demo_agents:
            agent_id = agent["id"]
            await workspace_registry.register(agent_id, workspace.id, workspace)
            await self._coordinator.watch_workspace(agent_id, workspace)
            await self._event_bus.publish(
                Event.agent_started(
                    agent_id=agent_id,
                    name=agent["name"],
                    workspace_id=workspace.id,
                    parent_id=agent["parent"],
                )
            )

        return JSONResponse(
            {
                "status": "started",
                "graph_id": graph_id,
                "agents": len(demo_agents),
                "workspace": workspace.id,
            }
        )

    async def respond(self, request: Request, agent_id: str) -> JSONResponse:
        """
        Handle user response to an agent's blocked question.

        This is the KEY endpoint for user interaction:
        1. Find the agent's workspace
        2. Write response to workspace KV (inbox:response:{msg_id})
        3. Coordinator publishes agent_resumed event
        """
        signals = await read_signals(request) or {}
        answer = signals.get("answer", "")
        question = signals.get("question", "")

        msg_id = signals.get("msg_id", "")
        if not msg_id:
            for blocked in self._hub_state.blocked.values():
                if blocked.get("agent_id") == agent_id:
                    msg_id = blocked.get("msg_id", "")
                    if msg_id:
                        break

        if not msg_id:
            return JSONResponse(
                {"error": "No pending question found for this agent. Is the agent still running?"}, status_code=400
            )

        workspace = workspace_registry.get_workspace(agent_id)
        if not workspace:
            return JSONResponse({"error": "No workspace found for agent. Is the agent still running?"}, status_code=400)

        await self._coordinator.respond(
            agent_id=agent_id,
            msg_id=msg_id,
            answer=answer,
            workspace=workspace,
        )

        return JSONResponse(
            {
                "status": "ok",
                "agent_id": agent_id,
                "msg_id": msg_id,
                "answer": answer,
            }
        )


async def run_hub(
    workspace_path: Path = Path(".remora/hub.workspace"),
    host: str = "0.0.0.0",
    port: int = 8000,
) -> None:
    """Run the Remora Hub server."""
    server = HubServer(workspace_path, host, port)
    await server.start()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_hub())
