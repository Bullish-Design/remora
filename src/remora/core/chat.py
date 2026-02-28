"""Chat session wrapper for single-agent interactions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import time
import uuid

from remora.core.events import RemoraEvent
from remora.core.event_bus import EventBus
from remora.core.cairn_bridge import CairnWorkspaceService


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
        tool_calls = [{"name": tc.name, "arguments": tc.arguments} for tc in result.tool_calls]

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
