# structured-agents v0.3.0 Implementation Guide

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Ground-up refactor of structured-agents to v0.3.0 — simplified architecture with ~60% fewer files.

**Architecture:** 5 core concepts (Tool, ModelAdapter, DecodingConstraint, Kernel, Agent). Collapse 6-layer tool abstraction into single Tool protocol. Flatten plugin system into ModelAdapter dataclass. Grammar as standalone ConstraintPipeline. Unified event model with single emit() method.

**Tech Stack:** Python >=3.13, pytest (asyncio_mode = "auto"), hatchling, grail 3.0.0, vLLM, xgrammar

---

## Phase 1: Core Types

### Task 1: Create types.py with core value types

**Files:**
- Create: src/structured_agents/types.py
- Test: tests/test_types.py

**Step 1: Create test file**

```python
# tests/test_types.py
import pytest
from structured_agents.types import Message, ToolCall, ToolResult, ToolSchema, TokenUsage

def test_message_creation():
    msg = Message(role="user", content="Hello")
    assert msg.role == "user"
    assert msg.content == "Hello"

def test_message_to_openai_format():
    msg = Message(role="user", content="Hello")
    assert msg.to_openai_format() == {"role": "user", "content": "Hello"}

def test_tool_call_create():
    tc = ToolCall.create("add", {"a": 1, "b": 2})
    assert tc.name == "add"
    assert tc.arguments == {"a": 1, "b": 2}
    assert tc.id.startswith("call_")

def test_tool_result_error_property():
    result = ToolResult(call_id="call_123", name="add", output="error", is_error=True)
    assert result.is_error == True
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_types.py -v
```

Expected: FAIL — module not found

**Step 3: Create minimal types.py**

```python
"""Core data types for structured-agents."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Any, Literal

@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[Any] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_openai_format(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            msg["content"] = self.content
        return msg

@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]

    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> "ToolCall":
        return cls(id=f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments)

@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    output: str
    is_error: bool = False

@dataclass(frozen=True, slots=True)
class ToolSchema:
    name: str
    description: str
    parameters: dict[str, Any]

@dataclass(frozen=True, slots=True)
class TokenUsage:
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_types.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/structured_agents/types.py tests/test_types.py
git commit -m "feat: add core types for v0.3.0"
```

---

## Phase 1 (continued): Tool Protocol and Implementations

### Task 2: Create Tool protocol and GrailTool

**Files:**
- Create: src/structured_agents/tools/__init__.py
- Create: src/structured_agents/tools/protocol.py
- Create: src/structured_agents/tools/grail.py
- Test: tests/test_tools/test_grail_tool.py

**Step 1: Write the failing test**

```python
# tests/test_tools/test_grail_tool.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents.tools.protocol import Tool
from structured_agents.tools.grail import GrailTool

@pytest.mark.asyncio
async def test_grail_tool_execute():
    mock_script = MagicMock()
    mock_script.name = "test_tool"
    mock_script.run = AsyncMock(return_value={"result": 42})
    
    tool = GrailTool(script=mock_script, limits=None)
    
    assert tool.schema.name == "test_tool"
    
    class MockContext:
        call_id = "call_123"
    
    result = await tool.execute({"a": 1}, MockContext())
    assert result.is_error == False
    assert "42" in result.output
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_tools/test_grail_tool.py -v
```

Expected: FAIL — module not found

**Step 3: Create tools/protocol.py**

```python
"""Tool protocol definition."""
from __future__ import annotations
from typing import Protocol, Any
from structured_agents.types import ToolSchema, ToolResult

class Tool(Protocol):
    """A tool has a schema and can execute with arguments."""
    
    @property
    def schema(self) -> ToolSchema: ...
    
    async def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult: ...
```

**Step 4: Create tools```python
"""/grail.py**

Grail tool implementation."""
from __future__ import annotations
import json
from typing import Any
from structured_agents.types import ToolSchema, ToolResult

class GrailTool:
    """A tool backed by a .pym script."""
    
    def __init__(self, script: Any, limits: Any = None):
        self._script = script
        self._limits = limits
        self._schema = ToolSchema(
            name=script.name,
            description=f"Tool: {script.name}",
            parameters={"type": "object", "properties": {}}
        )
    
    @property
    def schema(self) -> ToolSchema:
        return self._schema
    
    async def execute(self, arguments: dict[str, Any], context: Any) -> ToolResult:
        try:
            result = await self._script.run(inputs=arguments, limits=self._limits)
            output = json.dumps(result) if not isinstance(result, str) else result
            return ToolResult(
                call_id=context.call_id if context else "unknown",
                name=self._script.name,
                output=output,
                is_error=False
            )
        except Exception as e:
            return ToolResult(
                call_id=context.call_id if context else "unknown",
                name=self._script.name,
                output=str(e),
                is_error=True
            )

def discover_tools(agents_dir: str):
    """Discover .pym tools in a directory."""
    # TODO: implement with grail.load()
    return []
```

