# Remora Demo Feature Refactor (Stario Demo Backend)

This document mirrors the exact backend code and recommendations from `DESIGN_DOC.md` so the Remora library can be updated to support the Stario demo app. The goal is a chat-focused HTTP service with session lifecycle, tool presets, and SSE tool telemetry.

> Note: These changes are intended for the Remora library repo. The `.context/` directory here was only used to study APIs and is not the source of truth.

---

## Architecture Snapshot (from DESIGN_DOC.md)

Two processes are required because of the Python version split:

- **Stario frontend**: Python 3.14
- **Remora backend**: Python 3.13

The backend will expose the following HTTP endpoints on port 8420:

- `POST /sessions`
- `DELETE /sessions/{id}`
- `POST /sessions/{id}/messages`
- `GET /sessions/{id}/events` (SSE)
- `GET /sessions/{id}/history`
- `GET /tools`
- `GET /health`

---

## Exact Backend Code (from DESIGN_DOC.md)

### 1) ChatSession: `remora/core/chat.py`

```python
"""Chat session wrapper for single-agent interactions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import time
import uuid

from remora.core.events import RemoraEvent
from remora.core.event_bus import EventBus
from remora.core.workspace import CairnWorkspaceService


@dataclass
class Message:
    """A message in the conversation."""
    id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    tool_calls: list[dict] = field(default_factory=list)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(
            id=str(uuid.uuid4()),
            role="user",
            content=content,
            timestamp=time.time(),
        )

    @classmethod
    def assistant(cls, content: str, tool_calls: list[dict] | None = None) -> "Message":
        return cls(
            id=str(uuid.uuid4()),
            role="assistant",
            content=content,
            timestamp=time.time(),
            tool_calls=tool_calls or [],
        )


@dataclass
class ChatConfig:
    """Configuration for a chat session."""
    workspace_path: str
    system_prompt: str
    tool_presets: list[str] = field(default_factory=lambda: ["file_ops"])
    model_name: str = "Qwen/Qwen3-4B"
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = "EMPTY"
    max_turns: int = 10


@dataclass
class AgentResponse:
    """Response from the agent."""
    message: Message
    turn_count: int


class ChatSession:
    """
    Simplified single-agent chat interface.

    Wraps Remora's AgentKernel to provide a conversation-oriented API
    with automatic history management and event streaming.
    """

    def __init__(
        self,
        session_id: str,
        config: ChatConfig,
        event_bus: EventBus,
    ):
        self.session_id = session_id
        self.config = config
        self.event_bus = event_bus

        self._history: list[Message] = []
        self._workspace: Any = None
        self._tools: list[Any] = []
        self._initialized = False

    @classmethod
    async def create(
        cls,
        config: ChatConfig,
        event_bus: EventBus | None = None,
    ) -> "ChatSession":
        """Factory method to create and initialize a chat session."""
        session_id = str(uuid.uuid4())
        event_bus = event_bus or EventBus()

        session = cls(
            session_id=session_id,
            config=config,
            event_bus=event_bus,
        )
        await session._initialize()
        return session

    async def _initialize(self) -> None:
        """Initialize workspace and tools."""
        from remora.core.tool_registry import ToolRegistry

        # Create workspace
        workspace_path = Path(self.config.workspace_path).expanduser().resolve()
        self._workspace = await CairnWorkspaceService.create(
            base_path=workspace_path,
        )

        # Get tools from registry
        self._tools = ToolRegistry.get_tools(
            workspace=self._workspace,
            presets=self.config.tool_presets,
        )

        self._initialized = True

    async def send(self, content: str) -> AgentResponse:
        """Send a message and get a response."""
        if not self._initialized:
            raise RuntimeError("Session not initialized")

        # Add user message
        user_msg = Message.user(content)
        self._history.append(user_msg)

        # Build messages for kernel
        messages = [{"role": m.role, "content": m.content} for m in self._history]

        # Run agent
        from structured_agents import AgentKernel, ModelAdapter

        kernel = AgentKernel(
            model=ModelAdapter.from_config(
                base_url=self.config.model_base_url,
                api_key=self.config.model_api_key,
                model=self.config.model_name,
            ),
            tools=self._tools,
            system_prompt=self.config.system_prompt,
            observer=self.event_bus,
        )

        result = await kernel.run(
            messages=messages,
            max_turns=self.config.max_turns,
        )

        # Extract response
        tool_calls = [
            {"name": tc.name, "arguments": tc.arguments}
            for tc in result.tool_calls
        ]

        assistant_msg = Message.assistant(
            content=result.final_message.content or "",
            tool_calls=tool_calls,
        )
        self._history.append(assistant_msg)

        return AgentResponse(
            message=assistant_msg,
            turn_count=result.turn_count,
        )

    @property
    def history(self) -> list[Message]:
        """Get conversation history."""
        return self._history.copy()

    def reset(self) -> None:
        """Clear conversation history."""
        self._history.clear()

    async def close(self) -> None:
        """Clean up resources."""
        if self._workspace:
            await self._workspace.cleanup()
```

