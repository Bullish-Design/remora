"""Chat session wrapper for single-agent interactions."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from remora.core.events import RemoraEvent
from remora.core.event_bus import EventBus
from remora.core.workspace import CairnWorkspaceService


@dataclass
class Message:
    """A message in the conversation."""
    role: str  # "user" or "assistant"
    content: str
    timestamp: float
    tool_calls: list[dict] = field(default_factory=list)


@dataclass
class AgentResponse:
    """Response from the agent."""
    content: str
    tool_calls: list[dict]
    turn_count: int


@dataclass
class ChatConfig:
    """Configuration for a chat session."""
    system_prompt: str
    model_name: str = "Qwen/Qwen3-4B"
    model_base_url: str = "http://localhost:8000/v1"
    model_api_key: str = "EMPTY"
    max_turns: int = 10


class ChatSession:
    """
    Simplified single-agent chat interface.

    Wraps Remora's AgentKernel to provide a conversation-oriented API
    with automatic history management.

    Example:
        session = await ChatSession.create(
            workspace_path=Path("/my/project"),
            config=ChatConfig(system_prompt="You are a helpful assistant."),
            tools=["file_ops"],
        )

        response = await session.send("What files are in this directory?")
        print(response.content)
    """

    def __init__(
        self,
        workspace_path: Path,
        config: ChatConfig,
        tools: list[str],
        event_bus: EventBus | None = None,
    ):
        self.workspace_path = workspace_path
        self.config = config
        self.tool_names = tools
        self.event_bus = event_bus or EventBus()

        self._history: list[Message] = []
        self._workspace: Any = None  # CairnWorkspaceService
        self._tools: list[Any] = []  # Tool instances
        self._initialized = False

    @classmethod
    async def create(
        cls,
        workspace_path: Path,
        config: ChatConfig,
        tools: list[str],
        event_bus: EventBus | None = None,
    ) -> "ChatSession":
        """Factory method to create and initialize a chat session."""
        session = cls(
            workspace_path=workspace_path,
            config=config,
            tools=tools,
            event_bus=event_bus,
        )
        await session._initialize()
        return session

    async def _initialize(self) -> None:
        """Initialize workspace and tools."""
        # Create workspace service
        self._workspace = await CairnWorkspaceService.create(
            base_path=self.workspace_path,
        )

        # Get tools from registry
        from remora.core.tool_registry import ToolRegistry
        self._tools = ToolRegistry.get_tools(
            workspace=self._workspace,
            presets=self.tool_names,
        )

        self._initialized = True

    async def send(self, message: str) -> AgentResponse:
        """
        Send a message to the agent and get a response.

        Args:
            message: The user's message

        Returns:
            AgentResponse with content, tool calls, and turn count
        """
        if not self._initialized:
            raise RuntimeError("ChatSession not initialized. Use create() factory.")

        import time

        # Add user message to history
        self._history.append(Message(
            role="user",
            content=message,
            timestamp=time.time(),
        ))

        # Build conversation context for kernel
        messages = self._build_messages()

        # Run the agent kernel
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
        response_content = result.final_message.content or ""
        tool_calls = [
            {"name": tc.name, "arguments": tc.arguments}
            for tc in result.tool_calls
        ]

        # Add assistant message to history
        self._history.append(Message(
            role="assistant",
            content=response_content,
            timestamp=time.time(),
            tool_calls=tool_calls,
        ))

        return AgentResponse(
            content=response_content,
            tool_calls=tool_calls,
            turn_count=result.turn_count,
        )

    def _build_messages(self) -> list[dict]:
        """Build message list for kernel from history."""
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self._history
        ]

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