**Step 5: Create tools/__init__.py**

```python
"""Tools package."""
from structured_agents.tools.protocol import Tool
from structured_agents.tools.grail import GrailTool, discover_tools

__all__ = ["Tool", "GrailTool", "discover_tools"]
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_tools/test_grail_tool.py -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add src/structured_agents/tools/ tests/test_tools/
git commit -m "feat: add Tool protocol and GrailTool implementation"
```

---

## Phase 2: Grammar System

### Task 3: Create DecodingConstraint and ConstraintPipeline

**Files:**
- Create: src/structured_agents/grammar/__init__.py
- Create: src/structured_agents/grammar/config.py
- Create: src/structured_agents/grammar/pipeline.py
- Test: tests/test_grammar/test_pipeline.py

**Step 1: Write the failing test**

```python
# tests/test_grammar/test_pipeline.py
import pytest
from structured_agents.grammar.config import DecodingConstraint
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.types import ToolSchema

def test_decoding_constraint_defaults():
    constraint = DecodingConstraint()
    assert constraint.strategy == "ebnf"
    assert constraint.allow_parallel_calls == False
    assert constraint.send_tools_to_api == False

def test_constraint_pipeline_returns_none_when_no_tools():
    # Mock builder that returns None
    mock_builder = lambda tools, config: None
    pipeline = ConstraintPipeline(builder=mock_builder, config=DecodingConstraint())
    
    result = pipeline.constrain([])
    assert result is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_grammar/test_pipeline.py -v
```

Expected: FAIL — module not found

**Step 3: Create grammar/config.py**

```python
"""Grammar/decoding constraint configuration."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True, slots=True)
class DecodingConstraint:
    """How to constrain the model's output to valid tool calls."""
    
    strategy: Literal["ebnf", "structural_tag", "json_schema"] = "ebnf"
    allow_parallel_calls: bool = False
    send_tools_to_api: bool = False
```

**Step 4: Create grammar/pipeline.py**

```python
"""Constraint pipeline for grammar generation."""
from __future__ import annotations
from typing import Any, Callable
from structured_agents.grammar.config import DecodingConstraint
from structured_agents.types import ToolSchema

class ConstraintPipeline:
    """Transforms tool schemas + config into vLLM grammar constraints."""
    
    def __init__(
        self,
        builder: Callable[[list[ToolSchema], DecodingConstraint], dict[str, Any] | None],
        config: DecodingConstraint,
    ):
        self._builder = builder
        self._config = config
    
    def constrain(self, tools: list[ToolSchema]) -> dict[str, Any] | None:
        """Build grammar constraints for the given tools.
        
        Returns the extra_body dict for vLLM, or None if no grammar is configured.
        """
        if not tools:
            return None
        return self._builder(tools, self._config)
```

**Step 5: Create grammar/__init__.py**

```python
"""Grammar package for constrained decoding."""
from structured_agents.grammar.config import DecodingConstraint
from structured_agents.grammar.pipeline import ConstraintPipeline

__all__ = ["DecodingConstraint", "ConstraintPipeline"]
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_grammar/test_pipeline.py -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add src/structured_agents/grammar/ tests/test_grammar/
git commit -m "feat: add DecodingConstraint and ConstraintPipeline"
```

---

## Phase 3: Model System

### Task 4: Create ModelAdapter and ResponseParser

**Files:**
- Create: src/structured_agents/models/__init__.py
- Create: src/structured_agents/models/adapter.py
- Create: src/structured_agents/models/parsers.py
- Test: tests/test_models/test_adapter.py

**Step 1: Write the failing test**

```python
# tests/test_models/test_adapter.py
import pytest
from dataclasses import dataclass
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import ResponseParser
from structured_agents.types import ToolSchema, ToolCall, ToolResult, TokenUsage
from structured_agents.grammar.config import DecodingConstraint

@dataclass
class MockParser:
    def parse(self, content, tool_calls):
        return content, []

def test_model_adapter_creation():
    adapter = ModelAdapter(
        name="test_model",
        grammar_builder=lambda tools, config: {"grammar": "test"},
        response_parser=MockParser(),
    )
    assert adapter.name == "test_model"
    assert adapter.grammar_builder is not None

def test_model_adapter_format_messages_default():
    adapter = ModelAdapter(
        name="test",
        grammar_builder=lambda t, c: None,
        response_parser=MockParser(),
    )
    from structured_agents.types import Message
    msg = Message(role="user", content="hello")
    result = adapter.format_messages([msg], [])
    assert result[0]["role"] == "user"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_models/test_adapter.py -v
```