### 2) ToolRegistry: `remora/core/tool_registry.py`

```python
"""Tool registry for dynamic tool selection."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class ToolDefinition:
    """Definition of an available tool."""
    name: str
    description: str
    category: str
    factory: Callable[..., Any]


class ToolRegistry:
    """Registry for managing available tools and presets."""

    _TOOLS: dict[str, ToolDefinition] = {}

    PRESETS: dict[str, list[str]] = {
        "file_ops": ["read_file", "write_file", "list_dir", "file_exists", "search_files"],
        "code_analysis": ["discover_symbols"],
        "all": [],
    }

    @classmethod
    def register(cls, name: str, description: str, category: str, factory: Callable) -> None:
        """Register a tool definition."""
        cls._TOOLS[name] = ToolDefinition(name, description, category, factory)
        if name not in cls.PRESETS["all"]:
            cls.PRESETS["all"].append(name)

    @classmethod
    def get_tools(cls, workspace: Any, presets: list[str]) -> list[Any]:
        """Get tool instances for the given workspace."""
        names: set[str] = set()
        for preset in presets:
            if preset in cls.PRESETS:
                names.update(cls.PRESETS[preset])

        return [
            cls._TOOLS[name].factory(workspace)
            for name in names
            if name in cls._TOOLS
        ]

    @classmethod
    def list_presets(cls) -> dict[str, list[str]]:
        """List available presets and their tools."""
        return {k: v for k, v in cls.PRESETS.items() if v}  # Exclude empty


# Tool registration (abbreviated - see full version in previous doc)
def _register_tools():
    from structured_agents import Tool

    def make_read_file(workspace):
        async def read_file(path: str) -> str:
            """Read file contents."""
            return await workspace.read_file(path)
        return Tool.from_function(read_file)

    def make_write_file(workspace):
        async def write_file(path: str, content: str) -> bool:
            """Write content to file."""
            await workspace.write_file(path, content)
            return True
        return Tool.from_function(write_file)

    def make_list_dir(workspace):
        async def list_dir(path: str = ".") -> list[str]:
            """List directory contents."""
            return await workspace.list_dir(path)
        return Tool.from_function(list_dir)

    def make_file_exists(workspace):
        async def file_exists(path: str) -> bool:
            """Check if file exists."""
            return await workspace.file_exists(path)
        return Tool.from_function(file_exists)

    def make_search_files(workspace):
        async def search_files(pattern: str) -> list[str]:
            """Search files by glob pattern."""
            return await workspace.search_files(pattern)
        return Tool.from_function(search_files)

    def make_discover_symbols(workspace):
        from remora.core.discovery import discover

        async def discover_symbols(path: str = ".") -> list[dict]:
            """Discover code symbols (functions, classes)."""
            full_path = workspace.resolve_path(path)
            return [
                {"name": n.name, "type": n.node_type, "file": str(n.file_path), "line": n.start_line}
                for n in discover([full_path])
            ]
        return Tool.from_function(discover_symbols)

    ToolRegistry.register("read_file", "Read file contents", "file_ops", make_read_file)
    ToolRegistry.register("write_file", "Write to file", "file_ops", make_write_file)
    ToolRegistry.register("list_dir", "List directory", "file_ops", make_list_dir)
    ToolRegistry.register("file_exists", "Check file exists", "file_ops", make_file_exists)
    ToolRegistry.register("search_files", "Search by pattern", "file_ops", make_search_files)
    ToolRegistry.register("discover_symbols", "Find code symbols", "code_analysis", make_discover_symbols)

_register_tools()
```

