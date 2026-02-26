# structured-agents v0.3.0 — Ground-Up Refactor Ideas

## Purpose

This document proposes ideas for a complete ground-up refactor of structured-agents, taking the opportunity presented by the grail 3.0.0 integration (described in `V03_CONCEPT.md`) to rethink the entire architecture. The goal: a library that is conceptually simple to hold in your head while developing with it, while achieving the same overall functionality — grammar-constrained LLM tool orchestration with sandboxed script execution.

---

## Current Architecture: What We're Working With

### The Good (Keep)

- **Protocol-based extensibility** — structural subtyping via `typing.Protocol` is the right approach
- **Frozen value types** — immutable dataclasses for domain objects (`Message`, `ToolCall`, `ToolResult`, `ToolSchema`) are correct
- **Observable lifecycle** — the event system with typed events is clean
- **Grammar-constrained decoding** — the core value prop of forcing valid tool calls from the LLM
- **Bundle-as-configuration** — declarative YAML for agent setup

### The Problematic (Rethink)

- **6 protocol hierarchies** for what is conceptually 3 concerns (discover tools, execute tools, format for model)
- **51 source files** across 8 packages for ~3800 lines of actual logic
- **3 layers of indirection** for grammar building: Plugin → GrammarProvider → GrammarBuilder
- **2 separate context injection mechanisms** that overlap (ToolSource.context_providers vs ToolSchema.context_providers)
- **Registry/Backend split** that forces a bridge class (`RegistryBackendToolSource`) and composite classes for both
- **Duplicated code** across model plugins (MessageFormatter, ToolFormatter are identical for all models)
- **Dead code paths** (GrailRegistry._schema_from_grail_check, Qwen3GrammarBuilder._build_args_grammar_for_tool)

---

## Core Insight: What Is This Library Really Doing?

Strip away the abstraction layers and structured-agents does three things:

1. **Prepare** — Discover tools, build schemas, construct grammar constraints
2. **Loop** — Send messages to LLM, receive tool calls, execute tools, repeat
3. **Execute** — Run sandboxed scripts with data in, validated results out

Everything else is configuration, formatting, and observation. A ground-up refactor should make these three concerns obvious in the code structure.

---

## Idea 1: Collapse the Tool Abstraction Stack

### Problem

Currently, a tool call flows through 6 abstractions:

```
Kernel → ToolSource → ToolRegistry (discovery)
                    → ToolBackend (execution)
                      → GrailBackend → _run_grail_script (process pool)
```

Plus composites at every level: `CompositeRegistry`, `CompositeBackend`, `RegistryBackendToolSource`.

### Proposal: Single `Tool` Protocol

```python
class Tool(Protocol):
    """A tool is something with a schema that can be executed."""
    
    @property
    def schema(self) -> ToolSchema: ...
    
    async def execute(self, arguments: dict[str, Any], context: ExecutionContext) -> ToolResult: ...
```

That's it. A tool knows its own schema and can execute itself. No separate registry, no separate backend, no bridge class.

**Concrete implementations:**

```python
class GrailTool:
    """A tool backed by a .pym script."""
    
    def __init__(self, script: GrailScript, limits: Limits, 
                 data_provider: DataProvider | None = None,
                 output_model: type[BaseModel] | None = None):
        self._script = script
        self._schema = _derive_schema(script)  # from GrailScript.inputs
        self._limits = limits
        self._data_provider = data_provider
        self._output_model = output_model
    
    @property
    def schema(self) -> ToolSchema:
        return self._schema
    
    async def execute(self, arguments, context) -> ToolResult:
        files = await self._data_provider.load_files(...) if self._data_provider else {}
        result = await self._script.run(
            inputs=arguments, files=files, 
            limits=self._limits, output_model=self._output_model
        )
        return ToolResult(output=json.dumps(result), is_error=False)


class PythonTool:
    """A tool backed by a Python callable."""
    
    def __init__(self, name: str, fn: Callable, schema: ToolSchema):
        self._fn = fn
        self._schema = schema
    
    async def execute(self, arguments, context) -> ToolResult:
        result = await self._fn(**arguments) if asyncio.iscoroutinefunction(self._fn) else self._fn(**arguments)
        return ToolResult(output=json.dumps(result), is_error=False)
```