Expected: FAIL — module not found

**Step 3: Create models/adapter.py**

```python
"""Model adapter for specific model families."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from structured_agents.types import Message, ToolSchema

@dataclass(frozen=True)
class ModelAdapter:
    """Adapts the kernel's generic tool-call loop to a specific model family."""
    
    name: str
    grammar_builder: Callable[[list[ToolSchema], Any], dict[str, Any] | None]
    response_parser: Any  # ResponseParser
    format_messages: Callable[[list[Message], list[dict]], list[dict]] | None = None
    format_tools: Callable[[list[ToolSchema]], list[dict]] | None = None
    
    def __post_init__(self):
        # Set defaults if not provided
        if self.format_messages is None:
            object.__setattr__(self, 'format_messages', self._default_format_messages)
        if self.format_tools is None:
            object.__setattr__(self, 'format_tools', self._default_format_tools)
    
    @staticmethod
    def _default_format_messages(messages: list[Message], tools: list[dict]) -> list[dict]:
        result = []
        for msg in messages:
            msg_dict = msg.to_openai_format()
            result.append(msg_dict)
        if tools:
            result.append({"role": "system", "content": "Available tools: " + str(tools)})
        return result
    
    @staticmethod
    def _default_format_tools(tool_schemas: list[ToolSchema]) -> list[dict]:
        return [ts.to_openai_format() for ts in tool_schemas]
```

**Step 4: Create models/parsers.py**

```python
"""Response parser implementations."""
from __future__ import annotations
from typing import Any, Protocol
from structured_agents.types import ToolCall

class ResponseParser(Protocol):
    """Parses model responses to extract tool calls."""
    
    def parse(self, content: str | None, tool_calls: list[dict[str, Any]] | None) -> tuple[str | None, list[ToolCall]]: ...


class QwenResponseParser:
    """Parser for Qwen models."""
    
    def parse(self, content: str | None, tool_calls: list[dict[str, Any]] | None) -> tuple[str | None, list[ToolCall]]:
        if tool_calls:
            parsed = []
            for tc in tool_calls:
                if isinstance(tc, dict) and "function" in tc:
                    func = tc["function"]
                    import json
                    args = json.loads(func.get("arguments", "{}"))
                    parsed.append(ToolCall.create(func["name"], args))
            return None, parsed
        return content, []


class FunctionGemmaResponseParser:
    """Parser for FunctionGemma models."""
    
    def parse(self, content: str | None, tool_calls: list[dict[str, Any]] | None) -> tuple[str | None, list[ToolCall]]:
        # Similar to Qwen but handles structural tags differently
        return QwenResponseParser().parse(content, tool_calls)
```

**Step 5: Create models/__init__.py**

```python
"""Models package for model-specific adapters."""
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import ResponseParser, QwenResponseParser, FunctionGemmaResponseParser

__all__ = ["ModelAdapter", "ResponseParser", "QwenResponseParser", "FunctionGemmaResponseParser"]
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_models/test_adapter.py -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add src/structured_agents/models/ tests/test_models/
git commit -m "feat: add ModelAdapter and ResponseParser"
```

---

## Phase 4: Unified Event System

### Task 5: Create Observer protocol with single emit() method

**Files:**
- Create: src/structured_agents/events/__init__.py
- Create: src/structured_agents/events/types.py
- Create: src/structured_agents/events/observer.py
- Test: tests/test_events/test_observer.py

**Step 1: Write the failing test**

```python
# tests/test_events/test_observer.py
import pytest
from structured_agents.events.types import (
    Event, KernelStartEvent, KernelEndEvent, 
    ModelRequestEvent, ToolCallEvent, ToolResultEvent
)
from structured_agents.events.observer import Observer, NullObserver

@pytest.mark.asyncio
async def test_null_observer_emit():
    observer = NullObserver()
    event = KernelStartEvent(max_turns=10, tools_count=3, initial_messages_count=1)
    # Should not raise
    await observer.emit(event)

@pytest.mark.asyncio
async def test_observer_pattern_matching():
    received_events = []
    
    class TestObserver:
        async def emit(self, event: Event):
            received_events.append(event)
    
    observer = TestObserver()
    await observer.emit(KernelStartEvent(max_turns=5, tools_count=2, initial_messages_count=1))
    await observer.emit(ToolCallEvent(turn=1, tool_name="test", call_id="c1", arguments={}))
    
    assert len(received_events) == 2
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_events/test_observer.py -v
```

