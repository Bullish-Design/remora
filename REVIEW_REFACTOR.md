# Code Review Refactor Plan

> Implementation guide for all non-Cairn refactoring tasks identified in [CODE_REVIEW.md](file:///c:/Users/Andrew/Documents/Projects/remora/CODE_REVIEW.md).
> Cairn/Grail integration is covered separately in [CAIRN_INTEGRATION_REFACTOR.md](file:///c:/Users/Andrew/Documents/Projects/remora/CAIRN_INTEGRATION_REFACTOR.md).

---

## Table of Contents

1. [Critical Findings](#1-critical-findings)
   - §1.1 [Runner Hardcoded Model Assumptions](#11-runner-hardcoded-model-assumptions)
   - §1.2 [Tool Registry Silent Failures](#12-tool-registry-silent-failures)
   - §1.3 [Orchestrator Exception Swallowing](#13-orchestrator-exception-swallowing)
   - §1.4 [Config Model-Aware Validation](#14-config-model-aware-validation)
2. [Code Quality Improvements](#2-code-quality-improvements)
   - §2.1 [Runner Decomposition](#21-runner-decomposition)
   - §2.2 [CLI Deduplication](#22-cli-deduplication)
   - §2.3 [Error Handling Gaps](#23-error-handling-gaps)
   - §2.4 [Testing Improvements](#24-testing-improvements)
3. [Implementation Order](#3-implementation-order)
4. [Verification Plan](#4-verification-plan)

---

## 1. Critical Findings

These are high-priority bugfixes that should be addressed before any structural refactoring.

---

### 1.1 Runner Hardcoded Model Assumptions → ModelProfile

**Files:** [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/runner.py), [config.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/config.py)

**Problem:** The `FunctionGemmaRunner` class name implies it's specific to FunctionGemma, but it's Remora's only runner. The `_tool_choice_for_turn()` method returns a fixed value from config without any model-specific logic. Adding support for a new model family (e.g. Mistral, Claude) would require editing runner internals. The class name is also confusing.

**What to change:**

#### Step 1.1.1: Define `ModelProfile` configuration entity

A `ModelProfile` encodes all model-family-specific behavior. Adding a new model means adding a new profile entry — no runner code changes.

**New file:** `remora/model_profile.py`

```python
"""Model-family-specific behavior profiles."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ModelProfile(BaseModel):
    """Describes the capabilities and behavior of a model family.

    Each profile encodes what the model supports so the runner can adapt
    its behavior without hardcoded checks.
    """

    name: str
    """Human-readable profile name, e.g. 'functiongemma', 'llama3'."""

    supported_tool_choice: set[str] = Field(default={"auto", "none", "required"})
    """Which tool_choice values the model/server actually supports.
    If the config asks for 'required' but the model doesn't support it,
    the runner falls back to 'auto'."""

    output_format: Literal["openai_json", "functiongemma_tags"] = "openai_json"
    """How the model returns tool calls. 'openai_json' = standard OpenAI
    tool_calls array. 'functiongemma_tags' = inline <tool_call> XML tags
    (used by FunctionGemma when tool_choice is unavailable)."""

    supports_parallel_tool_calls: bool = True
    """Whether the model can return multiple tool_calls in one response."""

    max_tool_calls_per_turn: int | None = None
    """Optional cap on tool calls per turn. None = no limit."""

    submit_result_strategy: Literal["tool_choice_force", "prompt_instruction"] = "tool_choice_force"
    """How to force the model to call submit_result on the final turn.
    'tool_choice_force' = set tool_choice={"type": "function", "function": {"name": "submit_result"}}.
    'prompt_instruction' = append a system message instructing the model to submit
    (for models that don't support function-level tool_choice forcing)."""


# ═══════════════════════════════════════════════════════════════
# Built-in profiles — add new models here, no runner changes needed
# ═══════════════════════════════════════════════════════════════

BUILTIN_PROFILES: dict[str, ModelProfile] = {
    "default": ModelProfile(
        name="default",
        supported_tool_choice={"auto", "none", "required"},
        output_format="openai_json",
        supports_parallel_tool_calls=True,
        submit_result_strategy="tool_choice_force",
    ),
    "functiongemma": ModelProfile(
        name="functiongemma",
        supported_tool_choice={"auto", "none"},  # 'required' → vLLM 400 error
        output_format="openai_json",             # vLLM normalizes to OpenAI format
        supports_parallel_tool_calls=True,
        submit_result_strategy="prompt_instruction",  # Can't force via tool_choice
    ),
    "llama3": ModelProfile(
        name="llama3",
        supported_tool_choice={"auto", "none", "required"},
        output_format="openai_json",
        supports_parallel_tool_calls=True,
        submit_result_strategy="tool_choice_force",
    ),
    "mistral": ModelProfile(
        name="mistral",
        supported_tool_choice={"auto", "none", "required"},
        output_format="openai_json",
        supports_parallel_tool_calls=False,  # Mistral sends one at a time
        submit_result_strategy="tool_choice_force",
    ),
}


def resolve_model_profile(profile_name: str | None, model_name: str | None) -> ModelProfile:
    """Resolve a ModelProfile from explicit name or model string.

    Priority:
      1. Explicit profile_name from config (e.g. model_profile: "functiongemma")
      2. Auto-detect from model_name string (e.g. adapter = "functiongemma-2b")
      3. Fall back to 'default'
    """
    if profile_name and profile_name in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[profile_name]

    # Auto-detect from model name
    if model_name:
        lower = model_name.lower()
        for key, profile in BUILTIN_PROFILES.items():
            if key != "default" and key in lower:
                return profile

    return BUILTIN_PROFILES["default"]
```

#### Step 1.1.2: Add `model_profile` to config

**Modify:** [config.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/config.py)

```python
class RunnerConfig(BaseModel):
    tool_choice: str = "auto"
    max_tokens: int = 4096
    max_turns: int = 10
    temperature: float = 0.0
    model_profile: str | None = None  # NEW — explicit profile override
```

When `model_profile` is `None`, the runner auto-detects from the adapter name. When set explicitly (e.g. `model_profile: "functiongemma"` in `remora.yaml`), it takes priority.

#### Step 1.1.3: Rename the class and use ModelProfile

**Modify:** [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/runner.py)

```diff
-class FunctionGemmaRunner:
+class AgentRunner:
```

Replace `_tool_choice_for_turn` with profile-aware logic:

```python
from remora.model_profile import ModelProfile, resolve_model_profile

@dataclass
class AgentRunner:
    # ... existing fields ...

    def __post_init__(self) -> None:
        self._profile = resolve_model_profile(
            profile_name=self.runner_config.model_profile,
            model_name=self.server_config.default_adapter,
        )
        # ... rest of init ...

    def _tool_choice_for_turn(self, next_turn: int) -> Any:
        """Resolve tool_choice for this turn using the model profile."""
        choice = self.runner_config.tool_choice
        if choice not in self._profile.supported_tool_choice:
            # Model doesn't support the requested tool_choice — fall back to 'auto'
            return "auto"
        return choice

    def _submit_result_tool_choice(self) -> Any:
        """Get the tool_choice value to force submit_result on the final turn."""
        if self._profile.submit_result_strategy == "tool_choice_force":
            return {"type": "function", "function": {"name": "submit_result"}}
        # For models that can't force tool_choice, return "auto"
        # and rely on the system prompt instruction
        return "auto"
```

#### Step 1.1.4: Update all references

- `orchestrator.py` — change `FunctionGemmaRunner(...)` → `AgentRunner(...)`
- Test files — update imports
- `__init__.py` — update re-exports if applicable
- Grep for `FunctionGemmaRunner` across the project to catch any remaining references

```bash
grep -rn "FunctionGemmaRunner" remora/ tests/
```

**How to test:**

```python
# tests/test_model_profile.py
import pytest
from remora.model_profile import (
    ModelProfile, BUILTIN_PROFILES, resolve_model_profile,
)

def test_resolve_explicit_profile():
    """Explicit profile_name takes priority over model string."""
    profile = resolve_model_profile("functiongemma", "llama-3.1-70b")
    assert profile.name == "functiongemma"

def test_resolve_auto_detect_from_model():
    """Auto-detect profile from adapter name."""
    profile = resolve_model_profile(None, "functiongemma-2b")
    assert profile.name == "functiongemma"
    assert "required" not in profile.supported_tool_choice

def test_resolve_fallback_to_default():
    """Unknown model falls back to default profile."""
    profile = resolve_model_profile(None, "my-custom-model")
    assert profile.name == "default"
    assert "required" in profile.supported_tool_choice

def test_functiongemma_profile_no_required():
    """FunctionGemma profile should not support 'required'."""
    p = BUILTIN_PROFILES["functiongemma"]
    assert p.supported_tool_choice == {"auto", "none"}
    assert p.submit_result_strategy == "prompt_instruction"

# tests/test_runner_tool_choice.py
def test_tool_choice_required_with_supporting_model(mock_runner):
    """Models that support 'required' should pass it through."""
    mock_runner._profile = BUILTIN_PROFILES["default"]
    mock_runner.runner_config.tool_choice = "required"
    assert mock_runner._tool_choice_for_turn(1) == "required"

def test_tool_choice_required_with_functiongemma(mock_runner):
    """FunctionGemma should fall back to 'auto' when 'required' is set."""
    mock_runner._profile = BUILTIN_PROFILES["functiongemma"]
    mock_runner.runner_config.tool_choice = "required"
    assert mock_runner._tool_choice_for_turn(1) == "auto"

def test_tool_choice_auto_always_passes(mock_runner):
    """'auto' should pass through for all profiles."""
    for name, profile in BUILTIN_PROFILES.items():
        mock_runner._profile = profile
        mock_runner.runner_config.tool_choice = "auto"
        assert mock_runner._tool_choice_for_turn(1) == "auto"
```

---

### 1.2 Tool Registry Silent Failures

**File:** [tool_registry.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/tool_registry.py)

**Problem:** When `grail.load()` or schema extraction fails for a tool, the error may be silently dropped (the tool is skipped). The agent then runs without that tool, which means it can't complete its task but gets no indication why.

**What to verify first:**

Before implementing any changes, check whether `GrailToolRegistry._build_tool_schemas` already raises or logs on load failure. Read the method carefully — the current behavior may be acceptable if it logs at WARNING level.

**What to change (if silent):**

1. **Add explicit logging** for every load failure:
   ```python
   import logging
   logger = logging.getLogger(__name__)

   def _build_tool_schemas(self, tools: list[ToolConfig]) -> list[dict[str, Any]]:
       schemas: list[dict[str, Any]] = []
       failed: list[str] = []
       for tool in tools:
           try:
               schema = self._load_tool_schema(tool)
               schemas.append(schema)
           except Exception as exc:
               logger.error(
                   "Failed to build schema for tool '%s': %s",
                   tool.name,
                   exc,
                   exc_info=True,
               )
               failed.append(f"{tool.name}: {exc}")
       if failed:
           raise ToolRegistryError(
               AGENT_001,
               f"Schema build failed for {len(failed)} tool(s):\n" + "\n".join(failed),
           )
       return schemas
   ```

2. **Add a `ToolRegistryError` class** (if one doesn't exist):
   ```python
   class ToolRegistryError(RuntimeError):
       def __init__(self, code: str, message: str) -> None:
           super().__init__(message)
           self.code = code
   ```

**How to test:**

```python
# tests/test_tool_registry.py
def test_schema_build_failure_raises(tool_registry, bad_pym_path):
    """A broken .pym file should raise ToolRegistryError, not silently skip."""
    tools = [ToolConfig(name="broken_tool", pym=bad_pym_path)]
    with pytest.raises(ToolRegistryError, match="broken_tool"):
        tool_registry._build_tool_schemas(tools)

def test_schema_build_success(tool_registry, valid_pym_path):
    """Valid .pym files should produce schemas without error."""
    tools = [ToolConfig(name="valid_tool", pym=valid_pym_path)]
    schemas = tool_registry._build_tool_schemas(tools)
    assert len(schemas) == 1
```

---

### 1.3 Orchestrator Exception Swallowing

**File:** [orchestrator.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/orchestrator.py)

**Problem:** The `Coordinator.run_with_limit()` inner function catches `Exception` broadly (line matches `except Exception as exc:`). This catches programming errors (e.g. `TypeError`, `AttributeError`, `KeyError`) alongside legitimate operational errors. Bugs hide behind "agent failed" results, making debugging very difficult.

**What to change:**

1. **Narrow the exception filter**. Define which exceptions are operational vs bugs:

   ```python
   # Operational errors that should be caught and returned as results
   OPERATIONAL_ERRORS = (
       AgentError,          # Remora-specific agent failures
       CairnError,          # Cairn subprocess issues
       APIConnectionError,  # vLLM unreachable
       APITimeoutError,     # vLLM timeout
       asyncio.TimeoutError,  # General timeout
   )

   async def run_with_limit(operation, node):
       try:
           result = await runner.run()
           return operation, result
       except OPERATIONAL_ERRORS as exc:
           # Expected operational failure — return as result
           logger.warning("Agent failed: %s on %s: %s", operation, node.name, exc)
           return operation, exc
       # Let programming errors (TypeError, AttributeError, etc.) propagate
   ```

2. **Add structured logging** for the caught errors:
   ```python
   logger.warning(
       "Agent operational failure",
       extra={
           "operation": operation,
           "node_id": node.node_id,
           "error_type": type(exc).__name__,
           "error_message": str(exc),
       },
   )
   ```

3. **Add a top-level try/except** in `process_node()` to catch unexpected bugs and emit a clear error event:
   ```python
   async def process_node(self, node, operations):
       tasks = []
       for op in operations:
           tasks.append(self._run_operation(op, node))
       try:
           results = await asyncio.gather(*tasks, return_exceptions=True)
       except Exception as exc:
           # Truly unexpected — log and re-raise
           logger.exception("Unexpected error processing node %s", node.node_id)
           raise
       return results
   ```

**How to test:**

```python
# tests/test_orchestrator.py
@pytest.mark.asyncio
async def test_programming_error_propagates(coordinator, mock_runner):
    """A TypeError in runner.run() should propagate, not be swallowed."""
    mock_runner.run.side_effect = TypeError("unexpected None")
    with pytest.raises(TypeError, match="unexpected None"):
        await coordinator.process_node(mock_node, ["lint"])

@pytest.mark.asyncio
async def test_operational_error_returned(coordinator, mock_runner):
    """An AgentError should be captured and returned as a result."""
    mock_runner.run.side_effect = AgentError(
        node_id="test", operation="lint", phase="loop",
        error_code="AGENT_004", message="Turn limit exceeded",
    )
    results = await coordinator.process_node(mock_node, ["lint"])
    assert isinstance(results[0][1], AgentError)
```

---

### 1.4 Config Model-Aware Validation (uses ModelProfile from §1.1)

**File:** [config.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/config.py)

**Problem:** The `RunnerConfig.tool_choice` field is a raw `str = "auto"` without any validation. Setting `tool_choice="required"` for a FunctionGemma model causes a vLLM 400 error at runtime — there's no early warning.

**What to change:**

1. **Add a Pydantic validator** to `RunnerConfig`:
   ```python
   from pydantic import field_validator

   class RunnerConfig(BaseModel):
       tool_choice: str = "auto"
       max_tokens: int = 4096
       max_turns: int = 10
       temperature: float = 0.0
       model_profile: str | None = None  # Added in §1.1

       @field_validator("tool_choice")
       @classmethod
       def validate_tool_choice(cls, value: str) -> str:
           allowed = {"auto", "none", "required"}
           if value not in allowed:
               raise ValueError(f"tool_choice must be one of {allowed}, got '{value}'")
           return value
   ```

2. **Add a config-level cross-validation** using `ModelProfile` from §1.1. This replaces fragile string matching with profile-based validation:
   ```python
   from remora.model_profile import resolve_model_profile

   class RemoraConfig(BaseModel):
       @model_validator(mode="after")
       def warn_tool_choice_compatibility(self) -> "RemoraConfig":
           profile = resolve_model_profile(
               profile_name=self.runner.model_profile,
               model_name=self.server.default_adapter,
           )
           if self.runner.tool_choice not in profile.supported_tool_choice:
               import warnings
               warnings.warn(
                   f"tool_choice='{self.runner.tool_choice}' is not supported by "
                   f"model profile '{profile.name}' "
                   f"(supported: {profile.supported_tool_choice}). "
                   f"The runner will fall back to 'auto' at runtime.",
                   stacklevel=2,
               )
           return self
   ```

**How to test:**

```python
# tests/test_config.py
def test_tool_choice_invalid_value():
    """Invalid tool_choice values should be rejected."""
    with pytest.raises(ValidationError, match="tool_choice"):
        RunnerConfig(tool_choice="force")

def test_tool_choice_valid_values():
    """All valid tool_choice values should be accepted."""
    for value in ("auto", "none", "required"):
        config = RunnerConfig(tool_choice=value)
        assert config.tool_choice == value

def test_gemma_required_warning_via_profile():
    """Using 'required' with a gemma model should emit a profile-based warning."""
    with pytest.warns(UserWarning, match="not supported by model profile 'functiongemma'"):
        RemoraConfig(
            server=ServerConfig(base_url="http://localhost:8000", default_adapter="functiongemma-2b"),
            runner=RunnerConfig(tool_choice="required"),
            # ... other required fields
        )

def test_llama_required_no_warning():
    """Using 'required' with a llama model should NOT emit a warning."""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        RemoraConfig(
            server=ServerConfig(base_url="http://localhost:8000", default_adapter="llama-3.1-70b"),
            runner=RunnerConfig(tool_choice="required"),
            # ... other required fields
        )
```

---

## 2. Code Quality Improvements

These are structural improvements that make the codebase more maintainable.

---

### 2.1 Runner Decomposition

**File:** [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/runner.py) (500 lines)

**Problem:** `FunctionGemmaRunner` handles three distinct responsibilities:
1. **Message construction** — building system prompts, coercing messages, payload serialization
2. **LLM communication** — calling vLLM, retries, event emission
3. **Tool dispatch** — routing tool calls to `.pym` scripts, merging context

**What to change:**

Split into three focused classes. Each class should be in its own file for clarity.

#### Step 2.1.1: Extract `MessageBuilder`

**New file:** `remora/messages.py`

```python
"""Message construction and serialization for agent conversations."""

import json
from typing import Any, cast

from openai.types.chat import ChatCompletionMessage, ChatCompletionMessageParam


class MessageBuilder:
    """Constructs and manages the chat message history."""

    def __init__(self, system_prompt: str, initial_message: str) -> None:
        self.messages: list[ChatCompletionMessageParam] = [
            cast(ChatCompletionMessageParam, {"role": "system", "content": system_prompt}),
            cast(ChatCompletionMessageParam, {"role": "user", "content": initial_message}),
        ]

    def append_assistant(self, message: ChatCompletionMessage) -> None:
        self.messages.append(self._coerce(message))

    def append_tool_result(self, tool_call_id: str, name: str, content: str) -> None:
        self.messages.append(
            cast(
                ChatCompletionMessageParam,
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": content,
                },
            )
        )

    @staticmethod
    def _coerce(message: ChatCompletionMessage) -> ChatCompletionMessageParam:
        return cast(ChatCompletionMessageParam, message.model_dump(exclude_none=True))

    def serialize_payload(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, (dict, list)):
            try:
                return json.dumps(value, ensure_ascii=False)
            except (TypeError, ValueError):
                return str(value)
        return str(value)

    def build_payload(self, *, truncate_fn: Any = None) -> dict[str, Any]:
        """Build serialized message payload for event emission."""
        messages: list[dict[str, Any]] = []
        total_chars = 0
        for msg in self.messages:
            role = str(msg.get("role", "unknown"))
            raw = msg.get("content") or ""
            content = self.serialize_payload(raw)
            total_chars += len(content)
            display = truncate_fn(content) if truncate_fn else content
            messages.append({"role": role, "content": display})
        return {"messages": messages, "prompt_chars": total_chars}
```

**What moves out of `runner.py`:**
- `_coerce_message_param()` → `MessageBuilder._coerce()`
- `_serialize_payload()` → `MessageBuilder.serialize_payload()`
- `_build_message_payload()` → `MessageBuilder.build_payload()`
- The message initialization in `__post_init__` → `MessageBuilder.__init__`

#### Step 2.1.2: Extract `ToolDispatcher`

**New file:** `remora/tools.py`

```python
"""Tool call dispatch and result handling."""

import json
from pathlib import Path
from typing import Any

from remora.cairn import CairnError
from remora.events import EventEmitter, NullEventEmitter


class ToolDispatcher:
    """Routes tool calls to .pym scripts via the Cairn client."""

    def __init__(
        self,
        cairn_client: Any,
        tools_by_name: dict[str, Any],
        base_inputs: dict[str, Any],
        workspace_id: str,
        node_id: str,
        operation: str,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self._cairn = cairn_client
        self._tools = tools_by_name
        self._base_inputs = base_inputs
        self._workspace_id = workspace_id
        self._node_id = node_id
        self._operation = operation
        self._emitter = event_emitter or NullEventEmitter()

    async def dispatch(self, tool_call: Any) -> str:
        """Dispatch a single tool call and return the result as a JSON string."""
        tool_function = getattr(tool_call, "function", None)
        tool_name = getattr(tool_function, "name", "unknown")
        arguments = getattr(tool_function, "arguments", None)

        args = self._parse_arguments(arguments)
        tool_inputs = {**self._base_inputs, **args}

        self._emit_call(tool_name)

        tool_def = self._tools.get(tool_name)
        if tool_def is None:
            return self._unknown_tool(tool_name)

        # Run context providers
        context_parts: list[str] = []
        for provider_path in tool_def.context_providers:
            try:
                context = await self._cairn.run_pym(
                    provider_path, self._workspace_id, inputs=self._base_inputs
                )
            except CairnError as exc:
                return self._tool_error(tool_name, f"Context provider failed: {exc}")
            context_parts.append(json.dumps(context))

        # Run the tool itself
        try:
            result = await self._cairn.run_pym(tool_def.pym, self._workspace_id, inputs=tool_inputs)
        except CairnError as exc:
            return self._tool_error(tool_name, str(exc))

        self._emit_result(tool_name, result)
        return "\n".join(context_parts + [json.dumps(result)])

    @staticmethod
    def _parse_arguments(arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                parsed = {}
            return parsed if isinstance(parsed, dict) else {}
        if isinstance(arguments, dict):
            return arguments
        return {}

    def _unknown_tool(self, name: str) -> str:
        error = {"error": f"Unknown tool: {name}"}
        self._emit_result(name, error)
        return json.dumps(error)

    def _tool_error(self, name: str, message: str) -> str:
        error = {"error": message}
        self._emit_result(name, error)
        return json.dumps(error)

    def _emit_call(self, tool_name: str) -> None:
        self._emitter.emit({
            "event": "tool_call",
            "agent_id": self._workspace_id,
            "node_id": self._node_id,
            "operation": self._operation,
            "tool_name": tool_name,
            "phase": "execution",
            "status": "ok",
        })

    def _emit_result(self, tool_name: str, result: Any) -> None:
        status = "error" if isinstance(result, dict) and result.get("error") else "ok"
        payload: dict[str, Any] = {
            "event": "tool_result",
            "agent_id": self._workspace_id,
            "node_id": self._node_id,
            "operation": self._operation,
            "tool_name": tool_name,
            "phase": "execution",
            "status": status,
        }
        if status == "error":
            payload["error"] = str(result.get("error") if isinstance(result, dict) else result)
        self._emitter.emit(payload)
```

**What moves out of `runner.py`:**
- `_dispatch_tool()` → `ToolDispatcher.dispatch()`
- `_base_tool_inputs()` → passed into `ToolDispatcher.__init__`
- `_emit_tool_result()` → `ToolDispatcher._emit_result()`
- Tool-call related event emission

#### Step 2.1.3: Simplify `AgentRunner`

After extraction, the runner becomes the orchestration glue — roughly 120 lines:

```python
# remora/runner.py (after decomposition)
@dataclass
class AgentRunner:
    definition: SubagentDefinition
    node: CSTNode
    workspace_id: str
    cairn_client: CairnClient
    server_config: ServerConfig
    runner_config: RunnerConfig
    # ...

    def __post_init__(self) -> None:
        self._messages = MessageBuilder(
            system_prompt=self.definition.initial_context.system_prompt,
            initial_message=self.definition.initial_context.render(self.node),
        )
        self._dispatcher = ToolDispatcher(
            cairn_client=self.cairn_client,
            tools_by_name=self.definition.tools_by_name,
            base_inputs=self._base_tool_inputs(),
            workspace_id=self.workspace_id,
            # ...
        )
        # ...

    async def run(self) -> AgentResult:
        message = await self._call_model(phase="model_load")
        while self.turn_count < self.definition.max_turns:
            self.turn_count += 1
            self._messages.append_assistant(message)
            tool_calls = message.tool_calls or []
            if not tool_calls:
                return self._handle_no_tool_calls(message)
            for tool_call in tool_calls:
                name = getattr(getattr(tool_call, "function", None), "name", None)
                if name == "submit_result":
                    return self._build_submit_result(...)
                content = await self._dispatcher.dispatch(tool_call)
                self._messages.append_tool_result(
                    tool_call_id=getattr(tool_call, "id", "unknown"),
                    name=name or "unknown",
                    content=content,
                )
            message = await self._call_model(phase="loop")
        raise AgentError(...)
```

**How to test the decomposition:**
1. Ensure the existing test suite still passes after the split
2. Add focused unit tests for `MessageBuilder` and `ToolDispatcher` in isolation
3. Verify event emission payloads haven't changed

---

### 2.2 CLI Deduplication

**File:** [cli.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/cli.py) (523 lines)

**Problem:** The `analyze`, `watch`, and `config` commands each declare ~15 identical CLI options (lines 143–160, 238–255, 344–361). Adding a new option requires editing 3 places. The `_build_overrides` function is also large because it mirrors these options.

**What to change:**

Typer doesn't have a built-in "option group" feature, but you can reduce duplication using a shared dataclass + `typer.Option` with callbacks.

#### Approach: Shared Options Dataclass

```python
# remora/cli_options.py
"""Shared CLI option definitions to avoid duplication."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import typer


@dataclass
class SharedOptions:
    """Options shared across analyze, watch, and config commands."""

    config_path: Path | None = None
    discovery_language: str | None = None
    query_pack: str | None = None
    agents_dir: Path | None = None
    max_turns: int | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    tool_choice: str | None = None
    cairn_command: str | None = None
    cairn_home: Path | None = None
    max_concurrent_agents: int | None = None
    cairn_timeout: int | None = None
    event_stream: bool | None = None
    event_stream_file: Path | None = None

    def to_overrides(self) -> dict[str, Any]:
        """Convert non-None options to config overrides dict."""
        overrides: dict[str, Any] = {}
        # Discovery
        disc: dict[str, Any] = {}
        if self.discovery_language is not None:
            disc["language"] = self.discovery_language
        if self.query_pack is not None:
            disc["query_pack"] = self.query_pack
        if disc:
            overrides["discovery"] = disc
        # Agents dir
        if self.agents_dir is not None:
            overrides["agents_dir"] = self.agents_dir
        # Runner
        runner: dict[str, Any] = {}
        for key in ("max_turns", "max_tokens", "temperature", "tool_choice"):
            val = getattr(self, key)
            if val is not None:
                runner[key] = val
        if runner:
            overrides["runner"] = runner
        # Cairn
        cairn: dict[str, Any] = {}
        if self.cairn_command is not None:
            cairn["command"] = self.cairn_command
        if self.cairn_home is not None:
            cairn["home"] = self.cairn_home
        if self.max_concurrent_agents is not None:
            cairn["max_concurrent_agents"] = self.max_concurrent_agents
        if self.cairn_timeout is not None:
            cairn["timeout"] = self.cairn_timeout
        if cairn:
            overrides["cairn"] = cairn
        # Events
        events: dict[str, Any] = {}
        if self.event_stream is not None:
            events["enabled"] = self.event_stream
        if self.event_stream_file is not None:
            events["output"] = self.event_stream_file
        if events:
            overrides["event_stream"] = events
        return overrides
```

Then in `cli.py`, each command uses the shared options via a **Typer callback**:

```python
# cli.py — simplified analyze command
from remora.cli_options import SharedOptions

def _parse_shared(ctx: typer.Context, **kwargs) -> SharedOptions:
    return SharedOptions(**{k: v for k, v in kwargs.items() if v is not None})

@app.command()
def analyze(
    paths: list[Path] = typer.Argument(default_factory=lambda: [Path(".")]),
    operations: str = typer.Option("lint,test,docstring", "--operations", "-o"),
    output_format: str = typer.Option("table", "--format", "-f"),
    auto_accept: bool = typer.Option(False, "--auto-accept"),
    # Shared options still declared, but _build_overrides removed
    **shared,  # Would need Typer plugin or explicit forwarding
) -> None:
    ...
```

> [!NOTE]
> Typer doesn't support `**kwargs` directly. The practical approach is to declare a `SharedOptions` dataclass and a helper function `_add_shared_options()` that programmatically adds the options using Typer's `@app.callback` or by using `click.pass_context`. See the [Typer docs on CLI option reuse](https://typer.tiangolo.com/).

**Simpler alternative (recommended for now):** Extract just the `_build_overrides` function to accept the dataclass, and have each command construct it:

```python
@app.command()
def analyze(
    paths: ...,
    operations: ...,
    # Still declare all options here (Typer requires it)
    # But the body becomes:
) -> None:
    opts = SharedOptions(
        config_path=config_path,
        discovery_language=discovery_language,
        # ... all shared fields
    )
    overrides = opts.to_overrides()
    config = load_config(opts.config_path, overrides)
    ...
```

This eliminates the standalone `_build_overrides` function and ensures all override logic is in one place.

**How to test:**

```python
# tests/test_cli_options.py
def test_shared_options_to_overrides_empty():
    """All-None options should produce empty overrides."""
    opts = SharedOptions()
    assert opts.to_overrides() == {}

def test_shared_options_to_overrides_partial():
    """Only set options should appear in overrides."""
    opts = SharedOptions(max_turns=5, cairn_timeout=30)
    overrides = opts.to_overrides()
    assert overrides == {"runner": {"max_turns": 5}, "cairn": {"timeout": 30}}
```

---

### 2.3 Error Handling Gaps

Multiple files have incomplete error handling. This section covers the fixes.

#### 2.3.1: Per-Turn Timeout in Runner

**File:** [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/runner.py)

**Problem:** Each `_call_model()` invocation has no per-turn timeout. If vLLM hangs (e.g. during KV cache compaction), the entire analysis hangs indefinitely.

**What to change:**

```python
async def _call_model(self, *, phase, tool_choice=None):
    timeout = self.runner_config.per_turn_timeout  # New config field, default 120s
    try:
        return await asyncio.wait_for(
            self._call_model_inner(phase=phase, tool_choice=tool_choice),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        raise AgentError(
            node_id=self.node.node_id,
            operation=self.definition.name,
            phase=phase,
            error_code=AGENT_002,
            message=f"Model call timed out after {timeout}s",
        )
```

**Config addition:**

```python
class RunnerConfig(BaseModel):
    per_turn_timeout: float = 120.0  # seconds
```

**How to test:**

```python
@pytest.mark.asyncio
async def test_per_turn_timeout(mock_runner):
    """A hanging model call should raise AgentError after timeout."""
    async def hang_forever():
        await asyncio.sleep(9999)
    mock_runner._http_client.chat.completions.create = hang_forever
    mock_runner.runner_config.per_turn_timeout = 0.1
    with pytest.raises(AgentError, match="timed out"):
        await mock_runner._call_model(phase="loop")
```

#### 2.3.2: Structured Error Reporting for Tool Failures

**File:** [runner.py](file:///c:/Users/Andrew/Documents/Projects/remora/remora/runner.py)

**Problem:** When a tool fails, the error is sent back to the model as a JSON string, but there's no structured event emitted for monitoring. The `_emit_tool_result` only captures basic status.

**What to change:**

Add structured error fields to the tool result event:

```python
def _emit_tool_result(self, tool_name: str, result: Any) -> None:
    status = "error" if isinstance(result, dict) and result.get("error") else "ok"
    payload = {
        "event": "tool_result",
        "agent_id": self.workspace_id,
        "node_id": self.node.node_id,
        "operation": self.definition.name,
        "tool_name": tool_name,
        "phase": "execution",
        "status": status,
    }
    if status == "error" and isinstance(result, dict):
        payload["error_code"] = result.get("code", "UNKNOWN")
        payload["error_message"] = str(result.get("error", ""))
        payload["error_recoverable"] = result.get("code") not in ("PROCESS_CRASH", "INTERNAL")
    self.event_emitter.emit(payload)
```

---

### 2.4 Testing Improvements

#### 2.4.1: Convert SubagentDefinition to Pydantic

**File:** `remora/subagent.py`

**Problem:** `SubagentDefinition` is likely a plain dataclass or dict-based structure. Converting to Pydantic gives free validation, serialization, and better error messages.

**What to change:**

```python
from pydantic import BaseModel, Field, field_validator

class ToolDefinition(BaseModel):
    name: str
    pym: Path
    context_providers: list[Path] = Field(default_factory=list)
    description: str = ""

class InitialContext(BaseModel):
    system_prompt: str
    template: str

    def render(self, node: CSTNode) -> str:
        return self.template.format(
            node_name=node.name,
            node_type=node.node_type,
            node_text=node.text,
            file_path=node.file_path,
        )

class SubagentDefinition(BaseModel):
    name: str
    max_turns: int = 10
    initial_context: InitialContext
    tools: list[ToolDefinition] = Field(default_factory=list)
    tool_schemas: list[dict[str, Any]] = Field(default_factory=list)
    grail_summary: dict[str, Any] = Field(default_factory=dict)

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, value: int) -> int:
        if value < 1:
            raise ValueError("max_turns must be >= 1")
        return value

    @property
    def tools_by_name(self) -> dict[str, ToolDefinition]:
        return {t.name: t for t in self.tools}
```

**How to test:**

```python
def test_subagent_definition_validation():
    """max_turns < 1 should be rejected."""
    with pytest.raises(ValidationError, match="max_turns"):
        SubagentDefinition(name="test", max_turns=0, initial_context=...)

def test_subagent_definition_from_yaml(tmp_path):
    """Loading from YAML should produce a valid SubagentDefinition."""
    yaml_content = """
    name: lint
    max_turns: 5
    initial_context:
      system_prompt: "You are a linter."
      template: "Lint {node_name}"
    tools:
      - name: read_file
        pym: tools/read_file.pym
    """
    yaml_file = tmp_path / "lint.yaml"
    yaml_file.write_text(yaml_content)
    definition = load_subagent_definition(yaml_file, tmp_path)
    assert definition.name == "lint"
    assert definition.max_turns == 5
    assert len(definition.tools) == 1
```

#### 2.4.2: Integration Tests with vLLM

Add integration tests that actually call a running vLLM server (skip if not available):

```python
# tests/integration/test_vllm.py
import pytest
from openai import AsyncOpenAI

VLLM_URL = "http://localhost:8000/v1"

@pytest.fixture
def vllm_client():
    return AsyncOpenAI(base_url=VLLM_URL, api_key="test")

@pytest.fixture
def skip_if_no_vllm(vllm_client):
    try:
        import httpx
        resp = httpx.get(f"{VLLM_URL}/models", timeout=2)
        resp.raise_for_status()
    except Exception:
        pytest.skip("vLLM server not available")

@pytest.mark.asyncio
async def test_basic_tool_call(vllm_client, skip_if_no_vllm):
    """Verify vLLM can handle a basic tool-calling request."""
    response = await vllm_client.chat.completions.create(
        model="functiongemma-2b",
        messages=[{"role": "user", "content": "Read the file main.py"}],
        tools=[{
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file",
                "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
            },
        }],
        tool_choice="auto",
    )
    assert response.choices[0].message is not None
```

---

## 3. Implementation Order

Execute in this order to minimize risk and avoid rework:

| Phase | Section | Priority | Risk | Dependencies |
|-------|---------|----------|------|--------------|
| 1 | §1.3 Orchestrator exception narrowing | 🔴 Critical | Low | None |
| 2 | §1.2 Tool registry silent failures | 🔴 Critical | Low | None |
| 3 | §1.4 Config validation | 🔴 Critical | Low | None |
| 4 | §1.1 Runner rename + ModelProfile | 🔴 Critical | Medium | None |
| 5 | §2.3.1 Per-turn timeout | 🟠 High | Low | §1.1 (rename) |
| 6 | §2.1 Runner decomposition | 🟠 High | Medium | §1.1 |
| 7 | §2.2 CLI deduplication | 🟡 Medium | Low | None |
| 8 | §2.4 Testing improvements | 🟡 Medium | Low | §2.1, §1.1 |
| 9 | Cairn integration | 🟠 High | High | §2.1 (runner decomposed) |

> [!IMPORTANT]
> The Cairn integration (Phase 9) depends on the runner decomposition (Phase 6) being complete, because the `ToolDispatcher` extracted in §2.1 will be replaced by the `ProcessIsolatedExecutor` from the Cairn refactor.

---

## 4. Verification Plan

### Automated Tests

Run after each phase:

```bash
# Run full test suite
pytest tests/ -v --tb=short

# Run with coverage to verify nothing regressed
pytest tests/ --cov=remora --cov-report=term-missing
```

### Phase-Specific Verification

| Phase | Verification |
|-------|-------------|
| §1.3 | `TypeError` in runner propagates; `AgentError` is caught and returned |
| §1.2 | Broken `.pym` → `ToolRegistryError`; valid `.pym` → schema |
| §1.4 | `tool_choice="force"` → `ValidationError`; gemma + required → warning |
| §1.1 | Rename is grep-clean; `ModelProfile` resolves correctly; FunctionGemma falls back to `auto` |
| §2.3.1 | Hanging model call raises `AgentError` after timeout |
| §2.1 | Event payloads unchanged; `MessageBuilder` and `ToolDispatcher` independently testable |
| §2.2 | `SharedOptions.to_overrides()` matches old `_build_overrides()` output |
| §2.4 | `SubagentDefinition` rejects invalid YAML; vLLM integration test passes |
