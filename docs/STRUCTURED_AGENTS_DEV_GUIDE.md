# Developer Guide: Building `structured-agents` from Scratch

## Overview

This guide walks through building `structured-agents`, a standalone Python library for structured tool orchestration with grammar-constrained LLM outputs. The library handles the core agent loop (model calls + tool execution) while remaining agnostic to specific orchestration concerns like workspace management or multi-agent coordination.

**What this library does:**
- Executes agentic tool-calling loops with LLMs
- Guarantees structured model output via XGrammar integration
- Provides pluggable tool execution backends (Grail .pym scripts as default)
- Supports directory-based "bundles" containing agent configurations
- Emits observable events for external TUI/logging integration

**What this library does NOT do:**
- Multi-agent orchestration (that's Remora's job)
- Workspace/filesystem management (consumers handle this)
- Code discovery or parsing (that's Remora's job)

---

## Prerequisites

- Python 3.11+
- `uv` package manager
- Understanding of async Python
- Familiarity with OpenAI's chat completion API format

---

## Part 1: Repository Setup

### Step 1.1: Initialize the Repository

```bash
# Create new directory (outside of remora)
mkdir structured-agents
cd structured-agents

# Initialize with uv
uv init

# Create src layout
mkdir -p src/structured_agents
mkdir -p tests/fixtures
```

### Step 1.2: Configure pyproject.toml

Replace the generated `pyproject.toml` with:

```toml
[project]
name = "structured-agents"
version = "0.1.0"
description = "Structured tool orchestration with grammar-constrained LLM outputs"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "httpx>=0.25",
    "openai>=1.0",
    "pyyaml>=6.0",
    "jinja2>=3.0",
]

[project.optional-dependencies]
grail = [
    "grail",
    "fsdantic",
]
xgrammar = [
    "xgrammar>=0.1.7",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/structured_agents"]

[tool.uv]
dev-dependencies = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "respx>=0.21",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

### Step 1.3: Create Directory Structure

```bash
# Create all directories
mkdir -p src/structured_agents/{observer,plugins/grammar,backends,bundles,client}
mkdir -p tests/{test_observer,test_plugins,test_backends,test_bundles,test_client,fixtures/sample_bundle/tools}

# Create __init__.py files
touch src/structured_agents/__init__.py
touch src/structured_agents/observer/__init__.py
touch src/structured_agents/plugins/__init__.py
touch src/structured_agents/plugins/grammar/__init__.py
touch src/structured_agents/backends/__init__.py
touch src/structured_agents/bundles/__init__.py
touch src/structured_agents/client/__init__.py

# Create py.typed marker for PEP 561
touch src/structured_agents/py.typed
```

### Step 1.4: Install Dependencies

```bash
uv sync
```

### Testing Step 1

```bash
# Verify the package is importable
uv run python -c "import structured_agents; print('OK')"
```

**Expected output:** `OK`

---

## Part 2: Core Types

### Step 2.1: Create exceptions.py

**File: `src/structured_agents/exceptions.py`**

```python
"""Exception hierarchy for structured-agents."""

from __future__ import annotations


class StructuredAgentsError(Exception):
    """Base exception for all structured-agents errors."""
    pass


class KernelError(StructuredAgentsError):
    """Error during kernel execution."""

    def __init__(self, message: str, turn: int | None = None, phase: str | None = None):
        super().__init__(message)
        self.turn = turn
        self.phase = phase


class ToolExecutionError(StructuredAgentsError):
    """Error during tool execution."""

    def __init__(
        self,
        message: str,
        tool_name: str,
        call_id: str,
        code: str | None = None,
    ):
        super().__init__(message)
        self.tool_name = tool_name
        self.call_id = call_id
        self.code = code


class PluginError(StructuredAgentsError):
    """Error in model plugin (parsing, formatting, etc.)."""
    pass


class BundleError(StructuredAgentsError):
    """Error loading or validating a bundle."""
    pass


class BackendError(StructuredAgentsError):
    """Error in tool backend."""
    pass
```

### Step 2.2: Create types.py

**File: `src/structured_agents/types.py`**

```python
"""Core data types for structured-agents."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


# =============================================================================
# Configuration
# =============================================================================

class KernelConfig(BaseModel):
    """Configuration for the AgentKernel."""

    base_url: str = Field(description="vLLM server URL (e.g., http://localhost:8000/v1)")
    model: str = Field(description="Model name or adapter to use")
    api_key: str = Field(default="EMPTY", description="API key (usually EMPTY for local vLLM)")
    timeout: float = Field(default=120.0, description="Request timeout in seconds")
    max_tokens: int = Field(default=4096, description="Maximum tokens per completion")
    temperature: float = Field(default=0.1, description="Sampling temperature")
    tool_choice: str = Field(default="auto", description="Tool choice strategy: auto, required, none")


# =============================================================================
# Messages
# =============================================================================

@dataclass(frozen=True, slots=True)
class Message:
    """A conversation message in the agent loop."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None  # For role="tool" messages
    name: str | None = None  # Tool name for role="tool" messages

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI API message format."""
        msg: dict[str, Any] = {"role": self.role}

        if self.content is not None:
            msg["content"] = self.content

        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments_json,
                    },
                }
                for tc in self.tool_calls
            ]

        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id

        if self.name:
            msg["name"] = self.name

        return msg


# =============================================================================
# Tool Calls and Results
# =============================================================================

@dataclass(frozen=True, slots=True)
class ToolCall:
    """A parsed tool call from model output."""

    id: str
    name: str
    arguments: dict[str, Any]

    @property
    def arguments_json(self) -> str:
        """Arguments as JSON string."""
        import json
        return json.dumps(self.arguments)

    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> ToolCall:
        """Create a ToolCall with auto-generated ID."""
        return cls(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=name,
            arguments=arguments,
        )


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Result of executing a tool."""

    call_id: str
    name: str
    output: str | dict[str, Any]
    is_error: bool = False

    @property
    def output_str(self) -> str:
        """Output as string."""
        if isinstance(self.output, str):
            return self.output
        import json
        return json.dumps(self.output)

    def to_message(self) -> Message:
        """Convert to a tool response message."""
        return Message(
            role="tool",
            content=self.output_str,
            tool_call_id=self.call_id,
            name=self.name,
        )


# =============================================================================
# Tool Schemas
# =============================================================================

@dataclass(frozen=True, slots=True)
class ToolSchema:
    """Schema for a tool, in OpenAI function format."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema
    script_path: Path | None = None  # For backends that use scripts
    context_providers: tuple[Path, ...] = ()  # Pre-execution context scripts

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI tools array format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


# =============================================================================
# Token Usage
# =============================================================================

@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token usage statistics from a completion."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# =============================================================================
# Results
# =============================================================================

@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of a single kernel step (one model call + tool execution)."""

    response_message: Message
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    usage: TokenUsage | None = None


@dataclass(frozen=True)
class RunResult:
    """Result of a full kernel run (multiple turns until termination)."""

    final_message: Message
    history: list[Message]
    turn_count: int
    termination_reason: str  # "max_turns", "termination_tool", "no_tool_calls", "error"
    final_tool_result: ToolResult | None = None  # The terminating tool result, if any
    total_usage: TokenUsage | None = None
```

### Testing Step 2

Create **`tests/test_types.py`**:

```python
"""Tests for core types."""

import json
import pytest
from structured_agents.types import (
    KernelConfig,
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
)


class TestKernelConfig:
    def test_defaults(self):
        config = KernelConfig(base_url="http://localhost:8000/v1", model="test")
        assert config.api_key == "EMPTY"
        assert config.timeout == 120.0
        assert config.temperature == 0.1
        assert config.tool_choice == "auto"

    def test_custom_values(self):
        config = KernelConfig(
            base_url="http://example.com",
            model="custom-model",
            temperature=0.7,
            max_tokens=2048,
        )
        assert config.temperature == 0.7
        assert config.max_tokens == 2048


class TestMessage:
    def test_simple_message(self):
        msg = Message(role="user", content="Hello")
        assert msg.to_openai_format() == {"role": "user", "content": "Hello"}

    def test_assistant_with_tool_calls(self):
        tc = ToolCall(id="call_123", name="read_file", arguments={"path": "/foo"})
        msg = Message(role="assistant", content=None, tool_calls=[tc])
        fmt = msg.to_openai_format()
        assert fmt["role"] == "assistant"
        assert len(fmt["tool_calls"]) == 1
        assert fmt["tool_calls"][0]["function"]["name"] == "read_file"

    def test_tool_response(self):
        msg = Message(role="tool", content="file contents", tool_call_id="call_123", name="read_file")
        fmt = msg.to_openai_format()
        assert fmt["role"] == "tool"
        assert fmt["tool_call_id"] == "call_123"
        assert fmt["name"] == "read_file"


class TestToolCall:
    def test_create_auto_id(self):
        tc = ToolCall.create(name="test", arguments={"x": 1})
        assert tc.name == "test"
        assert tc.arguments == {"x": 1}
        assert tc.id.startswith("call_")
        assert len(tc.id) == 13  # "call_" + 8 hex chars

    def test_arguments_json(self):
        tc = ToolCall(id="123", name="test", arguments={"nested": {"a": 1}})
        parsed = json.loads(tc.arguments_json)
        assert parsed == {"nested": {"a": 1}}


class TestToolResult:
    def test_string_output(self):
        result = ToolResult(call_id="123", name="test", output="hello")
        assert result.output_str == "hello"

    def test_dict_output(self):
        result = ToolResult(call_id="123", name="test", output={"key": "value"})
        assert result.output_str == '{"key": "value"}'

    def test_to_message(self):
        result = ToolResult(call_id="123", name="test", output="output")
        msg = result.to_message()
        assert msg.role == "tool"
        assert msg.content == "output"
        assert msg.tool_call_id == "123"
        assert msg.name == "test"

    def test_error_result(self):
        result = ToolResult(call_id="123", name="test", output="error msg", is_error=True)
        assert result.is_error is True