Expected: FAIL — module not found

**Step 3: Create events/types.py**

```python
"""Event types for unified event model."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Union
from structured_agents.types import TokenUsage

@dataclass(frozen=True)
class KernelStartEvent:
    max_turns: int
    tools_count: int
    initial_messages_count: int

@dataclass(frozen=True)
class KernelEndEvent:
    turn_count: int
    termination_reason: str
    total_duration_ms: int

@dataclass(frozen=True)
class ModelRequestEvent:
    turn: int
    messages_count: int
    tools_count: int
    model: str

@dataclass(frozen=True)
class ModelResponseEvent:
    turn: int
    duration_ms: int
    content: str | None
    tool_calls_count: int
    usage: TokenUsage | None

@dataclass(frozen=True)
class ToolCallEvent:
    turn: int
    tool_name: str
    call_id: str
    arguments: dict[str, Any]

@dataclass(frozen=True)
class ToolResultEvent:
    turn: int
    tool_name: str
    call_id: str
    is_error: bool
    duration_ms: int
    output_preview: str

@dataclass(frozen=True)
class TurnCompleteEvent:
    turn: int
    tool_calls_count: int
    tool_results_count: int
    errors_count: int

Event = Union[
    KernelStartEvent, KernelEndEvent,
    ModelRequestEvent, ModelResponseEvent,
    ToolCallEvent, ToolResultEvent,
    TurnCompleteEvent
]
```

**Step 4: Create events/observer.py**

```python
"""Observer protocol and implementations."""
from __future__ import annotations
from typing import Protocol
from structured_agents.events.types import Event

class Observer(Protocol):
    """Receives agent lifecycle events with single emit method."""
    
    async def emit(self, event: Event) -> None: ...


class NullObserver:
    """No-op observer that discards all events."""
    
    async def emit(self, event: Event) -> None:
        pass
```

**Step 5: Create events/__init__.py**

```python
"""Events package for unified event system."""
from structured_agents.events.types import (
    Event, KernelStartEvent, KernelEndEvent,
    ModelRequestEvent, ModelResponseEvent,
    ToolCallEvent, ToolResultEvent, TurnCompleteEvent
)
from structured_agents.events.observer import Observer, NullObserver

__all__ = [
    "Event", "KernelStartEvent", "KernelEndEvent",
    "ModelRequestEvent", "ModelResponseEvent",
    "ToolCallEvent", "ToolResultEvent", "TurnCompleteEvent",
    "Observer", "NullObserver"
]
```

**Step 6: Run test to verify it passes**

```bash
pytest tests/test_events/test_observer.py -v
```

Expected: PASS

**Step 7: Commit**

```bash
git add src/structured_agents/events/ tests/test_events/
git commit -m "feat: add unified event system with single emit()"
```

---

## Phase 5: Kernel

### Task 6: Create AgentKernel with list[Tool] and ModelAdapter

**Files:**
- Create: src/structured_agents/kernel.py
- Modify: src/structured_agents/types.py (add StepResult, RunResult, KernelConfig)
- Test: tests/test_kernel/test_basic.py

**Step 1: Write the failing test**

```python
# tests/test_kernel/test_basic.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import QwenResponseParser
from structured_agents.tools.protocol import Tool
from structured_agents.types import ToolSchema, ToolResult, Message
from structured_agents.client.protocol import CompletionResponse

@pytest.mark.asyncio
async def test_kernel_step_basic():
    # Setup mocks
    mock_client = AsyncMock()
    mock_client.chat_completion = AsyncMock(return_value=CompletionResponse(
        content="Hello",
        tool_calls=None,
        usage=None,
        finish_reason="stop",
        raw_response={}
    ))
    mock_client.close = AsyncMock()
    
    adapter = ModelAdapter(
        name="test",
        grammar_builder=lambda t, c: None,
        response_parser=QwenResponseParser(),
    )
    
    # Minimal tool
    mock_tool = MagicMock(spec=Tool)
    mock_tool.schema = ToolSchema(name="test", description="A test", parameters={})
    mock_tool.execute = AsyncMock(return_value=ToolResult(
        call_id="c1", name="test", output="result", is_error=False
    ))
    
    kernel = AgentKernel(
        client=mock_client,
        adapter=adapter,
        tools=[mock_tool],
    )
    
    messages = [Message(role="user", content="Hello")]
    result = await kernel.step(messages, tools=[mock_tool.schema])
    
    assert result.response_message.content == "Hello"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_kernel/test_basic.py -v
```

