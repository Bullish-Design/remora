# structured-agents v0.3 — Architecture Analysis

Reference for Remora's refactor. Distilled from V03_CONCEPT.md, V03_IMPLEMENTATION_GUIDE.md, and v03_GROUND_UP_REFACTOR_IDEAS.md.

---

## 1. What It Is

structured-agents is a library for **grammar-constrained LLM tool orchestration** with sandboxed script execution. It sends messages to an LLM, constrains the model's output to valid tool calls via EBNF/structural-tag/JSON-Schema grammars, executes those calls in grail's Monty sandbox, and loops until termination. v0.3 is a ground-up simplification: 51 files → ~20, 6 protocol hierarchies → 3, composite patterns eliminated entirely.

---

## 2. Five Core Concepts

| Concept | Role |
|---------|------|
| **Tool** | Has a schema, can execute with arguments and context. Single protocol replaces 6-layer Registry/Backend/ToolSource stack. |
| **ModelAdapter** | Frozen dataclass adapting the kernel to a specific model family. Holds a grammar builder, response parser, and optional message/tool formatters with sensible defaults. |
| **DecodingConstraint** | Configuration for how to constrain model output — strategy (`ebnf`, `structural_tag`, `json_schema`), `allow_parallel_calls`, `send_tools_to_api`. |
| **Kernel** | The loop: ask model → parse response → execute tool calls → repeat. Accepts `list[Tool]` directly (no composite wrappers). |
| **Agent** | User-facing entry point. `Agent.from_bundle(path)` loads YAML config, discovers tools, wires adapter/client/kernel, and exposes `run(user_input)`. |

---

## 3. Architecture

### Collapsed Tool Abstraction

v0.2 had: Kernel → ToolSource → ToolRegistry (discovery) + ToolBackend (execution) → composites at every level. v0.3 collapses this to a single `Tool` protocol. Each tool knows its schema and can execute itself. Discovery is a function (`discover_tools(dir) -> list[Tool]`), not a class.

### Flat ModelAdapter

v0.2 had 4 component protocols (MessageFormatter, ToolFormatter, ResponseParser, GrammarProvider), a ComposedModelPlugin, and per-model entry points — 14 classes across 10 files. v0.3 replaces all of this with a single `ModelAdapter` dataclass. Message/tool formatting are identical across models and get defaults; only `grammar_builder` and `response_parser` vary per model.

### ConstraintPipeline

Grammar construction was scattered across plugin → GrammarProvider → GrammarBuilder with an intermediate artifact layer. v0.3 makes it a standalone pipeline: `tools + config → vLLM extra_body dict`. The intermediate artifact types still exist internally but aren't part of the public interface.

### Unified Event Model

v0.2's Observer had 8+ fixed methods (one per event type). v0.3 uses a single `emit(event: Event)` method where `Event` is a union of frozen dataclasses. Adding new event types (e.g., grail script lifecycle events) requires zero changes to existing observer implementations. Observers use `match` for pattern matching.

---

## 4. Key Types

All are frozen dataclasses with `slots=True`:

```python
Message(role, content, tool_calls?, tool_call_id?, name?)
ToolCall(id, name, arguments)        # .create(name, args) factory
ToolResult(call_id, name, output, is_error)
ToolSchema(name, description, parameters)
TokenUsage(prompt_tokens, completion_tokens, total_tokens)
StepResult(response_message, tool_calls, tool_results, usage?)
RunResult(final_message, history, turn_count, termination_reason, total_usage?)
```

---

## 5. The Kernel Loop

### `step(messages, tools) -> StepResult`

1. Resolve tool schemas
2. Format messages via `adapter.format_messages()`
3. Build grammar constraint via `adapter.grammar_builder(tools, config)`
4. Call `client.chat_completion(messages, tools?, extra_body=grammar)`
5. Parse response via `adapter.response_parser.parse(content, tool_calls)`
6. Execute tool calls (sequential or concurrent via semaphore)
7. Return `StepResult`

### `run(messages, tools, max_turns) -> RunResult`

1. Emit `KernelStartEvent`
2. Loop: call `step()`, append response + tool results to messages
3. Terminate when: no tool calls returned, or max_turns reached
4. Emit `KernelEndEvent`
5. Return `RunResult`

---

## 6. Agent.from_bundle()

Single entry point that wires everything from a `bundle.yaml`:

```python
agent = await Agent.from_bundle("./my_agent")
result = await agent.run("List all tasks")
```

Internally: `load_manifest(path)` → `discover_tools(agents_dir)` → build `ModelAdapter` → `build_client()` → construct `AgentKernel` → return `Agent`. Advanced users can construct the kernel and components directly.

Bundle YAML simplified: no `registry.type`, no `backend.type`, no `max_workers`. Limits use preset names (`strict`, `default`, `permissive`) or inline config. Per-tool `output_model` and `limits` overrides supported.

---

## 7. Observer Pattern

```python
class Observer(Protocol):
    async def emit(self, event: Event) -> None: ...
```

`Event` is a union type:

- `KernelStartEvent`, `KernelEndEvent`
- `ModelRequestEvent`, `ModelResponseEvent`
- `ToolCallEvent`, `ToolResultEvent`
- `TurnCompleteEvent`
- (extensible: `ScriptStartEvent`, `ScriptCompleteEvent`, `ScriptErrorEvent`, `ScriptPrintEvent`)

`NullObserver` discards all events. The kernel accepts `list[Observer]` and iterates with `asyncio.gather()` — no `CompositeObserver` class needed.

---

## 8. How Tools Work (GrailTool)

`GrailTool` wraps a `.pym` script loaded via `grail.load()`:

1. **Schema derivation**: `GrailScript.inputs` (dict of `InputSpec`) → `ToolSchema` with JSON Schema parameters. Type mapping: `str→string`, `int→integer`, `float→number`, `bool→boolean`, `list→array`, `dict→object`.
2. **Execution**: In-process async `script.run()` (no subprocess). Data injected via grail's virtual filesystem (`files={}` populated by a `DataProvider`). Results validated against optional `output_model` (Pydantic). Limits via grail `Limits` objects with preset/merge semantics.
3. **Error handling**: All 7 grail error types (`ParseError`, `CheckError`, `InputError`, `ExternalError`, `ExecutionError`, `LimitError`, `OutputError`) caught and converted to `ToolResult(is_error=True)` with structured messages. Tool.execute() never raises.
4. **Scripts as pure functions**: Data flows in via virtual FS, scripts return structured mutation descriptions, host persists via `ResultHandler`. No `@external` for data access (reserved for genuine external service calls).

Discovery: `discover_tools(agents_dir)` globs `*.pym`, calls `grail.load()` on each, returns `list[GrailTool]`.

---

## 9. What Was Simplified from v0.2

| Aspect | v0.2 | v0.3 |
|--------|------|------|
| Files | 51 across 8 packages | ~20 across 4-5 packages |
| Protocol hierarchies | 6 (ToolRegistry, ToolBackend, ToolSource, MessageFormatter, ToolFormatter, GrammarProvider) | 3 (Tool, Observer, HistoryStrategy) |
| Composite classes | 3 (CompositeRegistry, CompositeBackend, CompositeObserver) | 0 (lists at kernel level) |
| Tool abstraction depth | 6 layers (Kernel→ToolSource→Registry+Backend→GrailBackend→subprocess) | 2 layers (Kernel→Tool.execute()) |
| Plugin system | 14 classes across 10 files | 1 dataclass (ModelAdapter) + per-model parsers |
| Observer protocol surface | 8+ methods | 1 method (emit) |
| Script execution | ProcessPoolExecutor subprocess with asyncio.run() | In-process async |
| Limits | Raw dicts, non-standard keys | Grail `Limits` objects with presets/merge |
| Tool schemas | Hand-written JSON files, 2 incompatible formats | `grail.load()` introspection (single source of truth) |
| Data flow | @external declarations for all I/O | Virtual FS + return-based mutations |
| Error handling | Catches 2 of 7 grail error types | Catches all 7 with structured messages |
| Dead code | `_schema_from_grail_check`, unused grammar builders | Eliminated |

---

## 10. Key Integration Points for Remora's Refactor

1. **Tool protocol**: Remora's tools should implement `Tool(Protocol)` — `schema` property + `async execute()`. This is the only interface the kernel cares about.

2. **GrailTool + DataProvider**: Remora's database-backed tools use `DataProvider.load_files()` to populate the virtual FS before script execution and `ResultHandler.handle()` to persist mutations after. These are the integration seams for Remora's data layer.

3. **Agent.from_bundle()**: Remora's agent configuration maps to `bundle.yaml`. The `Agent.from_bundle()` factory handles all wiring — Remora needs to provide its `DataProvider` and `ResultHandler` implementations plus any custom `ExternalsFactory`.

4. **Observer for telemetry**: Remora's logging/metrics plug into the `Observer.emit()` interface. Typed events enable structured telemetry without coupling to the kernel internals.

5. **ModelAdapter**: If Remora uses models beyond Qwen/FunctionGemma, it provides a new `ModelAdapter` with a custom `response_parser` and `grammar_builder`. Message/tool formatting defaults work for all OpenAI-compatible APIs.

6. **DecodingConstraint**: Remora configures its grammar strategy per agent via bundle YAML (`ebnf`, `structural_tag`, or `json_schema`). The `ConstraintPipeline` is standalone and testable.

7. **Kernel loop hooks**: `step()` and `run()` are the control points. Remora can call `step()` directly for single-turn interactions or `run()` for autonomous loops with `max_turns` and termination conditions.

8. **Error propagation**: `ToolResult.is_error` is the only error surface the kernel sees. GrailTool internally handles all grail exceptions. Remora's error monitoring hooks into `ToolResultEvent.is_error` via the observer.

9. **LLMClient**: `OpenAICompatibleClient` works with vLLM out of the box. Remora can provide a custom `LLMClient` implementation if needed (it's a protocol with one method: `chat_completion()`).

10. **Types are shared**: `Message`, `ToolCall`, `ToolResult`, `ToolSchema`, `TokenUsage`, `StepResult`, `RunResult` are the data contract between Remora and structured-agents. All frozen dataclasses — safe to pass across boundaries.
