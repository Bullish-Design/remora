# Refactoring structured-agents: LiteLLM Integration & Concept Alignment with Remora

**Status:** Brainstorming / Analysis Document
**Date:** 2026-03-03
**Prerequisite:** Read `LLM_PROVIDER_ENHANCEMENT.md` (Sections 1-9) first — this document builds on it.
**Key Constraint:** structured-agents is ONLY used inside Remora. The better aligned the concepts are, the better.
**User Directive:** "I like the idea of putting LiteLLM inside structured-agents" (Option A from Section 9.3.1 of the LLM Provider Enhancement doc).

---

## Table of Contents

1. **[Current structured-agents Architecture](#1-current-structured-agents-architecture)** — Complete internals walkthrough of the library as it exists today (v0.3.4). File-by-file analysis, data flow through the kernel step loop, component responsibilities, dependency graph, and the public API surface.
   - 1.1 File Inventory & Size — Every source file with line count and primary responsibility.
   - 1.2 Core Data Types — `Message`, `ToolCall`, `ToolResult`, `ToolSchema`, `TokenUsage`, `StepResult`, `RunResult`. How they flow through the system.
   - 1.3 The Client Layer — `LLMClient` Protocol, `CompletionResponse`, `OpenAICompatibleClient`, `build_client()`. The single concrete implementation wrapping `AsyncOpenAI`.
   - 1.4 The Kernel — `AgentKernel` dataclass and the step loop: format → constrain → call → parse → execute tools → emit events. Where `adapter`, `client`, `observer`, and `tools` plug in.
   - 1.5 The Model Adapter — `ModelAdapter`, `ResponseParser`, `QwenResponseParser`. How message/tool formatting and response parsing are abstracted (and how thin this layer actually is).
   - 1.6 The Grammar/Constraint Pipeline — `DecodingConstraint`, `ConstraintPipeline`, `StructuredOutputModel`. vLLM-specific `extra_body` generation for structural tags and JSON schema enforcement.
   - 1.7 The Event System — 7 event types, `Observer` Protocol, `NullObserver`, `CompositeObserver`. What gets emitted when.
   - 1.8 The Agent & Manifest Layer — `Agent` class, `AgentManifest`, `load_manifest()`, `_ADAPTER_REGISTRY`. Bundle-based agent construction (unused by Remora).
   - 1.9 The Tool Layer — `Tool` Protocol, `GrailTool`, `discover_tools()`. How tools plug into the kernel.
   - 1.10 Data Flow Diagram — End-to-end flow from `kernel.run(messages)` through step loop to `RunResult`.
   - 1.11 Dependency Graph — What depends on what. Which components are tightly coupled vs. loosely coupled.

2. **[How Remora Uses structured-agents](#2-how-remora-uses-structured-agents)** — Exhaustive mapping of every Remora file that imports from structured-agents, what it imports, and how it uses it. The three execution paths. Where Remora extends, wraps, duplicates, or ignores structured-agents concepts.
   - 2.1 Import Map — Every Remora file → what it imports from structured-agents.
   - 2.2 Execution Path A: SwarmExecutor → kernel_factory → AgentKernel — The primary path. Connection pooling, manifest loading, model resolution, tool discovery, prompt assembly, kernel.run().
   - 2.3 Execution Path B: ChatSession → kernel_factory → AgentKernel — The interactive chat path. New kernel per call, custom tools (FunctionTool), no connection pooling.
   - 2.4 Execution Path C: LSP Runner → Own Tool Loop (No Kernel) — The divergent path. Own `LLMClient` wrapper, own `ToolCall` model, own XML tool call parser, own tool format. Does NOT use AgentKernel.
   - 2.5 Remora Extensions — Where Remora adds functionality on top of structured-agents: custom tool implementations (grail, swarm, spawn_child), event store/bus bridging, UI projection.
   - 2.6 Remora Duplications — Where Remora re-implements things structured-agents already does: tool discovery, tool call parsing (LSP runner), client wrapping (LSP runner), event types (Pydantic vs. dataclass).
   - 2.7 Unused structured-agents Features — What Remora never touches: `Agent` class, `Agent.from_bundle()`, `discover_tools()`, `GrailTool`.

3. **[LiteLLM Integration into structured-agents](#3-litellm-integration-into-structured-agents)** — Detailed design for replacing `OpenAICompatibleClient` with a LiteLLM-based client inside the library. This is Option A from the LLM Provider Enhancement doc, which the user has chosen.
   - 3.1 Why Option A (Not Option B) — The user's reasoning: structured-agents is only used inside Remora, so putting LiteLLM inside simplifies the overall system by eliminating the need for a separate ProviderRegistry layer in Remora.
   - 3.2 The New Client: `LiteLLMClient` — Implementation design, signature mapping from `chat_completion()` to `litellm.acompletion()`, response normalization from `ModelResponse` to `CompletionResponse`.
   - 3.3 Model Routing — How LiteLLM's prefix convention (`anthropic/...`, `hosted_vllm/...`, `openai/...`) replaces the ProviderRegistry's named-provider system. What model strings look like in config.
   - 3.4 API Key Management — Per-call `api_key` parameter vs. environment variables. How Remora's config feeds keys through to LiteLLM.
   - 3.5 `extra_body` Passthrough for vLLM Grammar Constraints — The critical question: does `litellm.acompletion(model="hosted_vllm/...", extra_body={...})` preserve the `structured_outputs` payload? Analysis and fallback strategy.
   - 3.6 What Happens to `OpenAICompatibleClient` — Keep as fallback for direct vLLM? Remove entirely? Make `LiteLLMClient` the only implementation?
   - 3.7 What Happens to `build_client()` — Updated factory signature, backward compatibility for existing callers.
   - 3.8 Dependency Impact — Adding `litellm` to structured-agents' dependencies. Since the library is only used inside Remora, the "heavy dependency" concern from Section 9 is less relevant.
   - 3.9 Connection Management — LiteLLM's internal httpx client management vs. the current explicit `AsyncOpenAI` lifecycle. Impact on `SwarmExecutor`'s connection pooling pattern.

4. **[Concept Misalignments & Simplification Opportunities](#4-concept-misalignments--simplification-opportunities)** — Thorough analysis of every place where structured-agents and Remora concepts are misaligned, duplicated, confusing, or over-abstracted. Each with a concrete simplification proposal.
   - 4.1 Two Divergent Execution Paths (Kernel vs. LSP Runner) — The biggest structural issue. The LSP runner duplicates the entire agent loop outside of AgentKernel. Proposal: unify on AgentKernel.
   - 4.2 Naming Collisions — LSP runner's `ToolCall` and `LLMClient` shadow structured-agents' types. Proposal: eliminate the LSP-local types, use the structured-agents types.
   - 4.3 The Unused `Agent` Class — Remora never uses `Agent.from_bundle()` or `Agent.run()`. The class reads env vars (`STRUCTURED_AGENTS_BASE_URL`) which conflict with Remora's config. Proposal: deprecate or remove.
   - 4.4 `load_manifest()` vs. Double YAML Parsing — Remora calls `load_manifest()` but ALSO re-reads `bundle.yaml` in `_resolve_model_name()` for model info. Proposal: make `AgentManifest` carry all needed model metadata.
   - 4.5 `QwenResponseParser` Is Not Qwen-Specific — The "Qwen" parser handles standard API tool_calls AND XML-style tool calls. It's the universal default. Proposal: rename to `DefaultResponseParser` or `UniversalResponseParser`.
   - 4.6 Dual Tool Discovery — structured-agents has `discover_tools()` (for GrailTool). Remora has its own `discover_grail_tools()`. Neither uses the other. Proposal: consolidate or clearly separate responsibilities.
   - 4.7 Grammar Pipeline Is vLLM-Specific — The `grammar/` subpackage generates vLLM-specific `extra_body` payloads. With LiteLLM, the grammar constraint mechanism needs to work across providers (or be explicitly scoped to vLLM-only). Proposal: make grammar constraints provider-aware.
   - 4.8 `ModelAdapter` Is Over-Abstracted — Its `format_messages` and `format_tools` default to identity transforms. The only real payload is `response_parser` and optional `constraint_pipeline`. Proposal: flatten into kernel config or simplify.
   - 4.9 Event Type Split (dataclass vs. Pydantic) — structured-agents events are frozen dataclasses. Remora events are frozen Pydantic models. `EventStore.append()` and `EventBus.emit()` handle both via duck typing with dual serialization paths. Proposal: unify on one format.
   - 4.10 Double `ModelRequestEvent` Emission — `kernel.run()` emits `ModelRequestEvent` at line 233, then `kernel.step()` emits it again at line 87. Every turn produces duplicate events. Proposal: fix the bug.
   - 4.11 `CompletionResponse.tool_calls` Type Confusion — The type is `list[dict] | None` but `QwenResponseParser` returns `list[ToolCall]`. The protocol says dicts, the parser returns dataclasses. Proposal: pick one and be consistent.
   - 4.12 Debug Print Statements in Production Code — `OpenAICompatibleClient` has `print()` calls (lines 53-54, 60). Proposal: remove or convert to proper logging.

5. **[Proposed Refactored Architecture](#5-proposed-refactored-architecture)** — What structured-agents looks like after applying the LiteLLM integration and addressing all concept misalignments. New file layout, simplified public API, better Remora alignment.
   - 5.1 Design Principles — What guides the refactor: single execution path, no naming collisions, LiteLLM as transport, minimal abstraction layers, unified event types.
   - 5.2 New File Layout — Reorganized source tree with clear responsibilities per file.
   - 5.3 Simplified Public API — What's exported from `__init__.py`. What's removed, renamed, or consolidated.
   - 5.4 The Refactored Client Layer — `LiteLLMClient` as primary, optional `DirectOpenAIClient` as fallback for zero-dependency vLLM usage.
   - 5.5 The Refactored Kernel — Same core loop, but with clearer config (no `ModelAdapter` indirection), unified event emission (no duplicates), and explicit provider awareness.
   - 5.6 The Refactored Parser — `DefaultResponseParser` (renamed from `QwenResponseParser`), consistent `ToolCall` typing.
   - 5.7 The Refactored Grammar Pipeline — Provider-aware constraint generation. Explicit "this only works with vLLM" scoping.
   - 5.8 The Refactored Event System — Unified event format (all Pydantic? all dataclass? proposal with rationale).
   - 5.9 Impact on Remora — How each Remora file changes with the refactored structured-agents. Can the LSP runner finally use AgentKernel?

6. **[Migration Path & Risk Assessment](#6-migration-path--risk-assessment)** — How to get from the current state to the proposed architecture without breaking Remora. Phased approach with validation gates.
   - 6.1 Phase 0: Bug Fixes (No API Changes) — Fix double event emission, remove debug prints, rename parser. Safe, backward-compatible.
   - 6.2 Phase 1: LiteLLM Client Addition — Add `LiteLLMClient` alongside `OpenAICompatibleClient`. Update `build_client()`. Remora starts using LiteLLM model strings.
   - 6.3 Phase 2: Concept Cleanup — Flatten `ModelAdapter`, fix `tool_calls` typing, consolidate `CompletionResponse` normalization.
   - 6.4 Phase 3: LSP Runner Unification — Refactor LSP runner to use AgentKernel. Eliminate duplicate tool loop, naming collisions, and custom tool call parser.
   - 6.5 Phase 4: Event Unification — Migrate to unified event format across structured-agents and Remora.
   - 6.6 Phase 5: Remove Dead Code — Delete unused `Agent` class, `GrailTool`/`discover_tools()`, old `OpenAICompatibleClient` (if fully replaced by LiteLLM).
   - 6.7 Risk Assessment — What could go wrong at each phase. Rollback strategies.

7. **[Open Questions](#7-open-questions)** — Remaining unknowns and decisions that need input.
   - 7.1 Should structured-agents still exist as a separate library, or should it be folded into Remora?
   - 7.2 LiteLLM `extra_body` passthrough — still unverified.
   - 7.3 Event format unification — Pydantic or dataclass?
   - 7.4 Should `kernel.run()` become an async generator for streaming support?
   - 7.5 Config simplification — should Remora's `providers` section be eliminated in favor of LiteLLM's model prefix convention?
   - 7.6 Version strategy — how to version structured-agents through the refactor (breaking changes).

---

## 1. Current structured-agents Architecture

structured-agents (v0.3.4) is a small but opinionated library for running tool-using LLM agents. It lives at `.context/structured-agents_v0.3.4/src/structured_agents/` and is vendored into Remora. Here's the full internals.

### 1.1 File Inventory & Size

| File | Lines | Primary Responsibility |
|------|-------|----------------------|
| `__init__.py` | 87 | Public API exports (35+ symbols) |
| `types.py` | 167 | Core data types: Message, ToolCall, ToolResult, ToolSchema, TokenUsage, StepResult, RunResult |
| `exceptions.py` | 43 | Exception hierarchy: StructuredAgentsError → KernelError, ToolExecutionError, BundleError, AdapterError |
| `kernel.py` | 275 | AgentKernel — the step loop (format → constrain → call → parse → execute tools) |
| `agent.py` | 167 | Agent class, AgentManifest, load_manifest(), adapter registry |
| `client/__init__.py` | 7 | Client subpackage exports |
| `client/protocol.py` | 56 | LLMClient Protocol + CompletionResponse dataclass |
| `client/openai.py` | 115 | OpenAICompatibleClient (wraps AsyncOpenAI) + build_client() factory |
| `models/__init__.py` | 14 | Model adapter subpackage exports |
| `models/adapter.py` | 40 | ModelAdapter dataclass (carries parser + constraint pipeline + formatters) |
| `models/parsers.py` | 64 | ResponseParser Protocol + QwenResponseParser (the only concrete parser) |
| `grammar/__init__.py` | 17 | Grammar subpackage exports |
| `grammar/config.py` | 20 | DecodingConstraint dataclass (strategy, allow_parallel_calls, send_tools_to_api, schema_model) |
| `grammar/pipeline.py` | 99 | ConstraintPipeline — generates vLLM-specific extra_body payloads |
| `grammar/models.py` | 11 | StructuredOutputModel (BaseModel base class for JSON schema outputs) |
| `events/__init__.py` | 28 | Event subpackage exports |
| `events/observer.py` | 30 | Observer Protocol + NullObserver + CompositeObserver |
| `events/types.py` | 75 | 7 event dataclasses: KernelStart/End, ModelRequest/Response, ToolCall/Result, TurnComplete |
| `tools/__init__.py` | 7 | Tool subpackage exports |
| `tools/protocol.py` | 17 | Tool Protocol (schema + execute) |
| `tools/grail.py` | 99 | GrailTool (wraps grail scripts) + discover_tools() |

**Total: ~1,438 lines across 21 files.** A small library.

### 1.2 Core Data Types

All defined in `types.py`. All are frozen dataclasses (immutable).

**`Message`** — A chat message. Fields: `role` (str), `content` (str | None), `tool_calls` (list[ToolCall] | None), `tool_call_id` (str | None), `name` (str | None). Has `to_openai_format()` method that converts to an OpenAI-compatible dict. This is the universal message format throughout the library.

**`ToolCall`** — A request from the model to call a tool. Fields: `id` (str), `name` (str), `arguments_json` (str). Has `create(name, arguments)` classmethod for convenience.

**`ToolResult`** — The result of executing a tool. Fields: `call_id` (str), `name` (str), `content` (str), `is_error` (bool). Has `to_message()` method that creates a `Message` with `role="tool"`.

**`ToolSchema`** — Describes a tool for the model. Fields: `name` (str), `description` (str), `parameters` (dict — JSON Schema). Has `to_openai_format()` that wraps in the OpenAI `{"type": "function", "function": {...}}` envelope.

**`TokenUsage`** — Token accounting. Fields: `prompt_tokens` (int), `completion_tokens` (int), `total_tokens` (int).

**`StepResult`** — Result of a single kernel step (one LLM call + tool executions). Fields: `messages` (list[Message]), `tool_results` (list[ToolResult]), `usage` (TokenUsage | None), `finish_reason` (str | None).

**`RunResult`** — Result of a full kernel run (multiple steps). Fields: `final_message` (str | None), `history` (list[Message]), `turn_count` (int), `termination_reason` (str).

**Data flow through types:**
```
Input: list[Message]
  ↓ kernel.step()
  → Message.to_openai_format() → list[dict]  (for LLM API call)
  → ToolSchema.to_openai_format() → list[dict]  (for LLM API call)
  ↓ LLM responds
  → CompletionResponse  (from client layer)
  ↓ ResponseParser.parse()
  → (content: str, tool_calls: list[ToolCall])
  ↓ tool execution
  → list[ToolResult]  →  ToolResult.to_message()  →  list[Message]
  ↓ append to history
  → StepResult
  ↓ kernel.run() accumulates steps
  → RunResult
```

### 1.3 The Client Layer

**`LLMClient` Protocol** (`client/protocol.py`):
```python
class LLMClient(Protocol):
    model: str
    async def chat_completion(
        self, messages, tools, tool_choice, max_tokens, temperature, extra_body, model
    ) -> CompletionResponse: ...
    async def close(self) -> None: ...
```

This is the sole point of contact between the kernel and the outside world. It's clean, minimal, and provider-agnostic in design. The `model` parameter on `chat_completion()` allows per-call model override while the instance carries a default.

**`CompletionResponse`** (`client/protocol.py`):
```python
@dataclass(frozen=True)
class CompletionResponse:
    content: str | None
    tool_calls: list[dict] | None    # ← Note: list[dict], not list[ToolCall]
    usage: TokenUsage | None
    finish_reason: str | None
    raw_response: dict
```

Important: `tool_calls` is typed as `list[dict] | None` — raw dicts in OpenAI format (`{"id": ..., "type": "function", "function": {"name": ..., "arguments": ...}}`). The `ResponseParser` converts these dicts into `ToolCall` dataclasses. This is a type confusion point we'll revisit in Section 4.

**`OpenAICompatibleClient`** (`client/openai.py`):
The sole concrete `LLMClient` implementation. Wraps `AsyncOpenAI`. Straightforward: constructs kwargs from the Protocol parameters, calls `self._client.chat.completions.create(**kwargs)`, converts the response to `CompletionResponse`.

Notable: has DEBUG `print()` statements at lines 53-54 and 60 that should be removed.

**`build_client(config: dict)`** (`client/openai.py`):
Factory function that takes a flat config dict (`base_url`, `api_key`, `model`, `timeout`) and returns `OpenAICompatibleClient`. This is the only way structured-agents creates clients.

### 1.4 The Kernel

`AgentKernel` (`kernel.py`) is the core. It's a dataclass with these fields:

```python
@dataclass
class AgentKernel:
    client: LLMClient
    adapter: ModelAdapter
    tools: list[Tool]
    observer: Observer = field(default_factory=NullObserver)
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
```

**`step(messages)` method** — One turn of the agent loop:

1. **Format messages** via `adapter.format_messages()` (defaults to `Message.to_openai_format()`)
2. **Format tools** via `adapter.format_tools()` (defaults to `ToolSchema.to_openai_format()`)
3. **Get grammar constraint** via `adapter.constraint_pipeline.constrain(tools)` (returns `extra_body` dict or empty)
4. **Emit `ModelRequestEvent`** (turn number, message count, tool count, model name)
5. **Call `client.chat_completion()`** with formatted messages, tools, tool_choice, max_tokens, temperature, extra_body, model
6. **Emit `ModelResponseEvent`** (turn number, duration, content, tool_calls_count, usage)
7. **Parse response** via `adapter.response_parser.parse(content, tool_calls)` → `(content_str, list[ToolCall])`
8. **Execute tools** — if tool calls exist, execute them (sequential or concurrent via semaphore), emit `ToolCallEvent` and `ToolResultEvent` per tool
9. **Build and return `StepResult`**

**`run(messages, max_turns)` method** — The outer loop:

1. Emit `KernelStartEvent`
2. Loop up to `max_turns` times:
   a. **Emit `ModelRequestEvent`** ← **BUG: This is emitted AGAIN inside step() — double emission**
   b. Call `step(messages)`
   c. Append step results to message history
   d. Emit `TurnCompleteEvent`
   e. If no tool calls in the step result → terminate (model is done calling tools)
3. Emit `KernelEndEvent`
4. Return `RunResult`

**The double `ModelRequestEvent` bug**: `run()` emits `ModelRequestEvent` at line 233 before calling `step()`. Then `step()` emits it again at line 87. Every turn produces two identical events. This is clearly a bug — the emission in `run()` should be removed.

### 1.5 The Model Adapter

**`ModelAdapter`** (`models/adapter.py`):
```python
@dataclass
class ModelAdapter:
    name: str
    response_parser: ResponseParser
    constraint_pipeline: ConstraintPipeline | None = None
    format_messages: Callable = Message.to_openai_format  # static method
    format_tools: Callable = ToolSchema.to_openai_format  # static method
```

This is an almost-no-op abstraction. In practice:
- `format_messages` is always `Message.to_openai_format()` — never overridden
- `format_tools` is always `ToolSchema.to_openai_format()` — never overridden
- `constraint_pipeline` is sometimes `None`, sometimes a `ConstraintPipeline`
- `response_parser` is always `QwenResponseParser` (the only parser)

The adapter's real value is carrying the `response_parser` and optional `constraint_pipeline`. The format functions are dead weight.

**`ResponseParser` Protocol** (`models/parsers.py`):
```python
class ResponseParser(Protocol):
    def parse(self, content: str | None, tool_calls: list[dict] | None) -> tuple[str | None, list[ToolCall]]: ...
```

**`QwenResponseParser`** — The only concrete parser. Despite its name, it handles ALL models:
1. If API `tool_calls` (list of dicts) are present → converts each dict's `function` key to a `ToolCall` dataclass
2. If text content contains `<tool_call>` XML tags → extracts tool calls from XML
3. Returns `(content, list[ToolCall])`

The XML parsing is for models that emit tool calls as text (some open-source models). The dict-based parsing is for models with native function calling (OpenAI, Anthropic via LiteLLM, etc.).

**`_ADAPTER_REGISTRY`** (`agent.py`):
```python
_ADAPTER_REGISTRY = {
    "qwen": QwenResponseParser,
    "function_gemma": QwenResponseParser,
}
```

`get_response_parser(model_name)` checks if any key in this dict is a substring of the model name. If yes, returns that parser class. If no, returns `QwenResponseParser` anyway. So the registry is purely cosmetic — everything resolves to `QwenResponseParser`.

### 1.6 The Grammar/Constraint Pipeline

This subsystem generates vLLM-specific `extra_body` payloads for constrained decoding.

**`DecodingConstraint`** (`grammar/config.py`):
```python
@dataclass(frozen=True)
class DecodingConstraint:
    strategy: str  # "ebnf", "structural_tag", "json_schema"
    allow_parallel_calls: bool = True
    send_tools_to_api: bool = True
    schema_model: type[StructuredOutputModel] | None = None
```

**`ConstraintPipeline`** (`grammar/pipeline.py`):
Takes a `DecodingConstraint`, provides `constrain(tools) → dict` method.
- For `structural_tag` strategy → builds `{"structural_tag": {"begin": "<tool_call>", ...}}` payload
- For `json_schema` strategy → builds `{"guided_json": <schema>}` payload from the Pydantic `schema_model`
- Returns dict to be passed as `extra_body` to `client.chat_completion()`

**Key fact:** This entire subsystem is **vLLM-specific**. The `extra_body` payloads it generates are vLLM extensions to the OpenAI API. Other providers ignore or reject them. With LiteLLM, this needs careful handling — the grammar constraints should only be applied when the target is a vLLM server.

**`StructuredOutputModel`** (`grammar/models.py`):
```python
class StructuredOutputModel(BaseModel):
    """Base class for Pydantic models used as JSON schema constraints."""
    pass
```

A marker base class. User defines a Pydantic model inheriting from this; `ConstraintPipeline` extracts its JSON schema for the `json_schema` strategy.

### 1.7 The Event System

7 event types, all frozen dataclasses in `events/types.py`:

| Event | Fields | Emitted When |
|-------|--------|-------------|
| `KernelStartEvent` | max_turns, tools_count | `run()` starts |
| `KernelEndEvent` | total_turns, termination_reason | `run()` ends |
| `ModelRequestEvent` | turn, messages_count, tools_count, model | Before LLM call (emitted TWICE per turn — bug) |
| `ModelResponseEvent` | turn, duration_ms, content, tool_calls_count, usage | After LLM call |
| `ToolCallEvent` | turn, tool_name, call_id, arguments | Before tool execution |
| `ToolResultEvent` | turn, tool_name, call_id, content, is_error, duration_ms | After tool execution |
| `TurnCompleteEvent` | turn, messages_count, tool_results_count | After all tools in a turn |

`Event` = `Union[KernelStartEvent, KernelEndEvent, ModelRequestEvent, ModelResponseEvent, ToolCallEvent, ToolResultEvent, TurnCompleteEvent]`

**`Observer` Protocol** (`events/observer.py`):
```python
class Observer(Protocol):
    def emit(self, event: Event) -> None: ...
```

Synchronous. `NullObserver` is a no-op. `CompositeObserver` fans out to multiple observers.

Remora's `EventBus` implements this Protocol and bridges to its own async event system.

### 1.8 The Agent & Manifest Layer

**`AgentManifest`** (`agent.py`):
```python
@dataclass
class AgentManifest:
    name: str
    system_prompt: str
    agents_dir: Path
    limits: dict
    model: str
    grammar_config: DecodingConstraint | None
    max_turns: int
```

`load_manifest(bundle_path)` reads `bundle.yaml` and returns `AgentManifest`. It reads `model` from `bundle.yaml`'s `model.plugin` key (specific nesting path).

**`Agent` class** (`agent.py`):
```python
class Agent:
    def __init__(self, kernel, manifest): ...
    
    @classmethod
    def from_bundle(cls, bundle_path, ...):
        # Reads env vars: STRUCTURED_AGENTS_BASE_URL, STRUCTURED_AGENTS_API_KEY
        # Creates OpenAICompatibleClient via build_client()
        # Creates ModelAdapter, AgentKernel
        # Discovers tools via discover_tools()
        ...
    
    async def run(self, user_input: str) -> RunResult: ...
```

**Remora never uses this class.** It builds kernels directly via `kernel_factory.py`. The `Agent` class reads its own env vars (`STRUCTURED_AGENTS_BASE_URL`) which conflicts with Remora's `Config` system. This class is dead code from Remora's perspective.

### 1.9 The Tool Layer

**`Tool` Protocol** (`tools/protocol.py`):
```python
class Tool(Protocol):
    @property
    def schema(self) -> ToolSchema: ...
    async def execute(self, arguments: dict, context: dict | None = None) -> ToolResult: ...
```

Clean and minimal. The kernel calls `tool.schema` to get the schema for the LLM, and `tool.execute(arguments, context)` to run it.

**`GrailTool`** (`tools/grail.py`):
Wraps a `grail.GrailScript`. Builds `ToolSchema` from the script's input definitions. Executes by calling `script.run()`.

**`discover_tools(agents_dir)`** (`tools/grail.py`):
Globs `*.pym` files in the given directory, loads each as a `GrailTool`.

**Remora doesn't use either of these.** Remora has its own tool implementations (`FunctionTool` in `chat.py`, grail tools in `core/tools/grail.py`, swarm tools in `core/tools/swarm.py`). structured-agents' `GrailTool` and `discover_tools()` are unused.

### 1.10 Data Flow Diagram

```
User provides: list[Message] + max_turns

kernel.run(messages, max_turns)
│
├─ emit KernelStartEvent
│
├─ for turn in 1..max_turns:
│   │
│   ├─ emit ModelRequestEvent  ← BUG: duplicate (also in step())
│   │
│   ├─ kernel.step(messages)
│   │   │
│   │   ├─ formatted_msgs = adapter.format_messages(messages)     # → list[dict]
│   │   ├─ formatted_tools = adapter.format_tools(tool_schemas)   # → list[dict]
│   │   ├─ extra_body = adapter.constraint_pipeline.constrain(tools)  # → dict (vLLM grammar)
│   │   │
│   │   ├─ emit ModelRequestEvent  ← first real emission
│   │   ├─ response = client.chat_completion(
│   │   │      messages=formatted_msgs,
│   │   │      tools=formatted_tools,
│   │   │      tool_choice=self.tool_choice,
│   │   │      max_tokens=self.max_tokens,
│   │   │      temperature=self.temperature,
│   │   │      extra_body=extra_body,
│   │   │      model=adapter.name
│   │   │  )
│   │   ├─ emit ModelResponseEvent
│   │   │
│   │   ├─ content, tool_calls = adapter.response_parser.parse(
│   │   │      response.content, response.tool_calls
│   │   │  )
│   │   │
│   │   ├─ for each tool_call:
│   │   │   ├─ emit ToolCallEvent
│   │   │   ├─ result = tool.execute(arguments, context)
│   │   │   ├─ emit ToolResultEvent
│   │   │   └─ append ToolResult.to_message() to messages
│   │   │
│   │   └─ return StepResult
│   │
│   ├─ append step messages to history
│   ├─ emit TurnCompleteEvent
│   │
│   └─ if no tool_calls → break (model is done)
│
├─ emit KernelEndEvent
└─ return RunResult(final_message, history, turn_count, termination_reason)
```

### 1.11 Dependency Graph

```
kernel.py ──→ client/protocol.py (LLMClient, CompletionResponse)
    │     ──→ models/adapter.py (ModelAdapter)
    │     ──→ tools/protocol.py (Tool)
    │     ──→ events/types.py (all event types)
    │     ──→ events/observer.py (Observer)
    │     ──→ types.py (Message, ToolCall, ToolResult, StepResult, RunResult)
    │
models/adapter.py ──→ models/parsers.py (ResponseParser)
    │              ──→ grammar/pipeline.py (ConstraintPipeline)
    │              ──→ types.py (Message, ToolSchema)
    │
client/openai.py ──→ client/protocol.py
    │            ──→ openai (AsyncOpenAI)  ← external dep
    │
grammar/pipeline.py ──→ grammar/config.py (DecodingConstraint)
    │               ──→ grammar/models.py (StructuredOutputModel)
    │
agent.py ──→ kernel.py
    │    ──→ client/openai.py (build_client)
    │    ──→ models/adapter.py
    │    ──→ models/parsers.py
    │    ──→ tools/grail.py (discover_tools)
    │
tools/grail.py ──→ tools/protocol.py
    │          ──→ grail (external, optional)
```

**Key observations:**
- The kernel depends on the Protocol/interface layers, not on concrete implementations. Good design.
- `agent.py` is the only file that wires everything together — and Remora bypasses it entirely.
- The `openai` SDK is the sole external dependency at the client layer.
- `grammar/` is entirely self-contained but generates vLLM-specific output.

---

## 2. How Remora Uses structured-agents

This section maps every integration point between Remora and structured-agents. The key finding: Remora uses structured-agents heavily but inconsistently — some paths use the full kernel stack, one path bypasses it entirely, and several structured-agents features go unused.

### 2.1 Import Map

Every Remora file that imports from structured-agents, what it imports, and what layer it touches:

| Remora File | Imports | Layer |
|---|---|---|
| `core/kernel_factory.py` | `get_response_parser`, `build_client`, `ConstraintPipeline`, `AgentKernel`, `ModelAdapter` | Client + Kernel + Models + Grammar |
| `core/swarm_executor.py` | `load_manifest`, `build_client`, `Message` | Agent + Client + Types |
| `core/chat.py` | `Tool`, `Message` (as KernelMessage), `ToolCall`, `ToolResult`, `ToolSchema` | Types + Tools Protocol |
| `core/events.py` | All 7 event types (re-exports them) | Events |
| `core/event_store.py` | `Event as StructuredEvent` | Events |
| `core/event_bus.py` | `Event as StructuredEvent` | Events |
| `core/tools/grail.py` | `ToolCall`, `ToolSchema`, `ToolResult` | Types |
| `core/tools/swarm.py` | `ToolCall`, `ToolResult`, `ToolSchema` | Types |
| `core/tools/spawn_child.py` | `ToolCall`, `ToolResult`, `ToolSchema` | Types |
| `lsp/runner.py` | `build_client` (lazy import) | Client |
| `ui/projector.py` | `Event as StructuredEvent` | Events |

**Pattern:** Most Remora files import **types** (Message, ToolCall, ToolResult, ToolSchema) and **events**. Only `kernel_factory.py` uses the full kernel + adapter + grammar stack. Only `kernel_factory.py` and `swarm_executor.py` create clients. The LSP runner touches only `build_client`.

### 2.2 Execution Path A: SwarmExecutor → kernel_factory → AgentKernel

This is the **primary path** for automated agent execution in Remora.

**Flow:**
```
SwarmExecutor.__init__(config, event_bus, event_store, ...)
  └─ self._client = build_client({base_url, api_key, model, timeout})
       └─ Creates ONE OpenAICompatibleClient (connection pooling)

SwarmExecutor.run_agent(agent_node)
  ├─ manifest = load_manifest(bundle_path)
  ├─ model_name = self._resolve_model_name(bundle_path, manifest)
  │     └─ Re-reads bundle.yaml for model.id / model.name / model.model
  ├─ tools = discover_grail_tools(...)  # Remora's own tool discovery, NOT s-a's
  ├─ prompt = build_prompt(manifest.system_prompt, agent_node, ...)
  └─ self._run_kernel(manifest, prompt, tools, model_name=model_name)

SwarmExecutor._run_kernel(manifest, prompt, tools, *, model_name, ...)
  ├─ kernel = create_kernel(
  │     client=self._client,    # ← reuses the pooled client
  │     model_name=model_name,
  │     tools=tools,
  │     observer=event_bus,     # EventBus implements Observer Protocol
  │     grammar_config=manifest.grammar_config,
  │  )
  ├─ messages = [Message(role="system", content=prompt),
  │              Message(role="user", content=user_input)]
  └─ result = await kernel.run(messages, max_turns=manifest.max_turns)
```

**Key details:**
- **Connection pooling:** `SwarmExecutor` creates one `OpenAICompatibleClient` in `__init__` and passes it to every `create_kernel()` call via `client=self._client`. Multiple agents share the same HTTP connection pool.
- **Double YAML read:** `load_manifest()` reads `bundle.yaml` for the manifest. Then `_resolve_model_name()` reads `bundle.yaml` AGAIN to extract the model name (because the manifest's `model` field uses a different key path — `model.plugin` — than what Remora expects — `model.id`/`model.name`/`model.model`).
- **Remora's own tool discovery:** Uses `discover_grail_tools()` from `remora/core/tools/grail.py`, NOT `discover_tools()` from structured-agents. Remora's version wraps tools with context and file providers.
- **Event bridging:** `event_bus` (Remora's `EventBus`) is passed as the `observer` to `AgentKernel`. It implements the structured-agents `Observer` Protocol and bridges dataclass events into Remora's async event system.

### 2.3 Execution Path B: ChatSession → kernel_factory → AgentKernel

The interactive chat path. Used for direct user-to-agent conversations.

**Flow:**
```
ChatSession(config, tools, observer, ...)
  # No client created yet

ChatSession.send(user_message)
  ├─ kernel = create_kernel(
  │     model_name=config.model,
  │     base_url=config.base_url,
  │     api_key=config.api_key,
  │     timeout=config.timeout,
  │     tools=self._tools,          # FunctionTool instances
  │     observer=self._observer,
  │     grammar_config=config.grammar_config,
  │     # Note: NO client= parameter — creates a new one each time
  │  )
  ├─ messages = [system_msg] + self._history + [user_msg]
  └─ result = await kernel.run(messages, max_turns=config.max_turns)
```

**Key details:**
- **No connection pooling:** Every `send()` call creates a new `AgentKernel` and therefore a new `OpenAICompatibleClient` and `AsyncOpenAI` instance. Each call opens a fresh HTTP connection.
- **Custom tools:** Uses `FunctionTool` (defined in `chat.py`), which wraps Python callables as tools implementing the structured-agents `Tool` Protocol.
- **Simpler config:** Takes model info from a `ChatConfig` dataclass rather than `bundle.yaml`.

### 2.4 Execution Path C: LSP Runner → Own Tool Loop (No Kernel)

This is the **divergent path** that does NOT use `AgentKernel`. It's the most structurally concerning finding.

**Flow:**
```
AgentRunner.__init__(server, agent_node, observer, ...)
  └─ self.llm = LLMClient(config)   # ← This is runner.py's OWN LLMClient class
        └─ self._client = build_client({...})  # Uses s-a's build_client for the underlying client

AgentRunner.execute_turn(messages)
  ├─ tools_schemas = [tool_dict for tool in self.tools]  # Raw dicts, NOT ToolSchema
  │
  ├─ # OWN TOOL LOOP (not AgentKernel):
  ├─ for turn in range(max_turns):
  │   ├─ response = await self.llm.chat(messages, tools_schemas)
  │   │     └─ Calls self._client.chat_completion() internally
  │   │     └─ Returns runner.py's OWN LLMResponse model (not CompletionResponse)
  │   │
  │   ├─ # Extract tool calls — TWO methods:
  │   ├─ tool_calls = response.tool_calls  # From API response
  │   ├─ if not tool_calls:
  │   │   └─ tool_calls = self._extract_text_tool_calls(response.content)
  │   │         └─ OWN XML parser for <tool_call> tags (duplicates QwenResponseParser logic)
  │   │
  │   ├─ for tool_call in tool_calls:  # These are runner.py's OWN ToolCall model
  │   │   ├─ result = await self._execute_tool(tool_call)
  │   │   └─ messages.append(tool_result_message)
  │   │
  │   └─ if no tool_calls → break
  │
  └─ return final_response
```

**What the LSP runner duplicates from structured-agents:**

| Concept | structured-agents Version | LSP Runner Version |
|---|---|---|
| Tool loop | `AgentKernel.run()` / `step()` | `AgentRunner.execute_turn()` |
| LLM client wrapper | `LLMClient` Protocol | Own `LLMClient` class (same name!) |
| Tool call model | `ToolCall` dataclass | Own `ToolCall` Pydantic model (same name!) |
| LLM response model | `CompletionResponse` | Own `LLMResponse` Pydantic model |
| XML tool call parsing | `QwenResponseParser._parse_xml_tool_calls()` | `_extract_text_tool_calls()` |
| Tool format | `ToolSchema.to_openai_format()` | Raw dicts constructed manually |
| Event emission | Via `Observer` Protocol | Direct calls to own event methods |

**Why this is problematic:**
1. **Two codebases to maintain.** Any change to the agent loop logic (error handling, retry, timeout, tool execution) must be made in two places.
2. **Naming collisions.** `ToolCall` and `LLMClient` mean different things depending on whether you're in the LSP runner or the kernel path. This is a source of confusion.
3. **Different capabilities.** The kernel path has grammar constraints, concurrent tool execution via semaphore, configurable tool_choice, and the full observer event stream. The LSP runner has none of these.
4. **The LSP runner should use AgentKernel.** There's no fundamental reason it can't — the kernel is flexible enough. The duplication appears to be historical (the LSP runner was built independently or before the kernel was mature enough).

### 2.5 Remora Extensions

Where Remora adds functionality on top of structured-agents:

**Custom Tool Implementations:**
- `FunctionTool` (`chat.py`) — Wraps Python callables as `Tool` Protocol implementations. Used in ChatSession.
- `GrailToolWrapper` (`core/tools/grail.py`) — Remora's own grail tool implementation with context/files_provider. Different from s-a's `GrailTool`.
- `SwarmBaseTool` (`core/tools/swarm.py`) — Base class for swarm-specific tools.
- `SpawnChildTool` (`core/tools/spawn_child.py`) — Tool that spawns child agents.

All of these implement the structured-agents `Tool` Protocol. This is a clean extension point — structured-agents defines the Protocol, Remora provides the implementations. No issues here.

**Event System Bridging:**
- `EventBus` (`core/event_bus.py`) — Implements the s-a `Observer` Protocol. Accepts both `StructuredEvent` (s-a dataclasses) and `RemoraEvent` (Pydantic models). Routes to async subscribers.
- `EventStore` (`core/event_store.py`) — Persists events. Accepts both types. Serializes dataclass events via `asdict()`, Pydantic events via `model_dump()`.
- `core/events.py` — Re-exports all 7 s-a event types alongside Remora-specific event types. Defines `RemoraEvent` union.

This bridging works but is awkward. Two serialization paths, two type systems, duck typing to distinguish them. Unifying the event format would simplify this significantly.

**`kernel_factory.py`:**
Remora's own factory that wraps structured-agents' construction into a single `create_kernel()` call. This is Remora's primary point of contact with the kernel. It's a clean integration pattern — structured-agents provides the pieces, Remora assembles them.

### 2.6 Remora Duplications

Where Remora re-implements things structured-agents already does:

| Duplicated Feature | s-a Location | Remora Location | Notes |
|---|---|---|---|
| Tool execution loop | `kernel.py` step/run | `lsp/runner.py` execute_turn | Complete duplication of the agent loop |
| XML tool call parsing | `parsers.py` QwenResponseParser | `lsp/runner.py` _extract_text_tool_calls | Same regex-based XML parsing |
| LLM client wrapping | `client/protocol.py` LLMClient | `lsp/runner.py` LLMClient class | Wraps the same underlying client |
| Tool call type | `types.py` ToolCall (dataclass) | `lsp/runner.py` ToolCall (Pydantic) | Different type, same concept |
| Tool discovery | `tools/grail.py` discover_tools | `core/tools/grail.py` discover_grail_tools | Different implementations, same concept |
| Model name resolution | `agent.py` load_manifest (model.plugin) | `swarm_executor.py` _resolve_model_name (model.id) | Read same YAML, different key paths |

The LSP runner is the biggest source of duplication. The tool discovery and model name resolution are minor but add confusion.

### 2.7 Unused structured-agents Features

What Remora never touches:

| Feature | Location | Why Unused |
|---|---|---|
| `Agent` class | `agent.py` | Remora builds kernels directly via `kernel_factory.py`. Agent reads its own env vars which conflict with Remora's Config. |
| `Agent.from_bundle()` | `agent.py` | Same as above — Remora has its own bundle loading in SwarmExecutor. |
| `GrailTool` | `tools/grail.py` | Remora has its own grail tool wrapper with richer context handling. |
| `discover_tools()` | `tools/grail.py` | Remora has its own `discover_grail_tools()`. |
| `format_messages` on ModelAdapter | `models/adapter.py` | Always uses default. Never overridden. |
| `format_tools` on ModelAdapter | `models/adapter.py` | Always uses default. Never overridden. |
| `_ADAPTER_REGISTRY` (effectively) | `agent.py` | All entries map to QwenResponseParser, which is the default anyway. |

**Summary:** Remora uses ~60% of structured-agents' surface area. The core kernel loop, the LLMClient Protocol, the types (Message, ToolCall, ToolResult, ToolSchema), the event system, and the grammar pipeline are all heavily used. The Agent class, tool discovery, GrailTool, and the format functions on ModelAdapter are dead weight.

---

## 3. LiteLLM Integration into structured-agents

The user's directive: **"I like the idea of putting LiteLLM inside structured-agents."** This is Option A from Section 9.3.1 of the LLM Provider Enhancement doc. This section designs it in detail.

### 3.1 Why Option A (Not Option B)

The LLM Provider Enhancement doc recommended Option B (Hybrid: ProviderRegistry + LiteLLM as transport in Remora, structured-agents unchanged). The user prefers Option A. Here's why Option A makes sense given the key constraint:

**structured-agents is ONLY used inside Remora.** This changes the calculus:

- **Option B's main advantage was keeping structured-agents "clean" for independent use.** But if it's never used independently, this advantage is zero. We're maintaining a separation that serves no one.
- **Option B requires a ProviderRegistry layer in Remora.** That's ~150 lines of config management, factory registration, named providers, and connection pooling — all sitting between Remora and structured-agents. With Option A, this entire layer is eliminated because LiteLLM's model prefix routing IS the provider routing mechanism.
- **Option A is simpler.** One client in structured-agents that handles all providers. No registry, no factory pattern, no per-provider type mapping. `model="anthropic/claude-sonnet-4-20250514"` just works.

**The "heavy dependency" concern from Section 9 is weaker in Option A's context:**
- Since structured-agents is only used inside Remora, the dependency chain is: Remora → structured-agents → litellm. This is equivalent to Remora → litellm. Whether the dependency is in structured-agents or Remora is a packaging question, not an architecture one.
- If structured-agents were ever extracted for independent use, the LiteLLM dependency could be made optional at that point. But we're not there, and YAGNI applies.

**What Option A eliminates from the system:**
- `ProviderRegistry` (~150 lines)
- `ProviderConfig` dataclass
- `register_provider_type()` machinery
- `build_registry_from_config()` bridge function
- `_build_litellm_provider()` factory
- `providers/` subpackage in Remora
- `ModelSpec` and `_resolve_model_spec()` in SwarmExecutor
- Extended `create_kernel()` signature with `provider_name` and `registry` params

All of these are replaced by: pass a model string with a LiteLLM prefix to `AgentKernel`.

### 3.2 The New Client: `LiteLLMClient`

This replaces `OpenAICompatibleClient` as the primary `LLMClient` implementation.

```python
# structured_agents/client/litellm_client.py  (NEW file, ~80 lines)

import litellm
from .protocol import CompletionResponse, LLMClient
from ..types import TokenUsage

class LiteLLMClient:
    """LLM client using LiteLLM for universal provider support.
    
    Model routing is via LiteLLM's prefix convention:
      - "anthropic/claude-sonnet-4-20250514"  → Anthropic API
      - "openai/gpt-4o"                 → OpenAI API
      - "hosted_vllm/Qwen/Qwen3-4B"     → Local vLLM server
      - "ollama/qwen2.5:7b"             → Local Ollama
      - "groq/llama-3.3-70b-versatile"   → Groq API
    
    API keys are passed per-call or via environment variables
    (ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.)
    """
    
    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str = "",
        timeout: float = 300.0,
    ):
        self.model = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout = timeout
    
    async def chat_completion(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        tool_choice: str = "auto",
        max_tokens: int = 4096,
        temperature: float = 0.1,
        extra_body: dict | None = None,
        model: str | None = None,
    ) -> CompletionResponse:
        kwargs: dict = {
            "model": model or self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": self._timeout,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if self._api_key:
            kwargs["api_key"] = self._api_key
        if self._base_url:
            kwargs["api_base"] = self._base_url
        if extra_body:
            kwargs["extra_body"] = extra_body
        
        response = await litellm.acompletion(**kwargs)
        return self._to_completion_response(response)
    
    def _to_completion_response(self, response) -> CompletionResponse:
        choice = response.choices[0]
        message = choice.message
        
        # Tool calls: LiteLLM normalizes all providers to OpenAI format
        tool_calls = None
        if message.tool_calls:
            tool_calls = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
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
            content=message.content,
            tool_calls=tool_calls,
            usage=usage,
            finish_reason=choice.finish_reason,
            raw_response=response.model_dump() if hasattr(response, 'model_dump') else {},
        )
    
    async def close(self) -> None:
        # LiteLLM manages its own HTTP clients internally
        pass
```

**Key design decisions:**

1. **`model` uses LiteLLM prefix convention.** The model string carries the provider routing information: `"anthropic/claude-sonnet-4-20250514"`, `"hosted_vllm/Qwen/Qwen3-4B"`. No separate provider config needed.

2. **`api_key` and `base_url` are optional per-instance defaults.** LiteLLM also reads standard env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`). The per-instance values override env vars when present.

3. **`extra_body` is passed straight through.** LiteLLM accepts `extra_body` as a kwarg and passes it to the underlying provider SDK. Critical for vLLM grammar constraints.

4. **Response normalization is minimal.** LiteLLM already returns OpenAI-format responses (`ModelResponse` mimicking `ChatCompletion`). We just extract the fields into `CompletionResponse`.

5. **`close()` is a no-op.** LiteLLM manages its own `httpx.AsyncClient` pool internally. We don't have explicit lifecycle control. This is a trade-off: simpler code, but less control over connection lifecycle.

### 3.3 Model Routing

LiteLLM's prefix convention replaces the entire ProviderRegistry concept:

| Provider | Model String | Notes |
|---|---|---|
| Local vLLM | `hosted_vllm/Qwen/Qwen3-4B` | Requires `api_base` to be set |
| OpenAI | `openai/gpt-4o` | Reads `OPENAI_API_KEY` env var |
| Anthropic | `anthropic/claude-sonnet-4-20250514` | Reads `ANTHROPIC_API_KEY` env var |
| Google Gemini | `gemini/gemini-2.0-flash` | Reads `GEMINI_API_KEY` env var |
| Groq | `groq/llama-3.3-70b-versatile` | Reads `GROQ_API_KEY` env var |
| Ollama | `ollama/qwen2.5:7b` | Assumes localhost:11434 |
| OpenRouter | `openrouter/anthropic/claude-3.5-sonnet` | Reads `OPENROUTER_API_KEY` |
| AWS Bedrock | `bedrock/anthropic.claude-v2` | Uses AWS credential chain |

**Impact on Remora config:**

Currently `remora.yaml` has:
```yaml
model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B
model_api_key: ""
```

With LiteLLM inside structured-agents:
```yaml
model_default: hosted_vllm/Qwen/Qwen3-4B   # ← Now includes provider prefix
model_base_url: http://localhost:8000/v1      # ← Still needed for hosted_vllm
model_api_key: ""                             # ← Passed through per-call
```

For multi-provider, API keys go in environment variables (standard convention):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
```

**Impact on `bundle.yaml`:**

Currently:
```yaml
model:
  id: Qwen/Qwen3-4B
```

With LiteLLM:
```yaml
model:
  id: hosted_vllm/Qwen/Qwen3-4B
  # Or for a different provider:
  id: anthropic/claude-sonnet-4-20250514
```

The `provider` field proposed in the LLM Provider Enhancement doc is no longer needed. The provider IS the model string prefix. This is simpler.

### 3.4 API Key Management

LiteLLM supports multiple API key mechanisms, in this priority order:

1. **Per-call `api_key` parameter** — highest priority
2. **Environment variables** — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
3. **LiteLLM config** — `litellm.api_key` global setting

For Remora, the recommended approach:

**For the default provider (local vLLM):** `api_key` is passed from `Config.model_api_key` through to `LiteLLMClient.__init__()`. This preserves the existing config mechanism.

**For additional providers:** API keys via standard environment variables. This is the simplest path and matches industry convention. Remora's `remora.yaml` could optionally support:

```yaml
# Optional: explicitly set API keys in config (with env var expansion)
api_keys:
  anthropic: ${ANTHROPIC_API_KEY}
  openai: ${OPENAI_API_KEY}
```

But this is optional — env vars work out of the box with LiteLLM. No extra config code needed.

**Per-agent API key override:** If a specific agent needs to use a different API key (e.g., a different OpenAI org), the model string + `api_key` in `bundle.yaml` would work:

```yaml
model:
  id: openai/gpt-4o
  api_key: ${TEAM_B_OPENAI_KEY}
```

This would require `_resolve_model_name()` to also extract `api_key` from bundle.yaml and pass it to the kernel. Small change.

### 3.5 `extra_body` Passthrough for vLLM Grammar Constraints

**This is the critical question.** The grammar pipeline generates vLLM-specific `extra_body` payloads:

```python
extra_body = {
    "structured_outputs": {
        "structural_tag": {
            "begin": "<tool_call>",
            "end": "</tool_call>",
            "type": "json",
            "json_schema": {...}
        }
    }
}
```

This is passed to `client.chat_completion(extra_body=extra_body)`, which must forward it to the vLLM server as additional JSON body keys.

**LiteLLM's handling of `extra_body`:**

LiteLLM accepts `extra_body` as a parameter to `acompletion()`. For OpenAI-compatible providers (which `hosted_vllm/` uses), LiteLLM passes `extra_body` through to the underlying `openai.ChatCompletion.create()` call. This is because `hosted_vllm/` internally uses the `openai` SDK — the same path as our current `OpenAICompatibleClient`.

**Evidence this should work:**
- LiteLLM's `hosted_vllm/` prefix is specifically designed for self-hosted vLLM servers
- LiteLLM's docs mention `extra_body` as a supported parameter for custom API options
- The `openai` SDK (which LiteLLM uses under the hood for vLLM) already supports `extra_body`

**Risk mitigation — verification steps:**
1. Write a test that calls `litellm.acompletion(model="hosted_vllm/...", extra_body={"structured_outputs": {...}})` against a local vLLM server
2. Verify the outgoing HTTP request body includes the `structured_outputs` key
3. Verify the vLLM server processes the constraint correctly

**Fallback if `extra_body` doesn't pass through:**
Keep `OpenAICompatibleClient` as a fallback specifically for vLLM. The kernel could detect `hosted_vllm/` prefix models and use the direct client instead of LiteLLM. But this is a last resort — it would reintroduce the dual-client complexity we're trying to eliminate.

### 3.6 What Happens to `OpenAICompatibleClient`

Three options:

**Option 1: Remove entirely.** `LiteLLMClient` handles everything, including `hosted_vllm/`. Simplest architecture. Requires verifying `extra_body` passthrough (Section 3.5).

**Option 2: Keep as fallback.** `LiteLLMClient` is the primary. `OpenAICompatibleClient` exists for users who don't want the LiteLLM dependency or need guaranteed `extra_body` passthrough. `build_client()` chooses based on a flag or model prefix.

**Option 3: Keep but deprecate.** Ship both, recommend `LiteLLMClient`, mark `OpenAICompatibleClient` as deprecated. Remove in the next major version.

**Recommendation: Option 1 (remove), contingent on `extra_body` verification.** Since structured-agents is only used inside Remora, there's no "independent user" who needs the old client. If `extra_body` works with LiteLLM's `hosted_vllm/`, the old client is dead code.

If `extra_body` doesn't work, fall back to Option 2 temporarily while we file a bug with LiteLLM or find a workaround.

### 3.7 What Happens to `build_client()`

Currently:
```python
def build_client(config: dict) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        base_url=config.get("base_url", "http://localhost:8000/v1"),
        api_key=config.get("api_key", "EMPTY"),
        model=config.get("model", ""),
        timeout=config.get("timeout", 300),
    )
```

With LiteLLM:
```python
def build_client(config: dict) -> LiteLLMClient:
    return LiteLLMClient(
        model=config.get("model", ""),
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", ""),
        timeout=config.get("timeout", 300),
    )
```

**The signature doesn't change.** Callers pass the same config dict. The return type changes from `OpenAICompatibleClient` to `LiteLLMClient`, but both satisfy the `LLMClient` Protocol, so all callers work unchanged.

**One subtlety:** the `base_url` is now only relevant for `hosted_vllm/` and `ollama/` prefixed models (providers with custom endpoints). For `openai/` and `anthropic/` models, LiteLLM uses the standard API endpoints automatically. Passing `base_url` for these providers would confuse LiteLLM. The factory should only set `base_url` if the model prefix indicates a custom-endpoint provider.

Updated:
```python
def build_client(config: dict) -> LiteLLMClient:
    model = config.get("model", "")
    # Only pass base_url for providers that need custom endpoints
    needs_base_url = any(model.startswith(p) for p in (
        "hosted_vllm/", "openai/", "ollama/", "text-completion-openai/"
    ))
    return LiteLLMClient(
        model=model,
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", "") if needs_base_url else "",
        timeout=config.get("timeout", 300),
    )
```

Actually, this is getting complicated. A simpler approach: **always pass `base_url` to `LiteLLMClient`, and let `LiteLLMClient` only include `api_base` in the `acompletion()` kwargs when it's non-empty.** LiteLLM ignores `api_base=None`, and only uses it when present. The current design in Section 3.2 already does this:

```python
if self._base_url:
    kwargs["api_base"] = self._base_url
```

So `build_client()` can stay simple — just pass everything through. `LiteLLMClient` handles the conditional logic.

### 3.8 Dependency Impact

Adding `litellm` to structured-agents' dependencies:

**`pyproject.toml` change:**
```toml
[project]
dependencies = [
    "litellm>=1.55,<2.0",
    "pyyaml",
    "pydantic>=2.0",
    # openai is no longer a direct dependency — litellm brings it transitively
]
```

**Transitive dependencies `litellm` brings:**
- `openai` (already a dependency)
- `tiktoken` (token counting)
- `tokenizers` (HuggingFace tokenizers)
- `jinja2` (template rendering for some providers)
- `aiohttp` (async HTTP)
- `click` (CLI, if using litellm CLI)
- `python-dotenv` (env file loading)
- `importlib-metadata`

**This is heavier than the current single `openai` dependency.** But since structured-agents is only used inside Remora (which is a full application, not a library), the additional dependencies are acceptable. Remora already has a large dependency tree.

**The `openai` package is no longer a direct dependency.** LiteLLM depends on `openai` transitively and uses it internally for OpenAI-compatible providers. We can remove `openai` from structured-agents' direct deps. (Or keep it for explicitness — doesn't matter much.)

### 3.9 Connection Management

**Current state:** `OpenAICompatibleClient` wraps `AsyncOpenAI`, which manages its own `httpx.AsyncClient` connection pool. `SwarmExecutor` creates one `OpenAICompatibleClient` and reuses it across agents — this is the connection pooling pattern.

**With `LiteLLMClient`:** LiteLLM manages its own internal `httpx.AsyncClient` pool. We don't create or manage HTTP clients explicitly. The `LiteLLMClient.close()` is a no-op.

**Impact on `SwarmExecutor`'s pooling pattern:**

Currently:
```python
# SwarmExecutor.__init__
self._client = build_client(config)  # One client, shared
# SwarmExecutor._run_kernel
kernel = create_kernel(client=self._client)  # Reuse pooled client
```

With LiteLLM, the pooling happens inside LiteLLM, not at the client-instance level. LiteLLM maintains a global pool of `httpx.AsyncClient` instances keyed by provider. So even if we create multiple `LiteLLMClient` instances, they share the same underlying connection pool.

This means `SwarmExecutor` can simplify:
```python
# SwarmExecutor.__init__
# No explicit client creation needed!
# SwarmExecutor._run_kernel
kernel = create_kernel(
    model_name=model_name,  # e.g., "hosted_vllm/Qwen/Qwen3-4B"
    base_url=config.model_base_url,
    api_key=config.model_api_key,
    ...
)
# create_kernel calls build_client() → LiteLLMClient
# LiteLLM reuses its internal connection pool automatically
```

Or, we can keep the current pattern (create one `LiteLLMClient` and reuse it) for consistency. Either way works — the connection pooling is handled by LiteLLM regardless.

**Recommendation:** Keep the current pooling pattern for now. It's explicit and easy to reason about. The `LiteLLMClient` instance carries the default model name, api_key, and base_url, and the kernel can override the model per-call. One fewer thing to change.

---

## 4. Concept Misalignments & Simplification Opportunities

This section catalogs every place where structured-agents and Remora are misaligned, duplicated, confusing, or over-abstracted. Each item includes analysis and a concrete simplification proposal. These are ordered roughly by impact — biggest wins first.

### 4.1 Two Divergent Execution Paths (Kernel vs. LSP Runner)

**The Problem:**

This is the single biggest structural issue. Remora has two completely independent agent execution paths:

- **Path A (Kernel-based):** `SwarmExecutor` / `ChatSession` → `kernel_factory.create_kernel()` → `AgentKernel.run()`. Uses the full structured-agents stack: adapter, parser, grammar pipeline, observer, typed tool execution.

- **Path C (LSP Runner):** `lsp/runner.py` → `AgentRunner.execute_turn()` → own tool loop. Has its own `LLMClient` wrapper, own `ToolCall` model, own XML parser, own tool format. Does NOT use `AgentKernel`.

These two paths duplicate ~200 lines of logic and diverge in capabilities:

| Capability | Kernel Path | LSP Runner Path |
|---|---|---|
| Grammar constraints | Yes (ConstraintPipeline → extra_body) | No |
| Concurrent tool execution | Yes (semaphore, max_concurrency) | No (sequential only) |
| Configurable tool_choice | Yes | No (hardcoded) |
| Observer/event emission | Full 7-event stream | Partial (own event methods) |
| Response parsing | QwenResponseParser (XML + API tool_calls) | Own _extract_text_tool_calls (XML only) + API tool_calls |
| Typed tool schema | ToolSchema → to_openai_format() | Raw dicts |
| Typed tool calls | ToolCall dataclass | Own ToolCall Pydantic model |
| History management | max_history_messages truncation | Own truncation |

**Why This Happened:** The LSP runner was likely built before `AgentKernel` was mature enough, or was built to be self-contained within the LSP server. Over time, the kernel gained features (grammar, concurrency, observer) that the runner never adopted.

**Proposal: Unify on AgentKernel.**

The LSP runner should use `AgentKernel` instead of reimplementing the agent loop. Concretely:

1. `AgentRunner.execute_turn()` calls `create_kernel()` with appropriate config
2. The kernel handles: LLM calls, response parsing, tool execution, event emission
3. `AgentRunner` handles: tool schema construction, prompt assembly, LSP-specific concerns (document sync, diagnostics)
4. The runner's `LLMClient` wrapper class, `ToolCall` model, `LLMResponse` model, and `_extract_text_tool_calls` are all deleted

**What blocks this:** The LSP runner constructs tools as raw dicts, not as `Tool` Protocol implementations. It would need to wrap its tools in a `Tool`-compatible adapter. This is straightforward — a thin wrapper class like `FunctionTool` in `chat.py` but for the LSP tool format.

**Estimated impact:** ~200 lines deleted from `runner.py`, ~30 lines added for tool adapter. Eliminates an entire class of divergence bugs.

### 4.2 Naming Collisions

**The Problem:**

The LSP runner defines its own types with the same names as structured-agents types:

| Name | structured-agents Type | LSP Runner Type | Difference |
|---|---|---|---|
| `ToolCall` | Frozen dataclass: `id`, `name`, `arguments_json` | Pydantic model: different field names | Different fields, different base class |
| `LLMClient` | Protocol: `chat_completion()` → `CompletionResponse` | Concrete class: `chat()` → `LLMResponse` | Different method names, different return types |

When reading Remora code, `ToolCall` means something different depending on which file you're in. This is a maintenance hazard — a developer might import the wrong one.

**Proposal:** Eliminate the LSP-local types by unifying on AgentKernel (Section 4.1). If the LSP runner uses the kernel, it uses the kernel's types. No naming collision possible.

If unification takes time, the immediate fix is renaming: `LspToolCall`, `LspLLMClient`. But this is a band-aid.

### 4.3 The Unused `Agent` Class

**The Problem:**

structured-agents defines `Agent` (`agent.py`):
```python
class Agent:
    @classmethod
    def from_bundle(cls, bundle_path, ...):
        # Reads STRUCTURED_AGENTS_BASE_URL env var
        # Reads STRUCTURED_AGENTS_API_KEY env var
        # Calls build_client()
        # Calls discover_tools()
        # Creates ModelAdapter, AgentKernel
        ...
    
    async def run(self, user_input: str) -> RunResult: ...
```

Remora never calls `Agent.from_bundle()` or `Agent.run()`. It builds kernels directly via `kernel_factory.py`. The `Agent` class has its own config mechanism (env vars) that conflicts with Remora's `Config` system.

**Why it exists:** It's the standalone API for using structured-agents without Remora. Run an agent from a bundle directory with just env vars.

**Proposal: Remove the `Agent` class from structured-agents.**

Since structured-agents is only used inside Remora, the standalone `Agent` class serves no purpose. Its responsibilities are split between Remora components:
- Client creation → `kernel_factory.py`
- Manifest loading → `SwarmExecutor`
- Tool discovery → Remora's `discover_grail_tools()`
- Kernel assembly → `kernel_factory.create_kernel()`

Removing it eliminates ~80 lines of code and one confusing config mechanism. If a standalone API is ever needed, it can be rebuilt from Remora's components.

**Also remove:** `_ADAPTER_REGISTRY` and `get_response_parser()` can move to `models/parsers.py` where they logically belong, rather than living in `agent.py`.

### 4.4 `load_manifest()` vs. Double YAML Parsing

**The Problem:**

`SwarmExecutor.run_agent()` calls `load_manifest(bundle_path)` to get an `AgentManifest`. But then `_resolve_model_name()` reads `bundle.yaml` AGAIN:

```python
# In run_agent():
manifest = load_manifest(bundle_path)  # First read

# In _resolve_model_name():
data = yaml.safe_load(path.read_text())  # Second read of same file
model_data = data.get("model")
model_id = model_data.get("id") or model_data.get("name") or model_data.get("model")
```

The double read happens because `load_manifest()` extracts the model from `model.plugin` (a structured-agents convention), but Remora's bundles use `model.id` / `model.name` / `model.model`. The manifest's `model` field has the wrong value for Remora's purposes.

**Proposal: Fix `AgentManifest` to carry the right model metadata.**

Two options:

**A) Extend `load_manifest()` to extract all model keys.** Add `model_id`, `model_provider` fields to `AgentManifest`. Read all relevant keys from `bundle.yaml` in one pass. Remora uses the fields it needs.

**B) Replace `load_manifest()` with Remora's own bundle loader.** Since the manifest format is Remora-specific anyway, define a `RemoraManifest` Pydantic model and load it directly. Removes the structured-agents dependency on `pyyaml` for this purpose.

**Recommendation: Option A for now** (minimal change), with Option B as a future simplification if structured-agents and Remora bundle formats continue to diverge.

### 4.5 `QwenResponseParser` Is Not Qwen-Specific

**The Problem:**

The parser is named `QwenResponseParser` but handles ALL models:
- Standard API `tool_calls` (dict format) → converts to `ToolCall` dataclass
- XML-style `<tool_call>` tags in text → extracts and converts to `ToolCall`
- Returns `(content, list[ToolCall])`

There's nothing Qwen-specific about it. It's the universal default. The `_ADAPTER_REGISTRY` maps both "qwen" and "function_gemma" to `QwenResponseParser`, and the fallback for unrecognized models is also `QwenResponseParser`.

**Why the name:** It was probably first written for Qwen models (which emit XML tool calls) and never renamed when it became the universal parser.

**Proposal: Rename to `DefaultResponseParser`.**

One-line change + imports update. Zero behavioral change. Makes the code self-documenting.

Also rename `_ADAPTER_REGISTRY` to `_PARSER_REGISTRY` since it maps model names to parsers, not to adapters.

### 4.6 Dual Tool Discovery

**The Problem:**

Two independent tool discovery mechanisms:

| Feature | structured-agents | Remora |
|---|---|---|
| Function | `discover_tools(agents_dir)` in `tools/grail.py` | `discover_grail_tools(agents_dir, ...)` in `core/tools/grail.py` |
| Returns | `list[GrailTool]` | `list[RemoraGrailTool]` (with context, files_provider) |
| Called by | `Agent.from_bundle()` (unused by Remora) | `SwarmExecutor.run_agent()` |

Remora's version is richer — it wraps grail scripts with context and file provider support that the structured-agents version doesn't have.

**Proposal: Remove `discover_tools()` and `GrailTool` from structured-agents.**

Since Remora has its own (better) implementation and the structured-agents version is never called, it's dead code. Removing it eliminates ~99 lines and the optional `grail` dependency from structured-agents.

The `Tool` Protocol stays — that's actively used by Remora's tool implementations. Only the concrete `GrailTool` and the discovery function go away.

### 4.7 Grammar Pipeline Is vLLM-Specific

**The Problem:**

The entire `grammar/` subpackage generates vLLM-specific `extra_body` payloads:
- `structural_tag` strategy → `{"structural_tag": {"begin": ..., "end": ..., "type": "json", "json_schema": ...}}`
- `json_schema` strategy → `{"guided_json": <schema>}`

With LiteLLM supporting multiple providers, sending vLLM-specific `extra_body` to Anthropic or OpenAI would be an error (they'd ignore it or return an error).

**Proposal: Make grammar constraints provider-aware.**

The constraint pipeline should only generate `extra_body` when the target model is a vLLM model (i.e., the model string starts with `hosted_vllm/`). For other providers, grammar constraints are either:
- Skipped (the model handles tool calls natively, no grammar enforcement needed)
- Translated to provider-specific equivalents (e.g., OpenAI's `response_format: {type: "json_schema", ...}`)

Implementation approaches:

**A) Kernel checks model prefix before applying constraints:**
```python
# In AgentKernel.step():
if self.adapter.constraint_pipeline and model_name.startswith("hosted_vllm/"):
    extra_body = self.adapter.constraint_pipeline.constrain(tool_schemas)
else:
    extra_body = {}
```

**B) ConstraintPipeline becomes provider-aware:**
```python
class ConstraintPipeline:
    def constrain(self, tools, model: str) -> dict:
        if not model.startswith("hosted_vllm/"):
            return {}  # No grammar constraint for non-vLLM
        # ... existing vLLM-specific logic ...
```

**C) Separate the concepts.** Grammar constraints are a "structured decoding" concern. Provider-specific structured output mechanisms (OpenAI's `response_format`, Anthropic's tool_use, vLLM's `extra_body`) should be mapped separately. The ConstraintPipeline could return a provider-agnostic constraint spec, and the client translates it.

**Recommendation: Option A for now** (simplest). The kernel already knows the model name; adding a prefix check is one line. Option C is the right long-term architecture but is a larger refactor.

### 4.8 `ModelAdapter` Is Over-Abstracted

**The Problem:**

`ModelAdapter` has 5 fields:
```python
@dataclass
class ModelAdapter:
    name: str                                    # Model name
    response_parser: ResponseParser              # Actually used
    constraint_pipeline: ConstraintPipeline | None  # Actually used
    format_messages: Callable = ...              # Never overridden
    format_tools: Callable = ...                 # Never overridden
```

The `format_messages` and `format_tools` are YAGNI. They exist "in case someone wants a different message format" but nobody does — OpenAI format is universal. The `name` field just carries the model name, which the kernel could get from `client.model`.

**Proposal: Flatten into kernel config.**

Replace:
```python
kernel = AgentKernel(
    client=client,
    adapter=ModelAdapter(name=model_name, response_parser=parser, constraint_pipeline=pipeline),
    tools=tools,
    observer=observer,
)
```

With:
```python
kernel = AgentKernel(
    client=client,
    response_parser=parser,
    constraint_pipeline=pipeline,  # Optional
    tools=tools,
    observer=observer,
)
```

The kernel gets the model name from `client.model`. No adapter needed.

**What this simplifies:**
- Eliminates `models/adapter.py` (~40 lines)
- Simplifies `kernel_factory.create_kernel()` (no adapter assembly)
- Removes one abstraction layer that adds zero value

**What we lose:** The ability to override `format_messages` / `format_tools` per model. But we never use this, and with LiteLLM normalizing everything to OpenAI format, there's even less reason to.

### 4.9 Event Type Split (dataclass vs. Pydantic)

**The Problem:**

structured-agents events are frozen dataclasses:
```python
@dataclass(frozen=True)
class ModelRequestEvent:
    turn: int
    messages_count: int
    tools_count: int
    model: str
```

Remora events are frozen Pydantic models:
```python
class AgentStartEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    agent_id: str
    agent_name: str
    ...
```

`EventStore.append()` handles both via duck typing:
```python
if isinstance(event, BaseModel):
    data = event.model_dump()  # Pydantic path
else:
    data = asdict(event)       # dataclass path
```

`EventBus.emit()` also handles both. `core/events.py` re-exports structured-agents event types alongside Remora event types into a single `RemoraEvent` union.

**Why this is messy:**
1. Two serialization paths in EventStore
2. Two type hierarchies in the same union type
3. Pyright complains about `model_dump` on dataclass events (the diagnostic errors we see)
4. No common base type for "any event"

**Proposal: Unify on Pydantic models.**

Since structured-agents is only used inside Remora, and Remora uses Pydantic everywhere, convert the 7 structured-agents event types from dataclasses to frozen Pydantic models:

```python
class ModelRequestEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    turn: int
    messages_count: int
    tools_count: int
    model: str
```

**Benefits:**
- Single serialization path in EventStore (`model_dump()` for everything)
- Single type hierarchy (all events are BaseModel subclasses)
- Pyright errors go away
- Can define a common `Event` base model if desired
- Consistent with all other Remora models

**Cost:** structured-agents gains a Pydantic dependency for events. But it already depends on Pydantic (for `StructuredOutputModel` in the grammar package), so this adds zero new dependencies.

### 4.10 Double `ModelRequestEvent` Emission

**The Problem:**

In `kernel.py`, `run()` emits `ModelRequestEvent` at line 233 before calling `step()`. Then `step()` emits it at line 87. Every turn produces two `ModelRequestEvent`s with identical data.

**Evidence:** Reading the source code, `run()` line 233:
```python
self.observer.emit(ModelRequestEvent(turn=turn, ...))
result = await self.step(messages, turn=turn)
```
And `step()` line 87:
```python
self.observer.emit(ModelRequestEvent(turn=turn, ...))
response = await self.client.chat_completion(...)
```

**Impact:** Any observer (including Remora's `EventBus` and `EventStore`) receives duplicate events. The timeline UI shows double model requests. Token usage accounting could double-count.

**Proposal: Remove the emission from `run()`.** The emission in `step()` is the correct one — it's emitted right before the actual LLM call. The one in `run()` is premature and redundant.

One-line fix. Zero API change. Fixes an actual bug.

### 4.11 `CompletionResponse.tool_calls` Type Confusion

**The Problem:**

`CompletionResponse` declares:
```python
tool_calls: list[dict] | None
```

But `QwenResponseParser.parse()` returns:
```python
def parse(...) -> tuple[str | None, list[ToolCall]]:
    # Returns ToolCall dataclasses, not dicts
```

So the data flows as: `CompletionResponse.tool_calls` (dicts) → `parser.parse()` → `list[ToolCall]` (dataclasses).

The parser converts dicts to ToolCall inside `parse()`. But `OpenAICompatibleClient` puts dicts into `CompletionResponse.tool_calls`. So the flow is: dicts in → dicts to parser → ToolCall out. This works, but the types are inconsistent at the boundaries.

**Additionally:** The kernel's `step()` method gets `list[ToolCall]` from the parser but constructs `Message` objects with `tool_calls: list[ToolCall]` field. Then `Message.to_openai_format()` converts `ToolCall` back to dicts for the next API call. So the full cycle is: dicts → ToolCall → dicts → ToolCall → ...

**Proposal: Pick one and be consistent.**

Two options:

**A) All ToolCall, everywhere.** Change `CompletionResponse.tool_calls` to `list[ToolCall] | None`. The client converts dicts to ToolCall during response construction. The parser receives ToolCall and passes them through (no dict conversion needed). Clean, but changes the client's responsibility.

**B) All dicts until the parser.** Keep `CompletionResponse.tool_calls` as `list[dict]`. The parser is the single conversion point from dicts to ToolCall. Kernel and tools work with ToolCall. This is the current design, just needs clearer documentation.

**Recommendation: Option B** (current design, just document it). The conversion boundary is already clear (parser). Changing `CompletionResponse` to use ToolCall would require the client to know about ToolCall's structure, which tightens coupling.

### 4.12 Debug Print Statements in Production Code

**The Problem:**

`OpenAICompatibleClient` (`client/openai.py`) has print statements:
```python
# Line 53-54:
print(f"DEBUG: chat_completion kwargs: {kwargs}")
print(f"DEBUG: tools count: {len(tools or [])}")
# Line 60:
print(f"DEBUG: response: {response}")
```

These are development artifacts that shouldn't be in production code.

**Proposal: Remove them.**

If debug logging is needed, use Python's `logging` module:
```python
import logging
logger = logging.getLogger(__name__)
logger.debug("chat_completion kwargs: %s", kwargs)
```

Or, with LiteLLM replacing `OpenAICompatibleClient`, this file is deleted entirely (Section 3.6). The debug prints go away with it.

---

## 5. Proposed Refactored Architecture

This section synthesizes the LiteLLM integration (Section 3) and all 12 concept misalignment fixes (Section 4) into a concrete target architecture. This is what structured-agents looks like after the refactor — new file layout, simplified public API, and the impact on every Remora integration point.

### 5.1 Design Principles

The refactored architecture is governed by these principles:

1. **Single execution path.** Every agent execution — swarm, chat, LSP — goes through `AgentKernel`. No parallel tool loops.

2. **LiteLLM as the sole transport layer.** One client implementation that handles all providers via model string prefixes. No per-provider client classes.

3. **Minimal abstraction layers.** If an abstraction doesn't carry its weight (i.e., it's never varied or overridden), remove it. Specifically: `ModelAdapter` is eliminated. `Agent` class is eliminated. Format functions are eliminated.

4. **Consistent types everywhere.** One `ToolCall` type, one event base class, one serialization path. No shadow types, no duck-typed dual paths.

5. **Provider-aware constraints.** Grammar/structured decoding only applies when the target provider supports it. The model prefix tells us the provider.

6. **Remora alignment over generality.** Since structured-agents is only used inside Remora, we optimize for Remora's needs. Dead abstractions that exist "for future extensibility" are removed.

### 5.2 New File Layout

```
structured_agents/
├── __init__.py              # Simplified public API (~50 exports → ~30)
├── types.py                 # UNCHANGED — Message, ToolCall, ToolResult, ToolSchema, TokenUsage, StepResult, RunResult
├── exceptions.py            # UNCHANGED — StructuredAgentsError hierarchy
├── kernel.py                # SIMPLIFIED — response_parser + constraint_pipeline as direct fields (no ModelAdapter)
│
├── client/
│   ├── __init__.py          # Exports: LLMClient, LiteLLMClient, build_client
│   ├── protocol.py          # UNCHANGED — LLMClient Protocol, CompletionResponse
│   └── litellm_client.py    # NEW — LiteLLMClient (replaces openai.py)
│
├── parsing/                 # RENAMED from models/ (clearer purpose)
│   ├── __init__.py          # Exports: ResponseParser, DefaultResponseParser
│   └── parsers.py           # RENAMED parser: QwenResponseParser → DefaultResponseParser
│
├── grammar/
│   ├── __init__.py          # UNCHANGED exports
│   ├── config.py            # UNCHANGED — DecodingConstraint
│   ├── pipeline.py          # MODIFIED — constrain() now takes model name, skips for non-vLLM
│   └── models.py            # UNCHANGED — StructuredOutputModel
│
├── events/
│   ├── __init__.py          # UNCHANGED exports
│   ├── observer.py          # UNCHANGED — Observer Protocol, NullObserver, CompositeObserver
│   └── types.py             # MODIFIED — all events become frozen Pydantic BaseModel (from dataclass)
│
└── tools/
    ├── __init__.py          # Exports: Tool (only)
    └── protocol.py          # UNCHANGED — Tool Protocol
```

**Deleted files (6 files, ~424 lines removed):**

| File | Lines | Reason |
|------|-------|--------|
| `client/openai.py` | 115 | Replaced by `litellm_client.py`. `build_client()` moves to `client/__init__.py`. |
| `models/adapter.py` | 40 | `ModelAdapter` eliminated. `response_parser` and `constraint_pipeline` move to kernel. |
| `models/__init__.py` | 14 | Subpackage removed (replaced by `parsing/`). |
| `agent.py` | 167 | `Agent` class, `AgentManifest`, `load_manifest()`, `_ADAPTER_REGISTRY` all removed. Manifest loading is Remora's responsibility. `get_response_parser()` moves to `parsing/parsers.py`. |
| `tools/grail.py` | 99 | `GrailTool` and `discover_tools()` removed. Remora has its own. |

**New files (1 file, ~80 lines):**

| File | Lines | Purpose |
|------|-------|---------|
| `client/litellm_client.py` | ~80 | `LiteLLMClient` implementation (see Section 3.2). |

**Renamed files (1 rename):**

| Old | New | Reason |
|-----|-----|--------|
| `models/` | `parsing/` | The subpackage's job is response parsing, not "models." The old name was confusing — "models" could mean ML models, data models, or model adapters. `parsing/` is precise. |

**Net change:** 6 files deleted, 1 file added, 1 renamed. From 21 files to 16 files. From ~1,438 lines to ~1,014 lines (~30% reduction).

### 5.3 Simplified Public API

**Current `__init__.py` exports (35+ symbols):**
```python
# Types (7)
Message, ToolCall, ToolResult, ToolSchema, TokenUsage, StepResult, RunResult
# Tools (3) — GrailTool and discover_tools are unused
Tool, GrailTool, discover_tools
# Models (3) — ModelAdapter is an internal detail
ModelAdapter, ResponseParser, QwenResponseParser
# Grammar (2)
DecodingConstraint, StructuredOutputModel
# Events (9)
Observer, NullObserver, Event,
KernelStartEvent, KernelEndEvent, ModelRequestEvent, ModelResponseEvent,
ToolCallEvent, ToolResultEvent, TurnCompleteEvent
# Core (4) — Agent and load_manifest are unused
AgentKernel, Agent, AgentManifest, load_manifest
# Client (3) — OpenAICompatibleClient is replaced
LLMClient, OpenAICompatibleClient, build_client
# Exceptions (5)
StructuredAgentsError, KernelError, ToolExecutionError, BundleError, AdapterError
```

**Proposed `__init__.py` exports (~28 symbols):**
```python
# Types (7) — UNCHANGED
Message, ToolCall, ToolResult, ToolSchema, TokenUsage, StepResult, RunResult

# Tool Protocol (1)
Tool

# Parsing (2) — renamed
ResponseParser, DefaultResponseParser

# Grammar (2) — UNCHANGED
DecodingConstraint, StructuredOutputModel

# Events (9) — UNCHANGED (but now Pydantic models)
Observer, NullObserver, Event,
KernelStartEvent, KernelEndEvent, ModelRequestEvent, ModelResponseEvent,
ToolCallEvent, ToolResultEvent, TurnCompleteEvent

# Core (1)
AgentKernel

# Client (3) — new client
LLMClient, LiteLLMClient, build_client

# Exceptions (4) — BundleError and AdapterError removed (no more Agent/Adapter)
StructuredAgentsError, KernelError, ToolExecutionError
```

**Removed from public API (9 symbols):**

| Symbol | Reason |
|--------|--------|
| `GrailTool` | Unused by Remora |
| `discover_tools` | Unused by Remora |
| `ModelAdapter` | Eliminated (internal detail flattened into kernel) |
| `QwenResponseParser` | Renamed to `DefaultResponseParser` |
| `Agent` | Unused by Remora |
| `AgentManifest` | Manifest loading is Remora's responsibility |
| `load_manifest` | Manifest loading is Remora's responsibility |
| `OpenAICompatibleClient` | Replaced by `LiteLLMClient` |
| `BundleError` | No more bundle loading in s-a |
| `AdapterError` | No more ModelAdapter |

**Added to public API (2 symbols):**

| Symbol | Reason |
|--------|--------|
| `LiteLLMClient` | The new client |
| `DefaultResponseParser` | Renamed from `QwenResponseParser` |

### 5.4 The Refactored Client Layer

**`client/protocol.py` — UNCHANGED:**
```python
class LLMClient(Protocol):
    model: str
    async def chat_completion(
        self, messages, tools, tool_choice, max_tokens, temperature, extra_body, model
    ) -> CompletionResponse: ...
    async def close(self) -> None: ...

@dataclass(frozen=True)
class CompletionResponse:
    content: str | None
    tool_calls: list[dict] | None    # Stays as list[dict] — parser is the conversion boundary
    usage: TokenUsage | None
    finish_reason: str | None
    raw_response: dict
```

The Protocol is clean and doesn't need to change. Any client that satisfies this Protocol works with the kernel.

**`client/litellm_client.py` — NEW (see Section 3.2 for full implementation):**

Key characteristics:
- Model routing via LiteLLM prefix convention (`anthropic/...`, `hosted_vllm/...`, etc.)
- `extra_body` passed straight through (critical for vLLM grammar constraints)
- `close()` is a no-op (LiteLLM manages its own connection pool)
- Response normalization is minimal (LiteLLM already returns OpenAI-format)

**`build_client()` — MOVED to `client/__init__.py`:**
```python
def build_client(config: dict) -> LiteLLMClient:
    return LiteLLMClient(
        model=config.get("model", ""),
        api_key=config.get("api_key", ""),
        base_url=config.get("base_url", ""),
        timeout=config.get("timeout", 300),
    )
```

Same signature, same callers, different return type. All callers use the `LLMClient` Protocol, so no code changes needed.

**What's deleted:** `client/openai.py` (115 lines). The `OpenAICompatibleClient` class and its debug print statements are gone. If `extra_body` passthrough fails with LiteLLM (Section 3.5), this file can be temporarily restored as a fallback.

### 5.5 The Refactored Kernel

**Key changes to `AgentKernel`:**

1. `adapter: ModelAdapter` field → replaced by `response_parser: ResponseParser` and `constraint_pipeline: ConstraintPipeline | None`
2. Grammar constraint application becomes provider-aware (checks model prefix)
3. The duplicate `ModelRequestEvent` emission in `run()` is removed

```python
@dataclass
class AgentKernel:
    """The core agent loop orchestrator."""

    client: LLMClient
    response_parser: ResponseParser                           # ← was adapter.response_parser
    tools: Sequence[Tool] = field(default_factory=list)
    observer: Observer = field(default_factory=NullObserver)
    constraint_pipeline: ConstraintPipeline | None = None     # ← was adapter.constraint_pipeline
    max_history_messages: int = 50
    max_concurrency: int = 1
    max_tokens: int = 4096
    temperature: float = 0.1
    tool_choice: str = "auto"
```

**In `step()`:**
```python
# Grammar constraints — only for providers that support it
extra_body = None
if self.constraint_pipeline:
    model = self.client.model
    if model.startswith("hosted_vllm/"):
        extra_body = self.constraint_pipeline.constrain(resolved_tools)
    # For other providers (anthropic/, openai/): no extra_body
    # They handle tool calling natively without grammar enforcement
```

**In `run()`:**
```python
# The duplicate ModelRequestEvent emission is REMOVED from run().
# step() handles it — the event is emitted right before the actual LLM call.
while turn_count < max_turns:
    turn_count += 1
    # ... history truncation ...
    # NO ModelRequestEvent here — step() emits it
    step_result = await self.step(messages, tools, turn=turn_count)
    # ... rest of loop ...
```

**Impact on `kernel_factory.py` in Remora:**

Current:
```python
parser = get_response_parser(model_name)
pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
adapter = ModelAdapter(name=model_name, response_parser=parser, constraint_pipeline=pipeline)
return AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)
```

Refactored:
```python
parser = get_response_parser(model_name)
pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
return AgentKernel(
    client=client,
    response_parser=parser,
    constraint_pipeline=pipeline,
    tools=tools,
    observer=observer,
)
```

One fewer line, one fewer concept. The `ModelAdapter` indirection is gone. The factory directly sets the kernel's parser and constraint pipeline.

### 5.6 The Refactored Parser

**Rename: `QwenResponseParser` → `DefaultResponseParser`**

```python
# parsing/parsers.py

class ResponseParser(Protocol):
    def parse(self, content: str | None, tool_calls: list[dict] | None) -> tuple[str | None, list[ToolCall]]: ...

class DefaultResponseParser:
    """Universal response parser. Handles both API tool_calls (dict format)
    and XML-style <tool_call> tags in text content.
    
    Formerly named QwenResponseParser — renamed because there's nothing
    Qwen-specific about it.
    """
    
    def parse(self, content: str | None, tool_calls: list[dict] | None) -> tuple[str | None, list[ToolCall]]:
        # ... existing logic, unchanged ...
```

**`get_response_parser()` moves here from `agent.py`:**
```python
_PARSER_REGISTRY: dict[str, type[ResponseParser]] = {
    "qwen": DefaultResponseParser,
    "function_gemma": DefaultResponseParser,
}

def get_response_parser(model_name: str) -> ResponseParser:
    """Resolve a ResponseParser for the given model name.
    
    Currently all models use DefaultResponseParser. The registry exists
    for future model-specific parsers if needed.
    """
    for key, parser_cls in _PARSER_REGISTRY.items():
        if key in model_name.lower():
            return parser_cls()
    return DefaultResponseParser()
```

This is functionally identical to the current code but lives in the right place (`parsing/parsers.py` instead of `agent.py`) and uses clear names.

**`CompletionResponse.tool_calls` type stays as `list[dict] | None`.** The parser remains the conversion boundary from dicts to `ToolCall` dataclasses. This is the current design, just documented explicitly (Section 4.11, Option B).

### 5.7 The Refactored Grammar Pipeline

**`grammar/pipeline.py` changes:**

The `ConstraintPipeline.constrain()` method itself does NOT change — it still generates the same vLLM-specific payloads. The change is that the **kernel** decides whether to call it based on the model prefix (Section 5.5).

However, there's a question: should the pipeline itself become provider-aware? Arguments for and against:

**Arguments for keeping the pipeline provider-unaware:**
- Single Responsibility: the pipeline's job is "generate constraint payloads," not "decide whether to apply constraints"
- The kernel already knows the model name and is the right place for the provider check
- If a future provider supports similar constraints (e.g., TGI's grammar support), we can add another prefix check in the kernel without modifying the pipeline

**Arguments for making the pipeline provider-aware:**
- Encapsulation: callers don't need to know which providers support constraints
- The pipeline could generate different payloads for different providers (e.g., OpenAI's `response_format` for structured output)

**Recommendation: Keep the pipeline provider-unaware for now.** The kernel checks the prefix and conditionally calls the pipeline. If we later need per-provider constraint translation, we can introduce a `ConstraintTranslator` layer at that point. YAGNI for now.

**One new consideration with LiteLLM:** LiteLLM itself has some structured output support via `response_format`. For `openai/` models:
```python
response = await litellm.acompletion(
    model="openai/gpt-4o",
    response_format={"type": "json_schema", "json_schema": {...}},
    ...
)
```

This could be an alternative to vLLM's `extra_body` grammar constraints for cloud models. But it's a different mechanism with different semantics. For now, we treat grammar constraints as vLLM-only and let cloud models handle tool calling natively (which they do well). This can be revisited if there's a need for structured output from cloud models.

### 5.8 The Refactored Event System

**All 7 structured-agents events convert from frozen dataclasses to frozen Pydantic models.**

Before:
```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ModelRequestEvent:
    turn: int
    messages_count: int
    tools_count: int
    model: str
```

After:
```python
from pydantic import BaseModel, ConfigDict

class ModelRequestEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    turn: int
    messages_count: int
    tools_count: int
    model: str
```

**All 7 events get the same treatment.** The field names and types stay identical. The only change is the base class.

**Optional: Common base class:**
```python
class KernelEvent(BaseModel):
    """Base class for all structured-agents kernel events."""
    model_config = ConfigDict(frozen=True)

class ModelRequestEvent(KernelEvent):
    turn: int
    messages_count: int
    tools_count: int
    model: str
```

This gives us a common base for pattern matching:
```python
if isinstance(event, KernelEvent):
    # It's a structured-agents event
```

**Impact on Remora:**

`core/events.py` — the `RemoraEvent` union already includes the structured-agents events. No change to the union. But the re-exported events are now Pydantic models, consistent with all Remora events.

`core/event_store.py` — the dual serialization path collapses:

Before:
```python
if isinstance(event, BaseModel):
    data = event.model_dump()   # Pydantic path
else:
    data = asdict(event)        # dataclass path
```

After:
```python
data = event.model_dump()      # Everything is Pydantic now
```

`core/event_bus.py` — same simplification. One path for all events.

`ui/projector.py` — whatever duck-typing it does for events simplifies because all events have the same interface (`model_dump()`, `model_fields`, etc.).

**Pydantic dependency in structured-agents:** Already exists (for `StructuredOutputModel` in the grammar package). Converting events to Pydantic adds zero new dependencies.

### 5.9 Impact on Remora

This is the key section — how does the refactored structured-agents change each Remora integration point?

#### `core/kernel_factory.py` — Simplifies

```python
# BEFORE (current):
from structured_agents.agent import get_response_parser
from structured_agents.client import build_client
from structured_agents.grammar.pipeline import ConstraintPipeline
from structured_agents.kernel import AgentKernel
from structured_agents.models.adapter import ModelAdapter

def create_kernel(...):
    client = build_client({...})
    parser = get_response_parser(model_name)
    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
    adapter = ModelAdapter(name=model_name, response_parser=parser, constraint_pipeline=pipeline)
    return AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)

# AFTER (refactored):
from structured_agents.parsing import get_response_parser
from structured_agents.client import build_client
from structured_agents.grammar import ConstraintPipeline
from structured_agents.kernel import AgentKernel

def create_kernel(...):
    client = build_client({...})
    parser = get_response_parser(model_name)
    pipeline = ConstraintPipeline(grammar_config) if grammar_config else None
    return AgentKernel(
        client=client,
        response_parser=parser,
        constraint_pipeline=pipeline,
        tools=tools,
        observer=observer,
    )
```

Changes: one fewer import (`ModelAdapter`), one fewer line (no adapter construction). Import path for `get_response_parser` changes from `agent` to `parsing`.

#### `core/swarm_executor.py` — Drops double YAML read, client pooling stays

Key changes:
- `load_manifest()` import is removed (Remora handles its own manifest loading, or `load_manifest` is moved to Remora)
- `_resolve_model_name()` is simplified because the manifest carries all model metadata
- `build_client()` now returns `LiteLLMClient` (transparent — the `LLMClient` Protocol is satisfied)
- The model string in config/manifest now uses LiteLLM prefixes: `"hosted_vllm/Qwen/Qwen3-4B"` instead of `"Qwen/Qwen3-4B"`

The connection pooling pattern (create one client in `__init__`, pass to every `create_kernel()`) stays. Even though LiteLLM pools internally, the explicit pattern is harmless and provides a clear model/api_key default.

#### `core/chat.py` — Minimal change

`ChatSession` already creates kernels via `create_kernel()`. The change is transparent — `build_client()` returns a `LiteLLMClient` instead of `OpenAICompatibleClient`. `FunctionTool` and its use of the `Tool` Protocol are unaffected.

One opportunity: the `ChatConfig` could now accept full LiteLLM model strings (`"anthropic/claude-sonnet-4-20250514"`) alongside the existing local vLLM model strings. Chat becomes multi-provider for free.

#### `core/events.py` — Simplified re-exports

The structured-agents event types are now Pydantic models. The `RemoraEvent` union stays the same, but all members are now `BaseModel` subclasses. No more mixed dataclass/Pydantic union.

If the `KernelEvent` base class is introduced, we could simplify the union:
```python
RemoraEvent = (
    AgentStartEvent | AgentCompleteEvent | ... | KernelEvent
)
```
Though this loses the explicit listing. Probably better to keep the explicit union for type checker precision.

#### `core/event_store.py` — Simplified serialization

The dual `isinstance` check collapses to a single `.model_dump()` call. ~5 lines of branching logic removed.

#### `core/event_bus.py` — Simplified serialization

Same as event_store — the dual path collapses.

#### `core/tools/grail.py`, `core/tools/swarm.py`, `core/tools/spawn_child.py` — No change

These import `ToolCall`, `ToolResult`, `ToolSchema` from structured-agents' `types.py`. That module is unchanged. No impact.

#### `lsp/runner.py` — The Big Win

This is the largest Remora-side change and the biggest architectural win. The LSP runner's duplicate agent loop, client wrapper, tool call model, and XML parser are all replaced by `AgentKernel`.

**Current runner structure (818 lines):**
- `ToolCall` Pydantic model (lines 39-44) — DELETED
- `LLMResponse` Pydantic model (lines 47-51) — DELETED
- `LLMClient` class (lines 54-112) — DELETED
- `_extract_text_tool_calls()` (lines 498-519) — DELETED
- `execute_turn()` tool loop (lines 453-483) — REPLACED with kernel.run()
- `handle_response()` (lines 521-673) — REFACTORED into Tool implementations
- `get_agent_tools()` (lines 731-784) — REFACTORED to return `Tool` Protocol implementations

**Refactored approach:**

The runner's tools (`rewrite_self`, `message_node`, `read_node`) become `Tool` Protocol implementations:

```python
class RewriteSelfTool:
    """Tool Protocol implementation for rewrite_self."""
    def __init__(self, runner: AgentRunner, agent: AgentNode, correlation_id: str):
        self._runner = runner
        self._agent = agent
        self._correlation_id = correlation_id
    
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="rewrite_self",
            description="Rewrite the agent's own source code with new implementation",
            parameters={"type": "object", "properties": {"new_source": {"type": "string", ...}}, "required": ["new_source"]},
        )
    
    async def execute(self, arguments: dict, context: Any = None) -> ToolResult:
        new_source = arguments.get("new_source", "")
        await self._runner.create_proposal(self._agent, new_source, self._correlation_id)
        return ToolResult(
            call_id=context.id if context else "",
            name="rewrite_self",
            output=f"proposal created — {len(new_source)} chars",
            is_error=False,
        )
```

Similar wrappers for `message_node` and `read_node`. Each is ~30 lines.

**`execute_turn()` becomes:**

```python
async def execute_turn(self, trigger: Trigger) -> None:
    # ... existing agent lookup, prompt assembly, event context loading ...
    
    tools = self.get_agent_tools(agent, correlation_id)  # Returns list[Tool]
    tool_schemas = [t.schema.name for t in tools]
    
    kernel = create_kernel(
        model_name=self.llm.model if self.llm else "",
        base_url=...,
        api_key=...,
        tools=tools,
        observer=...,  # Could use the LSP event emitter as Observer
        client=self.llm._client if self.llm else None,  # Reuse underlying client
    )
    
    messages = [Message(role="system", content=agent.to_system_prompt())]
    # ... add event context messages ...
    
    result = await kernel.run(messages, tools=tool_schemas, max_turns=MAX_TOOL_ROUNDS)
    # The kernel handles: LLM calls, response parsing, tool execution, event emission
```

**What this eliminates:**
- ~60 lines: `ToolCall`, `LLMResponse`, `LLMClient` classes
- ~25 lines: `_extract_text_tool_calls()` 
- ~30 lines: The manual tool loop in `execute_turn()`
- Naming collisions (`ToolCall`, `LLMClient`)
- XML parsing duplication

**What stays:** `handle_response()` logic for side-effect tools (rewrite_self, message_node) moves into `Tool.execute()` implementations. The cascade prevention, trigger queue, command dispatch, proposal creation, and event emission are all Remora-specific concerns that stay in the runner. The runner remains ~600+ lines, but it's cleaner — the LLM interaction is delegated to the kernel.

**Estimated impact on runner.py:** ~120 lines deleted, ~90 lines added (tool wrappers). Net ~30 line reduction, but the quality improvement is much larger than the line count suggests.

#### `ui/projector.py` — Minor simplification

Events are now all Pydantic, so any event projection/filtering logic that handles both types simplifies. The change is proportional to how much type-dispatching it currently does.

#### Summary Table: Remora File Impact

| Remora File | Change Magnitude | What Changes |
|---|---|---|
| `core/kernel_factory.py` | Small | Remove `ModelAdapter` import/usage, change `get_response_parser` import path |
| `core/swarm_executor.py` | Small | Remove `load_manifest` import, simplify `_resolve_model_name`, LiteLLM model strings |
| `core/chat.py` | Minimal | Transparent — `build_client()` returns `LiteLLMClient` |
| `core/events.py` | Minimal | Re-exports now point to Pydantic models (same names, same fields) |
| `core/event_store.py` | Small | Remove dual serialization path |
| `core/event_bus.py` | Small | Remove dual serialization path |
| `core/tools/grail.py` | None | No change — uses types from `types.py` |
| `core/tools/swarm.py` | None | No change |
| `core/tools/spawn_child.py` | None | No change |
| `lsp/runner.py` | **Large** | Delete duplicate types/loop, wrap tools as `Tool` Protocol, use `AgentKernel` |
| `ui/projector.py` | Minimal | Simplified event handling |

---

## 6. Migration Path & Risk Assessment

This section lays out how to get from the current architecture to the proposed one without breaking Remora at any intermediate step. The phases are ordered by risk (safest first) and dependency (later phases build on earlier ones). Each phase is independently shippable — you can stop after any phase and have a working system.

### 6.1 Phase 0: Bug Fixes (No API Changes)

**Scope:** Fix actual bugs and cosmetic issues. Zero API changes. Zero risk.

**Changes:**

| Item | File | Change | Risk |
|------|------|--------|------|
| Remove duplicate `ModelRequestEvent` | `kernel.py` lines 233-240 | Delete the `observer.emit(ModelRequestEvent(...))` call inside `run()`. Keep the one in `step()`. | None — fixes a bug. Event consumers get the correct number of events. |
| Remove debug `print()` statements | `client/openai.py` lines 53-54, 60 | Delete the three `print(f"DEBUG: ...")` lines. | None — removes console noise. |
| Rename `QwenResponseParser` → `DefaultResponseParser` | `models/parsers.py` | Rename the class. Add `QwenResponseParser = DefaultResponseParser` alias for backward compat. | Minimal — the alias ensures existing imports still work. |
| Rename `_ADAPTER_REGISTRY` → `_PARSER_REGISTRY` | `agent.py` | Rename the dict. Internal only, no external callers. | None. |

**Validation:** Run Remora's existing test suite. Run a swarm execution and a chat session. Verify events in EventStore (should see exactly one `ModelRequestEvent` per turn instead of two).

**Estimated effort:** ~30 minutes. Purely mechanical changes.

### 6.2 Phase 1: LiteLLM Client Addition

**Scope:** Add `LiteLLMClient` alongside `OpenAICompatibleClient`. Both coexist. Remora starts using LiteLLM model strings.

**Changes:**

1. **Add `client/litellm_client.py`** — New file, ~80 lines (Section 3.2). Implements `LLMClient` Protocol using `litellm.acompletion()`.

2. **Add `litellm` to dependencies** — In `pyproject.toml`: `"litellm>=1.55,<2.0"`.

3. **Update `build_client()`** — Add a `use_litellm: bool = False` parameter (or detect from model prefix):
   ```python
   def build_client(config: dict) -> LLMClient:
       model = config.get("model", "")
       # Use LiteLLM if the model has a provider prefix
       if "/" in model and any(model.startswith(p) for p in (
           "hosted_vllm/", "anthropic/", "openai/", "gemini/", "groq/", "ollama/",
       )):
           return LiteLLMClient(...)
       # Fallback to direct OpenAI client for bare model names
       return OpenAICompatibleClient(...)
   ```

4. **Test `extra_body` passthrough** — The critical verification from Section 3.5. Write a test that sends `extra_body={"structured_outputs": {...}}` via `LiteLLMClient` to a local vLLM server and verifies the constraint is applied.

5. **Update Remora config** — Start using LiteLLM model strings in `remora.yaml`:
   ```yaml
   model_default: hosted_vllm/Qwen/Qwen3-4B   # Was: Qwen/Qwen3-4B
   ```
   Existing bare model names still work (they hit the `OpenAICompatibleClient` fallback).

**Validation:**
- Run existing tests — bare model names should still use `OpenAICompatibleClient`
- Test with `hosted_vllm/` prefix — should use `LiteLLMClient` and produce identical results
- Test with `anthropic/` prefix (if API key available) — verify multi-provider works
- Verify grammar constraints work through LiteLLM's `hosted_vllm/` path

**Risk assessment:**
- **Medium risk.** The LiteLLM client is new code. The `extra_body` passthrough is the main uncertainty.
- **Rollback:** If `LiteLLMClient` fails, remove the `"/" in model` check in `build_client()`. Everything falls back to `OpenAICompatibleClient`. Zero impact.
- **Failure mode:** If `extra_body` doesn't pass through, grammar-constrained agents will get unconstrained responses. They'll likely still work (the parser handles both structured and unstructured responses) but with lower quality tool calling.

**Estimated effort:** ~2 hours. Most time is on the `extra_body` verification test.

### 6.3 Phase 2: Concept Cleanup

**Scope:** Flatten `ModelAdapter`, fix `ToolCall` typing documentation, consolidate `get_response_parser()` location. Requires Phase 0 (parser rename).

**Changes:**

1. **Eliminate `ModelAdapter`** — Modify `AgentKernel` to accept `response_parser` and `constraint_pipeline` directly:
   ```python
   # kernel.py — change fields
   - adapter: ModelAdapter
   + response_parser: ResponseParser
   + constraint_pipeline: ConstraintPipeline | None = None
   ```
   Update all references from `self.adapter.response_parser` to `self.response_parser`, and from `self.adapter.constraint_pipeline` to `self.constraint_pipeline`. Update `self.adapter.name` references to `self.client.model`.

2. **Move `get_response_parser()` from `agent.py` to `parsing/parsers.py`** — Create `parsing/` subpackage (rename from `models/`). Move the function and `_PARSER_REGISTRY`.

3. **Add provider-aware constraint check in kernel** — In `step()`, only apply `extra_body` if the model starts with `hosted_vllm/`:
   ```python
   if self.constraint_pipeline and self.client.model.startswith("hosted_vllm/"):
       extra_body = self.constraint_pipeline.constrain(resolved_tools)
   ```

4. **Update `kernel_factory.py` in Remora** — Change imports and remove adapter construction:
   ```python
   - from structured_agents.agent import get_response_parser
   + from structured_agents.parsing import get_response_parser
   - from structured_agents.models.adapter import ModelAdapter
   # ... remove adapter = ModelAdapter(...)
   # ... pass response_parser and constraint_pipeline directly to AgentKernel
   ```

5. **Document `CompletionResponse.tool_calls` type** — Add a docstring clarifying that `tool_calls` is `list[dict]` at the protocol boundary and the parser converts to `list[ToolCall]`. No code change, just documentation.

**Validation:**
- Run all Remora tests — kernel construction via `create_kernel()` must still work
- Run a full swarm execution to verify adapter removal didn't break anything
- Check that grammar constraints still apply for `hosted_vllm/` models
- Check that non-vLLM models (if tested) don't receive `extra_body`

**Risk assessment:**
- **Low-medium risk.** The `ModelAdapter` removal is a structural change but mechanically simple (moving fields from adapter to kernel). The kernel's `step()` logic is unchanged — just different attribute access paths.
- **Rollback:** Revert the `kernel.py` changes and restore `ModelAdapter`. The `parsing/` rename can coexist with the old `models/` path via re-exports.

**Estimated effort:** ~1.5 hours.

### 6.4 Phase 3: LSP Runner Unification

**Scope:** Refactor the LSP runner to use `AgentKernel` instead of its own tool loop. Eliminates naming collisions and the duplicate execution path. Requires Phase 1 (LiteLLM client) and Phase 2 (flattened kernel).

This is the largest phase and the biggest architectural win.

**Changes:**

1. **Create `Tool` Protocol implementations for LSP tools:**
   - `RewriteSelfTool` — Wraps `AgentRunner.create_proposal()` (see Section 5.9 for sketch)
   - `MessageNodeTool` — Wraps `AgentRunner.message_node()`
   - `ReadNodeTool` — Wraps `AgentRunner.server.event_store.get_node()`
   - Each extension tool gets a wrapper via a generic `ExtensionToolAdapter`
   
   These are ~30 lines each. They take the runner, agent, and correlation_id in their constructor, expose a `ToolSchema`, and delegate `execute()` to the existing runner methods.

2. **Create an `Observer` implementation for LSP events:**
   Currently the LSP runner emits events via `emit_event()` (Remora's LSP-specific event system). Create an `LspObserver` that implements the structured-agents `Observer` Protocol and bridges kernel events to LSP events:
   ```python
   class LspObserver:
       def __init__(self, agent_id: str, correlation_id: str):
           self._agent_id = agent_id
           self._correlation_id = correlation_id
       
       async def emit(self, event: Event) -> None:
           from remora.lsp.server import emit_event
           # Convert kernel events to LspAgentEvent
           await emit_event(LspAgentEvent(
               event_type=type(event).__name__,
               agent_id=self._agent_id,
               correlation_id=self._correlation_id,
               summary=str(event),
               timestamp=0.0,
               payload=event.model_dump(),
           ))
   ```

3. **Refactor `execute_turn()`** — Replace the manual tool loop with `kernel.run()`:
   ```python
   async def execute_turn(self, trigger: Trigger) -> None:
       # ... existing agent lookup, prompt assembly ...
       
       tools = self._build_tools(agent, correlation_id)  # Returns list[Tool]
       observer = LspObserver(agent_id, correlation_id)
       
       kernel = create_kernel(
           model_name=self.llm.model,
           base_url=...,
           api_key=...,
           tools=tools,
           observer=observer,
           client=self.llm._client,  # Reuse the underlying s-a client
       )
       
       messages = [Message(role="system", content=agent.to_system_prompt())]
       # ... add event-context messages as Message objects ...
       
       result = await kernel.run(messages, tools=[t.schema.name for t in tools], max_turns=MAX_TOOL_ROUNDS)
       
       # Post-run: emit text response if no tool calls
       if result.termination_reason == "no_tool_calls" and result.final_message.content:
           await emit_event(LspAgentEvent(
               event_type="AgentTextResponse",
               agent_id=agent_id,
               ...
           ))
   ```

4. **Delete duplicate types and code:**
   - Delete `ToolCall` Pydantic model (lines 39-44)
   - Delete `LLMResponse` Pydantic model (lines 47-51)
   - Delete `LLMClient` class (lines 54-112)
   - Delete `_extract_text_tool_calls()` (lines 498-519)
   - Delete the manual tool loop in `execute_turn()` (lines 453-483)

5. **Preserve `handle_response()` for side-effect tools:**
   The `rewrite_self` and `message_node` tools are "side-effect only" — they don't return results to feed back to the LLM. In the kernel model, they return a `ToolResult` with a status message, and the kernel appends it to the conversation. This changes the behavior slightly: previously, `rewrite_self` didn't produce a tool result message; now it does. The LLM will see "proposal created — N chars" as a tool result. This is actually **better** — the model gets feedback that its action succeeded.

**Validation:**
- **Critical test:** Trigger an LSP agent (via chat command or file change), verify it:
  1. Calls the LLM through `AgentKernel`
  2. Parses tool calls correctly (both API and XML formats)
  3. Executes `rewrite_self` → creates a proposal
  4. Executes `read_node` → reads source and feeds back to LLM for next round
  5. Executes `message_node` → sends message and triggers target agent
  6. Text-only responses are emitted as `AgentTextResponse` events
- **Cascade test:** Verify depth limiting and cooldown still work (they're in the runner, not the kernel)
- **Headless test:** Verify `AgentRunner.create_headless()` still works with the kernel path

**Risk assessment:**
- **Medium-high risk.** This is the largest structural change. The LSP runner's tool execution semantics change slightly (tool results are now fed back to the model via the kernel's conversation loop instead of custom message formatting).
- **The biggest risk is side-effect tools.** `rewrite_self` and `message_node` currently don't produce "tool result" messages in the conversation. With the kernel, they do. The LLM might behave differently when it sees tool results for these actions. In practice, this should be fine — the results are short status messages — but it needs testing.
- **Rollback:** The old runner code can be restored. The tool wrappers and observer are additive — they don't modify any existing code, just add new classes.

**Estimated effort:** ~4-6 hours. This is the most complex phase.

### 6.5 Phase 4: Event Unification

**Scope:** Convert structured-agents events from frozen dataclasses to frozen Pydantic models. Requires Phase 2 (so the kernel is already refactored and stable).

**Changes:**

1. **Convert 7 event types in `events/types.py`:**
   ```python
   # BEFORE:
   from dataclasses import dataclass
   
   @dataclass(frozen=True)
   class ModelRequestEvent:
       turn: int
       messages_count: int
       tools_count: int
       model: str
   
   # AFTER:
   from pydantic import BaseModel, ConfigDict
   
   class KernelEvent(BaseModel):
       model_config = ConfigDict(frozen=True)
   
   class ModelRequestEvent(KernelEvent):
       turn: int
       messages_count: int
       tools_count: int
       model: str
   ```
   
   All 7 events get the same treatment. Field names and types are identical.

2. **Update `Event` union type:**
   ```python
   Event = Union[KernelStartEvent, KernelEndEvent, ...]  # Same members, now BaseModel subclasses
   ```

3. **Simplify `EventStore.append()` in Remora:**
   ```python
   # Remove the isinstance check:
   - if isinstance(event, BaseModel):
   -     data = event.model_dump()
   - else:
   -     data = asdict(event)
   + data = event.model_dump()  # Everything is Pydantic now
   ```

4. **Simplify `EventBus.emit()` in Remora:**
   Same dual-path removal.

5. **Update `core/events.py` in Remora:**
   If `KernelEvent` base class is used, optionally add it to the `RemoraEvent` union. Or keep the explicit member list.

**Validation:**
- Run all tests — event serialization/deserialization must work
- Verify EventStore correctly persists and queries events
- Verify the UI timeline renders events correctly
- Check that pattern matching on event types still works

**Risk assessment:**
- **Low risk.** The field names and types don't change. Only the base class changes (dataclass → BaseModel). The serialization method changes from `asdict()` to `model_dump()`. Both produce identical dicts.
- **One subtle risk:** If any code does `isinstance(event, SomeDataclass)` checks, it will fail because the events are no longer dataclasses. But Remora's code already handles both types, so this is unlikely.
- **Another subtle risk:** Pydantic models have stricter validation by default. If any event is constructed with wrong types (e.g., passing a string where int is expected), Pydantic will raise a `ValidationError` whereas the dataclass would silently accept it. This is actually a feature (catches bugs), but could surface hidden issues.

**Estimated effort:** ~1 hour. Mechanical changes.

### 6.6 Phase 5: Remove Dead Code

**Scope:** Delete everything that's no longer needed. Requires all previous phases.

**Changes:**

1. **Delete `agent.py`** — `Agent` class, `AgentManifest`, `load_manifest()` are all unused:
   - `Agent` class — Remora never uses it
   - `AgentManifest` — Remora should own its own manifest type (if needed)
   - `load_manifest()` — Remora should own its own YAML loading
   - `_ADAPTER_REGISTRY` and `get_response_parser()` — already moved to `parsing/parsers.py` in Phase 2

2. **Delete `client/openai.py`** — `OpenAICompatibleClient` is replaced by `LiteLLMClient`. `build_client()` already returns `LiteLLMClient` for all prefixed model strings. If Phase 1 validation confirmed `extra_body` passthrough, the old client is dead code.

3. **Delete `tools/grail.py`** — `GrailTool` and `discover_tools()` are unused by Remora. Remove the file, simplify `tools/__init__.py` to export only `Tool`.

4. **Delete `models/` subpackage** — Fully replaced by `parsing/`. Remove `models/adapter.py`, `models/parsers.py`, `models/__init__.py`.

5. **Remove exceptions that no longer apply:**
   - `BundleError` — No more bundle loading in structured-agents
   - `AdapterError` — No more `ModelAdapter`

6. **Update `__init__.py`** — Remove all deleted symbols from exports. Final export list per Section 5.3.

7. **Remove `openai` from direct dependencies** — LiteLLM brings it transitively. Optional: keep for explicitness.

**Validation:**
- Verify no imports of deleted modules in Remora (search for `from structured_agents.agent`, `from structured_agents.models.adapter`, `from structured_agents.tools.grail`, etc.)
- Run full test suite
- Run a complete swarm execution end-to-end

**Risk assessment:**
- **Low risk.** Everything deleted in this phase is verified unused by the preceding phases. If any import was missed, it fails fast with an `ImportError`.
- **Rollback:** Restore deleted files from git history.

**Estimated effort:** ~30 minutes. Mostly deleting files and updating imports.

### 6.7 Risk Assessment Summary

| Phase | Risk Level | Primary Risk | Rollback Strategy | Dependencies |
|-------|-----------|-------------|-------------------|-------------|
| **Phase 0:** Bug fixes | Very low | None | Revert commits | None |
| **Phase 1:** LiteLLM client | Medium | `extra_body` passthrough failure | Remove prefix detection in `build_client()` | None |
| **Phase 2:** Concept cleanup | Low-medium | Kernel attribute access paths | Restore `ModelAdapter` | Phase 0 |
| **Phase 3:** LSP unification | Medium-high | Side-effect tool behavior change | Restore old runner code | Phases 1, 2 |
| **Phase 4:** Event unification | Low | Pydantic validation strictness | Restore dataclass events | Phase 2 |
| **Phase 5:** Dead code removal | Very low | Missed import | Restore from git | Phases 1-4 |

**Overall migration risk: Medium.** The riskiest phase is Phase 3 (LSP runner unification), which changes the most behavior. All other phases are structural refactors with minimal behavioral change. The entire migration can be done incrementally with each phase independently validated.

**Total estimated effort: ~10-12 hours across all phases.** This assumes a developer familiar with both codebases. Phase 3 is the bulk of the work.

**Recommended cadence:** Phases 0-2 can be done in a single session (they're small and build on each other). Phase 3 deserves its own focused session with thorough testing. Phases 4-5 are cleanup that can happen anytime after Phase 3 stabilizes.

---

## 7. Open Questions

These are decisions and unknowns that need investigation or input before (or during) implementation. They're ordered by impact — the first few could significantly change the refactor's direction.

### 7.1 Should structured-agents still exist as a separate library, or should it be folded into Remora?

**The question:** Given that structured-agents is only used inside Remora, is there value in keeping it as an independent package? Or should its source files be moved directly into `remora/core/kernel/` (or similar)?

**Arguments for keeping it separate:**

- **Boundary clarity.** The library has a well-defined responsibility: "run a tool-using agent loop against an LLM." Keeping it separate forces clean interfaces between "kernel mechanics" and "Remora application logic." If everything is in one codebase, the boundary blurs and kernel code starts importing Remora-specific types.
- **Testing isolation.** structured-agents can be tested independently of Remora's infrastructure (EventStore, LSP, config system). Tests are smaller and faster.
- **Optionality.** If you ever build another product that needs an agent loop, structured-agents is ready. Even if this never happens, the discipline of maintaining it as a library keeps the design clean.
- **Cognitive chunking.** A developer can understand "the kernel" without understanding Remora. The library boundary acts as a documentation boundary.

**Arguments for folding into Remora:**

- **Dependency management.** Currently structured-agents is vendored (copied into `.context/`). This creates version sync issues — Remora might use an outdated copy. Folding it in eliminates versioning entirely.
- **Refactoring friction.** Every change that crosses the library boundary (e.g., making events Pydantic) requires coordinated changes in two codebases. In a single codebase, it's a single PR.
- **No external consumers.** The "optionality" argument is speculative. YAGNI suggests we should optimize for the known use case (Remora) rather than hypothetical future ones.
- **Import path simplification.** `from remora.core.kernel import AgentKernel` is cleaner than `from structured_agents import AgentKernel` for Remora developers. It makes it clear this is part of Remora.

**My recommendation:** **Keep separate for now, but consider folding after the refactor stabilizes.**

The refactor described in this document already aligns the two codebases significantly. After Phases 0-5, structured-agents will be lean (~16 files, ~1,000 lines), focused, and tightly aligned with Remora's needs. At that point, the remaining benefit of separation is boundary clarity, and the cost is coordination overhead.

The pragmatic decision: complete the refactor with structured-agents as a separate package (this preserves git history and makes rollback easy). Then evaluate whether the boundary is worth maintaining. If every change to structured-agents requires a corresponding Remora change, the boundary has negative value and should be removed.

### 7.2 LiteLLM `extra_body` passthrough — still unverified

**The question:** Does `litellm.acompletion(model="hosted_vllm/...", extra_body={"structured_outputs": {...}})` correctly forward the `structured_outputs` key in the HTTP request body to the vLLM server?

**Why it matters:** This is the single technical gating question for the entire refactor. If `extra_body` doesn't pass through, grammar-constrained decoding breaks, and we need to keep `OpenAICompatibleClient` as a fallback for vLLM.

**How to verify:**

1. **Read the LiteLLM source code.** Find where `hosted_vllm/` model strings are handled and trace the `extra_body` parameter through to the `openai.ChatCompletion.create()` call.

2. **Write a test.** Stand up a vLLM server, call `litellm.acompletion(model="hosted_vllm/Qwen/Qwen3-4B", api_base="http://localhost:8000/v1", extra_body={"structured_outputs": {"structural_tag": {...}}})`, and verify:
   - The HTTP request body contains `structured_outputs`
   - The vLLM server processes the constraint (response contains tool call XML within the structural tags)

3. **Check LiteLLM's test suite.** Search for `extra_body` in their tests — they likely test this for at least some providers.

**Impact if it doesn't work:** Fall back to the dual-client design (Section 3.6, Option 2). `LiteLLMClient` for cloud providers, `OpenAICompatibleClient` for `hosted_vllm/`. This is less clean but still an improvement over the status quo (Remora gets multi-provider support, just with two client implementations instead of one).

### 7.3 Event format unification — Pydantic or dataclass?

**The question:** Should the unified event format be Pydantic `BaseModel` or plain dataclasses?

**The recommendation in Section 5.8 is Pydantic.** But here's the full trade-off:

**Pydantic BaseModel:**
- (+) Consistent with all other Remora models
- (+) Built-in serialization (`model_dump()`, `model_json_schema()`)
- (+) Validation on construction catches type errors early
- (+) structured-agents already depends on Pydantic
- (-) Slightly heavier construction cost (Pydantic validates fields on `__init__`)
- (-) Pydantic models are more opinionated about field types (no implicit coercion)

**Plain dataclasses:**
- (+) Lighter weight, faster construction
- (+) Simpler mental model (no validation magic)
- (+) Standard library, no dependency
- (-) No built-in serialization (need `asdict()` which doesn't handle nested objects well)
- (-) No validation — wrong types silently accepted
- (-) Inconsistent with Remora's event types (the dual-path problem persists)

**My position: Pydantic wins.** The consistency argument is decisive. Events flow through EventStore, EventBus, and the UI — all of which already speak Pydantic. The dual-path is the root cause of existing complexity. Unifying on Pydantic eliminates it.

The performance concern (Pydantic construction overhead) is negligible for events that are created ~10-50 times per agent turn. If it ever mattered, Pydantic v2's Rust-backed validation is already fast.

### 7.4 Should `kernel.run()` become an async generator for streaming support?

**The question:** Currently `kernel.run()` returns a `RunResult` after all turns complete. Should it instead `yield` events or step results incrementally?

**Why this matters:** Real-time UIs (like the timeline debugger) want to show events as they happen, not after the full run completes. Currently they get real-time events via the `Observer` Protocol. But the `run()` caller itself only gets the final result.

**Current state:** The `Observer` Protocol handles real-time needs. `EventBus` receives events as they're emitted. The UI subscribes to the EventBus. This works.

**What an async generator would add:**

```python
async for event in kernel.run_stream(messages, tools, max_turns=20):
    if isinstance(event, StepResult):
        # Process intermediate results
    elif isinstance(event, ModelResponseEvent):
        # Stream tokens (if supported by the provider)
```

This gives the caller fine-grained control over the execution flow (e.g., cancel after a specific event, inject messages mid-run).

**My position: Not now. The Observer Protocol is sufficient.**

The async generator pattern is more powerful but more complex. It changes the contract of `kernel.run()` and requires all callers to handle the generator protocol. The Observer already provides real-time events. The only thing missing is caller-side flow control (pausing/canceling mid-run), which hasn't been needed yet.

If streaming token-level responses becomes a requirement (e.g., for a chat UI that shows tokens as they arrive), the generator pattern becomes more compelling. But that's a separate feature that requires provider-level streaming support (LiteLLM's `acompletion(stream=True)`), not just a kernel API change.

**Recommendation:** Defer. Add it when there's a concrete use case.

### 7.5 Config simplification — should Remora's `providers` section be eliminated?

**The question:** The LLM Provider Enhancement doc proposed a `providers:` section in `remora.yaml`. With LiteLLM model prefixes as the routing mechanism, is this config section still needed?

**Current Remora config:**
```yaml
model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B
model_api_key: ""
```

**With LiteLLM (minimal config):**
```yaml
model_default: hosted_vllm/Qwen/Qwen3-4B
model_base_url: http://localhost:8000/v1    # Only for hosted_vllm
model_api_key: ""                           # Only for hosted_vllm
# Other providers use env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.
```

**With LiteLLM (explicit config):**
```yaml
model_default: hosted_vllm/Qwen/Qwen3-4B

# Optional: explicit provider config (overrides env vars)
providers:
  hosted_vllm:
    base_url: http://localhost:8000/v1
    api_key: ""
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}
  openai:
    api_key: ${OPENAI_API_KEY}
```

**My position: Start with minimal config, add `providers:` only if needed.**

The minimal config works for the common case (single default model, API keys via env vars). The `providers:` section adds complexity that's only valuable if:
- You need different `base_url`s for different vLLM instances
- You want to centralize API keys in the config instead of env vars
- You need per-provider timeout or retry config

These are all valid needs but not immediate ones. Start minimal, add the section when users ask for it.

### 7.6 Version strategy — how to version structured-agents through breaking changes

**The question:** Phases 2-5 introduce breaking changes to structured-agents' public API (removed symbols, renamed types, changed kernel fields). How should this be versioned?

**Options:**

**A) Semver bump to 1.0.0.** Declare the refactored library as the 1.0 stable release. The current v0.3.4 was the "pre-1.0 anything goes" phase. The post-refactor library is stable, lean, and purpose-built for Remora.

**B) Semver bump to 0.4.0.** Stay in 0.x range. The library isn't "1.0 stable" — it's still tightly coupled to Remora and might change if Remora's needs change.

**C) Don't version — fold into Remora.** If the decision from Section 7.1 is to fold structured-agents into Remora, versioning is moot. The kernel code is just part of Remora's version.

**My recommendation: Option B (0.4.0) during the refactor, with Option A (1.0.0) after stabilization.**

- Phase 0 → v0.3.5 (bug fixes only)
- Phase 1 → v0.4.0 (new client, backward compatible)
- Phase 2 → v0.5.0 (breaking: ModelAdapter removed)
- Phase 3 → no s-a version change (Remora-side only)
- Phase 4 → v0.6.0 (breaking: events change base class)
- Phase 5 → v0.7.0 (breaking: dead code removed)
- Stabilization → v1.0.0

Since structured-agents is only used inside Remora, the version numbers are mostly for bookkeeping and git history. But they're useful for tracking which phase of the refactor has been completed.

### 7.7 What about `AgentManifest` — who owns bundle loading?

**The question:** Phase 5 deletes `AgentManifest` and `load_manifest()` from structured-agents. But Remora's `SwarmExecutor` currently calls `load_manifest()` to get the manifest. What replaces it?

**Options:**

**A) Move `load_manifest()` into Remora.** Define a `RemoraManifest` (or `BundleManifest`) Pydantic model in `remora/core/`. Move the YAML loading logic there. This makes manifest loading Remora's responsibility, which is correct — the bundle format is Remora-defined.

**B) Keep `AgentManifest` and `load_manifest()` in structured-agents.** Just remove the `Agent` class. The manifest remains a shared concept between the library and Remora.

**My recommendation: Option A.** The manifest format is entirely Remora-specific. The `bundle.yaml` schema, the key paths (`model.plugin`, `model.id`, etc.), the `agents_dir` convention — these are all Remora concepts. Putting them in structured-agents created the double YAML read problem (Section 4.4). Moving them to Remora fixes it.

The new Remora manifest model should include all the fields Remora actually needs (model name with LiteLLM prefix, grammar config, system prompt, max turns, etc.) without the structured-agents-specific conventions that Remora ignores.