Expected: FAIL — module not found

**Step 3: Update types.py with additional types**

Add to src/structured_agents/types.py:

```python
@dataclass(frozen=True, slots=True)
class StepResult:
    """Result of a single kernel step."""
    response_message: Message
    tool_calls: list[Any]
    tool_results: list["ToolResult"]
    usage: "TokenUsage | None" = None

@dataclass(frozen=True)
class RunResult:
    """Result of a full kernel run."""
    final_message: Message
    history: list[Message]
    turn_count: int
    termination_reason: str
    final_tool_result: "ToolResult | None" = None
    total_usage: "TokenUsage | None" = None

# Add to KernelConfig
class KernelConfig:
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    max_concurrency: int = 1
```

**Step 4: Create kernel.py**

```python
"""AgentKernel - the core agent loop orchestrator."""
from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Sequence
from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.events.types import (
    Event, KernelStartEvent, KernelEndEvent,
    ModelRequestEvent, ModelResponseEvent,
    ToolCallEvent, ToolResultEvent, TurnCompleteEvent
)
from structured_agents.models.adapter import ModelAdapter
from structured_agents.tools.protocol import Tool
from structured_agents.types import (
    KernelConfig, Message, RunResult, StepResult, 
    TokenUsage, ToolCall, ToolResult, ToolSchema
)

@dataclass
class AgentKernel:
    """The core agent loop orchestrator."""
    
    client: LLMClient
    adapter: ModelAdapter
    tools: list[Tool] = field(default_factory=list)
    observer: Observer = field(default_factory=NullObserver)
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
    
    def _tool_map(self) -> dict[str, Tool]:
        return {t.schema.name: t for t in self.tools}
    
    async def step(
        self,
        messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
    ) -> StepResult:
        """Execute a single turn: model call + tool execution."""
        # Resolve tools
        resolved_tools = []
        for t in tools:
            if isinstance(t, ToolSchema):
                resolved_tools.append(t)
            elif isinstance(t, str):
                tool = self._tool_map().get(t)
                if tool:
(tool.schema)
                    resolved_tools.append        
        # Format for model
        formatted_messages = self.adapter.format_messages(messages, [])
        formatted_tools = self.adapter.format_tools(resolved_tools) if resolved_tools else None
        
        # Build grammar constraint
        grammar_constraint = None
        if self.adapter.grammar_builder:
            grammar_constraint = self.adapter.grammar_builder(resolved_tools, None)
        
        extra_body = grammar_constraint
        
        # Make API call
        response = await self.client.chat_completion(
            messages=formatted_messages,
            tools=formatted_tools,
            tool_choice=self.tool_choice if resolved_tools else "none",
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            extra_body=extra_body,
        )
        
        # Parse response
        content, tool_calls = self.adapter.response_parser.parse(
            response.content, response.tool_calls
        )
        
        response_message = Message(
            role="assistant",
            content=content,
            tool_calls=tool_calls if tool_calls else None,
        )
        
        # Execute tools
        tool_results = []
        tool_map = self._tool_map()
        
        async def execute_one(tc: ToolCall):
            tool = tool_map.get(tc.name)
            if not tool:
                return ToolResult(
                    call_id=tc.id,
                    name=tc.name,
                    output=f"Unknown tool: {tc.name}",
                    is_error=True
                )
            return await tool.execute(tc.arguments, None)
        
        if tool_calls:
            if self.max_concurrency <= 1:
                tool_results = [await execute_one(tc) for tc in tool_calls]
            else:
                sem = asyncio.Semaphore(self.max_concurrency)
                async def bounded(tc):
                    async with sem:
                        return await execute_one(tc)
                tool_results = await asyncio.gather(*[bounded(tc) for tc in tool_calls])
        
        return StepResult(
            response_message=response_message,
            tool_calls=list(tool_calls) if tool_calls else [],
            tool_results=tool_results,
            usage=response.usage,
        )
    
    async def run(
        self,
        initial_messages: list[Message],
        tools: Sequence[ToolSchema] | Sequence[str],
        max_turns: int = 20,
    ) -> RunResult:
        """Execute the full agent loop."""
        messages = list(initial_messages)
        turn_count = 0
        termination_reason = "max_turns"
        
        await self.observer.emit(KernelStartEvent(
            max_turns=max_turns,
            tools_count=len(self.tools),
            initial_messages_count=len(initial_messages)
        ))
        
        while turn_count < max_turns:
            turn_count += 1
            
            step_result = await self.step(messages, tools)
            
            messages.append(step_result.response_message)
            for result in step_result.tool_results:
                messages.append(result.to_message())
            
            if not step_result.tool_calls:
                termination_reason = "no_tool_calls"
                break
        
        final_message = messages[-1] if messages else Message(role="assistant", content="")
        
        return RunResult(
            final_message=final_message,
            history=messages,
            turn_count=turn_count,
            termination_reason=termination_reason,
        )
    
    async def close(self) -> None:
        await self.client.close()
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_kernel/test_basic.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add src/structured_agents/kernel.py src/structured_agents/types.py tests/test_kernel/
git commit -m "feat: add AgentKernel with simplified architecture"
```