**Discovery becomes a function, not a class:**

```python
def discover_tools(agents_dir: Path, limits: Limits = Limits.default()) -> list[Tool]:
    """Scan a directory for .pym files and return Tool objects."""
    tools = []
    for pym_path in agents_dir.rglob("*.pym"):
        script = grail.load(str(pym_path))
        tools.append(GrailTool(script, limits))
    return tools
```

**What this eliminates:**

- `ToolRegistry` protocol + 3 implementations + composite
- `ToolBackend` protocol + 3 implementations + composite
- `ToolSource` protocol + bridge class
- `RegistryBackendToolSource`
- ~15 files → ~3 files

**What this preserves:**

- Type safety (each tool knows its schema)
- Extensibility (implement `Tool` protocol for any execution model)
- Composability (a list of tools is all you need)

### Trade-off

You lose the ability to swap registries and backends independently at runtime. In practice, nobody does this — the registry and backend for a tool are always the same thing (grail tools use grail execution, python tools use python execution). The separation was an anticipation of variation that never materialized.

---

## Idea 2: Flatten the Plugin System into Two Concerns

### Problem

The current plugin system has 4 component protocols (`MessageFormatter`, `ToolFormatter`, `ResponseParser`, `GrammarProvider`), a composition class (`ComposedModelPlugin`), per-model entry points, and per-model component files. For 2 models, this produces 14 classes across 10 files.

The actual variation between models is in only 2 places:
1. **Grammar building** — different EBNF/structural tag formats per model
2. **Response parsing** — different regex patterns per model

Message and tool formatting are identical across all models (both just call `to_openai_format()`).

### Proposal: ModelAdapter with Defaults

```python
@dataclass(frozen=True)
class ModelAdapter:
    """Adapts the kernel's generic tool-call loop to a specific model family."""
    
    name: str
    grammar_builder: GrammarBuilder
    response_parser: ResponseParser
    
    # These have sensible defaults that work for all current models
    format_messages: Callable[[list[Message]], list[dict]] = _default_format_messages
    format_tools: Callable[[list[ToolSchema]], list[dict]] = _default_format_tools
```

Where `_default_format_messages` and `_default_format_tools` just call `to_openai_format()` on each item.

**Creating a model adapter:**

```python
# All you need to define for a new model family:
qwen_adapter = ModelAdapter(
    name="qwen",
    grammar_builder=Qwen3GrammarBuilder(),
    response_parser=QwenResponseParser(),
)

function_gemma_adapter = ModelAdapter(
    name="function_gemma",
    grammar_builder=FunctionGemmaGrammarBuilder(),
    response_parser=FunctionGemmaResponseParser(),
)
```

**What this eliminates:**

- `ComposedModelPlugin`
- `MessageFormatter` protocol (identical across models)
- `ToolFormatter` protocol (identical across models)
- `GrammarProvider` protocol (redundant wrapper around `GrammarBuilder`)
- Per-model entry point files (`function_gemma.py`, `qwen.py`)
- ~8 classes → ~2 (the adapter dataclass + per-model parsers)

**What this preserves:**

- Full customizability (override `format_messages` if a model genuinely needs it)
- Per-model grammar building and response parsing
- The `GrammarBuilder` protocol and all existing builders

### The `to_extra_body` Problem

Currently each `GrammarProvider` has a `to_extra_body()` method, but every implementation does the same thing: `artifact.to_vllm_payload()`. Since artifacts already know how to serialize themselves, this method should move to the kernel or be eliminated entirely. The kernel calls `adapter.grammar_builder.build(tools, config)` and then `artifact.to_vllm_payload()` directly.

---

