"""structured-agents: Structured tool orchestration with grammar-constrained LLM outputs."""

from structured_agents.deps import require_xgrammar_and_vllm

require_xgrammar_and_vllm()

from structured_agents.backends import (
    CompositeBackend,
    GrailBackend,
    GrailBackendConfig,
    PythonBackend,
    ToolBackend,
)
from structured_agents.bundles import AgentBundle, load_bundle
from structured_agents.client import (
    CompletionResponse,
    LLMClient,
    OpenAICompatibleClient,
    build_client,
)
from structured_agents.exceptions import (
    BackendError,
    BundleError,
    KernelError,
    PluginError,
    StructuredAgentsError,
    ToolExecutionError,
)
from structured_agents.history import (
    HistoryStrategy,
    KeepAllHistory,
    SlidingWindowHistory,
)
from structured_agents.kernel import AgentKernel
from structured_agents.observer import (
    CompositeObserver,
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    NullObserver,
    Observer,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.plugins import FunctionGemmaPlugin, ModelPlugin, QwenPlugin
from structured_agents.tool_sources import (
    ContextProvider,
    RegistryBackendToolSource,
    ToolSource,
)
from structured_agents.types import (
    KernelConfig,
    Message,
    RunResult,
    StepResult,
    TokenUsage,
    ToolCall,
    ToolExecutionStrategy,
    ToolResult,
    ToolSchema,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "AgentKernel",
    "KernelConfig",
    "Message",
    "ToolCall",
    "ToolExecutionStrategy",
    "ToolResult",
    "ToolSchema",
    "StepResult",
    "RunResult",
    "TokenUsage",
    "ModelPlugin",
    "FunctionGemmaPlugin",
    "QwenPlugin",
    "ToolBackend",
    "PythonBackend",
    "CompositeBackend",
    "GrailBackend",
    "GrailBackendConfig",
    "ToolSource",
    "RegistryBackendToolSource",
    "ContextProvider",
    "AgentBundle",
    "load_bundle",
    "Observer",
    "NullObserver",
    "CompositeObserver",
    "KernelStartEvent",
    "KernelEndEvent",
    "ModelRequestEvent",
    "ModelResponseEvent",
    "ToolCallEvent",
    "ToolResultEvent",
    "TurnCompleteEvent",
    "HistoryStrategy",
    "SlidingWindowHistory",
    "KeepAllHistory",
    "LLMClient",
    "OpenAICompatibleClient",
    "build_client",
    "CompletionResponse",
    "StructuredAgentsError",
    "KernelError",
    "ToolExecutionError",
    "PluginError",
    "BundleError",
    "BackendError",
]
