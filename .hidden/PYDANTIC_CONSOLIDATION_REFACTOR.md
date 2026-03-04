# Pydantic Consolidation Refactor Guide

> **Goal:** Reduce the "size of the library in the developer's head" by establishing a single rule —
> *all Remora value types are Pydantic BaseModel* — eliminating the cognitive overhead of remembering
> which types are stdlib dataclasses, which are Pydantic, and which serialization API to use.

---

## Table of Contents

1. **[Executive Summary](#1-executive-summary)** — The "one rule" mental model, current state, what changes, what doesn't
2. **[Item 1: ToolSchema](#2-item-1-toolschema)** — `core/agent_node.py:34-63` — Before/after, pros/cons, implications, risk
3. **[Item 2: SubscriptionPattern / Subscription](#3-item-2-subscriptionpattern--subscription)** — `core/subscriptions.py:26-86` — Before/after, pros/cons, implications, risk
4. **[Item 3: CSTNode](#4-item-3-cstnode)** — `core/discovery.py:44-65` — Before/after, pros/cons, implications, risk (frozen + hash)
5. **[Item 4: ToolCall / LLMResponse](#5-item-4-toolcall--llmresponse)** — `lsp/runner.py:40-54` — Before/after, pros/cons, implications, risk
6. **[Item 5: Message / ChatConfig / AgentResponse](#6-item-5-message--chatconfig--agentresponse)** — `core/chat.py:20-90` — Before/after, pros/cons, implications, risk
7. **[Serialization Simplification Analysis](#7-serialization-simplification-analysis)** — What branching is eliminated, what remains, why
8. **[Implementation Order](#8-implementation-order)** — Dependency analysis, recommended sequence
9. **[Estimated Scope](#9-estimated-scope)** — LOC changes, test impact, effort per item

---

## 1. Executive Summary

### The Problem: Two Mental Models

After the launch plan execution (Batches 1-8, 6.1-6.6), Remora's core types are split across two systems:

| System | Types | Serialization API | Immutability |
|--------|-------|--------------------|--------------|
| **Pydantic BaseModel** | Events (`_FrozenEvent` hierarchy), Config (`BaseSettings`), AgentContext, service models (`remora.models`) | `.model_dump()` | `frozen=True` via ConfigDict |
| **stdlib @dataclass** | ToolSchema, SubscriptionPattern, Subscription, CSTNode, ToolCall, LLMResponse, Message, ChatConfig, AgentResponse | `asdict(obj)` | `frozen=True` (CSTNode only) |

This split forces developers to remember:
- "Is this type Pydantic or dataclass?"
- "Do I call `.model_dump()` or `asdict()`?"
- "Do I need to import `dataclasses` just for serialization?"
- "Does `is_dataclass()` branching exist because of mixed types?"

### The Target: One Rule

> **All Remora-owned value types are Pydantic BaseModel.** Use `.model_dump()` to serialize. Period.

The only exception is types from `structured_agents` (an external dependency), which remain stdlib dataclasses. This is acceptable because they cross a package boundary — the rule applies to *Remora's* types.

### Current State (Post-Launch Plan)

| Category | Already Pydantic | Still @dataclass |
|----------|-----------------|------------------|
| Events | All 15 event types | - |
| Config | `RemoraConfig` (BaseSettings) | - |
| Agent context | `AgentContext` | - |
| Service models | `AgentInfo`, `AgentDetail`, `EventInfo`, `EventDetail` | - |
| **Tool schemas** | - | `ToolSchema` |
| **Subscriptions** | - | `SubscriptionPattern`, `Subscription` |
| **Discovery** | - | `CSTNode` |
| **Runner internals** | - | `ToolCall`, `LLMResponse` |
| **Chat types** | - | `Message`, `ChatConfig`, `AgentResponse` |

### What This Refactor Achieves

1. **Cognitive load reduction** — one serialization API, one base class, one set of patterns
2. **Validation for free** — Pydantic validates field types at construction time
3. **Serialization consistency** — `.model_dump()` everywhere eliminates `is_dataclass()` branching in `agent_node.py`
4. **Schema generation** — `.model_json_schema()` available on all types (useful for API docs, tool definitions)
5. **Nested model support** — Pydantic handles nested models natively (e.g., `Subscription.pattern: SubscriptionPattern`)

### What Does NOT Change

- `structured_agents` types remain stdlib dataclasses (external package, out of scope)
- `is_dataclass()` branching in `event_store.py` and `projector.py` stays (handles `structured_agents` events)
- No functional behavior changes — all types keep their existing fields, methods, and semantics

---

## 2. Item 1: ToolSchema

**Location:** `src/remora/core/agent_node.py:34-63`

### Before (stdlib @dataclass)

```python
@dataclass
class ToolSchema:
    """Schema for an agent tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_code_action(self, node_id: str) -> lsp.CodeAction:
        from lsprotocol import types as lsp
        return lsp.CodeAction(
            title=self.description,
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command=f"remora.tool.{self.name}",
                arguments=[node_id],
            ),
        )
```

### After (Pydantic BaseModel)

```python
class ToolSchema(BaseModel):
    """Schema for an agent tool."""

    name: str
    description: str
    parameters: dict  # JSON Schema object

    def to_llm_tool(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_code_action(self, node_id: str) -> lsp.CodeAction:
        from lsprotocol import types as lsp
        return lsp.CodeAction(
            title=self.description,
            kind=lsp.CodeActionKind.Empty,
            command=lsp.Command(
                title=self.name,
                command=f"remora.tool.{self.name}",
                arguments=[node_id],
            ),
        )
```

### Pros

1. **Unified serialization** — `ToolSchema.model_dump()` replaces `asdict(tool)`, aligning with every other Remora type
2. **Eliminates `is_dataclass()` branching** — `AgentNode.to_row()` (line 111) currently does `asdict(t) if is_dataclass(t) else t`; after conversion, it becomes `t.model_dump()`
3. **JSON Schema for free** — `ToolSchema.model_json_schema()` generates a schema that could be used for self-describing tool registries or API documentation
4. **Validation** — Pydantic validates that `parameters` is a `dict` at construction time, catching bad data earlier
5. **Consistent `from_row()` hydration** — `ToolSchema(**t)` already works identically for both dataclasses and Pydantic, so `AgentNode.from_row()` needs no change

### Cons

1. **Marginal performance cost** — Pydantic model construction is ~2-5x slower than dataclass construction; negligible here since `ToolSchema` instances are created infrequently (at agent discovery time, not in hot loops)
2. **Minor import change** — `from pydantic import BaseModel` replaces `from dataclasses import dataclass`

### Implications

1. **`AgentNode.to_row()` simplification** (`agent_node.py:111`):
   - Before: `json.dumps([asdict(t) if is_dataclass(t) else t for t in self.extra_tools])`
   - After: `json.dumps([t.model_dump() for t in self.extra_tools])`
2. **`AgentNode.from_row()` — no change needed** (`agent_node.py:124`): `ToolSchema(**t)` works for both dataclass and Pydantic
3. **`lsp/server.py:76,92`** — construction sites `ToolSchema(name=..., description=..., parameters=...)` — no change needed, keyword construction identical
4. **Re-exports in `core/__init__.py` and `remora/__init__.py`** — `AgentToolSchema` alias continues to work, no change needed

### Possibilities Unlocked

1. **Tool registry validation** — could add `field_validator` for `parameters` to enforce JSON Schema compliance (e.g., must have `"type": "object"`)
2. **Merge with `structured_agents.types.ToolSchema`** — if the external package eventually migrates to Pydantic, the two types could share a base or be unified. For now, they remain separate.
3. **`to_llm_tool()` could return a Pydantic model** instead of a raw dict, enabling typed tool definitions

### Risk Assessment

**Risk: LOW**

- No behavior changes, no serialization format changes
- Construction API is identical (keyword arguments)
- The only branching code change (`to_row()`) is a simplification

### Name Collision Warning

`structured_agents.types.ToolSchema` exists with identical fields but a different method (`to_openai_format()` vs `to_llm_tool()`). The swarm tools (`core/tools/swarm.py`, `core/tools/grail.py`) import the `structured_agents` version. Remora's `ToolSchema` adds `to_code_action()`. These two types are intentionally separate — do NOT attempt to merge them during this refactor.

### Files to Change

| File | Change | Lines |
|------|--------|-------|
| `src/remora/core/agent_node.py` | `@dataclass` -> `BaseModel`, update imports, simplify `to_row()` | 34-63, 111-114 |
| `src/remora/core/agent_node.py` | Remove `from dataclasses import asdict, is_dataclass, dataclass` (if no other usages remain) | top imports |
| `tests/unit/test_lsp_server.py:32` | Update `assert dataclasses.is_dataclass(CoreToolSchema)` to test Pydantic instead | 32 |
| `tests/unit/test_agent_node.py` | Verify existing tests pass (keyword construction unchanged) | - |
| `tests/unit/test_lsp_models.py` | Verify existing tests pass | - |

### Tests to Update

- `test_lsp_server.py:32` — currently asserts `dataclasses.is_dataclass(CoreToolSchema)`. Must change to assert `issubclass(CoreToolSchema, BaseModel)` or equivalent.
- All other tests use keyword construction (`ToolSchema(name=..., ...)`) which works identically — no changes needed.
- **29 total test references** — overwhelmingly just construction; only the one `is_dataclass` assertion needs updating.

---

## 3. Item 2: SubscriptionPattern / Subscription

**Location:** `src/remora/core/subscriptions.py:26-86`

### Before (stdlib @dataclass)

```python
@dataclass
class SubscriptionPattern:
    """Pattern for matching events."""

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: RemoraEvent) -> bool:
        # ... pattern matching logic ...

@dataclass
class Subscription:
    """A registered subscription."""

    id: int
    agent_id: str
    pattern: SubscriptionPattern
    is_default: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
```

### After (Pydantic BaseModel)

```python
class SubscriptionPattern(BaseModel):
    """Pattern for matching events."""

    event_types: list[str] | None = None
    from_agents: list[str] | None = None
    to_agent: str | None = None
    path_glob: str | None = None
    tags: list[str] | None = None

    def matches(self, event: RemoraEvent) -> bool:
        # ... pattern matching logic unchanged ...

class Subscription(BaseModel):
    """A registered subscription."""

    id: int
    agent_id: str
    pattern: SubscriptionPattern
    is_default: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
```

### Pros

1. **Nested model hydration** — Pydantic natively deserializes `{"pattern": {...}}` into `Subscription(pattern=SubscriptionPattern(...))` without manual unpacking
2. **Eliminates `asdict(pattern)` in `SubscriptionRegistry.register()`** (`subscriptions.py:178`):
   - Before: `json.dumps(asdict(pattern))`
   - After: `json.dumps(pattern.model_dump())`
3. **Eliminates `is_dataclass()` branching in `AgentNode.to_row()`** (`agent_node.py:112-114`):
   - Before: `json.dumps([asdict(s) if is_dataclass(s) else s for s in self.extra_subscriptions])`
   - After: `json.dumps([s.model_dump() for s in self.extra_subscriptions])`
4. **Validation on list fields** — Pydantic validates that `event_types`, `from_agents`, and `tags` are actually `list[str]` (or `None`), catching type errors at construction
5. **Schema introspection** — `SubscriptionPattern.model_json_schema()` could power a subscription builder UI

### Cons

1. **`field(default_factory=...)` becomes `Field(default_factory=...)`** — minor syntax change in `Subscription`
2. **`time.time` as default factory** — works identically in both systems, but worth noting that Pydantic's `Field(default_factory=time.time)` behaves the same as `dataclasses.field(default_factory=time.time)`
3. **56 test references** — more test sites to verify than ToolSchema, though almost all use keyword construction

### Implications

1. **`SubscriptionRegistry.register()` simplification** (`subscriptions.py:178`):
   - Before: `pattern_json = json.dumps(asdict(pattern))`
   - After: `pattern_json = json.dumps(pattern.model_dump())`
   - Alternatively: `pattern_json = pattern.model_dump_json()` (returns a JSON string directly, avoids double-serialization)
2. **`SubscriptionRegistry._load_subscriptions()` hydration** — wherever `SubscriptionPattern(**pattern_data)` is called, it continues to work identically with Pydantic
3. **`AgentNode.to_row()` and `from_row()`** — same simplification as ToolSchema (Item 1). Combined with Item 1, this fully eliminates the `is_dataclass()` branching in `to_row()`.
4. **`core/tools/swarm.py:132` — `SubscribeTool`** — creates `SubscriptionPattern(...)` from tool arguments; keyword construction unchanged
5. **Re-exports** — `core/__init__.py` and `remora/__init__.py` re-export both types; no change needed

### Possibilities Unlocked

1. **`model_dump_json()` for DB storage** — eliminates the `json.dumps(pattern.model_dump())` double-call; `pattern.model_dump_json()` is faster and produces identical output
2. **Subscription validation** — could add `model_validator` to ensure at least one filter field is non-None (prevent "match everything" patterns)
3. **Immutable subscriptions** — could add `model_config = ConfigDict(frozen=True)` if immutability is desired (currently mutable)

### Risk Assessment

**Risk: LOW**

- No behavior changes to `matches()` logic
- All construction sites use keyword arguments
- Serialization output is identical (`model_dump()` produces the same dict as `asdict()`)
- Hydration via `SubscriptionPattern(**data)` works identically

### Files to Change

| File | Change | Lines |
|------|--------|-------|
| `src/remora/core/subscriptions.py` | `@dataclass` -> `BaseModel` for both types, `field()` -> `Field()`, update imports | 26-86 |
| `src/remora/core/subscriptions.py` | `asdict(pattern)` -> `pattern.model_dump()` in `register()` | 178 |
| `src/remora/core/subscriptions.py` | Remove `from dataclasses import dataclass, field, asdict` | top imports |
| `src/remora/core/agent_node.py` | Simplify `to_row()` for `extra_subscriptions` (combined with Item 1) | 112-114 |

### Tests to Update

- **56 test references** across 9 test files — all use keyword construction, no `is_dataclass` assertions found
- `test_subscriptions.py` — primary test file; verify `matches()`, `register()`, `register_defaults()`
- `test_swarm_store.py`, `test_agent_node.py`, `test_agent_runner.py` — verify `SubscriptionPattern` construction
- No test assertions depend on stdlib dataclass identity — clean conversion

---

## 4. Item 3: CSTNode

**Location:** `src/remora/core/discovery.py:44-65`

### Before (stdlib @dataclass, frozen)

```python
@dataclass(frozen=True, slots=True)
class CSTNode:
    """A concrete syntax tree node discovered from source code."""

    node_id: str
    node_type: str  # "function", "class", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    def __hash__(self) -> int:
        return hash(self.node_id)
```

### After (Pydantic BaseModel, frozen)

```python
class CSTNode(BaseModel):
    """A concrete syntax tree node discovered from source code."""

    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str  # "function", "class", "file", "section", "table"
    name: str
    full_name: str
    file_path: str
    text: str
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    def __hash__(self) -> int:
        return hash(self.node_id)
```

### Pros

1. **Consistent with event models** — all other frozen Remora types (`_FrozenEvent` hierarchy) use `ConfigDict(frozen=True)`, so this follows the established pattern
2. **Validation** — Pydantic validates field types at construction (e.g., ensures `start_line` is actually an `int`)
3. **Model uniformity** — developers don't need to remember "CSTNode is a frozen dataclass but events are frozen Pydantic"

### Cons

1. **`__hash__` behavior requires explicit override** — Pydantic's `frozen=True` provides `__hash__` based on ALL fields. The current stdlib implementation uses custom `__hash__` returning `hash(self.node_id)` only. **We must keep the explicit `__hash__` override** to preserve the behavior where two CSTNode instances with the same `node_id` but different `text` (e.g., after a content change) hash identically. This is by design — `node_id` is the identity.

2. **`slots=True` not available in Pydantic** — stdlib dataclass `slots=True` enables `__slots__` for memory efficiency. Pydantic models use `__dict__` by default. For CSTNode instances (which can be numerous in large workspaces), this means slightly higher memory per instance. However, CSTNode instances are short-lived (created during discovery, consumed by reconciler, then discarded) — the memory impact is negligible.

3. **Performance at scale** — Pydantic construction is slower than dataclass construction. The `_parse_file()` function creates many CSTNode instances during discovery. In benchmarks, the difference should be measured — but since discovery is I/O-bound (reading files + tree-sitter parsing), construction overhead is likely negligible.

4. **Equality semantics change** — stdlib frozen dataclass `__eq__` compares all fields. Pydantic frozen model `__eq__` also compares all fields. No change here. However, since `__hash__` only uses `node_id`, two CSTNodes with same `node_id` but different `text` are `hash`-equal but `__eq__`-unequal. This is existing behavior and doesn't change.

### Implications

1. **`discovery.py` import changes** — remove `from dataclasses import dataclass`, add `from pydantic import BaseModel, ConfigDict`
2. **`reconciler.py`** — reads CSTNode attributes (`.text`, `.node_id`, `.file_path`, etc.) — no change needed, attribute access identical
3. **`swarm_executor.py:39-52`** — `_agent_node_to_cst_node()` constructs `CSTNode(...)` with keyword args — no change needed
4. **`core/workspace.py:121`** — `load_files(node: CSTNode, ...)` parameter type annotation — no change needed
5. **`projections.py:27-31`** — `_dataclass_default()` fallback — after this conversion, CSTNode instances (if they ever appear in extension data, which is unlikely) would need `model_dump()` instead of `asdict()`. See Section 7 for full analysis.

### Possibilities Unlocked

1. **Field validators** — could add `field_validator('node_type')` to enforce valid node types (`"function"`, `"class"`, `"file"`, `"section"`, `"table"`)
2. **Computed properties** — `@computed_field` could expose derived properties (e.g., `line_count = end_line - start_line + 1`)
3. **Serialization control** — `model_dump(exclude={'text'})` for lightweight node listings without source text (currently done manually in `list_nodes()` queries)

### Risk Assessment

**Risk: MEDIUM-LOW**

The main risk is the `__hash__` behavior. As long as the explicit `__hash__` override is preserved (which it must be), the behavior is identical. The risk is that a future developer removes the `__hash__` override thinking "Pydantic frozen models already provide `__hash__`" — not realizing the CSTNode hash is intentionally `node_id`-only.

**Mitigation:** Add a clear docstring comment on `__hash__`:

```python
def __hash__(self) -> int:
    """Hash by node_id only — two nodes with same ID are identity-equal
    regardless of content changes. Do NOT remove this override."""
    return hash(self.node_id)
```

### Files to Change

| File | Change | Lines |
|------|--------|-------|
| `src/remora/core/discovery.py` | `@dataclass(frozen=True, slots=True)` -> `BaseModel` + `ConfigDict(frozen=True)`, update imports | 44-65 |
| `src/remora/core/discovery.py` | Keep `__hash__` override, add docstring explaining why | 63-64 |
| `src/remora/core/discovery.py` | Remove `from dataclasses import dataclass` | top imports |

### Tests to Update

- **20 test references** across 5 test files — all use keyword construction
- `test_discovery.py` — primary test file; verify node creation, immutability, hashing
- `test_identity_unification.py`, `test_swarm_executor.py` — verify CSTNode construction in integration paths
- **Add a new test** to verify `__hash__` uses `node_id` only (guards against future regression if override is accidentally removed):
  ```python
  def test_cstnode_hash_uses_node_id_only():
      a = CSTNode(node_id="abc", ..., text="v1")
      b = CSTNode(node_id="abc", ..., text="v2")
      assert hash(a) == hash(b)
  ```

---

## 5. Item 4: ToolCall / LLMResponse

**Location:** `src/remora/lsp/runner.py:40-54`

### Before (stdlib @dataclass)

```python
@dataclass
class ToolCall:
    """Normalized tool call that handle_response expects."""

    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    """Normalized response from the LLM."""

    content: str | None
    tool_calls: list[ToolCall]
```

### After (Pydantic BaseModel)

```python
class ToolCall(BaseModel):
    """Normalized tool call that handle_response expects."""

    name: str
    arguments: dict[str, Any]
    id: str = ""


class LLMResponse(BaseModel):
    """Normalized response from the LLM."""

    content: str | None
    tool_calls: list[ToolCall]
```

### Pros

1. **Consistency** — eliminates the last `@dataclass` import in `lsp/runner.py`
2. **Nested model support** — `LLMResponse.tool_calls: list[ToolCall]` gets automatic nested validation
3. **Mental model** — developers working in `runner.py` don't need to switch between Pydantic (for events) and dataclass (for these types)

### Cons

1. **Lowest impact conversion** — these types are runner-internal, never serialized, never exported. The practical benefit is purely conceptual consistency.
2. **Performance in hot loop** — `ToolCall` and `LLMResponse` are created on every LLM response in the tool loop. Pydantic construction is ~2-5x slower than dataclass construction. In practice, the overhead is negligible compared to the LLM API call latency (seconds vs microseconds), but it's worth noting.

### Implications

1. **Entirely contained within `lsp/runner.py`** — no other file imports these types
2. **`_extract_text_tool_calls()`** — constructs `ToolCall(name=..., arguments=..., id=...)` — no change needed
3. **`LLMClient.chat()`** — returns `LLMResponse(content=..., tool_calls=[...])` — no change needed
4. **`AgentRunner.handle_response()`** — receives `LLMResponse`, accesses `.content` and `.tool_calls` — no change needed
5. **Test fakes** — `FakeToolCall` and `FakeToolCallFunction` in `src/remora/testing/fakes.py` are separate parallel types used by test mocks; they do NOT need to change (they simulate the `structured_agents` tool call format, not Remora's `ToolCall`)

### Possibilities Unlocked

1. **Frozen responses** — could make `LLMResponse` frozen to prevent accidental mutation during the tool loop
2. **Validation** — could add `field_validator('name')` on `ToolCall` to reject empty tool names early

### Risk Assessment

**Risk: VERY LOW**

- Entirely internal to one file
- No serialization, no export, no external consumers
- Construction API identical
- No tests directly reference these types (tests use mock/fake infrastructure)

### Name Collision Warning

`structured_agents.types.ToolCall` is a different type used by `core/tools/swarm.py` and `core/tools/grail.py`. Remora's `ToolCall` (in `lsp/runner.py`) is runner-internal and never leaks outside the module. There is no risk of confusion at runtime, but developers should be aware of the naming overlap when reading code.

### Files to Change

| File | Change | Lines |
|------|--------|-------|
| `src/remora/lsp/runner.py` | `@dataclass` -> `BaseModel` for both types, update imports | 40-54 |
| `src/remora/lsp/runner.py` | Remove `from dataclasses import dataclass` (if no other usages) | top imports |

### Tests to Update

- **No direct test references** to `ToolCall` or `LLMResponse` — these are internal types
- Test fakes (`FakeToolCall`, `FakeToolCallFunction`) are independent and don't change
- Existing runner tests exercise these types indirectly through the tool loop — they should pass without modification

---

## 6. Item 5: Message / ChatConfig / AgentResponse

**Location:** `src/remora/core/chat.py:20-90`

### Before (stdlib @dataclass)

```python
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
    model_api_key: str = ""
    max_turns: int = 10

    @classmethod
    def from_config(cls, config: Config, *, workspace_path: str,
                    system_prompt: str, tool_presets: list[str] | None = None,
                    max_turns: int = 10) -> "ChatConfig":
        return cls(
            workspace_path=workspace_path,
            system_prompt=system_prompt,
            tool_presets=tool_presets or ["file_ops"],
            model_name=config.model_default,
            model_base_url=config.model_base_url,
            model_api_key=config.model_api_key,
            max_turns=max_turns,
        )


@dataclass
class AgentResponse:
    """Response from the agent."""

    message: Message
    turn_count: int
```

### After (Pydantic BaseModel)

```python
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
    def from_config(cls, config: Config, *, workspace_path: str,
                    system_prompt: str, tool_presets: list[str] | None = None,
                    max_turns: int = 10) -> "ChatConfig":
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
```

### Pros

1. **API response serialization** — `chat_service.py` currently manually constructs dicts from Message fields (lines 113-119, 140-146). With Pydantic, could use `response.message.model_dump()` or `message.model_dump()` for cleaner code.
2. **Nested model serialization** — `AgentResponse.model_dump()` automatically serializes the nested `Message` — no manual dict construction needed.
3. **`@classmethod` factories work identically** — `Message.user()` and `Message.assistant()` use `cls(...)` which works for both dataclass and Pydantic.
4. **Validation** — `ChatConfig` fields like `max_turns` get type validation at construction (e.g., passing a string would raise immediately instead of silently succeeding).
5. **Dead import cleanup** — `chat_service.py:5` has `from dataclasses import asdict` which is never used. After this conversion, the entire `dataclasses` import in `chat.py` is removed.

### Cons

1. **`field(default_factory=...)` becomes `Field(default_factory=...)`** — syntactic change in `Message.tool_calls` and `ChatConfig.tool_presets`
2. **`ChatConfig` is config-like but NOT settings** — unlike `RemoraConfig` (which uses `BaseSettings` for env var support), `ChatConfig` is a plain value object. Using `BaseModel` (not `BaseSettings`) is correct here.
3. **Manual dict construction in `chat_service.py` is intentional** — the service deliberately constructs specific dict shapes for the API response. While `message.model_dump()` is now possible, the current manual approach gives fine-grained control. Converting to `model_dump()` is optional (see Possibilities).

### Implications

1. **`chat.py` import changes** — remove `from dataclasses import dataclass, field`, add `from pydantic import BaseModel, Field`
2. **`chat_service.py:5`** — remove dead `from dataclasses import asdict` import
3. **`service/chat_service.py:15`** — imports `ChatSession, ChatConfig, Message` — no change needed
4. **`ChatSession` class** — uses `Message`, `ChatConfig`, `AgentResponse` internally. Accesses fields via attribute access (`.id`, `.role`, `.content`, etc.) — no change needed.
5. **`ChatConfig.from_config()`** — `@classmethod` factory calling `cls(...)` — works identically with Pydantic

### Possibilities Unlocked

1. **API response simplification** — `chat_service.py` could replace manual dict construction:
   ```python
   # Before (manual):
   {"id": m.id, "role": m.role, "content": m.content, ...}
   # After (Pydantic):
   m.model_dump()
   ```
   This is optional — the manual approach is fine if the API shape should differ from the model shape.

2. **`role` field as Literal** — could change `role: str` to `role: Literal["user", "assistant"]` for stricter typing and validation

3. **`ChatConfig` validation** — could add validators for `model_base_url` (must be a URL), `max_turns` (must be positive), etc.

4. **Immutable messages** — could make `Message` frozen to prevent accidental mutation after creation (messages are conceptually immutable)

### Risk Assessment

**Risk: LOW**

- All three types are straightforward value objects with no complex behavior
- Construction API identical (keyword arguments, `@classmethod` factories)
- No serialization format changes (types are not currently serialized via `asdict()` — `chat_service.py` builds dicts manually)
- 6 test references, all using keyword construction

### Dead Import Cleanup

`chat_service.py:5` — `from dataclasses import asdict` is imported but never used. This should be removed during the conversion (or even before — it's dead code now).

### Files to Change

| File | Change | Lines |
|------|--------|-------|
| `src/remora/core/chat.py` | `@dataclass` -> `BaseModel` for all 3 types, `field()` -> `Field()`, update imports | 20-90 |
| `src/remora/core/chat.py` | Remove `from dataclasses import dataclass, field` | top imports |
| `src/remora/service/chat_service.py` | Remove dead `from dataclasses import asdict` (line 5) | 5 |

### Tests to Update

- **6 test references** in `test_chat_session.py` and `test_llm_config.py`
- All use keyword construction or `@classmethod` factories — no changes needed
- No `is_dataclass` assertions or `asdict()` calls in tests

---

## 7. Serialization Simplification Analysis

This section analyzes the four sites in the codebase that use `is_dataclass()` / `asdict()` branching, and what happens to each after converting all 5 items.

### Site 1: `agent_node.py:111-114` — `AgentNode.to_row()`

**Current code:**
```python
data["extra_tools"] = json.dumps([asdict(t) if is_dataclass(t) else t for t in self.extra_tools])
data["extra_subscriptions"] = json.dumps(
    [asdict(s) if is_dataclass(s) else s for s in self.extra_subscriptions]
)
```

**After converting Items 1 + 2 (ToolSchema + SubscriptionPattern):**
```python
data["extra_tools"] = json.dumps([t.model_dump() for t in self.extra_tools])
data["extra_subscriptions"] = json.dumps([s.model_dump() for s in self.extra_subscriptions])
```

**Status: FULLY ELIMINATED.** The `is_dataclass()` branching exists solely because `ToolSchema` and `SubscriptionPattern` are dataclasses while `AgentNode` is Pydantic. After conversion, all types are Pydantic and the branch is unnecessary.

**Also removes:** `from dataclasses import asdict, is_dataclass` import from `agent_node.py` (verify no other usages remain in the file first).

---

### Site 2: `event_store.py:665-677` — `_serialize_event()`

**Current code:**
```python
def _serialize_event(self, event: StructuredEvent | RemoraEvent) -> str:
    if hasattr(event, "model_dump"):
        data = event.model_dump()
    elif is_dataclass(event):
        data = asdict(event)
    elif hasattr(event, "__dict__"):
        data = dict(vars(event))
    else:
        data = {"value": str(event)}
    return json.dumps(data, default=str)
```

**After converting all 5 items:**

The `is_dataclass` branch is **still needed**. `StructuredEvent` types from the `structured_agents` package are stdlib dataclasses (e.g., `KernelStartEvent`, `KernelEndEvent`, `ModelRequestEvent`, etc.). These are from an external dependency and will not be converted.

**Status: CANNOT ELIMINATE.** The branching order is correct:
1. Check `model_dump` first (all Remora events hit this)
2. Fall back to `is_dataclass` for `structured_agents` events
3. Fall back to `__dict__` for anything else

No change needed.

---

### Site 3: `projections.py:27-31` — `_dataclass_default()`

**Current code:**
```python
def _dataclass_default(obj: Any) -> Any:
    """JSON serialization fallback for dataclass instances."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
```

**Context:** This function is used as a `json.dumps(default=...)` callback when serializing extension data (`get_extension_data()` dicts). Extension data is user-defined and might contain arbitrary types — this fallback catches any stray dataclass instances.

**After converting all 5 items:**

Extension data could still contain `structured_agents` dataclass types or user-defined dataclasses from extension configs. The fallback remains useful as a safety net.

**Improvement opportunity:** Add a `model_dump` check before the `is_dataclass` check:

```python
def _dataclass_default(obj: Any) -> Any:
    """JSON serialization fallback for model/dataclass instances."""
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")
```

**Status: SIMPLIFY BUT KEEP.** The `is_dataclass` branch stays for external types. Adding the `model_dump` check improves robustness.

---

### Site 4: `ui/projector.py:94-101` — `_event_payload()`

**Current code:**
```python
def _event_payload(event: StructuredEvent | RemoraEvent) -> dict[str, Any]:
    if is_dataclass(event):
        payload: dict[str, Any] = asdict(event)
    elif hasattr(event, "__dict__"):
        payload = dict(vars(event))
    else:
        payload = {"value": str(event)}
    return _to_jsonable(payload)
```

**After converting all 5 items:**

Same situation as `_serialize_event()` — `StructuredEvent` types from `structured_agents` are stdlib dataclasses. The `is_dataclass` branch is still needed for those.

**Improvement opportunity:** Add a `model_dump` check first (Remora events are Pydantic):

```python
def _event_payload(event: StructuredEvent | RemoraEvent) -> dict[str, Any]:
    if hasattr(event, "model_dump"):
        payload: dict[str, Any] = event.model_dump()
    elif is_dataclass(event):
        payload = asdict(event)
    elif hasattr(event, "__dict__"):
        payload = dict(vars(event))
    else:
        payload = {"value": str(event)}
    return _to_jsonable(payload)
```

**Status: SIMPLIFY BUT KEEP.** Adding the `model_dump` path improves consistency. The `is_dataclass` branch stays for `structured_agents` events.

---

### Summary Table

| Site | File | Can eliminate `is_dataclass`? | Action |
|------|------|------------------------------|--------|
| 1 | `agent_node.py:111-114` | **YES** | Remove branching entirely, use `model_dump()` |
| 2 | `event_store.py:665-677` | No | Keep as-is (handles `structured_agents` events) |
| 3 | `projections.py:27-31` | No | Add `model_dump` check before `is_dataclass` |
| 4 | `ui/projector.py:94-101` | No | Add `model_dump` check before `is_dataclass` |

### Net Result

- **1 out of 4 branching sites fully eliminated** (the most visible one — `AgentNode.to_row()`)
- **2 sites improved** with `model_dump` as the first check (Sites 3, 4)
- **1 site unchanged** (Site 2 — already has `model_dump` as first check)
- **All `from dataclasses import asdict, is_dataclass` can be removed from `agent_node.py`**
- `event_store.py`, `projections.py`, and `ui/projector.py` still need `is_dataclass`/`asdict` imports for `structured_agents` compatibility

---

## 8. Implementation Order

### Dependency Graph

```
Item 1 (ToolSchema) ──┐
                       ├──> agent_node.py to_row() simplification (requires both)
Item 2 (Subscriptions) ┘
                            │
Item 3 (CSTNode) ──────────── independent
Item 4 (ToolCall/LLMResponse) ── independent
Item 5 (Chat types) ──────── independent
```

Items 1 and 2 share a downstream dependency: the `AgentNode.to_row()` branching can only be fully eliminated after **both** are converted. Items 3, 4, and 5 are fully independent of each other and of Items 1-2.

### Recommended Order

| Step | Item | Rationale |
|------|------|-----------|
| **Step 1** | **Item 1: ToolSchema** | Smallest scope, highest visibility. Converts the type most referenced in the LSP layer. Partially simplifies `to_row()`. |
| **Step 2** | **Item 2: SubscriptionPattern / Subscription** | Second dependency for `to_row()` simplification. After this step, `to_row()` is fully cleaned up and `asdict`/`is_dataclass` can be removed from `agent_node.py`. |
| **Step 3** | **Item 4: ToolCall / LLMResponse** | Lowest risk (internal to one file, no tests to update). Quick win that clears `@dataclass` from `lsp/runner.py`. |
| **Step 4** | **Item 5: Message / ChatConfig / AgentResponse** | Clears `@dataclass` from `core/chat.py` and removes the dead import in `chat_service.py`. |
| **Step 5** | **Item 3: CSTNode** | Saved for last because it has the highest risk (frozen + custom `__hash__`). By this point, confidence in the conversion pattern is high. |
| **Step 6** | **Serialization cleanup** | After all items are converted: improve `projections.py` and `ui/projector.py` with `model_dump` as first check. |

### Alternative: Single Commit

All 5 items could be done in a single commit since they don't conflict. However, the step-by-step approach is recommended because:
1. Each step is independently testable
2. If a regression appears, `git bisect` isolates the exact conversion
3. The CSTNode `__hash__` risk is contained to its own commit

### TDD Per Step

Each step follows the standard TDD flow:
1. **Write a failing test** that exercises the Pydantic API (e.g., `isinstance(obj, BaseModel)`, `obj.model_dump()`)
2. **Convert the type** from `@dataclass` to `BaseModel`
3. **Run the full test suite** to verify no regressions
4. **Commit**

---

## 9. Estimated Scope

### Per-Item Breakdown

| Item | Production files | LOC changed (est.) | Tests affected | New tests | Risk | Effort |
|------|-----------------|-------------------|----------------|-----------|------|--------|
| 1. ToolSchema | 1 file (`agent_node.py`) | ~15 | 1 assertion update | 1-2 | Low | 15 min |
| 2. SubscriptionPattern/Subscription | 2 files (`subscriptions.py`, `agent_node.py`) | ~20 | 0 assertion updates | 1-2 | Low | 20 min |
| 3. CSTNode | 1 file (`discovery.py`) | ~10 | 0 assertion updates | 1 (hash regression test) | Medium-Low | 20 min |
| 4. ToolCall/LLMResponse | 1 file (`runner.py`) | ~8 | 0 | 0 | Very Low | 10 min |
| 5. Message/ChatConfig/AgentResponse | 2 files (`chat.py`, `chat_service.py`) | ~15 | 0 | 1-2 | Low | 15 min |
| 6. Serialization cleanup | 2 files (`projections.py`, `ui/projector.py`) | ~10 | 0 | 0 | Low | 10 min |
| **Total** | **~7 files** | **~78 LOC** | **1 assertion** | **4-7 new tests** | | **~90 min** |

### LOC Breakdown Detail

**Lines removed** (estimated):
- `from dataclasses import dataclass, field, asdict, is_dataclass` — ~5 import lines across 4 files
- `@dataclass` / `@dataclass(frozen=True, slots=True)` decorators — 5 lines
- `asdict(t) if is_dataclass(t) else t` branching in `to_row()` — 3 lines
- Dead `from dataclasses import asdict` in `chat_service.py` — 1 line

**Lines added** (estimated):
- `from pydantic import BaseModel, Field, ConfigDict` — ~4 import lines across 4 files
- `model_config = ConfigDict(frozen=True)` in CSTNode — 1 line
- `model_dump` checks in `projections.py` and `ui/projector.py` — 4 lines
- New TDD tests — ~30-50 lines

**Net change:** ~+20 lines (mostly tests), ~-14 lines (removed branching/imports). Very close to LOC-neutral in production code.

### Test Impact Summary

| Test file | References | Changes needed |
|-----------|-----------|----------------|
| `test_lsp_server.py` | 1 | Update `is_dataclass` assertion to `issubclass(_, BaseModel)` |
| `test_agent_node.py` | ~10 | Verify pass (no changes expected) |
| `test_subscriptions.py` | ~15 | Verify pass (no changes expected) |
| `test_discovery.py` | ~8 | Verify pass (no changes expected) |
| `test_runner_loop.py` | ~5 | Verify pass (no changes expected) |
| `test_chat_session.py` | ~4 | Verify pass (no changes expected) |
| `test_lsp_models.py` | ~5 | Verify pass (no changes expected) |
| `test_phase1_gaps.py` | ~8 | Verify pass (no changes expected) |
| Various integration tests | ~20 | Verify pass (no changes expected) |

**Total existing tests to verify:** ~111 references across ~15 test files
**Tests requiring code changes:** 1 (the `is_dataclass` assertion)
**New tests to write:** 4-7 (TDD tests for each conversion + CSTNode hash regression)

### What Success Looks Like

After all 6 steps:

1. **Zero `@dataclass` imports in Remora source** (excluding `ui/projector.py` which uses it for `UiStateProjector` — a separate concern)
2. **Zero `asdict()` calls in Remora source** for Remora types (only remaining calls are for `structured_agents` types)
3. **One rule:** every Remora value type is `BaseModel`. Serialize with `.model_dump()`. Done.
4. **653+ tests passing**, 2 xfailed, 0 failures
5. **~78 LOC changed**, ~7 production files touched — minimal blast radius

---

*Document generated from analysis of the Remora codebase post-launch-plan (all 75+ items complete, 653 passed, 2 xfailed). This is a planning document — no code changes have been made.*

---

## Appendix A: Data Flow Walkthrough (Before/After)

This appendix traces data through the full Remora system — from source file on disk through the core library, into the LSP server, out to Neovim, through the web service layer, and into the Graph Web UI frontend. Each scenario shows every type boundary crossing and exactly where `@dataclass` / `asdict()` / `is_dataclass()` currently appears vs. what changes after the Pydantic consolidation.

### Appendix Contents

- **A.1 — Discovery → Storage → LSP Display (Neovim Path)**
  The core read path. A Python file is opened in Neovim, tree-sitter parses it into `CSTNode` dataclasses, those become `NodeDiscoveredEvent` Pydantic models, get serialized into SQLite via EventStore, get hydrated back as `AgentNode` Pydantic models, and then rendered as LSP CodeLens/Hover responses that Neovim displays. Shows the `CSTNode` dataclass-to-Pydantic conversion point.

- **A.2 — Event → Subscription → Trigger → LLM → Proposal (Reactive Path)**
  The core write path. A `ContentChangedEvent` arrives, the `SubscriptionRegistry` matches it against `SubscriptionPattern` dataclasses, the matched agent is triggered via `AgentRunner`, the LLM returns tool calls as `ToolCall` dataclasses, the runner executes them in a loop, and eventually a `RewriteProposal` Pydantic model is created and sent to Neovim as a diagnostic/code action. Shows `SubscriptionPattern`, `Subscription`, `ToolCall`, and `LLMResponse` dataclass-to-Pydantic conversion points.

- **A.3 — Chat Service → Message → AgentResponse (HTTP API Path)**
  The standalone demo path. An HTTP POST arrives at the Starlette chat service, gets deserialized into a `ChatConfig` dataclass, creates a `ChatSession` with `Message` dataclasses, the LLM responds, and the result is manually serialized as JSON via `__dict__` access. Shows `Message`, `ChatConfig`, `AgentResponse` dataclass-to-Pydantic conversion points.

- **A.4 — Events → UiStateProjector → Graph Web UI (Frontend Path)**
  The visualization path. Events flow through the `EventBus`, the `UiStateProjector` dataclass reduces them into a snapshot dict (using `is_dataclass` / `asdict` branching in `_event_payload` and `_to_jsonable`), the service layer renders this as Datastar HTML patches via SSE, OR the graph web UI's `DBBridge` polls the shared SQLite DB directly, reads `GraphSnapshot` dataclasses, runs force-directed layout, and renders SVG via Stario's `w.patch()`. Shows the dual rendering pipeline and all serialization boundaries.

---

### A.1 — Discovery → Storage → LSP Display (Neovim Path)

**Trigger:** User opens a Python file in Neovim. The `.nvim.lua` project config has already started the Remora LSP server via `python -m remora_demo`.

#### The Full Pipeline

```
 Neovim                Remora LSP                    Remora Core
┌──────┐  didOpen    ┌───────────┐  parse         ┌──────────────┐
│ .py  │────────────>│ documents │───────────────>│  discovery   │
│ file │  (LSP msg)  │ handler   │  tree-sitter   │  _parse_file │
└──────┘             └─────┬─────┘                └──────┬───────┘
                           │                             │
                           │  list[dict]                 │ list[CSTNode]
                           │  (watcher output)           │ (@dataclass)
                           │                             │
                     ┌─────▼─────┐                       │
                     │  watcher  │<──────────────────────┘
                     │  parse_   │  (watcher wraps discovery
                     │  inject   │   and adds node IDs)
                     └─────┬─────┘
                           │
                           │  for each node dict:
                           │
                     ┌─────▼──────────────┐
                     │ NodeDiscoveredEvent │  (Pydantic frozen BaseModel)
                     │ event_store.append  │
                     └─────┬──────────────┘
                           │
                           │  _serialize_event → model_dump()
                           │  NodeProjection.project → SQL upsert
                           │
                     ┌─────▼──────────┐
                     │    SQLite DB   │  (nodes table: flat columns)
                     │  .remora/      │
                     │  indexer.db    │
                     └─────┬──────────┘
                           │
                           │  codeLens request
                           │
                     ┌─────▼──────────┐
                     │  list_nodes()  │  → SQL SELECT
                     │  from_row()    │  → AgentNode (Pydantic BaseModel)
                     └─────┬──────────┘
                           │
                           │  agent.to_code_lens()
                           │  agent.to_hover(events)
                           │  agent.to_document_symbol()
                           │
                     ┌─────▼──────────┐
                     │  lsp.CodeLens  │  → JSON-RPC response → Neovim
                     │  lsp.Hover     │
                     └────────────────┘
```

#### Step-by-Step with Types

**Step 1: Neovim sends `textDocument/didOpen`**

Neovim's built-in LSP client sends a JSON-RPC message containing the file URI and full text content. The pygls framework deserializes this into `lsp.DidOpenTextDocumentParams`.

- **Data type at boundary:** `lsp.DidOpenTextDocumentParams` (pygls/lsprotocol — not ours)
- **File:** `lsp/handlers/documents.py:14`

**Step 2: Watcher parses the file via tree-sitter**

The `did_open` handler calls `server.watcher.parse_and_inject_ids(uri, text, old_dicts)`. Internally, the watcher calls `discovery.discover(text)` which calls `_parse_file()` using tree-sitter.

- **BEFORE (current):** `_parse_file()` returns `list[CSTNode]` where `CSTNode` is a **stdlib `@dataclass(frozen=True)`** with fields: `node_type`, `name`, `full_name`, `start_line`, `end_line`, `start_byte`, `end_byte`, `source_code`, `source_hash`, `children`
- **Key point:** `CSTNode` instances never leave the `discovery.py` → `watcher.py` boundary. The watcher immediately converts them to plain dicts with `node_id` injected.
- **File:** `core/discovery.py:18-30` (CSTNode definition), `core/discovery.py:56` (`_parse_file` return)

**Step 3: NodeDiscoveredEvent created and appended to EventStore**

The handler iterates over the watcher's output dicts and creates a `NodeDiscoveredEvent` for each:

```python
event = NodeDiscoveredEvent(
    node_id=nd["node_id"],
    node_type=nd["node_type"],
    name=nd["name"],
    ...
)
await server.event_store.append("nodes", event)
```

- **Data type:** `NodeDiscoveredEvent` — **Pydantic frozen BaseModel** (already converted in Batch 6.1)
- **Serialization:** `EventStore.append()` → `_serialize_event()` calls `event.model_dump()` (Pydantic path)
- **File:** `lsp/handlers/documents.py:34-48`, `core/event_store.py` (`_serialize_event`)

**Step 4: NodeProjection writes to SQLite**

The `EventStore.append()` method also runs the `NodeProjection.project()` callback, which upserts the node data into the `nodes` table as flat SQL columns:

```sql
INSERT OR REPLACE INTO nodes (node_id, node_type, name, full_name, file_path,
    start_line, end_line, source_code, source_hash, parent_id, status)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
```

- **Data type at boundary:** plain dict from `model_dump()` → SQL bind parameters
- **No `asdict()` involved** — the event is Pydantic, so `model_dump()` is used
- **File:** `core/projections.py` (NodeProjection), `core/event_store.py`

**Step 5: CodeLens request → `list_nodes()` → `AgentNode.from_row()`**

When Neovim requests code lenses, the handler calls `event_store.list_nodes(file_path=uri)`:

```python
agents = await server.event_store.list_nodes(file_path=uri)
return [agent.to_code_lens() for agent in agents]
```

- `list_nodes()` runs a SQL SELECT and calls `AgentNode.from_row(row)` for each result
- **Data type:** `AgentNode` — **Pydantic BaseModel** with nested `ToolSchema` (**stdlib `@dataclass`**)
- **Key point:** `from_row()` hydrates `extra_tools` by deserializing JSON into `ToolSchema` dataclass instances. This is the `ToolSchema` conversion site from Section 3.1.
- **File:** `lsp/handlers/lens.py:9-16`, `core/agent_node.py` (`from_row`)

**Step 6: AgentNode renders LSP response objects**

`AgentNode.to_code_lens()` creates `lsp.CodeLens` with the agent name as the lens title. `to_hover()` creates `lsp.Hover` with a markdown string. `to_document_symbol()` creates `lsp.DocumentSymbol`.

- **Data type at boundary:** `lsp.CodeLens`, `lsp.Hover`, `lsp.DocumentSymbol` — pygls types, serialized to JSON-RPC by pygls
- **No Remora serialization involved** — pygls handles the wire format
- **File:** `core/agent_node.py` (`to_code_lens`, `to_hover`, `to_document_symbol`)

**Step 7: Neovim displays the results**

Neovim renders code lenses as virtual text above functions, hover info as a popup window, and document symbols in the outline sidebar.

#### Where `@dataclass` / `asdict()` / `is_dataclass()` Appears in This Path

| Location | What | Current | After Refactor |
|---|---|---|---|
| `discovery.py:18` | `CSTNode` definition | `@dataclass(frozen=True)` | `BaseModel` (frozen) |
| `discovery.py:56` | `_parse_file` return | `list[CSTNode]` (dataclass) | `list[CSTNode]` (Pydantic) |
| `event_store.py` | `_serialize_event` | `model_dump()` for events (already Pydantic) | No change |
| `agent_node.py` | `ToolSchema` nested in `AgentNode` | `@dataclass` — `from_row` constructs manually | `BaseModel` — `model_validate` |
| `agent_node.py` | `to_row()` serialization | `is_dataclass(tool)` → `asdict(tool)` for `extra_tools` | `tool.model_dump()` |

#### What Changes After Refactor

1. **`CSTNode` becomes `BaseModel(frozen=True)`** — the `_parse_file()` constructor calls change from positional/keyword args to Pydantic construction. Since `CSTNode` never crosses the watcher boundary as an object (immediately dict-ified), the blast radius is confined to `discovery.py`.

2. **`ToolSchema` becomes `BaseModel`** — `AgentNode.from_row()` switches from manual construction to `ToolSchema.model_validate(json_dict)`. `AgentNode.to_row()` switches from `asdict(tool)` to `tool.model_dump()`. Eliminates one `is_dataclass` branch.

3. **Everything else in this path is already Pydantic** — `NodeDiscoveredEvent`, `AgentNode`, and all LSP model types are already `BaseModel`.

---

### A.2 — Event → Subscription → Trigger → LLM → Proposal (Reactive Path)

**Trigger:** A file is saved in Neovim. The LSP `did_save` handler emits a `ContentChangedEvent`. The subscription system matches it to an agent, the agent runner calls the LLM, the LLM returns tool calls, and eventually a `RewriteProposal` lands as a Neovim diagnostic.

This is the **reactive write path** — it's how agents actually *do things* in response to code changes.

#### The Full Pipeline

```
 Neovim                  Remora LSP                          Remora Core
┌──────┐  didSave      ┌────────────┐  emit               ┌──────────────────┐
│ save │───────────────>│ documents  │────────────────────>│ ContentChanged   │
│ file │  (LSP msg)     │ handler    │                     │ Event (Pydantic) │
└──────┘                └────────────┘                     └────────┬─────────┘
                                                                    │
                                                                    │ EventStore.append()
                                                                    │ → _serialize_event → model_dump()
                                                                    │ → subscription trigger check
                                                                    │
                                                           ┌────────▼─────────────┐
                                                           │ SubscriptionRegistry │
                                                           │ get_matching_agents  │
                                                           └────────┬─────────────┘
                                                                    │
                                                    SubscriptionPattern.matches(event)
                                                    (@dataclass with match logic)
                                                                    │
                                                           ┌────────▼───────┐
                                                           │  matched_ids   │
                                                           │  list[str]     │
                                                           └────────┬───────┘
                                                                    │
                                                                    │ for each matched agent_id:
                                                                    │
                                                           ┌────────▼────────────┐
                                                           │ AgentRunner         │
                                                           │ execute_turn()      │
                                                           │ (cascade check,     │
                                                           │  depth tracking,    │
                                                           │  semaphore)         │
                                                           └────────┬────────────┘
                                                                    │
                                                                    │ build messages:
                                                                    │ - system prompt (from AgentNode)
                                                                    │ - recent events (from EventStore)
                                                                    │
                                                           ┌────────▼────────────┐
                                                           │ LLMClient.chat()   │
                                                           │ structured_agents   │
                                                           │ client.chat()      │
                                                           └────────┬────────────┘
                                                                    │
                                                                    │ returns LLMResponse
                                                                    │ (@dataclass: content, tool_calls)
                                                                    │ where tool_calls = list[ToolCall]
                                                                    │ (@dataclass: name, arguments, id)
                                                                    │
                                                           ┌────────▼────────────┐
                                                           │ handle_response()  │
                                                           │ tool loop          │
                                                           │ (MAX_TOOL_ROUNDS=5)│
                                                           └────────┬────────────┘
                                                                    │
                                          ┌─────────────────────────┼─────────────────────┐
                                          │                         │                     │
                                  ┌───────▼──────┐         ┌───────▼──────┐       ┌──────▼──────┐
                                  │ rewrite_self │         │ message_node │       │  read_node  │
                                  │ (tool call)  │         │ (tool call)  │       │ (tool call) │
                                  └───────┬──────┘         └──────────────┘       └─────────────┘
                                          │
                                          │ creates RewriteProposal
                                          │ (Pydantic BaseModel)
                                          │
                                  ┌───────▼─────────────┐
                                  │ RewriteProposal     │
                                  │ .to_diagnostic()    │  → lsp.Diagnostic
                                  │ .to_code_actions()  │  → lsp.CodeAction
                                  └───────┬─────────────┘
                                          │
                                          │ server.publish_diagnostics()
                                          │ server.emit_event(RewriteProposalEvent)
                                          │
                                  ┌───────▼──────────┐
                                  │ Neovim shows:    │
                                  │ ⚠ diagnostic     │
                                  │ 💡 code action    │
                                  │ (accept/reject)  │
                                  └──────────────────┘
```

#### Step-by-Step with Types

**Step 1: Neovim sends `textDocument/didSave`**

The user saves a file. Neovim's LSP client sends the notification. The `did_save` handler re-parses the file via the watcher (same as A.1 Steps 2-3), then emits a `ContentChangedEvent`:

```python
event = ContentChangedEvent(
    file_path=uri,
    agent_ids=changed_agent_ids,
    ...
)
await server.event_store.append("file_changes", event)
```

- **Data type:** `ContentChangedEvent` — **Pydantic frozen BaseModel** (already converted in Batch 6.1)
- **File:** `lsp/handlers/documents.py` (`did_save`)

**Step 2: EventStore appends and triggers subscription matching**

`EventStore.append()` serializes the event via `_serialize_event()` (calls `event.model_dump()` — already Pydantic), writes to the `events` table, then checks for matching subscriptions:

```python
matched = self._subscription_registry.get_matching_agents(event)
for agent_id in matched:
    self._trigger_callback(agent_id, event)
```

- **Data type at boundary:** `event` is Pydantic BaseModel, `matched` is `list[str]` (agent IDs)
- **No dataclass involvement** for the event itself — it's already Pydantic
- **File:** `core/event_store.py` (`append`, `_check_subscriptions`)

**Step 3: SubscriptionRegistry matches via SubscriptionPattern**

`get_matching_agents()` uses the in-memory index (built in Batch 2.9) keyed by `event_type` for O(1) lookup. For each candidate `Subscription`, it calls `subscription.pattern.matches(event)`:

```python
def matches(self, event) -> bool:
    if self.event_types and type(event).__name__ not in self.event_types:
        return False
    if self.from_agents and getattr(event, 'agent_id', None) not in self.from_agents:
        return False
    if self.tags:  # tag intersection check
        ...
    return True
```

- **BEFORE (current):** `SubscriptionPattern` is a **stdlib `@dataclass`** with fields: `event_types: tuple[str, ...]`, `from_agents: tuple[str, ...]`, `tags: tuple[str, ...]`
- **BEFORE (current):** `Subscription` is a **stdlib `@dataclass`** with fields: `id: str`, `agent_id: str`, `pattern: SubscriptionPattern`, `is_default: bool`
- **Key serialization site:** `SubscriptionRegistry` stores patterns as JSON via `asdict(pattern)` when persisting to SQLite, and reconstructs via `SubscriptionPattern(**row_dict)` when loading
- **File:** `core/subscriptions.py` (`SubscriptionPattern.matches`, `SubscriptionRegistry.get_matching_agents`)

**Step 4: AgentRunner.execute_turn() prepares messages**

The trigger callback queues the agent for execution. `execute_turn()` applies cascade safety checks (depth tracking, cooldown, semaphore), then builds the message list:

1. **System prompt** from `AgentNode.to_system_prompt()` — includes agent name, type, language, subscriptions, and any extension instructions
2. **Recent events** from `EventStore.get_recent_events(agent_id)` — these are returned as dicts (SQL rows), accessed via `event["event_type"]`, `event["data"]`, etc.
3. **The triggering event** formatted as a user message

- **Data type:** Messages are `list[dict]` with `{"role": "system"|"user"|"assistant", "content": str}` format — plain dicts, not dataclass/Pydantic
- **No dataclass/Pydantic serialization here** — messages are constructed as dicts directly
- **File:** `lsp/runner.py` (`execute_turn`, `_build_messages`)

**Step 5: LLMClient.chat() calls the LLM and returns LLMResponse**

The runner calls `self.llm.chat(messages, tools)`. The `LLMClient` wraps the `structured_agents` client, translates the response into local types:

```python
response = await self.client.chat(messages, tools=tools)
return LLMResponse(
    content=response.content or "",
    tool_calls=[
        ToolCall(name=tc.name, arguments=tc.arguments, id=tc.id)
        for tc in (response.tool_calls or [])
    ]
)
```

- **BEFORE (current):** `LLMResponse` is a **stdlib `@dataclass`** with fields: `content: str`, `tool_calls: list[ToolCall]`
- **BEFORE (current):** `ToolCall` is a **stdlib `@dataclass`** with fields: `name: str`, `arguments: dict[str, Any]`, `id: str`
- **Key point:** These types are purely internal to the runner — they never get serialized to SQLite or sent over JSON-RPC. They exist only as typed containers for the LLM response within the tool loop.
- **File:** `lsp/runner.py:22-30` (`ToolCall`, `LLMResponse` definitions), `lsp/runner.py` (`LLMClient.chat`)

**Step 6: handle_response() processes tool calls in a loop**

The runner enters a tool loop (up to `MAX_TOOL_ROUNDS = 5`):

```python
for tool_call in response.tool_calls:
    if tool_call.name == "rewrite_self":
        result = await self._handle_rewrite_self(agent, tool_call.arguments)
    elif tool_call.name == "message_node":
        result = await self._handle_message_node(agent, tool_call.arguments)
    elif tool_call.name == "read_node":
        result = await self._handle_read_node(agent, tool_call.arguments)
    else:
        result = await self._handle_extension_tool(agent, tool_call)
```

- **Data type:** `tool_call` is a `ToolCall` **dataclass** — accessed via `.name`, `.arguments`, `.id` attribute access
- **No serialization** — pure in-memory attribute access
- **File:** `lsp/runner.py` (`handle_response`)

**Step 7: rewrite_self creates a RewriteProposal**

When the LLM calls the `rewrite_self` tool, the handler creates a `RewriteProposal`:

```python
proposal = RewriteProposal(
    agent_id=agent.node_id,
    file_path=agent.file_path,
    start_line=agent.start_line,
    end_line=agent.end_line,
    new_content=arguments["new_content"],
    rationale=arguments.get("rationale", ""),
)
server.proposals[proposal.agent_id] = proposal
```

- **Data type:** `RewriteProposal` — **Pydantic BaseModel** (already, from `lsp/models.py`)
- **File:** `lsp/runner.py` (`_handle_rewrite_self`), `lsp/models.py` (definition)

**Step 8: Proposal published as diagnostic + code action**

The proposal is rendered into LSP types and sent to Neovim:

```python
diagnostic = proposal.to_diagnostic()     # → lsp.Diagnostic
server.publish_diagnostics(uri, [diagnostic])

event = RewriteProposalEvent(
    agent_id=proposal.agent_id,
    proposal_id=proposal.agent_id,
    ...
)
server.emit_event(event)  # → event.model_dump() → JSON-RPC notification
```

When Neovim requests code actions (e.g., user presses a keybind), the handler returns:

```python
actions = proposal.to_code_actions()  # → list[lsp.CodeAction] with "Accept"/"Reject"
```

- **Data type at boundary:** `lsp.Diagnostic`, `lsp.CodeAction` — pygls types, serialized to JSON-RPC automatically
- **`RewriteProposalEvent`** is Pydantic — serialized via `model_dump()` in `emit_event`
- **File:** `lsp/models.py` (`to_diagnostic`, `to_code_actions`), `lsp/server.py` (`emit_event`)

**Step 9: User accepts or rejects**

User triggers the code action in Neovim → LSP `workspace/executeCommand` → `remora.acceptProposal` or `remora.rejectProposal`:

- **Accept:** applies a `WorkspaceEdit` (from `proposal.to_workspace_edit()`), emits `RewriteAppliedEvent` (Pydantic)
- **Reject:** sends `$/remora/requestInput` for feedback, then emits `RewriteRejectedEvent` (Pydantic), may re-trigger the agent with feedback

- **File:** `lsp/handlers/commands.py` (`_accept_proposal`, `_reject_proposal`)

#### Where `@dataclass` / `asdict()` / `is_dataclass()` Appears in This Path

| Location | What | Current | After Refactor |
|---|---|---|---|
| `subscriptions.py:12` | `SubscriptionPattern` definition | `@dataclass` | `BaseModel` (frozen) |
| `subscriptions.py:23` | `Subscription` definition | `@dataclass` | `BaseModel` (frozen) |
| `subscriptions.py` | `SubscriptionRegistry` persist | `asdict(pattern)` → JSON | `pattern.model_dump()` → JSON |
| `subscriptions.py` | `SubscriptionRegistry` load | `SubscriptionPattern(**d)` | `SubscriptionPattern.model_validate(d)` |
| `runner.py:22` | `ToolCall` definition | `@dataclass` | `BaseModel` (frozen) |
| `runner.py:28` | `LLMResponse` definition | `@dataclass` | `BaseModel` (frozen) |
| `runner.py` | `LLMClient.chat()` return | Constructs `ToolCall`/`LLMResponse` dataclasses | Constructs `ToolCall`/`LLMResponse` Pydantic models |
| `runner.py` | `handle_response()` access | `tool_call.name`, `.arguments` | Same — attribute access unchanged |

#### What Changes After Refactor

1. **`SubscriptionPattern` and `Subscription` become `BaseModel(frozen=True)`** — The `matches()` method stays as-is (it's pure logic using attribute access). The `SubscriptionRegistry` switches from `asdict(pattern)` to `pattern.model_dump()` for persistence and from `SubscriptionPattern(**d)` to `SubscriptionPattern.model_validate(d)` for loading. This eliminates one `asdict()` call site.

2. **`ToolCall` and `LLMResponse` become `BaseModel(frozen=True)`** — Construction in `LLMClient.chat()` changes from `ToolCall(name=..., arguments=..., id=...)` to the same syntax (Pydantic accepts keyword args just like dataclass). Attribute access in `handle_response()` is unchanged (`.name`, `.arguments`, `.id`). These types are never serialized, so the conversion is purely a definition change.

3. **Everything else in this path is already Pydantic** — `ContentChangedEvent`, `RewriteProposal`, `RewriteProposalEvent`, `RewriteAppliedEvent`, `RewriteRejectedEvent`, and `AgentNode` are all already `BaseModel`.

4. **Net effect on the reactive path:** Two `asdict()` calls eliminated (subscription persistence). Zero serialization logic changes in the runner tool loop — `ToolCall`/`LLMResponse` are in-memory only.

---

### A.3 — Chat Service → Message → AgentResponse (HTTP API Path)

**Trigger:** An HTTP POST arrives at the Starlette chat service endpoint. This is the standalone demo path — a simple HTTP API for chatting with agents, separate from the LSP server.

This path is notable because it's the **most manual serialization** in the codebase. `Message`, `ChatConfig`, and `AgentResponse` are all stdlib dataclasses, and the service constructs JSON responses by hand-picking fields from `__dict__` rather than using `asdict()` or `model_dump()`.

#### The Full Pipeline

```
 HTTP Client            Starlette App                    Remora Core
┌──────────┐  POST     ┌───────────────┐  create       ┌──────────────┐
│ curl /   │──────────>│ chat_service  │──────────────>│  ChatConfig  │
│ chat     │  JSON     │ route handler │               │  (@dataclass)│
└──────────┘           └───────┬───────┘               └──────┬───────┘
                               │                              │
                               │  ChatConfig(                 │
                               │    model="...",              │
                               │    system_prompt="...",      │
                               │  )                           │
                               │                              │
                       ┌───────▼───────────┐                  │
                       │  ChatSession      │<─────────────────┘
                       │  (holds config,   │
                       │   history:        │
                       │   list[Message])  │  Message = @dataclass(role, content)
                       └───────┬───────────┘
                               │
                               │  session.send(user_text)
                               │  → appends Message(role="user", content=text)
                               │  → calls LLM
                               │
                       ┌───────▼───────────┐
                       │  structured_agents│
                       │  client.chat()   │
                       └───────┬───────────┘
                               │
                               │  returns AgentResponse
                               │  (@dataclass: content, tool_calls, ...)
                               │
                       ┌───────▼───────────┐
                       │  Manual JSON      │
                       │  serialization    │
                       │  via __dict__     │
                       │  access           │
                       └───────┬───────────┘
                               │
                               │  JSONResponse({
                               │    "role": msg.role,
                               │    "content": msg.content,
                               │  })
                               │
                       ┌───────▼───────────┐
                       │  HTTP Response    │  → JSON → Client
                       └───────────────────┘
```

#### Step-by-Step with Types

**Step 1: HTTP POST arrives at the chat endpoint**

The Starlette route handler receives a JSON body with the user's message and (optionally) configuration overrides:

```python
body = await request.json()
user_message = body["message"]
```

- **Data type at boundary:** plain `dict` from `request.json()`
- **File:** `service/chat_service.py`

**Step 2: ChatConfig created from request or defaults**

The handler creates a `ChatConfig` to hold LLM settings:

```python
config = ChatConfig(
    model=body.get("model", "qwen2.5-coder:7b"),
    system_prompt=body.get("system_prompt", DEFAULT_SYSTEM_PROMPT),
    max_tokens=body.get("max_tokens", 4096),
    temperature=body.get("temperature", 0.7),
)
```

- **BEFORE (current):** `ChatConfig` is a **stdlib `@dataclass`** with fields: `model: str`, `system_prompt: str`, `max_tokens: int`, `temperature: float`, and optional overrides
- **Key point:** `ChatConfig` is never serialized — it's used purely as a typed container to pass configuration to `ChatSession`
- **File:** `core/chat.py` (`ChatConfig` definition)

**Step 3: ChatSession initialized with config and message history**

```python
session = ChatSession(config=config)
```

The session maintains `history: list[Message]` — a running list of conversation messages.

- **Data type:** `ChatSession` is a regular class (not a dataclass). `history` contains `Message` dataclass instances.
- **File:** `core/chat.py` (`ChatSession`)

**Step 4: User message appended as a Message dataclass**

```python
session.history.append(Message(role="user", content=user_message))
```

- **BEFORE (current):** `Message` is a **stdlib `@dataclass`** with fields: `role: str`, `content: str`
- **Key point:** `Message` is used in two ways — (1) as typed objects in `session.history`, and (2) converted to dicts when building the LLM request: `[{"role": m.role, "content": m.content} for m in history]`
- **File:** `core/chat.py` (`Message` definition)

**Step 5: ChatSession calls the LLM**

The session formats history as dicts and calls the LLM:

```python
messages = [{"role": m.role, "content": m.content} for m in self.history]
response = await self.client.chat(messages)
```

- **Data type at boundary:** `list[dict]` sent to LLM client — manual dict construction from `Message` attributes
- **This is where Pydantic would simplify:** instead of manual dict building, `[m.model_dump() for m in self.history]`
- **File:** `core/chat.py` (`ChatSession.send`)

**Step 6: LLM response wrapped as AgentResponse**

The `structured_agents` client returns its own response type. `ChatSession` wraps it:

```python
agent_response = AgentResponse(
    content=response.content or "",
    tool_calls=response.tool_calls,
    model=self.config.model,
    ...
)
self.history.append(Message(role="assistant", content=agent_response.content))
return agent_response
```

- **BEFORE (current):** `AgentResponse` is a **stdlib `@dataclass`** with fields: `content: str`, `tool_calls: list | None`, `model: str`, plus metadata
- **Key point:** `AgentResponse` is the return type from the session — it gets serialized to JSON for the HTTP response
- **File:** `core/chat.py` (`AgentResponse` definition, `ChatSession.send`)

**Step 7: Manual dict serialization for HTTP response**

The route handler builds the JSON response manually:

```python
return JSONResponse({
    "response": {
        "content": agent_response.content,
        "model": agent_response.model,
        "tool_calls": agent_response.tool_calls,
    },
    "history": [
        {"role": m.role, "content": m.content}
        for m in session.history
    ],
})
```

- **Data type at boundary:** hand-constructed `dict` → `JSONResponse` → HTTP JSON
- **Key problem:** This is manual field-by-field serialization. If a field is added to `Message` or `AgentResponse`, this code must be updated manually — there's no `asdict()` or `model_dump()` to automatically pick up new fields
- **Dead import:** `from dataclasses import asdict` on line 5 of `chat_service.py` — imported but never used (likely intended to be used here but the manual approach was chosen instead)
- **File:** `service/chat_service.py`

#### Where `@dataclass` / `asdict()` / `is_dataclass()` Appears in This Path

| Location | What | Current | After Refactor |
|---|---|---|---|
| `chat.py` | `Message` definition | `@dataclass` | `BaseModel` (frozen) |
| `chat.py` | `ChatConfig` definition | `@dataclass` | `BaseModel` (frozen) |
| `chat.py` | `AgentResponse` definition | `@dataclass` | `BaseModel` |
| `chat.py` | History → LLM messages | `{"role": m.role, "content": m.content}` (manual) | `m.model_dump()` |
| `chat_service.py:5` | Dead import | `from dataclasses import asdict` (unused) | Removed |
| `chat_service.py` | Response serialization | Manual dict construction | `agent_response.model_dump()` |
| `chat_service.py` | History serialization | Manual `{"role": m.role, ...}` list | `[m.model_dump() for m in history]` |

#### What Changes After Refactor

1. **`Message` becomes `BaseModel(frozen=True)`** — History-to-LLM conversion simplifies from manual dict building to `m.model_dump()`. Since `Message` has only 2 fields (`role`, `content`), the construction syntax is identical: `Message(role="user", content="...")`.

2. **`ChatConfig` becomes `BaseModel(frozen=True)`** — Pure definition change. `ChatConfig` is never serialized — it's only used to pass settings to `ChatSession`. The constructor call doesn't change.

3. **`AgentResponse` becomes `BaseModel`** — The HTTP response handler simplifies from manual field extraction to `agent_response.model_dump()`. This is the **biggest ergonomic win** in this path — no more fragile manual dict construction that falls out of sync when fields are added.

4. **Dead `asdict` import removed** — `chat_service.py` line 5 imports `asdict` but never uses it. This gets deleted since there are no remaining `@dataclass` types to call it on.

5. **Net effect on the chat path:** Zero `asdict()` or `is_dataclass()` calls affected (there were none — the code used manual `__dict__` access instead). The refactor replaces **manual dict construction** with `model_dump()`, which is the primary value here — correctness and maintainability rather than eliminating branching logic.

---

### A.4 — Events → UiStateProjector → Graph Web UI (Frontend Path)

**Trigger:** Events flow through the system (from any of the paths above). They need to be visualized in two independent UIs: (1) the **Datastar dashboard** served by `RemoraService`, and (2) the **Graph Web UI** served by the Stario app in `remora-demo/frontend/`.

This scenario is unique because it has **two parallel rendering pipelines** that consume the same underlying data through completely different mechanisms. The Datastar dashboard subscribes to the in-process `EventBus` and serializes events on the fly. The Graph Web UI reads from the shared SQLite database via polling — it never touches the Python event objects directly.

#### The Two Pipelines — Overview

```
                         ┌───────────────────────────────────────────┐
                         │           Remora Core (in-process)        │
                         │                                           │
  Events from            │  ┌──────────┐     ┌────────────────────┐  │
  LSP handlers,  ───────>│  │ EventBus │────>│  UiStateProjector  │  │
  runner, etc.           │  │ publish  │     │  (@dataclass)       │  │
                         │  └──────────┘     │  record()           │  │
                         │       │           │  _event_payload()   │  │
                         │       │           │  _to_jsonable()     │  │
                         │       │           │  normalize_event()  │  │
                         │       │           └─────────┬──────────┘  │
                         │       │                     │             │
                         │       │           snapshot dict           │
                         │       │                     │             │
                         │  ┌────▼─────────────────────▼──────────┐  │
                         │  │          RemoraService              │  │
                         │  │  subscribe_stream() → Datastar SSE  │──── Pipeline 1
                         │  │  events_stream() → raw SSE          │  │   (Datastar
                         │  └─────────────────────────────────────┘  │    Dashboard)
                         │                                           │
                         │  ┌──────────────────────┐                 │
                         │  │ EventStore + RemoraDB │                 │
                         │  │ (SQLite .remora/      │                 │
                         │  │  indexer.db)          │                 │
                         │  └──────────┬───────────┘                 │
                         └─────────────│─────────────────────────────┘
                                       │
                          ┌────────────▼────────────────────────────┐
                          │     Graph Web UI (separate process)     │
                          │                                         │
                          │  ┌──────────┐  poll    ┌─────────────┐  │
                          │  │ DBBridge │─────────>│ GraphState  │  │
                          │  │ (0.3s)   │  SQLite  │ read_only   │  │
                          │  └────┬─────┘  WAL     │ WAL mode    │  │
                          │       │                └──────┬──────┘  │
                          │       │                       │         │
                          │  ┌────▼────────┐    GraphSnapshot      │
                          │  │ ForceLayout │    (@dataclass)       │
                          │  │ set_graph() │              │         │
                          │  │ step()      │              │         │
                          │  └────┬────────┘              │         │
                          │       │                       │         │
                          │  positions                    │         │
                          │  {id: (x,y)}                  │         │
                          │       │                       │         │
                          │  ┌────▼──────────────────┐    │         │
                          │  │ render_graph_svg()    │    │         │  Pipeline 2
                          │  │ render_sidebar_content│<───┘         │  (Graph
                          │  │ render_event_list     │              │   Web UI)
                          │  └────┬─────────────────┘              │
                          │       │                                 │
                          │  ┌────▼───────────┐                     │
                          │  │ Stario w.patch │  → SSE → Browser   │
                          │  └────────────────┘                     │
                          └─────────────────────────────────────────┘
```

#### Pipeline 1: Datastar Dashboard (In-Process Event Subscription)

**This pipeline stays entirely within the Remora process.** Events arrive on the EventBus, get reduced by `UiStateProjector`, and are rendered as HTML patches streamed via SSE.

**Step 1: Event arrives on EventBus**

When any handler calls `event_store.append()` or `server.emit_event()`, the event is also published to the `EventBus`. Subscribers receive the live Python object.

- **Data type:** Any `RemoraEvent` union member — these are **Pydantic frozen BaseModel** instances (Remora events) or **stdlib `@dataclass`** instances (7 re-exported `structured_agents` events)
- **Key point:** This is the only place in the system where both Pydantic and dataclass event objects coexist in the same stream. The `UiStateProjector` must handle both.
- **File:** `core/event_bus.py`, `core/events.py` (re-exports)

**Step 2: UiStateProjector.record() processes the event**

The projector maintains a running snapshot of UI state. When an event arrives:

```python
def record(self, event):
    payload = self._event_payload(event)
    normalized = self.normalize_event(event, payload)
    self.events.append(normalized)
    # update agent status, blocked agents, etc. based on event type
```

- **Data type:** `UiStateProjector` is a **stdlib `@dataclass(slots=True)`** — but this is a *service component*, not a data model. It is NOT a conversion candidate (see Key Decision #14).
- **File:** `ui/projector.py` (`record`)

**Step 3: `_event_payload()` — the `is_dataclass` branching site**

This is one of the 4 serialization branching sites identified in Section 6 of the main document:

```python
def _event_payload(self, event) -> dict:
    if is_dataclass(event):
        return asdict(event)
    elif hasattr(event, 'model_dump'):
        return event.model_dump()
    else:
        return vars(event)
```

- **BEFORE (current):** The `is_dataclass` branch catches the 7 `structured_agents` re-exported events (which are stdlib dataclasses from an external library). The `model_dump` branch catches all 15 Remora core events (which are Pydantic). The `vars` branch is a fallback.
- **AFTER refactor:** The `is_dataclass` branch **still needed** for `structured_agents` external events — those are NOT Remora types and won't be converted. However, after the consolidation, no *Remora* type will ever hit the `is_dataclass` branch. The branch order could be swapped to check `model_dump` first for a micro-optimization, but functionally nothing changes.
- **File:** `ui/projector.py` (`_event_payload`)

**Step 4: `_to_jsonable()` — recursive serialization with `is_dataclass` check**

The second branching site in the projector. This recursively converts nested objects to JSON-serializable dicts:

```python
def _to_jsonable(self, obj):
    if is_dataclass(obj) and not isinstance(obj, type):
        return asdict(obj)
    elif hasattr(obj, 'model_dump'):
        return obj.model_dump()
    elif isinstance(obj, dict):
        return {k: self._to_jsonable(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        return [self._to_jsonable(v) for v in obj]
    else:
        return obj
```

- **Same situation as `_event_payload`:** The `is_dataclass` branch remains for external types. After the Remora consolidation, only `structured_agents` dataclass events will hit it. All Remora types will use `model_dump`.
- **File:** `ui/projector.py` (`_to_jsonable`)

**Step 5: `normalize_event()` wraps payload in UI envelope**

```python
def normalize_event(self, event, payload) -> dict:
    return {
        "kind": "event",
        "type": type(event).__name__,
        "graph_id": getattr(event, 'graph_id', None),
        "agent_id": getattr(event, 'agent_id', None),
        "timestamp": getattr(event, 'timestamp', None),
        "payload": payload,
    }
```

- **Data type:** plain `dict` — this is the normalized form used by all downstream consumers
- **No dataclass/Pydantic here** — pure dict construction from `getattr` calls
- **File:** `ui/projector.py` (`normalize_event`)

**Step 6: RemoraService.subscribe_stream() renders Datastar patches**

The service layer takes the projector's snapshot and renders it as HTML:

```python
async def subscribe_stream(self):
    state = self.projector.snapshot()  # → dict
    html = render_dashboard(state)     # → HTML string
    yield render_patch(html)           # → Datastar SSE format
```

- **Data type at boundary:** `state` is a plain `dict` (already fully serialized by `_to_jsonable`). `html` is a string. `render_patch()` wraps it in Datastar's SSE `data: ...` format.
- **No dataclass/Pydantic here** — the projector has already reduced everything to dicts
- **File:** `service/api.py` (`subscribe_stream`), `service/datastar.py` (`render_patch`)

**Step 7: Dashboard HTML rendered by UI components**

`render_dashboard(state)` passes the snapshot dict to the UI component tree:

```python
def render_dashboard(state: dict) -> str:
    return str(ComponentGroup(children=[
        EventsList(events=state["events"]),
        AgentStatusList(agents=state["agents"]),
        BlockedAgentCard(agents=state.get("blocked", [])),
        ResultsList(results=state.get("results", [])),
        ...
    ]))
```

- **Data type:** All UI components (`EventsList`, `AgentStatusList`, etc.) are **stdlib `@dataclass`** subclasses of `Component` ABC — but these are **rendering components**, not data models. They stay as `@dataclass` (Key Decision #14).
- **The snapshot `state` is a plain dict** — UI components just read dict keys, no type checking involved
- **File:** `ui/view.py` (`render_dashboard`), `ui/components/dashboard.py`

**Step 8: Browser receives SSE and Datastar updates the DOM**

The browser has loaded the initial HTML shell (from `render_shell()`) which includes the Datastar CDN script. Datastar's `data-on-load="@get('/subscribe')"` opens an SSE connection. Each `render_patch()` updates the DOM incrementally.

- **No Python types involved** — this is pure browser-side HTML/JS
- **File:** `service/datastar.py` (`render_shell`)

#### Pipeline 2: Graph Web UI (SQLite Polling from Separate Process)

**This pipeline runs in a separate Stario process.** It reads from the same SQLite database that Remora's `EventStore` and `RemoraDB` write to, using WAL mode for concurrent read access. It never touches Python event objects — it only sees SQL rows.

**Step 1: Shared SQLite DB written by Remora core**

The Remora LSP process writes to `.remora/indexer.db`:
- `EventStore.append()` writes to the `events` table (serialized via `_serialize_event` → `model_dump()`)
- `NodeProjection.project()` writes to the `nodes` table
- `RemoraDB` writes to the `edges`, `node_status`, and `proposals` tables

- **Data type at boundary:** SQL rows — all Python types have been serialized to primitive columns and JSON text
- **No dataclass/Pydantic types cross the process boundary** — only SQL data

**Step 2: DBBridge polls for changes**

The `DBBridge` runs a 0.3-second polling loop, checking fingerprints (row counts + max rowids) for changes:

```python
async def _poll_loop(self):
    while True:
        await asyncio.sleep(0.3)
        new_fp = self._read_fingerprints()
        if new_fp.nodes != self._fp.nodes or new_fp.edges != self._fp.edges:
            await self._on_topology_change()
        if new_fp.status != self._fp.status:
            await self._on_status_change()
        if new_fp.cursor != self._fp.cursor:
            await self._on_cursor_change()
        if new_fp.events != self._fp.events:
            await self._on_events_change()
        self._fp = new_fp
```

- **Data type:** Fingerprints are plain tuples of ints. `DBBridge` is a regular class.
- **File:** `remora-demo/frontend/graph/bridge.py` (`_poll_loop`)

**Step 3: GraphState.read_snapshot() returns a GraphSnapshot**

On topology change, the bridge reads the current graph state:

```python
snapshot = self.state.read_snapshot()
# → GraphSnapshot(nodes=[...], edges=[...], cursor_focus=..., timestamp=...)
```

- **Data type:** `GraphSnapshot` is a **stdlib `@dataclass`** with fields: `nodes: list[dict]`, `edges: list[dict]`, `cursor_focus: dict | None`, `timestamp: float`
- **Key point:** `GraphSnapshot` lives in `remora-demo/frontend/graph/state.py` — it is in the **external demo frontend**, NOT in `src/remora/`. It is NOT a Remora conversion candidate. It's a data transfer type for the frontend's own use.
- **The nodes and edges are already dicts** — `read_snapshot()` builds them from SQL rows. No Pydantic or dataclass objects are nested inside.
- **File:** `remora-demo/frontend/graph/state.py` (`GraphSnapshot`, `read_snapshot`)

**Step 4: ForceLayout computes positions**

The bridge updates the force-directed layout engine:

```python
self.layout.set_graph(snapshot.nodes, snapshot.edges)
self.layout.step(iterations=50)
positions = self.layout.get_positions()  # → {node_id: (x, y)}
```

- **Data type:** `LayoutNode` and `LayoutEdge` are **stdlib `@dataclass`** instances (internal to the layout engine). `positions` is `dict[str, tuple[float, float]]`.
- **These are internal frontend types** — not Remora conversion candidates
- **File:** `remora-demo/frontend/graph/layout.py` (`ForceLayout`, `LayoutNode`, `LayoutEdge`)

**Step 5: render_graph_svg() produces SVG**

The SVG renderer takes the raw data and positions:

```python
svg = render_graph_svg(
    nodes=snapshot.nodes,       # list[dict]
    edges=snapshot.edges,       # list[dict]
    positions=positions,        # {id: (x, y)}
)
```

- **Data type at boundary:** All inputs are plain dicts/tuples. Output is an SVG string.
- **Node circles** are colored by status (Catppuccin Mocha palette: green=active, yellow=triggered, red=error, gray=idle)
- **Nodes have `data-on-click`** attributes for Datastar interaction: `data-on-click="@get('/agent/{node_id}')"`
- **File:** `remora-demo/frontend/graph/svg.py` (`render_graph_svg`)

**Step 6: Stario streams patches via SSE**

The Stario app's subscribe handler streams updates:

```python
async def handle_subscribe(w, req):
    async for subject, data in w.alive(relay.subscribe("graph.*")):
        if subject == "graph.topology":
            w.patch("#graph-pane", render_graph(data["snapshot"], data["positions"]))
        elif subject == "graph.events":
            w.patch("#event-stream", render_event_list(data["events"]))
        elif subject == "graph.status":
            w.patch("#graph-pane", render_graph(data["snapshot"], data["positions"]))
        elif subject == "graph.cursor":
            w.patch("#cursor-indicator", render_cursor(data))
```

- **`w.patch(selector, html)`** sends a Datastar-compatible SSE message that replaces the element matching the CSS selector
- **Data type at boundary:** `data` is a plain dict published by `DBBridge`. `html` is a string from the render functions.
- **File:** `remora-demo/frontend/graph/app.py` (`handle_subscribe`)

**Step 7: Sidebar detail view (on node click)**

When a user clicks a node in the SVG, Datastar fires `@get('/agent/{node_id}')`:

```python
async def handle_agent_detail(w, req):
    node_id = req.path_params["node_id"]
    node = self.state.read_node(node_id)           # → dict
    events = self.state.read_events_for_agent(node_id)    # → list[dict]
    proposals = self.state.read_proposals_for_agent(node_id)  # → list[dict]
    connections = self.state.read_edges_for_node(node_id)     # → list[dict]
    html = render_sidebar_content(node, events, proposals, connections)
    w.patch("#sidebar", html)
```

- **All data is plain dicts** from SQL queries — no Pydantic or dataclass types involved
- **Sidebar tabs:** Log (events), Source (source code), Connections (edges), Actions (chat textarea, proposal approve/reject buttons)
- **File:** `remora-demo/frontend/graph/app.py`, `remora-demo/frontend/graph/views/sidebar.py`

**Step 8: Commands flow back (sidebar → command queue → runner)**

The sidebar's Actions tab has a chat textarea and proposal buttons that POST commands:

```python
# Browser → Stario POST /command
async def handle_command(w, req):
    body = await req.json()
    self.state.push_command(body)  # → INSERT INTO command_queue
```

The `AgentRunner` in the main Remora process polls this queue:

```python
# Remora process polls command_queue table
async def poll_command_queue(self):
    commands = self.event_store.db.execute("SELECT * FROM command_queue WHERE status='pending'")
    for cmd in commands:
        await self._execute_command(cmd)
```

- **Data type:** Plain dicts from JSON → SQL → dicts. No Pydantic/dataclass types cross this boundary.
- **File:** `remora-demo/frontend/graph/state.py` (`push_command`), `lsp/runner.py` (command polling)

#### Where `@dataclass` / `asdict()` / `is_dataclass()` Appears in This Path

| Location | What | Current | After Refactor |
|---|---|---|---|
| `ui/projector.py` | `UiStateProjector` itself | `@dataclass(slots=True)` | **No change** — service component, not a data model |
| `ui/projector.py` | `_event_payload()` | `is_dataclass(event)` → `asdict(event)` branch | **Kept** — needed for `structured_agents` external events |
| `ui/projector.py` | `_to_jsonable()` | `is_dataclass(obj)` → `asdict(obj)` branch | **Kept** — needed for `structured_agents` external events |
| `ui/components/*.py` | All UI components | `@dataclass` (Component subclasses) | **No change** — rendering components, not data models |
| `graph/state.py` | `GraphSnapshot` | `@dataclass` | **No change** — external frontend, not `src/remora/` |
| `graph/layout.py` | `LayoutNode`, `LayoutEdge` | `@dataclass` | **No change** — external frontend, not `src/remora/` |
| `graph/app.py` | `CommandSignals` | `@dataclass` | **No change** — external frontend, not `src/remora/` |

#### What Changes After Refactor

1. **`_event_payload()` and `_to_jsonable()` keep their `is_dataclass` branches** — but the branches now *only* fire for `structured_agents` external events (7 types: `AgentStarted`, `AgentCompleted`, `ToolInvoked`, `ToolResult`, `MessageCreated`, `ErrorOccurred`, `StreamChunk`). After the refactor, no *Remora* event type will be a stdlib dataclass, so these branches become "external compatibility" code rather than "dual-type bridging" code.

2. **Optionally reorder the checks:** Since Remora events (Pydantic) are more common than `structured_agents` events (dataclass), swapping `_event_payload()` to check `hasattr(event, 'model_dump')` first would be a micro-optimization. Not required, but a nice cleanup.

3. **No changes to the Graph Web UI** — `GraphSnapshot`, `LayoutNode`, `LayoutEdge`, `CommandSignals`, and all other types in `remora-demo/frontend/` are outside the Remora library. They never touch Remora's Python types directly — they only read SQL rows. The Pydantic consolidation is invisible to the graph frontend.

4. **No changes to UI components** — `EventsList`, `AgentStatusList`, `BlockedAgentCard`, `GraphLauncher`, `ResultsList`, and all layout/control components remain `@dataclass`. They are rendering components (subclasses of `Component` ABC), not data models. They consume plain dicts from the projector snapshot and produce HTML strings.

5. **Net effect on the visualization paths:** Zero dataclass-to-Pydantic conversions needed. The `is_dataclass` branches in the projector are retained for external compatibility. The Graph Web UI is completely unaffected. This is the path with the **least impact** from the Pydantic consolidation — which is exactly what you'd expect, since visualization is downstream of serialization and only consumes dicts.

---

### Appendix Summary — Cross-Cutting View

Across all four scenarios, here's the complete picture of `@dataclass` / `asdict()` / `is_dataclass()` in Remora's data flow:

| Path | Dataclass Types Affected | `asdict()` Eliminated | `is_dataclass()` Eliminated | Primary Benefit |
|---|---|---|---|---|
| A.1 (Discovery → LSP) | `CSTNode`, `ToolSchema` | 1 call (`to_row`) | 1 check (`to_row`) | Uniform `model_dump()` in `AgentNode` |
| A.2 (Reactive) | `SubscriptionPattern`, `Subscription`, `ToolCall`, `LLMResponse` | 2 calls (registry persist) | 0 | Subscription serialization simplification |
| A.3 (Chat API) | `Message`, `ChatConfig`, `AgentResponse` | 0 (none existed) | 0 | Replace manual dict construction with `model_dump()` |
| A.4 (Visualization) | None (all external or UI components) | 0 | 0 (kept for external compat) | No change — already dict-based downstream |
| **Total** | **9 types** | **3 `asdict()` calls** | **1 `is_dataclass()` check** | **One rule: every Remora type is BaseModel** |

The dominant theme: **the refactor's value is not in eliminating a large number of branching sites** (there are only 4, and 2 must be kept for external compatibility). The value is in **establishing a single rule** — every Remora value type is `BaseModel`, serialize with `.model_dump()`, done — and in **replacing fragile manual dict construction** (especially in the chat service path) with automatic Pydantic serialization.
