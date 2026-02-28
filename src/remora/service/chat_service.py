"""Standalone chat service for the demo."""

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

from remora.core.chat import ChatSession, ChatConfig, Message
from remora.core.event_bus import EventBus
from remora.core.events import ToolCallEvent, ToolResultEvent

import logging

logger = logging.getLogger(__name__)

DEFAULT_CHAT_TOOL_NAMES = [
    "read_file",
    "write_file",
    "list_dir",
    "file_exists",
    "search_files",
    "discover_symbols",
]

DEFAULT_TOOL_PRESETS = {
    "file_ops": DEFAULT_CHAT_TOOL_NAMES,
    "all": DEFAULT_CHAT_TOOL_NAMES,
}


class ChatServiceState:
    """Holds service state."""

    def __init__(self):
        self.sessions: dict[str, ChatSession] = {}
        self.event_buses: dict[str, EventBus] = {}


state = ChatServiceState()


async def create_session(request: Request) -> JSONResponse:
    """Create a new chat session."""
    body = await request.json()

    config = ChatConfig(
        workspace_path=body["workspace_path"],
        system_prompt=body.get("system_prompt", "You are a helpful assistant."),
        tool_presets=body.get("tool_presets", ["file_ops"]),
        model_name=body.get("model_name", "Qwen/Qwen3-4B"),
    )

    # Validate workspace path
    workspace = Path(config.workspace_path).expanduser().resolve()
    if not workspace.exists() or not workspace.is_dir():
        return JSONResponse(
            {"error": f"Invalid workspace path: {config.workspace_path}"},
            status_code=400,
        )

    event_bus = EventBus()
    session = await ChatSession.create(config=config, event_bus=event_bus)

    state.sessions[session.session_id] = session
    state.event_buses[session.session_id] = event_bus

    return JSONResponse(
        {
            "session_id": session.session_id,
            "workspace_path": str(workspace),
            "tool_presets": config.tool_presets,
        }
    )


async def delete_session(request: Request) -> Response:
    """End a chat session."""
    session_id = request.path_params["session_id"]

    if session_id in state.sessions:
        await state.sessions[session_id].close()
        del state.sessions[session_id]
        del state.event_buses[session_id]

    return Response(status_code=204)


async def send_message(request: Request) -> JSONResponse:
    """Send a message and get response."""
    session_id = request.path_params["session_id"]

    if session_id not in state.sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    body = await request.json()
    content = body.get("content", "").strip()

    if not content:
        return JSONResponse({"error": "Empty message"}, status_code=400)

    session = state.sessions[session_id]

    try:
        response = await session.send(content)
        return JSONResponse(
            {
                "message": {
                    "id": response.message.id,
                    "role": response.message.role,
                    "content": response.message.content,
                    "timestamp": response.message.timestamp,
                    "tool_calls": response.message.tool_calls,
                },
                "turn_count": response.turn_count,
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_history(request: Request) -> JSONResponse:
    """Get conversation history."""
    session_id = request.path_params["session_id"]

    if session_id not in state.sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    session = state.sessions[session_id]

    return JSONResponse(
        {
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "tool_calls": m.tool_calls,
                }
                for m in session.history
            ]
        }
    )


async def stream_events(request: Request) -> EventSourceResponse:
    """Stream tool events via SSE."""
    session_id = request.path_params["session_id"]

    if session_id not in state.event_buses:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    event_bus = state.event_buses[session_id]

    async def event_generator():
        async with event_bus.stream(ToolCallEvent, ToolResultEvent) as events:
            async for event in events:
                if isinstance(event, ToolCallEvent):
                    yield {
                        "event": "tool_call",
                        "data": json.dumps(
                            {
                                "name": event.tool_name,
                                "arguments": event.arguments,
                                "timestamp": event.timestamp,
                            }
                        ),
                    }
                elif isinstance(event, ToolResultEvent):
                    yield {
                        "event": "tool_result",
                        "data": json.dumps(
                            {
                                "name": event.tool_name,
                                "output": event.output_preview,
                                "is_error": event.is_error,
                                "timestamp": event.timestamp,
                            }
                        ),
                    }

    return EventSourceResponse(event_generator())


async def list_tools(request: Request) -> JSONResponse:
    """List available tool presets."""
    return JSONResponse(
        {
            "tools": DEFAULT_CHAT_TOOL_NAMES,
            "presets": DEFAULT_TOOL_PRESETS,
        }
    )


async def health(request: Request) -> JSONResponse:
    """Health check."""
    return JSONResponse(
        {
            "status": "ok",
            "sessions": len(state.sessions),
        }
    )


# Routes
routes = [
    Route("/sessions", create_session, methods=["POST"]),
    Route("/sessions/{session_id}", delete_session, methods=["DELETE"]),
    Route("/sessions/{session_id}/messages", send_message, methods=["POST"]),
    Route("/sessions/{session_id}/history", get_history, methods=["GET"]),
    Route("/sessions/{session_id}/events", stream_events, methods=["GET"]),
    Route("/tools", list_tools, methods=["GET"]),
    Route("/health", health, methods=["GET"]),
]

app = Starlette(routes=routes)


# Add startup event:
@app.on_event("startup")
async def startup_event():
    logger.info("Chat service starting...")

    try:
        from cairn import Cairn

        logger.info("cairn: OK")
    except ImportError as e:
        logger.error(f"cairn not available: {e}")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8420)