### 3) ChatService: `remora/service/chat_service.py`

```python
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
from remora.core.tool_registry import ToolRegistry


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

    return JSONResponse({
        "session_id": session.session_id,
        "workspace_path": str(workspace),
        "tool_presets": config.tool_presets,
    })


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
        return JSONResponse({
            "message": {
                "id": response.message.id,
                "role": response.message.role,
                "content": response.message.content,
                "timestamp": response.message.timestamp,
                "tool_calls": response.message.tool_calls,
            },
            "turn_count": response.turn_count,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_history(request: Request) -> JSONResponse:
    """Get conversation history."""
    session_id = request.path_params["session_id"]

    if session_id not in state.sessions:
        return JSONResponse({"error": "Session not found"}, status_code=404)

    session = state.sessions[session_id]

    return JSONResponse({
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
    })


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
                        "data": json.dumps({
                            "name": event.tool_name,
                            "arguments": event.arguments,
                            "timestamp": event.timestamp,
                        }),
                    }
                elif isinstance(event, ToolResultEvent):
                    yield {
                        "event": "tool_result",
                        "data": json.dumps({
                            "name": event.tool_name,
                            "output": event.output_preview,
                            "is_error": event.is_error,
                            "timestamp": event.timestamp,
                        }),
                    }

    return EventSourceResponse(event_generator())


async def list_tools(request: Request) -> JSONResponse:
    """List available tool presets."""
    return JSONResponse({
        "presets": ToolRegistry.list_presets(),
    })


async def health(request: Request) -> JSONResponse:
    """Health check."""
    return JSONResponse({
        "status": "ok",
        "sessions": len(state.sessions),
    })


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8420)
```

---

## Backend Packaging (from DESIGN_DOC.md)

`backend/pyproject.toml`:

```toml
[project]
name = "remora-demo-backend"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "remora @ file:../.context/remora",  # Or published version
    "starlette>=0.40",
    "sse-starlette>=2.0",
    "uvicorn>=0.30",
]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

---

## Recommendations / Decisions (from DESIGN_DOC.md)

- **Two-process architecture** is mandatory due to Python version split (Remora 3.13, Stario 3.14).
- **ChatService should be standalone (Option B)** rather than extending the existing RemoraService.
- **State is in-memory** for MVP; no persistence required.
- **Tool events** should be streamed via SSE to keep the UI tool log live.
- **Preset tool selection** is handled by the ToolRegistry; default to `file_ops`.

---

## Implementation Order (from DESIGN_DOC.md)

### Phase 1: Remora Backend (Python 3.13)
1. Create `remora/core/chat.py` (ChatSession)
2. Create `remora/core/tool_registry.py` (ToolRegistry)
3. Create `remora/service/chat_service.py` (HTTP endpoints)
4. Test endpoints with curl/httpie
5. Test SSE streaming

---

## Notes to Keep in Mind

- The code blocks above are the **source of truth** for this demo implementation.
- If Remora already has overlapping utilities (e.g., tool schemas or service abstractions), align them to match the exact behaviors specified above rather than inventing new APIs.
- Keep the API paths and JSON shapes **identical** to the code shown so the Stario frontend does not need modifications.