class TestToolSchema:
    def test_to_openai_format(self):
        schema = ToolSchema(
            name="read_file",
            description="Read a file",
            parameters={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        fmt = schema.to_openai_format()
        assert fmt["type"] == "function"
        assert fmt["function"]["name"] == "read_file"
        assert "path" in fmt["function"]["parameters"]["properties"]
```

Run tests:

```bash
uv run pytest tests/test_types.py -v
```

**Expected:** All tests pass.

---

## Part 3: Observer System

The observer system allows external code (like Remora's TUI) to receive events during kernel execution.

### Step 3.1: Create Observer Events

**File: `src/structured_agents/observer/events.py`**

```python
"""Typed event dataclasses for the observer system."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from structured_agents.types import TokenUsage


@dataclass(frozen=True, slots=True)
class ModelRequestEvent:
    """Fired before making a model request."""

    turn: int
    messages_count: int
    tools_count: int
    model: str


@dataclass(frozen=True, slots=True)
class ModelResponseEvent:
    """Fired after receiving a model response."""

    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None


@dataclass(frozen=True, slots=True)
class ToolCallEvent:
    """Fired before executing a tool."""

    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResultEvent:
    """Fired after a tool execution completes."""

    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str  # First N chars of output


@dataclass(frozen=True, slots=True)
class TurnCompleteEvent:
    """Fired after a full turn (model call + all tool executions)."""

    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int


@dataclass(frozen=True, slots=True)
class KernelStartEvent:
    """Fired when kernel.run() begins."""

    max_turns: int
    tools_count: int
    initial_messages_count: int


@dataclass(frozen=True, slots=True)
class KernelEndEvent:
    """Fired when kernel.run() completes."""

    turn_count: int
    termination_reason: str
    total_duration_ms: int
```

### Step 3.2: Create Observer Protocol

**File: `src/structured_agents/observer/protocol.py`**

```python
"""Observer protocol definition."""

from __future__ import annotations

from typing import Protocol

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class Observer(Protocol):
    """Protocol for receiving kernel execution events.

    All methods are async to allow for I/O operations (logging, network, etc.).
    Implementations should be fast and non-blocking to avoid slowing the kernel.
    """

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        """Called when kernel.run() begins."""
        ...

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        """Called before each model request."""
        ...

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        """Called after each model response."""
        ...

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        """Called before executing each tool."""
        ...

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        """Called after each tool execution."""
        ...

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        """Called after each complete turn."""
        ...

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        """Called when kernel.run() completes."""
        ...

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        """Called when an error occurs."""
        ...
```

### Step 3.3: Create NullObserver

**File: `src/structured_agents/observer/null.py`**

```python
"""Null observer implementation (no-op)."""

from __future__ import annotations

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)


class NullObserver:
    """Observer that does nothing. Used as default."""

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        pass

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        pass

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        pass

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        pass

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        pass

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        pass

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        pass

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        pass
```

### Step 3.4: Create CompositeObserver

**File: `src/structured_agents/observer/composite.py`**

```python
"""Composite observer for fan-out to multiple observers."""

from __future__ import annotations

import asyncio
import logging
from typing import Sequence

from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.observer.protocol import Observer

logger = logging.getLogger(__name__)


class CompositeObserver:
    """Fan-out observer that forwards events to multiple child observers.

    If a child observer raises an exception, it is logged but does not
    prevent other observers from receiving the event.
    """

    def __init__(self, observers: Sequence[Observer]):
        self._observers = list(observers)

    async def _notify_all(self, method_name: str, *args, **kwargs) -> None:
        """Call a method on all observers, catching exceptions."""
        tasks = []
        for obs in self._observers:
            method = getattr(obs, method_name, None)
            if method:
                tasks.append(method(*args, **kwargs))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"Observer {self._observers[i].__class__.__name__}.{method_name} "
                        f"raised {type(result).__name__}: {result}"
                    )

    async def on_kernel_start(self, event: KernelStartEvent) -> None:
        await self._notify_all("on_kernel_start", event)

    async def on_model_request(self, event: ModelRequestEvent) -> None:
        await self._notify_all("on_model_request", event)

    async def on_model_response(self, event: ModelResponseEvent) -> None:
        await self._notify_all("on_model_response", event)

    async def on_tool_call(self, event: ToolCallEvent) -> None:
        await self._notify_all("on_tool_call", event)

    async def on_tool_result(self, event: ToolResultEvent) -> None:
        await self._notify_all("on_tool_result", event)

    async def on_turn_complete(self, event: TurnCompleteEvent) -> None:
        await self._notify_all("on_turn_complete", event)

    async def on_kernel_end(self, event: KernelEndEvent) -> None:
        await self._notify_all("on_kernel_end", event)

    async def on_error(self, error: Exception, context: str | None = None) -> None:
        await self._notify_all("on_error", error, context)
```

### Step 3.5: Update observer/__init__.py

**File: `src/structured_agents/observer/__init__.py`**

```python
"""Observer system for kernel execution events."""

from structured_agents.observer.composite import CompositeObserver
from structured_agents.observer.events import (
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)
from structured_agents.observer.null import NullObserver
from structured_agents.observer.protocol import Observer

__all__ = [
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
]
```

### Testing Step 3

Create **`tests/test_observer/test_observer.py`**:

```python
"""Tests for the observer system."""

import pytest
from structured_agents.observer import (
    CompositeObserver,
    NullObserver,
    ModelRequestEvent,
    ToolResultEvent,
)


class RecordingObserver:
    """Test observer that records all events."""

    def __init__(self):
        self.events = []

    async def on_kernel_start(self, event):
        self.events.append(("kernel_start", event))

    async def on_model_request(self, event):
        self.events.append(("model_request", event))

    async def on_model_response(self, event):
        self.events.append(("model_response", event))

    async def on_tool_call(self, event):
        self.events.append(("tool_call", event))

    async def on_tool_result(self, event):
        self.events.append(("tool_result", event))

    async def on_turn_complete(self, event):
        self.events.append(("turn_complete", event))

    async def on_kernel_end(self, event):
        self.events.append(("kernel_end", event))

    async def on_error(self, error, context=None):
        self.events.append(("error", error, context))


class FailingObserver:
    """Observer that raises exceptions."""

    async def on_model_request(self, event):
        raise ValueError("Intentional failure")

    async def on_tool_result(self, event):
        pass  # This one works


class TestNullObserver:
    @pytest.mark.asyncio
    async def test_all_methods_are_noop(self):
        obs = NullObserver()
        event = ModelRequestEvent(turn=1, messages_count=2, tools_count=3, model="test")
        # Should not raise
        await obs.on_model_request(event)
        await obs.on_error(ValueError("test"))


class TestCompositeObserver:
    @pytest.mark.asyncio
    async def test_forwards_to_all_observers(self):
        obs1 = RecordingObserver()
        obs2 = RecordingObserver()
        composite = CompositeObserver([obs1, obs2])

        event = ModelRequestEvent(turn=1, messages_count=2, tools_count=3, model="test")
        await composite.on_model_request(event)

        assert len(obs1.events) == 1
        assert len(obs2.events) == 1
        assert obs1.events[0] == ("model_request", event)
        assert obs2.events[0] == ("model_request", event)

    @pytest.mark.asyncio
    async def test_continues_on_observer_failure(self):
        failing = FailingObserver()
        recording = RecordingObserver()
        composite = CompositeObserver([failing, recording])

        event = ModelRequestEvent(turn=1, messages_count=2, tools_count=3, model="test")
        # Should not raise, even though failing observer raises
        await composite.on_model_request(event)

        # Recording observer should still have received the event
        assert len(recording.events) == 1

    @pytest.mark.asyncio
    async def test_empty_composite(self):
        composite = CompositeObserver([])
        event = ModelRequestEvent(turn=1, messages_count=2, tools_count=3, model="test")
        # Should not raise
        await composite.on_model_request(event)
```

Run tests:

```bash
uv run pytest tests/test_observer/ -v
```

**Expected:** All tests pass.

---

## Part 4: History Management

### Step 4.1: Create history.py

**File: `src/structured_agents/history.py`**

```python
"""History management strategies for the agent loop."""

from __future__ import annotations

from typing import Protocol

from structured_agents.types import Message


class HistoryStrategy(Protocol):
    """Protocol for managing conversation history.

    Implementations control how history is trimmed to fit context limits.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        """Trim history to fit within limits.

        Args:
            messages: Current message history.
            max_messages: Maximum number of messages to retain.

        Returns:
            Trimmed message list. Must preserve the first message (system prompt)
            if it exists and is a system message.
        """
        ...


class SlidingWindowHistory:
    """Simple sliding window that keeps the system prompt + most recent messages.

    This is the default strategy. It preserves the system prompt (first message
    if role="system") and keeps the N most recent messages after that.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        if len(messages) <= max_messages:
            return messages

        if not messages:
            return messages

        # Check if first message is system prompt
        if messages[0].role == "system":
            # Keep system prompt + most recent (max_messages - 1)
            system_msg = messages[0]
            recent = messages[-(max_messages - 1):]
            return [system_msg] + recent
        else:
            # No system prompt, just keep most recent
            return messages[-max_messages:]


class KeepAllHistory:
    """Strategy that keeps all messages (no trimming).

    Use with caution - can exceed context limits.
    """

    def trim(self, messages: list[Message], max_messages: int) -> list[Message]:
        return messages
```

### Testing Step 4

Create **`tests/test_history.py`**:

```python
"""Tests for history management."""

import pytest
from structured_agents.history import SlidingWindowHistory, KeepAllHistory
from structured_agents.types import Message


class TestSlidingWindowHistory:
    def test_no_trim_needed(self):
        strategy = SlidingWindowHistory()
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi!"),
        ]
        result = strategy.trim(messages, max_messages=5)
        assert result == messages

    def test_trim_preserves_system_prompt(self):
        strategy = SlidingWindowHistory()
        messages = [
            Message(role="system", content="System prompt"),
            Message(role="user", content="Msg 1"),
            Message(role="assistant", content="Msg 2"),
            Message(role="user", content="Msg 3"),
            Message(role="assistant", content="Msg 4"),
            Message(role="user", content="Msg 5"),
        ]
        result = strategy.trim(messages, max_messages=3)

        # Should keep system + last 2
        assert len(result) == 3
        assert result[0].content == "System prompt"
        assert result[1].content == "Msg 4"
        assert result[2].content == "Msg 5"

    def test_trim_no_system_prompt(self):
        strategy = SlidingWindowHistory()
        messages = [
            Message(role="user", content="Msg 1"),
            Message(role="assistant", content="Msg 2"),
            Message(role="user", content="Msg 3"),
            Message(role="assistant", content="Msg 4"),
        ]
        result = strategy.trim(messages, max_messages=2)

        assert len(result) == 2
        assert result[0].content == "Msg 3"
        assert result[1].content == "Msg 4"

    def test_empty_list(self):
        strategy = SlidingWindowHistory()
        result = strategy.trim([], max_messages=5)
        assert result == []


class TestKeepAllHistory:
    def test_keeps_everything(self):
        strategy = KeepAllHistory()
        messages = [Message(role="user", content=f"Msg {i}") for i in range(100)]
        result = strategy.trim(messages, max_messages=5)
        assert len(result) == 100
```

Run tests:

```bash
uv run pytest tests/test_history.py -v
```

**Expected:** All tests pass.

---

## Part 5: Model Plugin System

### Step 5.1: Create Plugin Protocol

**File: `src/structured_agents/plugins/protocol.py`**

```python
"""Model plugin protocol definition."""

from __future__ import annotations

from typing import Any, Protocol

from structured_agents.types import Message, ToolCall, ToolSchema


class ModelPlugin(Protocol):
    """Protocol for model-specific formatting and parsing.

    Different models have different expectations for:
    - How messages are formatted
    - How tool calls are represented in output
    - What grammar constraints to apply

    Implementations handle these model-specific quirks.
    """

    @property
    def name(self) -> str:
        """Plugin identifier (e.g., 'function_gemma', 'qwen')."""
        ...

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
    ) -> list[dict[str, Any]]:
        """Convert messages to model-specific API format.

        Args:
            messages: Conversation history.
            tools: Available tools (may affect formatting).

        Returns:
            List of message dicts ready for the API.
        """
        ...

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Convert tool schemas to API format.

        Args:
            tools: Tool schemas.

        Returns:
            List of tool dicts ready for the API.
        """
        ...

    def build_grammar(self, tools: list[ToolSchema]) -> str | None:
        """Build XGrammar EBNF for constrained decoding.

        Args:
            tools: Available tools.

        Returns:
            EBNF grammar string, or None to disable grammar enforcement.
        """
        ...

    def parse_response(
        self,
        content: str | None,
        tool_calls_raw: list[dict[str, Any]] | None,
    ) -> tuple[str | None, list[ToolCall]]:
        """Parse model response into content and tool calls.

        Args:
            content: Response text content (may be None).
            tool_calls_raw: Raw tool calls from API (may be None).

        Returns:
            Tuple of (text_content, list_of_tool_calls).
        """
        ...

    def extra_body(self, grammar: str | None) -> dict[str, Any] | None:
        """Build extra_body for vLLM structured outputs.

        Args:
            grammar: EBNF grammar string (may be None).

        Returns:
            Dict to pass as extra_body to the API, or None.
        """
        ...
```

### Step 5.2: Create FunctionGemma Grammar Builder

**File: `src/structured_agents/plugins/grammar/function_gemma.py`**

```python
"""EBNF grammar builder for FunctionGemma format."""

from __future__ import annotations

from structured_agents.types import ToolSchema


def build_functiongemma_grammar(tools: list[ToolSchema]) -> str:
    """Build EBNF grammar for FunctionGemma tool calling format.

    FunctionGemma uses a specific format:
        <start_function_call>call:tool_name{arg1:value1,arg2:value2}<end_function_call>

    This grammar ensures the model output follows this format exactly.

    Args:
        tools: Available tool schemas.

    Returns:
        EBNF grammar string for XGrammar.
    """
    if not tools:
        # No tools = no grammar constraint, allow free text
        return ""

    tool_names = [tool.name for tool in tools]
    tool_name_rule = " | ".join(f'"{name}"' for name in tool_names)

    grammar = f'''
root ::= function_call

function_call ::= "<start_function_call>" "call:" tool_name "{{" arg_body "}}" "<end_function_call>"

tool_name ::= {tool_name_rule}

arg_body ::= arg_char*

arg_char ::= [^}}]
'''
    return grammar.strip()
```

### Step 5.3: Create FunctionGemma Plugin

**File: `src/structured_agents/plugins/function_gemma.py`**

```python
"""FunctionGemma model plugin implementation."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from structured_agents.exceptions import PluginError
from structured_agents.plugins.grammar.function_gemma import build_functiongemma_grammar
from structured_agents.types import Message, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class FunctionGemmaPlugin:
    """Plugin for Google's FunctionGemma models.

    FunctionGemma uses a specific output format:
        <start_function_call>call:tool_name{arg1:value1}<end_function_call>

    This plugin handles:
    - Building the appropriate grammar for constrained decoding
    - Parsing tool calls from the constrained output
    - Formatting messages in the expected format
    """

    name = "function_gemma"

    # Regex to extract tool calls from FunctionGemma format
    _TOOL_CALL_PATTERN = re.compile(
        r"<start_function_call>call:(\w+)\{([^}]*)\}<end_function_call>"
    )

    # Regex to parse key:value pairs from arguments
    _ARG_PATTERN = re.compile(r'(\w+):([^,}]+(?:,[^,}]+)*)')

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
    ) -> list[dict[str, Any]]:
        """Format messages for FunctionGemma."""
        formatted = []
        for msg in messages:
            formatted.append(msg.to_openai_format())
        return formatted

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Format tools for the API."""
        return [tool.to_openai_format() for tool in tools]

    def build_grammar(self, tools: list[ToolSchema]) -> str | None:
        """Build EBNF grammar for FunctionGemma format."""
        if not tools:
            return None
        return build_functiongemma_grammar(tools)

    def parse_response(
        self,
        content: str | None,
        tool_calls_raw: list[dict[str, Any]] | None,
    ) -> tuple[str | None, list[ToolCall]]:
        """Parse FunctionGemma response.

        FunctionGemma can output tool calls in two ways:
        1. Standard OpenAI format (tool_calls_raw)
        2. Grammar-constrained format in content

        We check both and prefer standard format if present.
        """
        tool_calls: list[ToolCall] = []

        # First, check for standard tool_calls format
        if tool_calls_raw:
            for tc in tool_calls_raw:
                try:
                    func = tc.get("function", {})
                    args_str = func.get("arguments", "{}")
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                    tool_calls.append(ToolCall(
                        id=tc.get("id", f"call_{id(tc)}"),
                        name=func.get("name", "unknown"),
                        arguments=args,
                    ))
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(f"Failed to parse tool call: {e}")
            return content, tool_calls

        # Second, try to parse from grammar-constrained content
        if content:
            matches = self._TOOL_CALL_PATTERN.findall(content)
            for name, args_str in matches:
                args = self._parse_arguments(args_str)
                tool_calls.append(ToolCall.create(name=name, arguments=args))

            # If we found tool calls, the "content" is really just the tool calls
            if tool_calls:
                return None, tool_calls

        return content, tool_calls

    def _parse_arguments(self, args_str: str) -> dict[str, Any]:
        """Parse FunctionGemma argument format.

        Format: key1:value1,key2:value2
        Values may be JSON or plain strings.
        """
        args: dict[str, Any] = {}

        if not args_str.strip():
            return args

        # Try to parse as JSON first (for complex arguments)
        try:
            # Wrap in braces if not already JSON
            if not args_str.strip().startswith("{"):
                args_str_json = "{" + args_str + "}"
            else:
                args_str_json = args_str
            return json.loads(args_str_json)
        except json.JSONDecodeError:
            pass

        # Fall back to key:value parsing
        for match in self._ARG_PATTERN.finditer(args_str):
            key, value = match.groups()
            # Try to parse value as JSON
            try:
                args[key] = json.loads(value)
            except json.JSONDecodeError:
                # Keep as string
                args[key] = value.strip().strip('"\'')

        return args

    def extra_body(self, grammar: str | None) -> dict[str, Any] | None:
        """Build extra_body for vLLM structured outputs."""
        if not grammar:
            return None

        return {
            "guided_grammar": grammar,
        }
```

### Step 5.4: Create Qwen Plugin (validates interface flexibility)

**File: `src/structured_agents/plugins/qwen.py`**

```python
"""Qwen model plugin implementation."""

from __future__ import annotations

import json
import logging
from typing import Any

from structured_agents.types import Message, ToolCall, ToolSchema

logger = logging.getLogger(__name__)


class QwenPlugin:
    """Plugin for Qwen/Qwen2.5 instruction-tuned models.

    Qwen models use standard OpenAI-compatible tool calling format.
    This plugin demonstrates that the interface works for different models.
    """

    name = "qwen"

    def format_messages(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
    ) -> list[dict[str, Any]]:
        """Format messages for Qwen."""
        return [msg.to_openai_format() for msg in messages]

    def format_tools(self, tools: list[ToolSchema]) -> list[dict[str, Any]]:
        """Format tools for the API."""
        return [tool.to_openai_format() for tool in tools]

    def build_grammar(self, tools: list[ToolSchema]) -> str | None:
        """Qwen uses standard tool calling, no grammar needed."""
        return None

    def parse_response(
        self,
        content: str | None,
        tool_calls_raw: list[dict[str, Any]] | None,
    ) -> tuple[str | None, list[ToolCall]]:
        """Parse Qwen response (standard OpenAI format)."""
        tool_calls: list[ToolCall] = []

        if tool_calls_raw:
            for tc in tool_calls_raw:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    args = {}
                    logger.warning(f"Failed to parse arguments: {args_str}")

                tool_calls.append(ToolCall(
                    id=tc.get("id", f"call_{id(tc)}"),
                    name=func.get("name", "unknown"),
                    arguments=args,
                ))

        return content, tool_calls

    def extra_body(self, grammar: str | None) -> dict[str, Any] | None:
        """Qwen doesn't use grammar constraints."""
        return None
```

### Step 5.5: Update plugins/__init__.py

**File: `src/structured_agents/plugins/__init__.py`**

```python
"""Model plugins for structured-agents."""

from structured_agents.plugins.function_gemma import FunctionGemmaPlugin
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.plugins.qwen import QwenPlugin

__all__ = [
    "ModelPlugin",
    "FunctionGemmaPlugin",
    "QwenPlugin",
]
```

### Testing Step 5

Create **`tests/test_plugins/test_function_gemma.py`**:

```python
"""Tests for FunctionGemma plugin."""

import pytest
from structured_agents.plugins import FunctionGemmaPlugin
from structured_agents.plugins.grammar.function_gemma import build_functiongemma_grammar
from structured_agents.types import Message, ToolSchema


class TestFunctionGemmaGrammar:
    def test_empty_tools_returns_empty(self):
        grammar = build_functiongemma_grammar([])
        assert grammar == ""

    def test_single_tool(self):
        tools = [
            ToolSchema(name="read_file", description="Read a file", parameters={}),
        ]
        grammar = build_functiongemma_grammar(tools)
        assert "read_file" in grammar
        assert "<start_function_call>" in grammar
        assert "<end_function_call>" in grammar

    def test_multiple_tools(self):
        tools = [
            ToolSchema(name="read_file", description="Read", parameters={}),
            ToolSchema(name="write_file", description="Write", parameters={}),
        ]
        grammar = build_functiongemma_grammar(tools)
        assert "read_file" in grammar
        assert "write_file" in grammar


class TestFunctionGemmaPlugin:
    def test_name(self):
        plugin = FunctionGemmaPlugin()
        assert plugin.name == "function_gemma"

    def test_format_messages(self):
        plugin = FunctionGemmaPlugin()
        messages = [
            Message(role="system", content="You are helpful."),
            Message(role="user", content="Hello"),
        ]
        formatted = plugin.format_messages(messages, [])
        assert len(formatted) == 2
        assert formatted[0]["role"] == "system"
        assert formatted[1]["content"] == "Hello"

    def test_parse_standard_tool_calls(self):
        plugin = FunctionGemmaPlugin()
        tool_calls_raw = [
            {
                "id": "call_123",
                "function": {
                    "name": "read_file",
                    "arguments": '{"path": "/test.txt"}',
                },
            }
        ]
        content, calls = plugin.parse_response(None, tool_calls_raw)
        assert content is None
        assert len(calls) == 1
        assert calls[0].name == "read_file"
        assert calls[0].arguments == {"path": "/test.txt"}

    def test_parse_grammar_format(self):
        plugin = FunctionGemmaPlugin()
        content = "<start_function_call>call:read_file{path:/test.txt}<end_function_call>"
        result_content, calls = plugin.parse_response(content, None)
        assert result_content is None  # Content was a tool call
        assert len(calls) == 1
        assert calls[0].name == "read_file"

    def test_extra_body_with_grammar(self):
        plugin = FunctionGemmaPlugin()
        result = plugin.extra_body("some grammar")
        assert result == {"guided_grammar": "some grammar"}

    def test_extra_body_without_grammar(self):
        plugin = FunctionGemmaPlugin()
        result = plugin.extra_body(None)
        assert result is None
```

Run tests:

```bash
uv run pytest tests/test_plugins/ -v
```

**Expected:** All tests pass.

---

## Part 6: Tool Backend System

### Step 6.1: Create Backend Protocol

**File: `src/structured_agents/backends/protocol.py`**

```python
"""Tool backend protocol definition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from structured_agents.types import ToolCall, ToolResult, ToolSchema


@dataclass
class Snapshot:
    """Snapshot of backend state for pause/resume functionality."""

    id: str
    backend_type: str
    state: dict[str, Any]


class ToolBackend(Protocol):
    """Protocol for tool execution backends.

    Backends handle the actual execution of tools. The default implementation
    uses Grail .pym scripts, but backends can use any execution strategy.
    """

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a single tool call.

        Args:
            tool_call: The parsed tool call with name and arguments.
            tool_schema: Schema for the tool (may include script path).
            context: Additional context to merge with arguments.

        Returns:
            ToolResult with output or error.
        """
        ...

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Execute context provider scripts before tool execution.

        Context providers inject domain-specific context (e.g., reading
        project config files) that gets prepended to tool results.

        Args:
            providers: Paths to context provider scripts.
            context: Base context for provider execution.

        Returns:
            List of serialized provider outputs.
        """
        ...

    def supports_snapshots(self) -> bool:
        """Check if this backend supports pause/resume via snapshots."""
        ...

    def create_snapshot(self) -> Snapshot | None:
        """Create a snapshot of current backend state.

        Returns:
            Snapshot object for pause/resume, or None if not supported.
        """
        ...

    def restore_snapshot(self, snapshot: Snapshot) -> None:
        """Restore backend state from a snapshot."""
        ...
```

### Step 6.2: Create Simple Python Backend

**File: `src/structured_agents/backends/python.py`**

```python
"""Simple Python function backend for testing and simple use cases."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Awaitable

from structured_agents.backends.protocol import Snapshot
from structured_agents.types import ToolCall, ToolResult, ToolSchema


class PythonBackend:
    """Backend that executes Python functions directly.

    This is useful for:
    - Testing without Grail dependencies
    - Simple tools that don't need sandboxing
    - Wrapping existing Python functions as tools
    """

    def __init__(
        self,
        handlers: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    ):
        """Initialize with optional tool handlers.

        Args:
            handlers: Dict mapping tool names to async handler functions.
                      Handler signature: async def handler(**kwargs) -> Any
        """
        self._handlers = handlers or {}

    def register(
        self,
        name: str,
        handler: Callable[..., Awaitable[Any]],
    ) -> None:
        """Register a tool handler.

        Args:
            name: Tool name.
            handler: Async function to handle the tool.
        """
        self._handlers[name] = handler

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a tool using the registered handler."""
        handler = self._handlers.get(tool_call.name)

        if not handler:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"No handler registered for tool: {tool_call.name}",
                is_error=True,
            )

        try:
            # Merge context with arguments (arguments take precedence)
            kwargs = {**context, **tool_call.arguments}
            result = await handler(**kwargs)

            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=result,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"{type(e).__name__}: {e}",
                is_error=True,
            )

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Python backend doesn't support context providers."""
        return []

    def supports_snapshots(self) -> bool:
        return False

    def create_snapshot(self) -> Snapshot | None:
        return None

    def restore_snapshot(self, snapshot: Snapshot) -> None:
        pass
```

### Step 6.3: Create Grail Backend Stub

**File: `src/structured_agents/backends/grail.py`**

```python
"""Grail .pym script execution backend.

This backend executes tools defined as Grail .pym scripts in isolated
processes. It's the default backend for production use.

Note: This module requires the 'grail' optional dependency.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from structured_agents.backends.protocol import Snapshot
from structured_agents.exceptions import BackendError
from structured_agents.types import ToolCall, ToolResult, ToolSchema

logger = logging.getLogger(__name__)


@dataclass
class GrailBackendConfig:
    """Configuration for the Grail backend."""

    grail_dir: Path = field(default_factory=Path.cwd)
    max_workers: int = 4
    timeout: float = 300.0
    limits: dict[str, Any] = field(default_factory=lambda: {
        "max_memory_mb": 512,
        "max_duration_s": 60,
        "max_recursion": 100,
    })


class GrailBackend:
    """Backend that executes Grail .pym scripts in isolated processes.

    This backend:
    - Runs .pym scripts in separate processes for isolation
    - Supports context providers for injecting per-tool context
    - Handles Grail limits (memory, duration, recursion)
    - Optionally supports snapshots for pause/resume
    """

    def __init__(
        self,
        config: GrailBackendConfig | None = None,
        externals_factory: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    ):
        """Initialize the Grail backend.

        Args:
            config: Backend configuration.
            externals_factory: Factory function to create Grail externals.
                Signature: (agent_id, context) -> externals_dict
        """
        self._config = config or GrailBackendConfig()
        self._externals_factory = externals_factory
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=self._config.max_workers
        )
        self._snapshots: dict[str, Snapshot] = {}

    async def execute(
        self,
        tool_call: ToolCall,
        tool_schema: ToolSchema,
        context: dict[str, Any],
    ) -> ToolResult:
        """Execute a .pym script for the tool call."""
        # Run context providers first
        if tool_schema.context_providers:
            try:
                context_outputs = await self.run_context_providers(
                    list(tool_schema.context_providers),
                    context,
                )
            except Exception as e:
                logger.warning(f"Context provider failed: {e}")
                context_outputs = []
        else:
            context_outputs = []

        # Get script path
        script_path = tool_schema.script_path
        if not script_path:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"No script path for tool: {tool_call.name}",
                is_error=True,
            )

        # Merge inputs
        inputs = {**context, **tool_call.arguments}

        # Execute in process pool
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    self._executor,
                    _run_grail_script,
                    str(script_path),
                    str(self._config.grail_dir),
                    inputs,
                    self._config.limits,
                    context.get("agent_id"),
                    context.get("workspace_path"),
                    context.get("stable_path"),
                    context.get("node_source"),
                    context.get("node_metadata"),
                    self._externals_factory,
                ),
                timeout=self._config.timeout,
            )
        except asyncio.TimeoutError:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"Tool execution timed out after {self._config.timeout}s",
                is_error=True,
            )
        except Exception as e:
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=f"Execution error: {type(e).__name__}: {e}",
                is_error=True,
            )

        # Format result
        if result.get("error"):
            return ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                output=result,
                is_error=True,
            )

        # Combine context provider outputs with result
        tool_output = result.get("result", {})
        if context_outputs:
            combined = "\n".join(context_outputs)
            if isinstance(tool_output, str):
                combined += "\n" + tool_output
            else:
                combined += "\n" + json.dumps(tool_output)
            output = combined
        else:
            output = tool_output

        return ToolResult(
            call_id=tool_call.id,
            name=tool_call.name,
            output=output,
            is_error=False,
        )

    async def run_context_providers(
        self,
        providers: list[Path],
        context: dict[str, Any],
    ) -> list[str]:
        """Execute context provider scripts."""
        outputs = []
        for provider_path in providers:
            try:
                loop = asyncio.get_event_loop()
                result = await loop.run_in_executor(
                    self._executor,
                    _run_grail_script,
                    str(provider_path),
                    str(self._config.grail_dir),
                    context,
                    self._config.limits,
                    None, None, None, None, None, None,
                )
                if not result.get("error"):
                    output = result.get("result", "")
                    if isinstance(output, dict):
                        output = json.dumps(output)
                    outputs.append(str(output))
            except Exception as e:
                logger.warning(f"Context provider {provider_path} failed: {e}")

        return outputs

    def supports_snapshots(self) -> bool:
        return True

    def create_snapshot(self) -> Snapshot | None:
        snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
        snapshot = Snapshot(
            id=snapshot_id,
            backend_type="grail",
            state={},  # Grail snapshots would include script state
        )
        self._snapshots[snapshot_id] = snapshot
        return snapshot

    def restore_snapshot(self, snapshot: Snapshot) -> None:
        if snapshot.id not in self._snapshots:
            raise BackendError(f"Unknown snapshot: {snapshot.id}")
        # Restore logic would go here

    def shutdown(self) -> None:
        """Shutdown the process pool."""
        self._executor.shutdown(wait=True)


def _run_grail_script(
    pym_path: str,
    grail_dir: str,
    inputs: dict[str, Any],
    limits: dict[str, Any],
    agent_id: str | None,
    workspace_path: str | None,
    stable_path: str | None,
    node_source: str | None,
    node_metadata: dict[str, Any] | None,
    externals_factory: Callable | None,
) -> dict[str, Any]:
    """Execute a .pym script in a child process.

    This function runs in a separate OS process via ProcessPoolExecutor.
    """
    try:
        import grail
    except ImportError:
        return {
            "error": True,
            "code": "IMPORT_ERROR",
            "message": "grail package not installed. Install with: pip install structured-agents[grail]",
        }

    async def _execute_async() -> dict[str, Any]:
        path = Path(pym_path)
        if not path.exists():
            return {"error": True, "code": "FILE_NOT_FOUND", "message": f".pym file not found: {pym_path}"}

        try:
            script = grail.load(pym_path, grail_dir=grail_dir)
        except Exception as exc:
            return {"error": True, "code": "LOAD_ERROR", "message": f"{type(exc).__name__}: {exc}"}

        check = script.check()
        if not check.valid:
            errors = [str(e) for e in (check.errors or [])]
            return {"error": True, "code": "GRAIL_CHECK", "message": "; ".join(errors)}

        externals = {}
        if externals_factory and agent_id:
            try:
                externals = externals_factory(agent_id, {
                    "workspace_path": workspace_path,
                    "stable_path": stable_path,
                    "node_source": node_source,
                    "node_metadata": node_metadata,
                })
            except Exception as e:
                return {"error": True, "code": "EXTERNALS_ERROR", "message": str(e)}

        try:
            result = await script.run(inputs=inputs, limits=limits, externals=externals)
            return {"error": False, "result": result}
        except grail.LimitError as exc:
            return {"error": True, "code": "LIMIT", "message": str(exc)}
        except grail.ExecutionError as exc:
            return {"error": True, "code": "EXECUTION", "message": str(exc)}
        except grail.GrailError as exc:
            return {"error": True, "code": "GRAIL", "message": str(exc)}

    import asyncio
    return asyncio.run(_execute_async())
```

### Step 6.4: Update backends/__init__.py

**File: `src/structured_agents/backends/__init__.py`**

```python
"""Tool execution backends."""

from structured_agents.backends.protocol import Snapshot, ToolBackend
from structured_agents.backends.python import PythonBackend

# GrailBackend is optional
try:
    from structured_agents.backends.grail import GrailBackend, GrailBackendConfig
except ImportError:
    GrailBackend = None  # type: ignore
    GrailBackendConfig = None  # type: ignore

__all__ = [
    "ToolBackend",
    "Snapshot",
    "PythonBackend",
    "GrailBackend",
    "GrailBackendConfig",
]
```

### Testing Step 6

Create **`tests/test_backends/test_python_backend.py`**:

```python
"""Tests for Python backend."""

import pytest
from structured_agents.backends import PythonBackend
from structured_agents.types import ToolCall, ToolSchema


class TestPythonBackend:
    @pytest.mark.asyncio
    async def test_execute_registered_handler(self):
        backend = PythonBackend()

        async def my_handler(x: int, y: int) -> int:
            return x + y

        backend.register("add", my_handler)

        tool_call = ToolCall(id="123", name="add", arguments={"x": 2, "y": 3})
        tool_schema = ToolSchema(name="add", description="Add numbers", parameters={})

        result = await backend.execute(tool_call, tool_schema, {})

        assert result.is_error is False
        assert result.output == 5

    @pytest.mark.asyncio
    async def test_execute_unregistered_handler(self):
        backend = PythonBackend()

        tool_call = ToolCall(id="123", name="unknown", arguments={})
        tool_schema = ToolSchema(name="unknown", description="Unknown", parameters={})

        result = await backend.execute(tool_call, tool_schema, {})

        assert result.is_error is True
        assert "No handler registered" in result.output

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self):
        backend = PythonBackend()

        async def failing_handler() -> None:
            raise ValueError("Intentional error")

        backend.register("fail", failing_handler)

        tool_call = ToolCall(id="123", name="fail", arguments={})
        tool_schema = ToolSchema(name="fail", description="Fail", parameters={})

        result = await backend.execute(tool_call, tool_schema, {})

        assert result.is_error is True
        assert "ValueError" in result.output

    @pytest.mark.asyncio
    async def test_context_merged_with_arguments(self):
        backend = PythonBackend()
        received_kwargs = {}

        async def capture_handler(**kwargs):
            received_kwargs.update(kwargs)
            return "ok"

        backend.register("capture", capture_handler)

        tool_call = ToolCall(id="123", name="capture", arguments={"arg1": "value1"})
        tool_schema = ToolSchema(name="capture", description="Capture", parameters={})
        context = {"ctx1": "ctx_value"}

        await backend.execute(tool_call, tool_schema, context)

        assert received_kwargs["arg1"] == "value1"
        assert received_kwargs["ctx1"] == "ctx_value"

    def test_supports_snapshots_is_false(self):
        backend = PythonBackend()
        assert backend.supports_snapshots() is False
```

Run tests:

```bash
uv run pytest tests/test_backends/ -v
```

**Expected:** All tests pass.

---

## Part 7: LLM Client

### Step 7.1: Create Client Protocol

**File: `src/structured_agents/client/protocol.py`**

```python
"""LLM client protocol definition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from structured_agents.types import TokenUsage


@dataclass
class CompletionResponse:
    """Response from an LLM completion request."""

    content: str | None
    tool_calls: list[dict[str, Any]] | None
    usage: TokenUsage | None
    finish_reason: str | None
    raw_response: dict[str, Any]


class LLMClient(Protocol):
    """Protocol for LLM API clients."""

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        """Make a chat completion request.

        Args:
            messages: List of message dicts.
            tools: List of tool dicts (OpenAI format).
            tool_choice: Tool choice strategy.
            max_tokens: Maximum completion tokens.
            temperature: Sampling temperature.
            extra_body: Additional request body parameters (e.g., for grammar).

        Returns:
            CompletionResponse with the result.
        """
        ...

    async def close(self) -> None:
        """Close any open connections."""
        ...
```

### Step 7.2: Create OpenAI-Compatible Client

**File: `src/structured_agents/client/openai_compat.py`**

```python
"""OpenAI-compatible client for vLLM and similar servers."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI, APIConnectionError, APITimeoutError

from structured_agents.client.protocol import CompletionResponse
from structured_agents.exceptions import KernelError
from structured_agents.types import KernelConfig, TokenUsage

logger = logging.getLogger(__name__)


class OpenAICompatibleClient:
    """Client for OpenAI-compatible APIs (vLLM, etc.)."""

    def __init__(self, config: KernelConfig):
        self._config = config
        self._client = AsyncOpenAI(
            base_url=config.base_url,
            api_key=config.api_key,
            timeout=config.timeout,
        )

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
    ) -> CompletionResponse:
        """Make a chat completion request."""
        try:
            kwargs: dict[str, Any] = {
                "model": self._config.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }

            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = tool_choice

            if extra_body:
                kwargs["extra_body"] = extra_body

            response = await self._client.chat.completions.create(**kwargs)

            # Extract response data
            choice = response.choices[0]
            message = choice.message

            # Parse usage
            usage = None
            if response.usage:
                usage = TokenUsage(
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )

            # Parse tool calls
            tool_calls_raw = None
            if message.tool_calls:
                tool_calls_raw = [
                    {
                        "id": tc.id,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]

            return CompletionResponse(
                content=message.content,
                tool_calls=tool_calls_raw,
                usage=usage,
                finish_reason=choice.finish_reason,
                raw_response=response.model_dump(),
            )

        except APIConnectionError as e:
            raise KernelError(
                f"Failed to connect to LLM server at {self._config.base_url}: {e}",
                phase="model_call",
            )
        except APITimeoutError as e:
            raise KernelError(
                f"LLM request timed out after {self._config.timeout}s: {e}",
                phase="model_call",
            )
        except Exception as e:
            raise KernelError(
                f"LLM request failed: {type(e).__name__}: {e}",
                phase="model_call",
            )

    async def close(self) -> None:
        """Close the client."""
        await self._client.close()
```

### Step 7.3: Update client/__init__.py

**File: `src/structured_agents/client/__init__.py`**

```python
"""LLM client implementations."""

from structured_agents.client.openai_compat import OpenAICompatibleClient
from structured_agents.client.protocol import CompletionResponse, LLMClient

__all__ = [
    "LLMClient",
    "CompletionResponse",
    "OpenAICompatibleClient",
]
```

---

## Part 8: The Agent Kernel

### Step 8.1: Create kernel.py

**File: `src/structured_agents/kernel.py`**

```python
"""AgentKernel - the core agent loop orchestrator."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from structured_agents.backends.protocol import ToolBackend
from structured_agents.client.openai_compat import OpenAICompatibleClient
from structured_agents.exceptions import KernelError
from structured_agents.history import HistoryStrategy, SlidingWindowHistory
from structured_agents.observer import (
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
from structured_agents.plugins.protocol import ModelPlugin
from structured_agents.types import (
    KernelConfig,
    Message,
    RunResult,
    StepResult,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)

logger = logging.getLogger(__name__)

# Type alias for termination condition
TerminationCondition = Callable[[ToolResult], bool]

# Type alias for context provider
ContextProvider = Callable[[], Awaitable[dict[str, Any]]]


@dataclass
class AgentKernel:
    """The core agent loop orchestrator.

    The kernel handles:
    - Making model calls with appropriate formatting
    - Parsing responses and extracting tool calls
    - Executing tools via the backend
    - Managing conversation history
    - Emitting events to observers

    It does NOT handle:
    - Workspace management (that's the consumer's responsibility)
    - Multi-agent orchestration (that's Remora's job)
    - External state management (that's the consumer's job)
    """

    config: KernelConfig
    plugin: ModelPlugin
    backend: ToolBackend
    observer: Observer = field(default_factory=NullObserver)
    history_strategy: HistoryStrategy = field(default_factory=SlidingWindowHistory)
    max_history_messages: int = 50

    def __post_init__(self):
        self._client = OpenAICompatibleClient(self.config)

    async def step(
        self,
        messages: list[Message],
        tools: list[ToolSchema],
        context: dict[str, Any] | None = None,
        turn: int = 1,
    ) -> StepResult:
        """Execute a single turn: model call + tool execution.

        Args:
            messages: Current conversation history.
            tools: Available tool schemas.
            context: Per-step context to pass to tool execution.
            turn: Current turn number (for events).

        Returns:
            StepResult with response, tool calls, and results.
        """
        context = context or {}

        # Format messages and tools using plugin
        formatted_messages = self.plugin.format_messages(messages, tools)
        formatted_tools = self.plugin.format_tools(tools) if tools else None

        # Build grammar if plugin supports it
        grammar = self.plugin.build_grammar(tools) if tools else None
        extra_body = self.plugin.extra_body(grammar)

        # Emit model request event
        await self.observer.on_model_request(ModelRequestEvent(
            turn=turn,
            messages_count=len(messages),
            tools_count=len(tools),
            model=self.config.model,
        ))

        # Make model call
        start_time = time.monotonic()
        response = await self._client.chat_completion(
            messages=formatted_messages,
            tools=formatted_tools,
            tool_choice=self.config.tool_choice if tools else "none",
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            extra_body=extra_body,
        )
        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Parse response using plugin
        content, tool_calls = self.plugin.parse_response(
            response.content,
            response.tool_calls,
        )

        # Emit model response event
        await self.observer.on_model_response(ModelResponseEvent(
            turn=turn,
            duration_ms=duration_ms,
            content=content,
            tool_calls_count=len(tool_calls),
            usage=response.usage,
        ))

        # Create response message
        response_message = Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )

        # Execute tool calls
        tool_results: list[ToolResult] = []
        for tool_call in tool_calls:
            # Find the matching tool schema
            tool_schema = next(
                (t for t in tools if t.name == tool_call.name),
                None,
            )

            if not tool_schema:
                # Unknown tool
                result = ToolResult(
                    call_id=tool_call.id,
                    name=tool_call.name,
                    output=f"Unknown tool: {tool_call.name}",
                    is_error=True,
                )
            else:
                # Emit tool call event
                await self.observer.on_tool_call(ToolCallEvent(
                    turn=turn,
                    tool_name=tool_call.name,
                    call_id=tool_call.id,
                    arguments=tool_call.arguments,
                ))

                # Execute tool
                tool_start = time.monotonic()
                result = await self.backend.execute(tool_call, tool_schema, context)
                tool_duration_ms = int((time.monotonic() - tool_start) * 1000)

                # Emit tool result event
                output_preview = str(result.output)[:200] if result.output else ""
                await self.observer.on_tool_result(ToolResultEvent(
                    turn=turn,
                    tool_name=tool_call.name,
                    call_id=tool_call.id,
                    is_error=result.is_error,
                    duration_ms=tool_duration_ms,
                    output_preview=output_preview,
                ))

            tool_results.append(result)

        return StepResult(
            response_message=response_message,
            tool_calls=tool_calls,
            tool_results=tool_results,
            usage=response.usage,
        )

    async def run(
        self,
        initial_messages: list[Message],
        tools: list[ToolSchema],
        *,
        max_turns: int = 20,
        termination: TerminationCondition | None = None,
        context_provider: ContextProvider | None = None,
    ) -> RunResult:
        """Execute the full agent loop until termination.

        Args:
            initial_messages: Starting conversation (system prompt + user message).
            tools: Available tool schemas.
            max_turns: Maximum iterations before forced stop.
            termination: Optional function that returns True when a tool result
                should terminate the loop (e.g., submit_result tool).
            context_provider: Optional async function to provide per-turn context.

        Returns:
            RunResult with final state and conversation history.
        """
        messages = list(initial_messages)
        turn_count = 0
        final_tool_result: ToolResult | None = None
        termination_reason = "max_turns"
        total_usage = TokenUsage(0, 0, 0)

        # Emit kernel start event
        start_time = time.monotonic()
        await self.observer.on_kernel_start(KernelStartEvent(
            max_turns=max_turns,
            tools_count=len(tools),
            initial_messages_count=len(initial_messages),
        ))

        try:
            while turn_count < max_turns:
                turn_count += 1

                # Get per-turn context
                context = {}
                if context_provider:
                    context = await context_provider()

                # Trim history if needed
                messages = self.history_strategy.trim(messages, self.max_history_messages)

                # Execute step
                step_result = await self.step(
                    messages=messages,
                    tools=tools,
                    context=context,
                    turn=turn_count,
                )

                # Accumulate usage
                if step_result.usage:
                    total_usage = TokenUsage(
                        prompt_tokens=total_usage.prompt_tokens + step_result.usage.prompt_tokens,
                        completion_tokens=total_usage.completion_tokens + step_result.usage.completion_tokens,
                        total_tokens=total_usage.total_tokens + step_result.usage.total_tokens,
                    )

                # Add response to history
                messages.append(step_result.response_message)

                # Add tool results to history
                for result in step_result.tool_results:
                    messages.append(result.to_message())

                # Count errors
                errors_count = sum(1 for r in step_result.tool_results if r.is_error)

                # Emit turn complete event
                await self.observer.on_turn_complete(TurnCompleteEvent(
                    turn=turn_count,
                    tool_calls_count=len(step_result.tool_calls),
                    tool_results_count=len(step_result.tool_results),
                    errors_count=errors_count,
                ))

                # Check termination condition
                if termination:
                    for result in step_result.tool_results:
                        if termination(result):
                            final_tool_result = result
                            termination_reason = "termination_tool"
                            break
                    if final_tool_result:
                        break

                # No tool calls = natural termination
                if not step_result.tool_calls:
                    termination_reason = "no_tool_calls"
                    break

            # Get final message
            final_message = messages[-1] if messages else Message(role="assistant", content="")

            return RunResult(
                final_message=final_message,
                history=messages,
                turn_count=turn_count,
                termination_reason=termination_reason,
                final_tool_result=final_tool_result,
                total_usage=total_usage if total_usage.total_tokens > 0 else None,
            )

        except Exception as e:
            await self.observer.on_error(e, f"turn {turn_count}")
            raise

        finally:
            # Emit kernel end event
            total_duration_ms = int((time.monotonic() - start_time) * 1000)
            await self.observer.on_kernel_end(KernelEndEvent(
                turn_count=turn_count,
                termination_reason=termination_reason,
                total_duration_ms=total_duration_ms,
            ))

    async def close(self) -> None:
        """Close the kernel and release resources."""
        await self._client.close()
```

### Testing Step 8

Create **`tests/test_kernel.py`**:

```python
"""Tests for AgentKernel."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from structured_agents.kernel import AgentKernel
from structured_agents.types import (
    KernelConfig,
    Message,
    ToolCall,
    ToolResult,
    ToolSchema,
    TokenUsage,
)
from structured_agents.plugins import FunctionGemmaPlugin
from structured_agents.backends import PythonBackend
from structured_agents.client.protocol import CompletionResponse


class TestAgentKernel:
    @pytest.fixture
    def config(self):
        return KernelConfig(
            base_url="http://localhost:8000/v1",
            model="test-model",
        )

    @pytest.fixture
    def plugin(self):
        return FunctionGemmaPlugin()

    @pytest.fixture
    def backend(self):
        backend = PythonBackend()

        async def echo_handler(message: str = "") -> str:
            return f"Echo: {message}"

        async def submit_handler(summary: str = "") -> dict:
            return {"status": "success", "summary": summary}

        backend.register("echo", echo_handler)
        backend.register("submit_result", submit_handler)
        return backend

    @pytest.fixture
    def tools(self):
        return [
            ToolSchema(
                name="echo",
                description="Echo a message",
                parameters={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                },
            ),
            ToolSchema(
                name="submit_result",
                description="Submit final result",
                parameters={
                    "type": "object",
                    "properties": {"summary": {"type": "string"}},
                },
            ),
        ]

    @pytest.mark.asyncio
    async def test_step_no_tool_calls(self, config, plugin, backend, tools):
        kernel = AgentKernel(config=config, plugin=plugin, backend=backend)

        # Mock the client
        mock_response = CompletionResponse(
            content="Hello, world!",
            tool_calls=None,
            usage=TokenUsage(10, 5, 15),
            finish_reason="stop",
            raw_response={},
        )
        kernel._client.chat_completion = AsyncMock(return_value=mock_response)

        messages = [Message(role="user", content="Hi")]
        result = await kernel.step(messages, tools)

        assert result.response_message.content == "Hello, world!"
        assert len(result.tool_calls) == 0
        assert len(result.tool_results) == 0

    @pytest.mark.asyncio
    async def test_step_with_tool_calls(self, config, plugin, backend, tools):
        kernel = AgentKernel(config=config, plugin=plugin, backend=backend)

        # Mock response with tool call
        mock_response = CompletionResponse(
            content=None,
            tool_calls=[
                {
                    "id": "call_123",
                    "function": {
                        "name": "echo",
                        "arguments": '{"message": "test"}',
                    },
                }
            ],
            usage=TokenUsage(10, 5, 15),
            finish_reason="tool_calls",
            raw_response={},
        )
        kernel._client.chat_completion = AsyncMock(return_value=mock_response)

        messages = [Message(role="user", content="Echo test")]
        result = await kernel.step(messages, tools)

        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "echo"
        assert len(result.tool_results) == 1
        assert "Echo: test" in result.tool_results[0].output

    @pytest.mark.asyncio
    async def test_run_terminates_on_no_tool_calls(self, config, plugin, backend, tools):
        kernel = AgentKernel(config=config, plugin=plugin, backend=backend)

        mock_response = CompletionResponse(
            content="Done!",
            tool_calls=None,
            usage=TokenUsage(10, 5, 15),
            finish_reason="stop",
            raw_response={},
        )
        kernel._client.chat_completion = AsyncMock(return_value=mock_response)

        messages = [Message(role="user", content="Hi")]
        result = await kernel.run(messages, tools, max_turns=5)

        assert result.turn_count == 1
        assert result.termination_reason == "no_tool_calls"

    @pytest.mark.asyncio
    async def test_run_terminates_on_termination_tool(self, config, plugin, backend, tools):
        kernel = AgentKernel(config=config, plugin=plugin, backend=backend)

        # First call returns tool call, second returns submit
        call_count = 0
        async def mock_completion(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return CompletionResponse(
                    content=None,
                    tool_calls=[{
                        "id": "call_1",
                        "function": {"name": "echo", "arguments": '{"message": "test"}'},
                    }],
                    usage=TokenUsage(10, 5, 15),
                    finish_reason="tool_calls",
                    raw_response={},
                )
            else:
                return CompletionResponse(
                    content=None,
                    tool_calls=[{
                        "id": "call_2",
                        "function": {"name": "submit_result", "arguments": '{"summary": "done"}'},
                    }],
                    usage=TokenUsage(10, 5, 15),
                    finish_reason="tool_calls",
                    raw_response={},
                )

        kernel._client.chat_completion = mock_completion

        def is_submit(result: ToolResult) -> bool:
            return result.name == "submit_result"

        messages = [Message(role="user", content="Work")]
        result = await kernel.run(messages, tools, max_turns=10, termination=is_submit)

        assert result.turn_count == 2
        assert result.termination_reason == "termination_tool"
        assert result.final_tool_result is not None
        assert result.final_tool_result.name == "submit_result"

    @pytest.mark.asyncio
    async def test_run_respects_max_turns(self, config, plugin, backend, tools):
        kernel = AgentKernel(config=config, plugin=plugin, backend=backend)

        # Always return a tool call (never terminates naturally)
        mock_response = CompletionResponse(
            content=None,
            tool_calls=[{
                "id": "call_1",
                "function": {"name": "echo", "arguments": '{"message": "loop"}'},
            }],
            usage=TokenUsage(10, 5, 15),
            finish_reason="tool_calls",
            raw_response={},
        )
        kernel._client.chat_completion = AsyncMock(return_value=mock_response)

        messages = [Message(role="user", content="Loop forever")]
        result = await kernel.run(messages, tools, max_turns=3)

        assert result.turn_count == 3
        assert result.termination_reason == "max_turns"
```

Run tests:

```bash
uv run pytest tests/test_kernel.py -v
```

**Expected:** All tests pass.

---

## Part 9: Bundle System

### Step 9.1: Create Bundle Schema

**File: `src/structured_agents/bundles/schema.py`**

```python
"""Bundle schema definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ToolInputSchema(BaseModel):
    """Schema for a tool input parameter."""

    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None
    enum: list[str] | None = None


class ToolDefinition(BaseModel):
    """Definition of a tool in a bundle."""

    name: str
    script: str  # Relative path to .pym file
    description: str
    inputs: dict[str, ToolInputSchema] = Field(default_factory=dict)
    context_providers: list[str] = Field(default_factory=list)


class ModelConfig(BaseModel):
    """Model configuration in a bundle."""

    plugin: str = "function_gemma"
    adapter: str | None = None
    grammar_strategy: str = "permissive"


class InitialContext(BaseModel):
    """Initial context (prompts) in a bundle."""

    system_prompt: str
    user_template: str = "{{ input }}"


class BundleManifest(BaseModel):
    """The bundle.yaml schema."""

    name: str
    version: str = "1.0"

    model: ModelConfig = Field(default_factory=ModelConfig)
    initial_context: InitialContext

    max_turns: int = 20
    termination_tool: str = "submit_result"

    tools: list[ToolDefinition]

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, tools: list[ToolDefinition]) -> list[ToolDefinition]:
        names = [t.name for t in tools]
        if len(names) != len(set(names)):
            raise ValueError("Duplicate tool names in bundle")
        return tools
```

### Step 9.2: Create Bundle Loader

**File: `src/structured_agents/bundles/loader.py`**

```python
"""Bundle loading and management."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template

from structured_agents.bundles.schema import BundleManifest, ToolDefinition
from structured_agents.exceptions import BundleError
from structured_agents.plugins import FunctionGemmaPlugin, ModelPlugin, QwenPlugin
from structured_agents.types import Message, ToolSchema


class AgentBundle:
    """A loaded agent bundle with tools, prompts, and configuration."""

    def __init__(self, path: Path, manifest: BundleManifest):
        self.path = path
        self.manifest = manifest
        self._tool_schemas: list[ToolSchema] | None = None
        self._system_template = Template(manifest.initial_context.system_prompt)
        self._user_template = Template(manifest.initial_context.user_template)

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def max_turns(self) -> int:
        return self.manifest.max_turns

    @property
    def termination_tool(self) -> str:
        return self.manifest.termination_tool

    def get_plugin(self) -> ModelPlugin:
        """Get the appropriate model plugin for this bundle."""
        plugin_name = self.manifest.model.plugin.lower()

        if plugin_name == "function_gemma":
            return FunctionGemmaPlugin()
        elif plugin_name == "qwen":
            return QwenPlugin()
        else:
            raise BundleError(f"Unknown plugin: {plugin_name}")

    @property
    def tool_schemas(self) -> list[ToolSchema]:
        """Get tool schemas for this bundle."""
        if self._tool_schemas is None:
            self._tool_schemas = self._build_tool_schemas()
        return self._tool_schemas

    def _build_tool_schemas(self) -> list[ToolSchema]:
        """Build tool schemas from manifest."""
        schemas = []
        for tool_def in self.manifest.tools:
            # Build JSON Schema from inputs
            properties = {}
            required = []

            for name, input_schema in tool_def.inputs.items():
                prop: dict[str, Any] = {"type": input_schema.type}
                if input_schema.description:
                    prop["description"] = input_schema.description
                if input_schema.enum:
                    prop["enum"] = input_schema.enum
                if input_schema.default is not None:
                    prop["default"] = input_schema.default
                properties[name] = prop

                if input_schema.required:
                    required.append(name)

            parameters = {
                "type": "object",
                "properties": properties,
            }
            if required:
                parameters["required"] = required

            # Resolve script path
            script_path = self.path / tool_def.script

            # Resolve context provider paths
            context_providers = tuple(
                self.path / cp for cp in tool_def.context_providers
            )

            schemas.append(ToolSchema(
                name=tool_def.name,
                description=tool_def.description,
                parameters=parameters,
                script_path=script_path,
                context_providers=context_providers,
            ))

        return schemas

    def build_initial_messages(
        self,
        context: dict[str, Any] | None = None,
    ) -> list[Message]:
        """Build initial messages from templates.

        Args:
            context: Variables to render in templates.
                     Common variables: node_text, input, etc.
        """
        context = context or {}

        system_prompt = self._system_template.render(**context)
        user_message = self._user_template.render(**context)

        return [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_message),
        ]

    def get_system_prompt(self, context: dict[str, Any] | None = None) -> str:
        """Render the system prompt with context."""
        context = context or {}
        return self._system_template.render(**context)


def load_bundle(directory: str | Path) -> AgentBundle:
    """Load an agent bundle from a directory.

    Args:
        directory: Path to bundle directory containing bundle.yaml

    Returns:
        Loaded AgentBundle

    Raises:
        BundleError: If bundle is invalid or cannot be loaded
    """
    path = Path(directory)

    if not path.is_dir():
        raise BundleError(f"Bundle path is not a directory: {path}")

    manifest_path = path / "bundle.yaml"
    if not manifest_path.exists():
        # Also try bundle.yml
        manifest_path = path / "bundle.yml"
        if not manifest_path.exists():
            raise BundleError(f"No bundle.yaml found in: {path}")

    try:
        with open(manifest_path) as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise BundleError(f"Invalid YAML in bundle.yaml: {e}")

    try:
        manifest = BundleManifest.model_validate(data)
    except Exception as e:
        raise BundleError(f"Invalid bundle manifest: {e}")

    return AgentBundle(path, manifest)
```

### Step 9.3: Update bundles/__init__.py

**File: `src/structured_agents/bundles/__init__.py`**

```python
"""Bundle system for structured-agents."""

from structured_agents.bundles.loader import AgentBundle, load_bundle
from structured_agents.bundles.schema import (
    BundleManifest,
    InitialContext,
    ModelConfig,
    ToolDefinition,
    ToolInputSchema,
)

__all__ = [
    "AgentBundle",
    "load_bundle",
    "BundleManifest",
    "InitialContext",
    "ModelConfig",
    "ToolDefinition",
    "ToolInputSchema",
]
```

### Step 9.4: Create Test Bundle

Create **`tests/fixtures/sample_bundle/bundle.yaml`**:

```yaml
name: test_agent
version: "1.0"

model:
  plugin: function_gemma

initial_context:
  system_prompt: |
    You are a helpful assistant.
  user_template: |
    User input: {{ input }}

max_turns: 10
termination_tool: submit_result

tools:
  - name: greet
    script: tools/greet.pym
    description: Greet someone by name.
    inputs:
      name:
        type: string
        description: The name to greet.
        required: true

  - name: submit_result
    script: tools/submit.pym
    description: Submit the final result.
    inputs:
      summary:
        type: string
        description: Summary of what was done.
```

Create **`tests/fixtures/sample_bundle/tools/.gitkeep`** (empty file to create directory).

### Testing Step 9

Create **`tests/test_bundles/test_loader.py`**:

```python
"""Tests for bundle loading."""

import pytest
from pathlib import Path

from structured_agents.bundles import load_bundle, AgentBundle
from structured_agents.exceptions import BundleError


class TestLoadBundle:
    @pytest.fixture
    def sample_bundle_path(self):
        return Path(__file__).parent.parent / "fixtures" / "sample_bundle"

    def test_load_valid_bundle(self, sample_bundle_path):
        bundle = load_bundle(sample_bundle_path)

        assert bundle.name == "test_agent"
        assert bundle.max_turns == 10
        assert bundle.termination_tool == "submit_result"

    def test_bundle_has_tools(self, sample_bundle_path):
        bundle = load_bundle(sample_bundle_path)

        assert len(bundle.tool_schemas) == 2
        tool_names = [t.name for t in bundle.tool_schemas]
        assert "greet" in tool_names
        assert "submit_result" in tool_names

    def test_bundle_tool_schema(self, sample_bundle_path):
        bundle = load_bundle(sample_bundle_path)

        greet_tool = next(t for t in bundle.tool_schemas if t.name == "greet")
        assert greet_tool.description == "Greet someone by name."
        assert "name" in greet_tool.parameters["properties"]

    def test_bundle_builds_messages(self, sample_bundle_path):
        bundle = load_bundle(sample_bundle_path)

        messages = bundle.build_initial_messages({"input": "Hello!"})

        assert len(messages) == 2
        assert messages[0].role == "system"
        assert "helpful assistant" in messages[0].content
        assert messages[1].role == "user"
        assert "Hello!" in messages[1].content

    def test_bundle_gets_plugin(self, sample_bundle_path):
        bundle = load_bundle(sample_bundle_path)
        plugin = bundle.get_plugin()

        assert plugin.name == "function_gemma"

    def test_load_nonexistent_directory(self):
        with pytest.raises(BundleError, match="not a directory"):
            load_bundle("/nonexistent/path")

    def test_load_directory_without_manifest(self, tmp_path):
        with pytest.raises(BundleError, match="No bundle.yaml"):
            load_bundle(tmp_path)
```

Run tests:

```bash
uv run pytest tests/test_bundles/ -v
```

**Expected:** All tests pass.

---

## Part 10: Public API

### Step 10.1: Update Main __init__.py

**File: `src/structured_agents/__init__.py`**

```python
"""structured-agents: Structured tool orchestration with grammar-constrained LLM outputs."""

from structured_agents.backends import (
    GrailBackend,
    GrailBackendConfig,
    PythonBackend,
    Snapshot,
    ToolBackend,
)
from structured_agents.bundles import AgentBundle, load_bundle
from structured_agents.client import CompletionResponse, LLMClient, OpenAICompatibleClient
from structured_agents.exceptions import (
    BackendError,
    BundleError,
    KernelError,
    PluginError,
    StructuredAgentsError,
    ToolExecutionError,
)
from structured_agents.history import HistoryStrategy, KeepAllHistory, SlidingWindowHistory
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
from structured_agents.types import (
    KernelConfig,
    Message,
    RunResult,
    StepResult,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolSchema,
)

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Kernel
    "AgentKernel",
    "KernelConfig",
    # Types
    "Message",
    "ToolCall",
    "ToolResult",
    "ToolSchema",
    "StepResult",
    "RunResult",
    "TokenUsage",
    # Plugins
    "ModelPlugin",
    "FunctionGemmaPlugin",
    "QwenPlugin",
    # Backends
    "ToolBackend",
    "PythonBackend",
    "GrailBackend",
    "GrailBackendConfig",
    "Snapshot",
    # Bundles
    "AgentBundle",
    "load_bundle",
    # Observer
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
    # History
    "HistoryStrategy",
    "SlidingWindowHistory",
    "KeepAllHistory",
    # Client
    "LLMClient",
    "OpenAICompatibleClient",
    "CompletionResponse",
    # Exceptions
    "StructuredAgentsError",
    "KernelError",
    "ToolExecutionError",
    "PluginError",
    "BundleError",
    "BackendError",
]
```

### Testing Step 10

Create **`tests/test_public_api.py`**:

```python
"""Tests for public API surface."""

import pytest


def test_all_exports_importable():
    """Verify all __all__ exports are importable."""
    import structured_agents

    for name in structured_agents.__all__:
        obj = getattr(structured_agents, name)
        assert obj is not None, f"Export {name} is None"


def test_version_exists():
    import structured_agents
    assert hasattr(structured_agents, "__version__")
    assert isinstance(structured_agents.__version__, str)


def test_core_classes_importable():
    from structured_agents import (
        AgentKernel,
        KernelConfig,
        Message,
        ToolCall,
        ToolResult,
        ToolSchema,
        FunctionGemmaPlugin,
        PythonBackend,
        load_bundle,
    )

    # Just verify they're the right types
    assert KernelConfig.__name__ == "KernelConfig"
    assert AgentKernel.__name__ == "AgentKernel"
```

Run all tests:

```bash
uv run pytest -v
```

**Expected:** All tests pass.

---

## Part 11: Integration Test

Create a comprehensive integration test that validates the full system:

**File: `tests/test_integration.py`**

```python
"""Integration tests for the complete system."""

import pytest
from unittest.mock import AsyncMock

from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    ToolResult,
    ToolSchema,
    FunctionGemmaPlugin,
    PythonBackend,
    NullObserver,
)
from structured_agents.client.protocol import CompletionResponse
from structured_agents.types import TokenUsage


class RecordingObserver:
    """Observer that records events for testing."""

    def __init__(self):
        self.events = []

    async def on_kernel_start(self, event):
        self.events.append(("kernel_start", event))

    async def on_model_request(self, event):
        self.events.append(("model_request", event))

    async def on_model_response(self, event):
        self.events.append(("model_response", event))

    async def on_tool_call(self, event):
        self.events.append(("tool_call", event))

    async def on_tool_result(self, event):
        self.events.append(("tool_result", event))

    async def on_turn_complete(self, event):
        self.events.append(("turn_complete", event))

    async def on_kernel_end(self, event):
        self.events.append(("kernel_end", event))

    async def on_error(self, error, context=None):
        self.events.append(("error", error, context))


class TestFullAgentLoop:
    """Test complete agent workflows."""

    @pytest.fixture
    def backend(self):
        backend = PythonBackend()

        async def analyze_code(code: str = "") -> dict:
            return {
                "lines": len(code.split("\n")),
                "has_docstring": '"""' in code or "'''" in code,
            }

        async def write_docstring(docstring: str = "", function_name: str = "") -> dict:
            return {
                "success": True,
                "function": function_name,
                "docstring": docstring,
            }

        async def submit_result(summary: str = "", status: str = "success") -> dict:
            return {
                "status": status,
                "summary": summary,
            }

        backend.register("analyze_code", analyze_code)
        backend.register("write_docstring", write_docstring)
        backend.register("submit_result", submit_result)
        return backend

    @pytest.fixture
    def tools(self):
        return [
            ToolSchema(
                name="analyze_code",
                description="Analyze Python code",
                parameters={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                    },
                },
            ),
            ToolSchema(
                name="write_docstring",
                description="Write a docstring",
                parameters={
                    "type": "object",
                    "properties": {
                        "docstring": {"type": "string"},
                        "function_name": {"type": "string"},
                    },
                },
            ),
            ToolSchema(
                name="submit_result",
                description="Submit final result",
                parameters={
                    "type": "object",
                    "properties": {
                        "summary": {"type": "string"},
                        "status": {"type": "string"},
                    },
                },
            ),
        ]

    @pytest.mark.asyncio
    async def test_multi_turn_agent_loop(self, backend, tools):
        """Test a realistic multi-turn agent workflow."""
        config = KernelConfig(base_url="http://localhost:8000/v1", model="test")
        plugin = FunctionGemmaPlugin()
        observer = RecordingObserver()

        kernel = AgentKernel(
            config=config,
            plugin=plugin,
            backend=backend,
            observer=observer,
        )

        # Simulate model responses for a 3-turn workflow
        turn = 0
        async def mock_completion(*args, **kwargs):
            nonlocal turn
            turn += 1

            if turn == 1:
                # First turn: analyze code
                return CompletionResponse(
                    content=None,
                    tool_calls=[{
                        "id": "call_1",
                        "function": {
                            "name": "analyze_code",
                            "arguments": '{"code": "def foo():\\n    pass"}',
                        },
                    }],
                    usage=TokenUsage(50, 20, 70),
                    finish_reason="tool_calls",
                    raw_response={},
                )
            elif turn == 2:
                # Second turn: write docstring
                return CompletionResponse(
                    content=None,
                    tool_calls=[{
                        "id": "call_2",
                        "function": {
                            "name": "write_docstring",
                            "arguments": '{"docstring": "A foo function.", "function_name": "foo"}',
                        },
                    }],
                    usage=TokenUsage(80, 30, 110),
                    finish_reason="tool_calls",
                    raw_response={},
                )
            else:
                # Third turn: submit
                return CompletionResponse(
                    content=None,
                    tool_calls=[{
                        "id": "call_3",
                        "function": {
                            "name": "submit_result",
                            "arguments": '{"summary": "Added docstring to foo", "status": "success"}',
                        },
                    }],
                    usage=TokenUsage(100, 25, 125),
                    finish_reason="tool_calls",
                    raw_response={},
                )

        kernel._client.chat_completion = mock_completion

        # Define termination
        def is_submit(result: ToolResult) -> bool:
            return result.name == "submit_result"

        # Run
        messages = [
            Message(role="system", content="You are a docstring writer."),
            Message(role="user", content="Add a docstring to: def foo(): pass"),
        ]

        result = await kernel.run(
            initial_messages=messages,
            tools=tools,
            max_turns=10,
            termination=is_submit,
        )

        # Verify result
        assert result.turn_count == 3
        assert result.termination_reason == "termination_tool"
        assert result.final_tool_result is not None
        assert result.final_tool_result.name == "submit_result"

        # Verify history
        assert len(result.history) > 2  # More than initial messages

        # Verify events
        event_types = [e[0] for e in observer.events]
        assert "kernel_start" in event_types
        assert "kernel_end" in event_types
        assert event_types.count("model_request") == 3
        assert event_types.count("tool_result") == 3

        # Verify usage accumulation
        assert result.total_usage is not None
        assert result.total_usage.total_tokens == 70 + 110 + 125
