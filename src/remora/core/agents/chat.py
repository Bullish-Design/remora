"""Chat session wrapper for single-agent interactions."""

from pathlib import Path
from typing import Any, Callable, Awaitable, cast, get_type_hints
import inspect
import json
import time
import uuid

from pydantic import BaseModel, Field

from remora.core.code.discovery import discover
from remora.core.events.event_bus import EventBus
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.config import Config
from remora.core.agents.kernel_factory import create_kernel
from remora.core.agents.workspace import AgentWorkspace
from structured_agents import Tool
from structured_agents.types import Message as KernelMessage, ToolCall, ToolResult, ToolSchema


class Message(BaseModel):
    """A message in the conversation."""

    id: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    tool_calls: list[dict] = Field(default_factory=list)

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


class ChatConfig(BaseModel):
    """Configuration for a chat session."""

    workspace_path: str
    system_prompt: str
    tool_presets: list[str] = Field(default_factory=lambda: ["file_ops"])
    model_name: str = "Qwen/Qwen3-4B"
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = ""
    max_turns: int = 10

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        workspace_path: str,
        system_prompt: str,
        tool_presets: list[str] | None = None,
        max_turns: int = 10,
    ) -> "ChatConfig":
        """Create a ChatConfig from the canonical Config object."""
        return cls(
            workspace_path=workspace_path,
            system_prompt=system_prompt,
            tool_presets=tool_presets or ["file_ops"],
            model_name=config.model_default,
            model_base_url=config.model_base_url,
            model_api_key=config.model_api_key,
            max_turns=max_turns,
        )


class AgentResponse(BaseModel):
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
        workspace_path = Path(self.config.workspace_path).expanduser().resolve()

        workspace_config = Config(
            bundle_root=str(workspace_path / ".remora"),
            workspace_ignore_patterns=(),
            workspace_ignore_dotfiles=False,
        )
        self._workspace = CairnWorkspaceService(
            config=workspace_config,
            swarm_root=workspace_path / ".remora",
            project_root=workspace_path,
        )
        await self._workspace.initialize()

        agent_workspace = await self._workspace.get_agent_workspace(self.session_id)
        self._tools = build_chat_tools(agent_workspace, workspace_path)

        self._initialized = True

    async def send(self, content: str) -> AgentResponse:
        """Send a message and get a response."""
        if not self._initialized:
            raise RuntimeError("Session not initialized")

        # Add user message
        user_msg = Message.user(content)
        self._history.append(user_msg)

        # Build messages for kernel
        messages = [KernelMessage(role="system", content=self.config.system_prompt)]
        messages += [KernelMessage(role=cast(Any, m.role), content=m.content) for m in self._history]
        tool_schemas = [tool.schema for tool in self._tools]

        # Run agent
        kernel = create_kernel(
            model_name=self.config.model_name,
            base_url=self.config.model_base_url,
            api_key=self.config.model_api_key or "EMPTY",
            tools=self._tools,
            observer=self.event_bus,
        )

        try:
            result = await kernel.run(
                messages,
                tool_schemas,
                max_turns=self.config.max_turns,
            )
        finally:
            await kernel.close()

        # Extract response
        tool_calls = []
        if result.final_message.tool_calls:
            tool_calls = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in result.final_message.tool_calls
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
            await self._workspace.close()


_PY_TYPE_TO_JSON: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def _params_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Build a JSON-Schema-style ``parameters`` dict from *func*'s signature."""
    sig = inspect.signature(func)
    hints = get_type_hints(func)

    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in sig.parameters.items():
        json_type = _PY_TYPE_TO_JSON.get(hints.get(name, str), "string")
        properties[name] = {"type": json_type}
        if param.default is inspect.Parameter.empty:
            required.append(name)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


class FunctionTool:
    """Wraps an async callable so it satisfies the ``Tool`` protocol."""

    def __init__(self, func: Callable[..., Awaitable[Any]]) -> None:
        self._func = func
        self._schema = ToolSchema(
            name=func.__name__,
            description=func.__doc__ or func.__name__,
            parameters=_params_schema(func),
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolCall | None = None,
    ) -> ToolResult:
        call_id = context.id if context else "unknown"
        try:
            result = await self._func(**arguments)
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=output,
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(exc),
                is_error=True,
            )


def build_chat_tools(agent_workspace: AgentWorkspace, project_root: Path) -> list[Tool]:
    """Construct the basic file and discovery tools for chat sessions."""

    async def read_file(path: str) -> str:
        return await agent_workspace.read(path)

    async def write_file(path: str, content: str) -> bool:
        await agent_workspace.write(path, content)
        return True

    async def list_dir(path: str = ".") -> list[str]:
        return await agent_workspace.list_dir(path)

    async def file_exists(path: str) -> bool:
        return await agent_workspace.exists(path)

    async def search_files(pattern: str) -> list[str]:
        matches: list[str] = []
        for candidate in project_root.rglob(pattern or "*"):
            if candidate.is_file():
                try:
                    matches.append(str(candidate.relative_to(project_root)))
                except ValueError:
                    matches.append(str(candidate))
        return sorted(matches)

    async def discover_symbols(path: str = ".") -> list[dict]:
        target = project_root / path
        nodes = discover([target])
        return [
            {
                "name": getattr(node, "name", ""),
                "type": getattr(node, "node_type", ""),
                "file": str(getattr(node, "file_path", "")),
                "line": getattr(node, "start_line", 0),
            }
            for node in nodes
        ]

    return [
        FunctionTool(read_file),
        FunctionTool(write_file),
        FunctionTool(list_dir),
        FunctionTool(file_exists),
        FunctionTool(search_files),
        FunctionTool(discover_symbols),
    ]