---

## Phase 6: Agent Entry Point

### Task 7: Create Agent.from_bundle() as high-level API

**Files:**
- Create: src/structured_agents/agent.py
- Test: tests/test_agent/test_bundle.py

**Step 1: Write the failing test**

```python
# tests/test_agent/test_bundle.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from structured_agents.agent import Agent

@pytest.mark.asyncio
async def test_agent_from_bundle_minimal():
    with patch("structured_agents.agent.load_manifest") as mock_load:
        mock_load.return_value = MagicMock(
            name="test_agent",
            system_prompt="You are helpful.",
            agents_dir="/tmp/agents",
            limits=None,
            model="qwen",
            grammar_config=None,
        )
        
        with patch("structured_agents.agent.discover_tools") as mock_discover:
            mock_discover.return_value = []
            
            with patch("structured_agents.agent.build_client") as mock_client:
                mock_client.return_value = AsyncMock()
                
                agent = await Agent.from_bundle("/tmp/bundle")
                
                assert agent is not None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_agent/test_bundle.py -v
```

Expected: FAIL — module not found

**Step 3: Create agent.py**

```python
"""Agent - high-level entry point for structured-agents."""
from __future__ import annotations
from pathlib import Path
from typing import Any
from dataclasses import dataclass, field
import yaml

from structured_agents.client.protocol import LLMClient
from structured_agents.client.factory import build_client
from structured_agents.events.observer import NullObserver, Observer
from structured_agents.grammar.config import DecodingConstraint
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter
from structured_agents.models.parsers import QwenResponseParser
from structured_agents.tools.grail import discover_tools
from structured_agents.types import Message, RunResult, ToolSchema


@dataclass
class AgentManifest:
    """Loaded bundle manifest."""
    name: str
    system_prompt: str
    agents_dir: Path
    limits: Any = None
    model: str = "qwen"
    grammar_config: DecodingConstraint | None = None
    max_turns: int = 20


def load_manifest(bundle_path: str | Path) -> AgentManifest:
    """Load a bundle manifest from a YAML file."""
    path = Path(bundle_path)
    if path.is_dir():
        path = path / "bundle.yaml"
    
    with open(path) as f:
        data = yaml.safe_load(f)
    
    return AgentManifest(
        name=data.get("name", "unnamed"),
        system_prompt=data.get("system_prompt", ""),
        agents_dir=Path(bundle_path).parent / data.get("agents_dir", "agents"),
        limits=data.get("limits"),
        model=data.get("model", "qwen"),
        grammar_config=None,  # TODO: parse from yaml
        max_turns=data.get("max_turns", 20),
    )


class Agent:
    """A ready-to-run agent. The top-level user-facing API."""
    
    def __init__(
        self,
        kernel: AgentKernel,
        manifest: AgentManifest,
        observer: Observer | None = None,
    ):
        self.kernel = kernel
        self.manifest = manifest
        self.observer = observer or NullObserver()
    
    @classmethod
    async def from_bundle(cls, path: str | Path, **overrides) -> "Agent":
        """Load a bundle and construct a fully wired agent."""
        manifest = load_manifest(path)
        
        # Discover tools
        tools = discover_tools(str(manifest.agents_dir))
        
        # Build adapter
        adapter = ModelAdapter(
            name=manifest.model,
            grammar_builder=lambda t, c: None,  # TODO: use grammar_config
            response_parser=QwenResponseParser(),
        )
        
        # Build client
        client = build_client({
            "model": manifest.model,
            "base_url": "http://localhost:8000/v1",
            "api_key": "EMPTY",
        })
        
        # Build kernel
        kernel = AgentKernel(
            client=client,
            adapter=adapter,
            tools=tools,
        )
        
        return cls(kernel, manifest)
    
    async def run(self, user_input: str, **kwargs) -> RunResult:
        """Run the agent with a user message."""
        messages = [
            Message(role="system", content=self.manifest.system_prompt),
            Message(role="user", content=user_input),
        ]
        
        tool_schemas = [t.schema for t in self.kernel.tools]
        
        return await self.kernel.run(
            messages,
            tool_schemas,
            max_turns=kwargs.get("max_turns", self.manifest.max_turns),
        )
    
    async def close(self) -> None:
        await self.kernel.close()
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_agent/test_bundle.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/structured_agents/agent.py tests/test_agent/
git commit -m "feat: add Agent.from_bundle() entry point"
```