```

Run integration test:

```bash
uv run pytest tests/test_integration.py -v
```

**Expected:** All tests pass.

---

## Final Verification

Run the complete test suite:

```bash
uv run pytest -v --tb=short
```

**Expected:** All tests pass.

Create a simple README:

```bash
cat > README.md << 'EOF'
# structured-agents

Structured tool orchestration with grammar-constrained LLM outputs.

## Installation

```bash
pip install structured-agents

# With Grail support
pip install structured-agents[grail]
```

## Quick Start

```python
from structured_agents import (
    AgentKernel,
    KernelConfig,
    Message,
    ToolSchema,
    FunctionGemmaPlugin,
    PythonBackend,
)

# Configure
config = KernelConfig(
    base_url="http://localhost:8000/v1",
    model="google/functiongemma-270m-it",
)

# Create backend with tool handlers
backend = PythonBackend()

@backend.register("greet")
async def greet(name: str) -> str:
    return f"Hello, {name}!"

# Create kernel
kernel = AgentKernel(
    config=config,
    plugin=FunctionGemmaPlugin(),
    backend=backend,
)

# Run
result = await kernel.run(
    initial_messages=[
        Message(role="user", content="Greet Alice"),
    ],
    tools=[
        ToolSchema(name="greet", description="Greet someone", parameters={}),
    ],
)
```

## License

MIT
EOF
```

---

## Summary

You have now built the complete `structured-agents` library with:

1. **Core Types** - Message, ToolCall, ToolResult, ToolSchema, etc.
2. **Observer System** - Event streaming for TUI integration
3. **History Management** - Pluggable history trimming strategies
4. **Model Plugins** - FunctionGemma and Qwen implementations
5. **Tool Backends** - PythonBackend for testing, GrailBackend for production
6. **LLM Client** - OpenAI-compatible client for vLLM
7. **Agent Kernel** - The core loop orchestrator
8. **Bundle System** - Directory-based agent configurations

Each component has been tested incrementally. The library is ready for integration with Remora.