## Idea 3: Grammar as a First-Class Pipeline Stage

### Problem

Grammar construction is currently scattered across the plugin system. The kernel asks the plugin to build a grammar, the plugin asks its GrammarProvider, which asks a GrammarBuilder. The artifact then goes back up the chain to be serialized. This is 3 layers for what is fundamentally: tools + config → vLLM extra_body dict.

### Proposal: Grammar Pipeline

```python
class GrammarPipeline:
    """Transforms tool schemas + config into vLLM grammar constraints."""
    
    def __init__(self, builder: GrammarBuilder, config: GrammarConfig):
        self._builder = builder
        self._config = config
    
    def constrain(self, tools: list[ToolSchema]) -> dict[str, Any] | None:
        """Build grammar constraints for the given tools.
        
        Returns the extra_body dict for vLLM, or None if no grammar is configured.
        """
        artifact = self._builder.build(tools, self._config)
        if artifact is None:
            return None
        return artifact.to_vllm_payload()
```

This makes the grammar system a standalone, testable pipeline that the kernel uses directly. It doesn't need to be wrapped in the plugin/adapter at all.

**The kernel's model call becomes:**

```python
# In kernel.step():
extra_body = self.grammar_pipeline.constrain(tools) if self.grammar_pipeline else None
tools_for_api = tools if self.grammar_config.send_tools_to_api else None
response = await self.client.chat_completion(messages, tools_for_api, extra_body)
```

Clear, direct, no delegation chains.

---

## Idea 4: The Kernel as a Minimal State Machine

### Problem

The current `AgentKernel` is 425 lines with `step()` at 181 lines and `run()` at 129 lines. It handles: tool resolution, message formatting, grammar construction, API calls, response parsing, tool matching, sequential/concurrent execution, event emission, history trimming, token accumulation, termination checking, error counting, and context building.

This is too many concerns for one class. The `step()` method has two execution paths (sequential vs concurrent) that double the logic.

### Proposal: Thin Kernel + Execution Strategy

```python
@dataclass
class AgentKernel:
    """The agent loop. Sends messages, receives tool calls, executes them."""
    
    client: LLMClient
    adapter: ModelAdapter
    tools: list[Tool]  # flat list, no ToolSource indirection
    observer: Observer = field(default_factory=NullObserver)
    grammar: GrammarPipeline | None = None
    history: HistoryStrategy = field(default_factory=SlidingWindowHistory)
    config: KernelConfig = field(default_factory=KernelConfig)
    
    async def step(self, messages: list[Message]) -> StepResult:
        """Single turn: ask model, execute any tool calls, return result."""
        ...
    
    async def run(self, messages: list[Message], max_turns: int = 10, 
                  terminate_on: TerminationCondition | None = None) -> RunResult:
        """Multi-turn loop until termination or max_turns."""
        ...
```

Key simplifications:
- **`tools: list[Tool]`** instead of `ToolSource` — flat, inspectable, no protocol indirection
- **`adapter: ModelAdapter`** instead of `ModelPlugin` — the adapter is a data object, not a protocol
- **`grammar: GrammarPipeline | None`** instead of grammar config woven through the plugin
- **Tool execution extracted:** The sequential vs concurrent logic becomes a standalone function:

```python
async def execute_tools(
    tool_calls: list[ToolCall],
    tools: dict[str, Tool],
    context: ExecutionContext,
    max_concurrent: int = 1,
    observer: Observer | None = None,
) -> list[ToolResult]:
    """Execute tool calls, sequentially or concurrently."""
    if max_concurrent == 1:
        return [await _execute_one(tc, tools, context, observer) for tc in tool_calls]
    
    sem = asyncio.Semaphore(max_concurrent)
    async def bounded(tc):
        async with sem:
            return await _execute_one(tc, tools, context, observer)
    
    return await asyncio.gather(*[bounded(tc) for tc in tool_calls])
```

This is a pure function — no class needed. It takes a list of calls, a tool lookup dict, and returns results. The kernel calls it.

