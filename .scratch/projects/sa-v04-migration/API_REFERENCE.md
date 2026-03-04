# structured-agents v0.4 API Reference

## Public API Surface

All public exports from `structured_agents`:

```python
from structured_agents import (
    # === Core ===
    AgentKernel,
    
    # === Types ===
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
    StepResult,
    RunResult,
    
    # === Tools ===
    Tool,  # Protocol
    
    # === Parsing ===
    ResponseParser,       # Protocol
    DefaultResponseParser,
    get_response_parser,
    
    # === Grammar ===
    DecodingConstraint,
    StructuredOutputModel,
    ConstraintPipeline,
    
    # === Events ===
    Event,               # Union type
    KernelEvent,         # Base class
    KernelStartEvent,
    KernelEndEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
    
    # === Observer ===
    Observer,            # Protocol
    NullObserver,
    CompositeObserver,
    
    # === Client ===
    LLMClient,           # Protocol
    CompletionResponse,
    OpenAICompatibleClient,
    LiteLLMClient,
    build_client,
    
    # === Exceptions ===
    StructuredAgentsError,
    KernelError,
    ToolExecutionError,
)
```

---

## AgentKernel

```python
@dataclass
class AgentKernel:
    """The core agent loop orchestrator."""
    
    client: LLMClient
    response_parser: ResponseParser = field(default_factory=DefaultResponseParser)
    tools: Sequence[Tool] = field(default_factory=list)
    observer: Observer = field(default_factory=NullObserver)
    constraint_pipeline: ConstraintPipeline | None = None
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    
    async def step(
        self,
        messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        turn: int = 0,
    ) -> StepResult:
        """Execute a single turn: model call + tool execution."""
        ...
    
    async def run(
        self,
        initial_messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        max_turns: int = 20,
    ) -> RunResult:
        """Execute the full agent loop."""
        ...
    
    async def close(self) -> None:
        """Close the underlying client."""
        ...
```

---

## LLMClient Protocol

```python
class LLMClient(Protocol):
    """Protocol for LLM clients."""
    
    model: str  # Required property
    
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tool_choice: str | dict[str, Any] | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        ...
    
    async def close(self) -> None:
        ...
```

---

## CompletionResponse

```python
@dataclass(frozen=True)
class CompletionResponse:
    """Response from an LLM completion."""
    
    content: str | None
    tool_calls: list[dict[str, Any]] | None = None
    usage: TokenUsage | None = None
    finish_reason: str | None = None
```

---

## ResponseParser Protocol

```python
class ResponseParser(Protocol):
    """Protocol for parsing model responses."""
    
    def parse(
        self,
        content: str | None,
        tool_calls: list[dict[str, Any]] | None,
    ) -> tuple[str | None, list[ToolCall]]:
        """Parse response content and tool calls.
        
        Returns:
            Tuple of (parsed_content, list_of_tool_calls)
        """
        ...
```

---

## Observer Protocol

```python
class Observer(Protocol):
    """Protocol for event observers."""
    
    async def emit(self, event: Event) -> None:
        """Emit an event."""
        ...
```

---

## Event Types (Pydantic Models)

All events inherit from `KernelEvent` and are frozen Pydantic models.

```python
class KernelEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

class KernelStartEvent(KernelEvent):
    max_turns: int
    tools_count: int
    initial_messages_count: int

class KernelEndEvent(KernelEvent):
    turn_count: int
    termination_reason: str
    total_duration_ms: int

class ModelRequestEvent(KernelEvent):
    turn: int
    messages_count: int
    tools_count: int
    model: str

class ModelResponseEvent(KernelEvent):
    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None

class ToolCallEvent(KernelEvent):
    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]

class ToolResultEvent(KernelEvent):
    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str

class TurnCompleteEvent(KernelEvent):
    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int
```

---

## Tool Protocol

```python
class Tool(Protocol):
    """Protocol for tools."""
    
    @property
    def schema(self) -> ToolSchema:
        """Return the tool schema."""
        ...
    
    async def execute(
        self,
        arguments: dict[str, Any],
        context: ToolCall | None = None,
    ) -> ToolResult:
        """Execute the tool with given arguments."""
        ...
```

---

## Core Types

```python
@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    
    def to_openai_format(self) -> dict[str, Any]: ...

@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    
    @property
    def arguments_json(self) -> str: ...
    
    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> "ToolCall": ...

@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    output: str
    is_error: bool = False
    
    def to_message(self) -> Message: ...

@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]
    
    def to_openai_format(self) -> dict[str, Any]: ...

@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

@dataclass(frozen=True, slots=True)
class StepResult:
    response_message: Message
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    usage: TokenUsage | None = None

@dataclass(frozen=True, slots=True)
class RunResult:
    final_message: Message
    history: list[Message]
    turn_count: int
    termination_reason: str
    final_tool_result: ToolResult | None = None
    total_usage: TokenUsage | None = None
```

---

## build_client()

```python
def build_client(config: dict[str, Any]) -> LLMClient:
    """Build an LLM client from config dict.
    
    Config keys:
        model: Model name/path (required)
        base_url: API base URL (for vLLM endpoints)
        api_key: API key (defaults to "EMPTY" for local vLLM)
        timeout: Request timeout in seconds (default 120.0)
    
    Routing:
        - Model with provider prefix → LiteLLMClient
        - Plain model name → OpenAICompatibleClient
    
    Provider prefixes:
        - hosted_vllm/
        - anthropic/
        - openai/
        - gemini/
        - azure/
        - bedrock/
        - vertex_ai/
    """
```

---

## get_response_parser()

```python
def get_response_parser(model_name: str) -> ResponseParser:
    """Get appropriate response parser for a model.
    
    Currently returns DefaultResponseParser for all models.
    The DefaultResponseParser handles:
    - Native tool_calls from the API
    - XML-style <tool_call> tags in content (Qwen-style)
    """
```

---

## ConstraintPipeline

```python
class ConstraintPipeline:
    """Pipeline for grammar-constrained decoding."""
    
    def __init__(self, config: StructuredOutputModel | None = None):
        ...
    
    def constrain(self, tools: Sequence[ToolSchema]) -> dict[str, Any] | None:
        """Generate extra_body for constrained decoding.
        
        Returns dict with 'guided_grammar' or 'guided_json' key,
        or None if no constraints.
        """
        ...
```