---

## Phase 7: Client and Final Wiring

### Task 8: Create LLMClient protocol and OpenAICompatibleClient

**Files:**
- Create: src/structured_agents/client/__init__.py
- Modify: src/structured_agents/client/protocol.py (already exists, verify)
- Create: src/structured_agents/client/openai.py
- Test: tests/test_client/test_openai.py

**Step 1: Write the failing test**

```python
# tests/test_client/test_openai.py
import pytest
from unittest.mock import AsyncMock, patch
from structured_agents.client.openai import OpenAICompatibleClient
from structured_agents.client.protocol import CompletionResponse
from structured_agents.types import TokenUsage

@pytest.mark.asyncio
async def test_openai_client_chat_completion():
    client = OpenAICompatibleClient(
        base_url="http://localhost:8000/v1",
        api_key="test-key",
        model="test-model",
    )
    
    with patch.object(client, "_client") as mock_client:
        mock_client.chat.completions.create = AsyncMock(return_value=MagicMock(
            id="chatcmpl-123",
            choices=[MagicMock(
                message=MagicMock(content="Hello", tool_calls=None),
                finish_reason="stop"
            )],
            usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            model="test-model",
            to_dict.return_value={}
        ))
        
        result = await client.chat_completion(
            messages=[{"role": "user", "content": "Hi"}],
            tools=None,
        )
        
        assert result.content == "Hello"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_client/test_openai.py -v
 — module not found```

Expected: FAIL

**Step 3: Create client/openai.py**

```python
"""OpenAI-compatible LLM client."""
from __future__ import annotations
from typing import Any
from openai import AsyncOpenAI
from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.types import TokenUsage


class OpenAICompatibleClient:
    """OpenAI-compatible client for vLLM and similar backends."""
    
    def __init__(
        self,
        base_url: str,
        api_key: str = "EMPTY",
        model: str = "default",
        timeout: float = 120.0,
    ):
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout,
        )
    
    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict[str, Any] | None = None,
        model: str | None = None,
    ) -> CompletionResponse:
        """Make a chat completion request."""
        response = await self._client.chat.completions.create(
            model=model or self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        )
        
        choice = response.choices[0]
        message = choice.message
        
        content = message.content
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                }
                for tc in message.tool_calls
            ]
        
        usage = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            )
        
        return CompletionResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response=response.to_dict(),
        )
    
    async def close(self) -> None:
        await self._client.close()


def build_client(config: dict[str, Any]) -> LLMClient:
    """Build an LLM client from config dict."""
    return OpenAICompatibleClient(
        base_url=config.get("base_url", "http://localhost:8000/v1"),
        api_key=config.get("api_key", "EMPTY"),
        model=config.get("model", "default"),
        timeout=config.get("timeout", 120.0),
    )
```

**Step 4: Update client/__init__.py**

```python
"""Client package for LLM connections."""
from structured_agents.client.protocol import CompletionResponse, LLMClient
from structured_agents.client.openai import OpenAICompatibleClient, build_client

__all__ = ["CompletionResponse", "LLMClient", "OpenAICompatibleClient", "build_client"]
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/test_client/test_openai.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add src/structured_agents/client/ tests/test_client/
git commit -m "feat: add OpenAICompatibleClient"
```

---

### Task 9: Create __init__.py exports

**Files:**
- Modify: src/structured_agents/__init__.py

**Step 1: Create src/structured_agents/__init__.py**

```python
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
from structured_agents.tools import Tool, GrailTool
from structured_agents.models import ModelAdapter, QwenResponseParser
from structured_agents.grammar import DecodingConstraint, ConstraintPipeline
from structured_agents.events import Observer, NullObserver, Event
from structured_agents.kernel import AgentKernel
from structured_agents.agent import Agent, AgentManifest
from structured_agents.client import LLMClient, OpenAICompatibleClient, build_client

__version__ = "0.3.0"

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
    # Models
    "ModelAdapter",
    "QwenResponseParser",
    # Grammar
    "DecodingConstraint",
    "ConstraintPipeline",
    # Events
    "Observer",
    "NullObserver",
    "Event",
    # Core
    "AgentKernel",
    "Agent",
    "AgentManifest",
    # Client
    "LLMClient",
    "OpenAICompatibleClient",
    "build_client",
]
```