---

## Idea 5: Unified Event Model

### Problem

V03_CONCEPT.md introduces 5 new event types for grail script lifecycle (`tool.script.start`, `tool.script.complete`, `tool.script.error`, `tool.script.print`, `tool.script.stdout`). The current observer protocol has 8 fixed methods. Adding 5 more methods to the protocol means every observer implementation needs 5 more no-op methods.

### Proposal: Single `emit` Method with Typed Events

```python
class Observer(Protocol):
    """Receives agent lifecycle events."""
    
    async def emit(self, event: Event) -> None: ...


# Events are a union of frozen dataclasses
Event = (
    KernelStartEvent | KernelEndEvent |
    ModelRequestEvent | ModelResponseEvent |
    ToolCallEvent | ToolResultEvent |
    TurnCompleteEvent |
    ScriptStartEvent | ScriptCompleteEvent | ScriptErrorEvent | ScriptPrintEvent |
    ErrorEvent
)
```

**Advantages:**
- Adding new event types requires zero changes to Observer implementations
- Pattern matching on event types is natural: `match event: case ToolCallEvent(): ...`
- Observers that only care about specific events just ignore others
- The protocol surface stays at exactly one method forever

**Concrete observer example:**

```python
class LoggingObserver:
    async def emit(self, event: Event) -> None:
        match event:
            case ToolCallEvent(tool_name=name, turn=turn):
                logger.info(f"Turn {turn}: calling {name}")
            case ScriptErrorEvent(error=err):
                logger.error(f"Script error: {err}")
            case _:
                pass  # ignore events we don't care about
```

---

## Idea 6: Bundle as the Only Entry Point

### Problem

Currently, using structured-agents requires manually wiring: client, plugin, grammar config, registries, backends, tool source, observer, history strategy, and kernel config. The bundle system helps but still requires `bundle.build_tool_source(backend)` and manual backend construction.

### Proposal: Bundle Produces a Ready-to-Run Agent

```python
agent = Agent.from_bundle("./my_agent")
result = await agent.run("List all tasks")
```

Where `Agent.from_bundle()` handles all wiring internally:

```python
class Agent:
    """A ready-to-run agent. The top-level user-facing API."""
    
    @classmethod
    def from_bundle(cls, path: str | Path, **overrides) -> Agent:
        """Load a bundle and construct a fully wired agent."""
        manifest = load_manifest(path)
        tools = discover_tools(manifest.agents_dir, manifest.limits)
        adapter = get_adapter(manifest.model.plugin)
        grammar = GrammarPipeline(adapter.grammar_builder, manifest.grammar_config)
        client = build_client(manifest.model)
        kernel = AgentKernel(client, adapter, tools, grammar=grammar)
        return cls(kernel, manifest)
    
    async def run(self, user_input: str, **kwargs) -> RunResult:
        """Run the agent with a user message."""
        messages = self._build_messages(user_input)
        return await self.kernel.run(messages, **kwargs)
```

**For advanced users**, the kernel and all components are still individually accessible and composable. The `Agent` class is sugar, not a cage.

**The bundle.yaml simplifies too:**

```yaml
name: workspace_agent
model: qwen                          # adapter name
grammar: json_schema                 # or ebnf, structural_tag
limits: default                      # or strict, permissive, or inline

system_prompt: |
  You are a workspace assistant.

tools:
  - agents/workspace/*.pym           # glob pattern!
  
termination: submit_result
max_turns: 10
```

Notice: no `registry` section, no `backend` section, no `model.grammar.args_format`. These were implementation details that leaked into the config. The glob pattern for tools is cleaner than listing each tool by name.

---

## Idea 7: Rethink the Module Structure

### Current: 8 Packages, 51 Files

```
structured_agents/
  backends/ (4 files)
  bundles/ (2 files)
  client/ (3 files)
  grammar/ (7 files)
  observer/ (4 files)
  plugins/ (10 files)
  registries/ (4 files)
  tool_sources/ (2 files)
  + 5 top-level files
```

