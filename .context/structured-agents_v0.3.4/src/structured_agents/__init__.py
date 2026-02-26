"""structured-agents - Structured tool orchestration with grammar-constrained LLM outputs."""

from structured_agents.types import (
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
    StepResult,
    RunResult,
)
from structured_agents.tools import Tool, GrailTool, discover_tools
from structured_agents.models import ModelAdapter, ResponseParser, QwenResponseParser
from structured_agents.grammar import DecodingConstraint, StructuredOutputModel
from structured_agents.events import (
    Observer,
    NullObserver,
    Event,
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.kernel import AgentKernel
from structured_agents.agent import Agent, AgentManifest, load_manifest
from structured_agents.client import LLMClient, OpenAICompatibleClient, build_client
from structured_agents.exceptions import (
    StructuredAgentsError,
    KernelError,
    ToolExecutionError,
    BundleError,
    AdapterError,
)

__version__ = "0.3.1"

__all__ = [
    # Types
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolSchema",
    "TokenUsage",
    "StepResult",
    "RunResult",
    # Tools
    "Tool",
    "GrailTool",
    "discover_tools",
    # Models
    "ModelAdapter",
    "ResponseParser",
    "QwenResponseParser",
    # Grammar
    "DecodingConstraint",
    "StructuredOutputModel",
    # Events
    "Observer",
    "NullObserver",
    "Event",
    "KernelStartEvent",
    "KernelEndEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    # Core
    "AgentKernel",
    "Agent",
    "AgentManifest",
    "load_manifest",
    # Client
    "LLMClient",
    "OpenAICompatibleClient",
    "build_client",
    # Exceptions
    "StructuredAgentsError",
    "KernelError",
    "ToolExecutionError",
    "BundleError",
    "AdapterError",
]