**Step 2: Run test to verify imports work**

```bash
python -c "import structured_agents; print(structured_agents.__version__)"
```

Expected: 0.3.0

**Step 3: Commit**

```bash
git add src/structured_agents/__init__.py
git commit -m "feat: add public API exports"
```

---

## Phase 8: Integration Tests

### Task 10: Full integration test

**Files:**
- Test: tests/test_integration/test_full_agent.py

**Step 1: Write integration test**

```python
# tests/test_integration/test_full_agent.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from structured_agents import Agent, AgentKernel
from structured_agents.models import ModelAdapter, QwenResponseParser
from structured_agents.tools import Tool
from structured_agents.types import Message, ToolSchema, ToolResult, ToolCall

@pytest.mark.asyncio
async def test_full_agent_loop():
    """End-to-end test of agent running one turn."""
    
    # Mock client that returns a tool call
    mock_client = AsyncMock()
    mock_client.chat_completion = AsyncMock(return_value=MagicMock(
        content=None,
        tool_calls=[{
            "id": "call_123",
            "type": "function", 
            "function": {
                "name": "add",
                "arguments": '{"a": 1, "b": 2}'
            }
        }],
        usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        to_dict=lambda: {}
    ))
    mock_client.close = AsyncMock()
    
    # Mock tool
    mock_tool = MagicMock(spec=Tool)
    mock_tool.schema = ToolSchema(
        name="add", 
        description="Add two numbers",
        parameters={"type": "object", "properties": {"a": {"type": "int"}, "b": {"type": "int"}}}
    )
    mock_tool.execute = AsyncMock(return_value=ToolResult(
        call_id="call_123",
        name="add",
        output='{"result": 3}',
        is_error=False
    ))
    
    # Build kernel
    adapter = ModelAdapter(
        name="test",
        grammar_builder=lambda t, c: None,
        response_parser=QwenResponseParser(),
    )
    
    kernel = AgentKernel(
        client=mock_client,
        adapter=adapter,
        tools=[mock_tool],
    )
    
    # Run
    messages = [
        Message(role="system", content="You are a calculator."),
        Message(role="user", content="What is 1 + 2?"),
    ]
    
    result = await kernel.run(messages, [mock_tool.schema], max_turns=1)
    
    # Verify
    assert result.turn_count == 1
    assert result.termination_reason == "no_tool_calls"  # tool called, then done
    
    # Tool should have been executed
    mock_tool.execute.assert_called_once()
    
    await kernel.close()

**Step 2: Run integration test**

```bash
pytest tests/test_integration/test_full_agent.py -v
```

Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration/
git commit -m "test: add full integration test"
```

---

## Summary

### Files Created

| Phase | Files |
|-------|-------|
| 1. Types | `types.py` |
| 2. Tools | `tools/protocol.py`, `tools/grail.py`, `tools/__init__.py` |
| 3. Grammar | `grammar/config.py`, `grammar/pipeline.py`, `grammar/__init__.py` |
| 4. Models | `models/adapter.py`, `models/parsers.py`, `models/__init__.py` |
| 5. Events | `events/types.py`, `events/observer.py`, `events/__init__.py` |
| 6. Kernel | `kernel.py` |
| 7. Agent | `agent.py` |
| 8. Client | `client/openai.py`, `client/__init__.py` |
| 9. Exports | `__init__.py` |

### Architecture Summary

The v0.3.0 architecture has 5 core concepts:

1. **Tool** — has a schema, can execute with arguments
2. **ModelAdapter** — formats messages and parses responses for a specific model family
3. **DecodingConstraint** — forces the model to output valid tool calls
4. **Kernel** — the loop: ask model → execute tools → repeat
5. **Agent** — the entry point: load config, wire everything, run

### What Was Simplified

- 6-layer tool abstraction → single Tool protocol
- Plugin system → ModelAdapter dataclass
- 8-method Observer protocol → single emit() with typed Event union
- Composite patterns → flat lists at kernel level
- 51 files → ~20 files

### Next Steps

After completing all tasks:

1. Run full test suite: `pytest`
2. Verify mypy type checking: `mypy src/structured_agents`
3. Migrate existing .pym scripts to new patterns
4. Update README.md with new API examples
5. Bump version to 0.3.0 in pyproject.toml