### Proposed: 4 Packages, ~20 Files

```
structured_agents/
  __init__.py          # Public API: Agent, AgentKernel, Tool, ToolResult, etc.
  types.py             # Core value types (Message, ToolCall, ToolResult, ToolSchema)
  kernel.py            # AgentKernel (the loop)
  agent.py             # Agent (high-level entry point, bundle loading)
  execution.py         # execute_tools(), ExecutionContext
  history.py           # HistoryStrategy, SlidingWindowHistory
  exceptions.py        # Error hierarchy

  tools/
    __init__.py
    protocol.py        # Tool protocol
    grail.py           # GrailTool, discover_tools()
    python.py          # PythonTool
    data.py            # DataProvider, ResultHandler protocols + impls

  models/
    __init__.py
    adapter.py         # ModelAdapter dataclass
    parsers.py         # ResponseParser protocol + impls (qwen, function_gemma)
    
  grammar/
    __init__.py
    pipeline.py        # GrammarPipeline
    config.py          # GrammarConfig
    artifacts.py       # EBNFGrammar, StructuralTagGrammar, JsonSchemaGrammar
    builders.py        # All builders in one file (they're small)

  events/
    __init__.py
    types.py           # All event dataclasses + Event union type
    observer.py        # Observer protocol, NullObserver, CompositeObserver

  client/
    __init__.py        # LLMClient protocol, OpenAICompatibleClient, build_client
```

**Reduction: 51 → ~20 files.** Each file is meaningful. No file exists just to hold a 3-line protocol or a 10-line bridge class.

