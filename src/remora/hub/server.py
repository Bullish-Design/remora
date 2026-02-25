import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles

from datastar_py import ServerSentEventGenerator as SSE
from datastar_py.starlette import DatastarResponse, datastar_response, read_signals

from remora.agent_graph import AgentGraph, GraphConfig, ErrorPolicy
from remora.event_bus import Event, EventBus, get_event_bus
from remora.interactive.coordinator import WorkspaceInboxCoordinator
from remora.workspace import GraphWorkspace, WorkspaceManager

from .registry import workspace_registry
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
        workspace_base: Path | None = None,
    ):
        self.workspace_path = workspace_path
        self.host = host
        self.port = port
        self.workspace_base = workspace_base or Path(os.environ.get("WORKSPACE_BASE", "/tmp/remora/workspaces"))
        self.workspace_base.mkdir(parents=True, exist_ok=True)

        self._event_bus: EventBus | None = None
        self._coordinator: WorkspaceInboxCoordinator | None = None
        self._workspace_manager: WorkspaceManager | None = None

        self._hub_state = HubState()

        self._app: Starlette | None = None

        self._running_graphs: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """Start the hub server."""
        logger.info(f"Starting Remora Hub at {self.host}:{self.port}")

        self._event_bus = get_event_bus()
        self._workspace_manager = WorkspaceManager(base_dir=self.workspace_base)
        self._coordinator = WorkspaceInboxCoordinator(self._event_bus)

        await self._event_bus.subscribe("agent:*", self._on_event)

        self._app = Starlette(
            routes=[
                Route("/", self.home),
                Route("/subscribe", self.subscribe),
                Route("/graph/execute", self.execute_graph, methods=["POST"]),
                Route("/graph/list", self.list_graphs, methods=["GET"]),
                Route("/api/files", self.list_workspace_files),
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

        return await event_stream()

    async def list_workspace_files(self, request: Request) -> JSONResponse:
        """
        List files under workspace_base.

        Query params:
        - path: relative path from workspace_base (default: "")

        Returns:
        {
            "path": "subdir",
            "entries": [
                {"name": "file.py", "type": "file", "size": 1234},
                {"name": "subdir", "type": "directory"},
            ]
        }
        """
        query = request.query_params.get("path", "")

        # SECURITY: Prevent directory traversal
        resolved = (self.workspace_base / query).resolve()
        if not str(resolved).startswith(str(self.workspace_base.resolve())):
            return JSONResponse({"error": "Invalid path"}, status_code=400)

        if not resolved.exists():
            return JSONResponse({"error": "Path not found"}, status_code=404)

        entries = []
        for item in sorted(resolved.iterdir()):
            entries.append(
                {
                    "name": item.name,
                    "type": "directory" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )

        return JSONResponse(
            {
                "path": query,
                "entries": entries,
            }
        )

    async def execute_graph(self, request: Request) -> JSONResponse:
        """Execute an agent graph - starts agents in the graph."""
        signals = await read_signals(request) or {}
        graph_id = signals.get("graph_id", "")

        if not graph_id:
            graph_id = uuid.uuid4().hex[:8]

        workspace = await self._workspace_manager.create(graph_id)

        target_path = signals.get("target_path")
        if target_path:
            await workspace.snapshot_original(Path(target_path))

        metadata = {
            "graph_id": graph_id,
            "bundle": signals.get("bundle", "default"),
            "target": signals.get("target", ""),
            "target_path": target_path or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "running",
        }
        await workspace.save_metadata(metadata)

        graph = self._build_agent_graph(graph_id, workspace, signals)

        for agent_id, agent in graph.agents().items():
            await workspace_registry.register(agent_id, workspace.id, workspace)
            await self._coordinator.watch_workspace(agent_id, workspace)

        task = asyncio.create_task(self._execute_graph_async(graph))
        self._running_graphs[graph_id] = task

        return JSONResponse(
            {
                "status": "started",
                "graph_id": graph_id,
                "agents": len(graph.agents()),
                "workspace": workspace.id,
            }
        )

    def _build_agent_graph(self, graph_id: str, workspace: GraphWorkspace, signals: dict[str, Any]) -> AgentGraph:
        """Build an AgentGraph from configuration or signals.

        This creates real agents based on:
        - The bundle names provided
        - The target code to operate on
        - Any discovered nodes from code analysis
        """
        graph = AgentGraph(event_bus=self._event_bus)

        bundle_name = signals.get("bundle", "default")
        target = signals.get("target", "")
        target_path = signals.get("target_path")
        target_type = signals.get("target_type", "code")

        if not target:
            target = "Sample target code for demonstration"

        agent_name = f"{bundle_name}-agent-{graph_id}"
        graph.agent(
            name=agent_name,
            bundle=bundle_name,
            target=target,
            target_path=Path(target_path) if target_path else None,
            target_type=target_type,
        )

        graph._agents[agent_name].workspace = workspace

        return graph

    async def _execute_graph_async(self, graph: AgentGraph) -> None:
        """Execute the graph asynchronously and handle errors."""
        try:
            config = GraphConfig(
                max_concurrency=4,
                interactive=True,
                timeout=300.0,
                error_policy=ErrorPolicy.STOP_GRAPH,
            )
            executor = graph.execute(config=config)
            await executor.run()
        except Exception as e:
            logger.exception("Graph execution failed")
            await self._event_bus.publish(Event.agent_failed(agent_id=graph.id, graph_id=graph.id, error=str(e)))

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

    async def list_graphs(self, request: Request) -> JSONResponse:
        """List all existing workspaces (root nodes of each graph)."""
        workspaces = await self._workspace_manager.list_all()

        graphs = []
        for ws in workspaces:
            metadata = await ws.load_metadata()
            graphs.append(
                {
                    "graph_id": ws.id,
                    "bundle": metadata.get("bundle", "default") if metadata else "default",
                    "target": metadata.get("target", "") if metadata else "",
                    "target_path": metadata.get("target_path", "") if metadata else "",
                    "created_at": metadata.get("created_at", "") if metadata else "",
                    "status": metadata.get("status", "unknown") if metadata else "unknown",
                }
            )

        return JSONResponse({"graphs": graphs})


async def run_hub(
    workspace_path: Path = Path(".remora/hub.workspace"),
    host: str = "0.0.0.0",
    port: int = 8000,
    workspace_base: Path | None = None,
) -> None:
    """Run the Remora Hub server."""
    server = HubServer(workspace_path, host, port, workspace_base)
    await server.start()


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_hub())
