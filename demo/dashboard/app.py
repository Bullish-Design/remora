"""Dashboard server - Event-driven web UI for Remora.

This module provides:
1. SSE endpoint for streaming events to the browser
2. REST API for responding to blocked agents
3. Static file serving for the dashboard UI
"""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from remora.event_bus import Event, EventBus, get_event_bus


@dataclass
class AgentResponse:
    """Stores user responses for blocked agents."""

    agent_id: str
    question: str
    answer: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


class DashboardState:
    """Application state for the dashboard."""

    def __init__(self):
        self.event_bus: EventBus = get_event_bus()
        self._responses: dict[str, AgentResponse] = {}
        self._websockets: set[WebSocket] = set()

    def add_response(self, agent_id: str, question: str, answer: str) -> None:
        """Store a user response for a blocked agent."""
        response = AgentResponse(agent_id=agent_id, question=question, answer=answer)
        self._responses[f"{agent_id}:{question}"] = response

    def get_response(self, agent_id: str, question: str) -> str | None:
        """Get a response for a blocked agent."""
        key = f"{agent_id}:{question}"
        response = self._responses.get(key)
        return response.answer if response else None

    async def broadcast_event(self, event: Event) -> None:
        """Broadcast an event to all connected websockets."""
        data = event.model_dump_json()
        message = f"data: {data}\n\n"
        dead_connections = set()

        for ws in self._websockets:
            try:
                await ws.send_text(message)
            except Exception:
                dead_connections.add(ws)

        for ws in dead_connections:
            self._websockets.discard(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    state = DashboardState()
    app.state.dashboard = state

    async def event_forwarder():
        """Forward events from the EventBus to the dashboard."""
        event_bus = state.event_bus
        async for event in event_bus.stream():
            await state.broadcast_event(event)

    task = asyncio.create_task(event_forwarder())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Remora Dashboard",
    description="Event-driven dashboard for agent graph workflows",
    version="2.0.0",
    lifespan=lifespan,
)

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    from fastapi.staticfiles import StaticFiles

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


class RespondRequest(BaseModel):
    """Request body for responding to a blocked agent."""

    question: str
    answer: str


@app.get("/events")
async def events_endpoint(request: Request):
    """Stream all events as Server-Sent Events."""

    async def generator():
        event_bus = get_event_bus()
        try:
            async for event in event_bus.stream():
                yield f"data: {event.model_dump_json()}\n\n"
        except asyncio.CancelledError:
            pass

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """WebSocket endpoint for real-time events."""
    await websocket.accept()
    state: DashboardState = websocket.app.state.dashboard
    state._websockets.add(websocket)

    try:
        event_bus = get_event_bus()
        async for event in event_bus.stream():
            await websocket.send_text(event.model_dump_json())
    except WebSocketDisconnect:
        pass
    finally:
        state._websockets.discard(websocket)


@app.post("/agent/{agent_id}/respond")
async def respond_to_agent(
    agent_id: str,
    request: RespondRequest,
    http_request: Request,
):
    """User responds to a blocked agent."""
    state: DashboardState = http_request.app.state.dashboard

    state.add_response(agent_id, request.question, request.answer)

    return {"status": "ok", "agent_id": agent_id}


@app.get("/agent/{agent_id}/questions")
async def get_agent_questions(agent_id: str, request: Request):
    """Get all pending questions for an agent."""
    state: DashboardState = request.app.state.dashboard
    questions = [
        {"question": r.question, "answer": r.answer, "created_at": r.created_at.isoformat()}
        for r in state._responses.values()
        if r.agent_id == agent_id and r.answer is None
    ]
    return {"agent_id": agent_id, "questions": questions}


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the main dashboard page."""
    static_dir = Path(__file__).parent / "static"
    index_file = static_dir / "index.html"

    if index_file.exists():
        return HTMLResponse(index_file.read_text())

    return HTMLResponse("<h1>Dashboard not found</h1>")


@app.get("/projector", response_class=HTMLResponse)
async def projector():
    """Serve the projector view."""
    static_dir = Path(__file__).parent / "static"
    projector_file = static_dir / "projector.html"

    if projector_file.exists():
        return HTMLResponse(projector_file.read_text())

    return HTMLResponse("<h1>Projector not found</h1>")


@app.get("/mobile", response_class=HTMLResponse)
async def mobile():
    """Serve the mobile remote view."""
    static_dir = Path(__file__).parent / "static"
    mobile_file = static_dir / "projector.html"

    if mobile_file.exists():
        return HTMLResponse(mobile_file.read_text())

    return HTMLResponse("<h1>Mobile view not found</h1>")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