**Rationale for merges:**
- `backends/` + `registries/` + `tool_sources/` → `tools/` (one concern: tools)
- `plugins/` → `models/` (it's about model-specific behavior, not "plugins")
- All composites eliminated (lists replace CompositeRegistry; GrammarPipeline replaces GrammarProvider; single emit() replaces CompositeObserver's delegation)
- Grammar builders consolidated into one file (they share structure and are each ~100 lines)

---

## Idea 8: Eliminate the Composite Pattern Entirely

### Problem

The codebase has 3 composite classes (`CompositeRegistry`, `CompositeBackend`, `CompositeObserver`) that all do the same thing: hold a list, iterate, delegate. These exist because the kernel expects a single registry, single backend, single observer.

### Proposal: Accept Lists at the Kernel Level

```python
@dataclass
class AgentKernel:
    tools: list[Tool]            # was: ToolSource (wrapping CompositeRegistry + CompositeBackend)
    observers: list[Observer]    # was: Observer (wrapping CompositeObserver)
```

- **Tools**: A `list[Tool]` is already a composite. The kernel builds a lookup dict on init. No `CompositeRegistry` or `CompositeBackend` needed.
- **Observers**: The kernel's `_emit()` helper iterates the list with `asyncio.gather()`. No `CompositeObserver` needed.

This eliminates 3 classes and their associated files while making the composition explicit and inspectable.

---

## Idea 9: Context as a First-Class Object, Not a Dict

### Problem

Context flows through the system as `dict[str, Any]` — stringly typed, no validation, no documentation of expected keys. The `ExecutionContext` in V03_CONCEPT.md starts to fix this but is minimal.

### Proposal: Typed Context Chain

```python
@dataclass(frozen=True)
class AgentContext:
    """Immutable context that flows through the entire agent lifecycle."""
    agent_id: str
    workspace: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def with_call(self, call_id: str, tool_name: str) -> ToolContext:
        """Create a tool-execution context from this agent context."""
        return ToolContext(
            agent_id=self.agent_id,
            call_id=call_id,
            tool_name=tool_name,
            workspace=self.workspace,
            metadata=self.metadata,
        )


@dataclass(frozen=True)
class ToolContext:
    """Context for a single tool execution."""
    agent_id: str
    call_id: str
    tool_name: str
    workspace: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
```

This replaces:
- The loose `context: dict[str, Any]` parameter on backends
- The `ExecutionContext` from V03_CONCEPT.md
- The `context_providers` mechanism (context is built once and flows down, not assembled per-call)

---

## Idea 10: Error Handling as Result Types, Not Exceptions

### Problem

V03_CONCEPT.md proposes catching 7 grail exception types and converting each to a `ToolResult(is_error=True)`. The kernel also wraps tool execution in try/except and converts exceptions to error results. This means errors are thrown as exceptions, caught immediately, and converted to values — the worst of both worlds.

### Proposal: Tool.execute() Always Returns, Never Throws

```python
@dataclass(frozen=True)
class ToolResult:
    call_id: str
    output: str
    error: ToolError | None = None  # None = success
    
    @property
    def is_error(self) -> bool:
        return self.error is not None


@dataclass(frozen=True)
class ToolError:
    kind: str          # "limit", "input", "execution", "parse", "output", "external", "check"
    message: str
    line: int | None = None
    detail: str | None = None
```

`GrailTool.execute()` internally catches all grail exceptions and returns `ToolResult` with a `ToolError`. It never raises. The kernel never needs try/except around tool execution — it processes results uniformly.

This is cleaner because:
- The kernel's tool execution loop has zero error handling code
- Error information is structured and inspectable (not just a string)
- Observers receive error data in a typed format, not exception tracebacks
- Tests can assert on `result.error.kind == "limit"` instead of `assertRaises`

---

## Idea 11: Constrained Decoding Deserves a Clearer Mental Model

### Problem

The grammar system is powerful but its naming is confusing. `"json_schema"` mode in FunctionGemma produces EBNF, not JSON Schema. The relationship between `GrammarConfig.mode`, `GrammarBuilder`, `GrammarArtifact`, and `send_tools_to_api` requires reading implementation code to understand.

### Proposal: Name Things by What They Do

```python
@dataclass(frozen=True)
class DecodingConstraint:
    """How to constrain the model's output to valid tool calls."""
    
    strategy: Literal["ebnf", "structural_tag", "json_schema"]
    # "ebnf": Custom EBNF grammar → model outputs must match grammar rules
    # "structural_tag": xgrammar StructuralTag → model fills in tagged slots
    # "json_schema": JSON Schema → model outputs valid JSON matching schema
    
    allow_parallel_calls: bool = False
    send_tools_to_api: bool = False
    # When True: tools are sent in the API request (vLLM may override our grammar)
    # When False: tools are embedded in the grammar only (full control)
```

And the pipeline:

```python
class ConstraintBuilder(Protocol):
    """Builds a decoding constraint for a specific model family."""
    
    def build(self, tools: list[ToolSchema], constraint: DecodingConstraint) -> VLLMPayload | None: ...

# Where VLLMPayload is just:
VLLMPayload = dict[str, Any]  # The extra_body dict for vLLM
```

Renaming `GrammarConfig` → `DecodingConstraint`, `GrammarBuilder` → `ConstraintBuilder`, `GrammarArtifact` → eliminated (just return the payload directly), `GrammarPipeline` → `ConstraintPipeline`.

The intermediate `GrammarArtifact` types (`EBNFGrammar`, `StructuralTagGrammar`, `JsonSchemaGrammar`) still exist internally as builder implementation details, but the public interface is just: tools in, vLLM payload out.

---

## Idea 12: The V03 Data Flow Model is Right — Generalize It

V03_CONCEPT.md's biggest insight is **scripts as pure functions**: data in via virtual filesystem, validated result out, host persists mutations. This should be the organizing principle for the whole library, not just the grail integration.

### Generalized Data Flow

```
User Input → Agent Context
           → Tools (discovered from config)
           → Model Adapter (formats for specific LLM)
           → Decoding Constraints (grammar for valid output)
           ─────────────────────────────────────
           → Kernel Loop:
               Model Call (constrained) → Tool Calls
               Data Provider → Virtual FS → Script Execution → Validated Result
               Result Handler → Persistence
               Observer ← Events at each stage
           ─────────────────────────────────────
           → Run Result (final message, usage, history)
```

Every stage is a pure transform with observable side effects. The kernel is the loop that ties them together. This is the mental model a developer should hold.

---

## Summary: The Proposed Architecture

### Conceptual Model (5 things to hold in your head)

1. **Tool** — has a schema, can execute with arguments and context
2. **ModelAdapter** — formats messages and parses responses for a specific model family  
3. **DecodingConstraint** — forces the model to output valid tool calls
4. **Kernel** — the loop: ask model → execute tools → repeat
5. **Agent** — the entry point: load config, wire everything, run

### File Count

| Current | Proposed | Reduction |
|---------|----------|-----------|
| 51 files | ~20 files | 60% fewer |
| 8 packages | 4-5 packages | 40-50% fewer |
| ~3800 LOC | ~2000 LOC (est.) | ~47% less |
| 6 protocol hierarchies | 3 protocols | 50% fewer |
| 3 composite classes | 0 | eliminated |

### Protocols (the only abstractions that matter)

```python
class Tool(Protocol):
    schema: ToolSchema
    async def execute(self, arguments: dict, context: ToolContext) -> ToolResult: ...

class Observer(Protocol):
    async def emit(self, event: Event) -> None: ...

class HistoryStrategy(Protocol):
    def trim(self, messages: list[Message], max_messages: int) -> list[Message]: ...
```

Everything else is a concrete class or a dataclass. Three protocols is the right number for a library of this scope.

### The Acid Test

Can a new developer understand the architecture in 15 minutes? With the proposed design:

1. Read `agent.py` — see how an agent is created from a bundle
2. Read `kernel.py` — see the loop (ask model, execute tools, repeat)
3. Read `tools/grail.py` — see how a .pym script becomes a tool
4. Read `models/adapter.py` — see how model-specific formatting works
5. Read `grammar/pipeline.py` — see how constrained decoding works

Five files. That's the whole system.

---

## Risk Assessment

| Idea | Risk | Mitigation |
|------|------|------------|
| Collapsing Tool abstraction stack | Loses runtime registry/backend swapping | Nobody does this in practice; composition at construction is sufficient |
| Flattening plugin system | May need MessageFormatter variation for future models | ModelAdapter has override slots; add them when needed, not before |
| Single emit() observer | Slightly more work per observer implementation | Pattern matching is natural in Python 3.10+; much less protocol surface |
| Eliminating composites | Kernel takes lists instead of single objects | Lists are simpler and more inspectable |
| Error-as-values | Different from Python convention of raising exceptions | Tools are I/O boundaries; result types at boundaries are well-established |
| Glob patterns in bundle.yaml | More implicit than explicit tool listing | Support both: `tools: [agents/*.pym]` or `tools: [{name: add_entry, path: ...}]` |

---

## What This Does NOT Change

- **Grail as the script runtime** — .pym scripts are still the tool authoring format
- **vLLM as the inference backend** — OpenAI-compatible client stays
- **xgrammar for constrained decoding** — grammar builders still use xgrammar
- **The core loop semantics** — ask model, execute tools, repeat until done
- **Frozen value types** — Message, ToolCall, ToolResult, ToolSchema stay immutable
- **Async-first** — everything remains async

The refactor changes how the pieces are organized and connected, not what the pieces do.

---

## Recommended Reading Order for Implementation

1. Start with `types.py` — define the value types (mostly unchanged)
2. Then `tools/protocol.py` + `tools/grail.py` — the Tool abstraction + grail impl
3. Then `grammar/` — the constraint pipeline
4. Then `models/adapter.py` + parsers — model-specific formatting
5. Then `kernel.py` — the loop
6. Then `agent.py` + bundle loading — the entry point
7. Then `events/` — observer system
8. Finally, migrate existing .pym scripts and demos
