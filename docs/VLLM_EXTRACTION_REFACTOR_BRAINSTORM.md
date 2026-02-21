# VLLM Extraction Refactor Brainstorm

Date: 2026-02-21

This document explores a two-part refactor:

1. Extract a standalone structured tool orchestration core that integrates XGrammar + `.pym` execution and owns vLLM configuration.
2. Refactor Remora to depend on this core and simplify its architecture.

The goal is to reduce developer cognitive overhead, clarify responsibilities, and make Remora easier to compose into custom agent workflows.

---

## Part 1: Structured Tool Orchestration Core

### 1.1 Concept and Goals

This new library is not a generic “model runtime.” Instead, it is an opinionated core for **structured tool execution**:

- Guarantees model output format via XGrammar.
- Parses tool calls and executes them via `.pym` scripts by default.
- Allows alternative tool backends when needed.
- Owns vLLM configuration defaults and schema.
- Exposes a small API centered on “run prompt + tools → tool calls + results.”

The emphasis is on turning a model into a reliable tool-call generator and executor.

### 1.2 Packaging Proposal

- Package name: `remora-toolcore` or `remora-structured-tools`.
- Optional extras:
  - `remora-toolcore[vllm]` for server launcher helpers.
  - `remora-toolcore[xgrammar]` for grammar validation utilities.

### 1.3 Core API Sketch

```python
from remora_toolcore import ToolKernel, KernelConfig
from remora_toolcore.plugins import FunctionGemmaPlugin

kernel = ToolKernel(
    config=KernelConfig(
        model="function-gemma",
        base_url="http://localhost:8000",
    ),
    plugin=FunctionGemmaPlugin(grammar_strategy="permissive"),
)

result = await kernel.run(
    prompt="Summarize this file...",
    tools=tool_schemas,
)

print(result.text)
print(result.tool_calls)
print(result.tool_results)
```

### 1.4 Plugin System (Model-Specific Behavior)

Plugins define model- and grammar-specific behavior:

```python
class ModelPlugin(Protocol):
    name: str

    def build_messages(self, prompt: str, system: str | None) -> list[dict]: ...
    def tool_choice(self, tools: list[dict]) -> str | dict: ...
    def grammar_strategy(self) -> str | None: ...
    def parse_response(self, response: dict) -> ModelResult: ...
```

The core owns the orchestration; plugins handle model quirks.

### 1.5 Tool Backends (Default `.pym` Executor)

The core should ship with a default `.pym` tool backend, but allow alternates:

```python
class ToolBackend(Protocol):
    async def execute(self, tool_call: ToolCall, inputs: dict) -> ToolResult: ...
```

**Default backend**: `.pym` execution with process isolation and input shaping.

**Alternate backends** (optional):
- Direct Python function registry
- RPC or sandboxed runner
- External tool service

This keeps `.pym` as the first-class experience without blocking future needs.

### 1.6 Grammar Strategy Registry

```python
GRAMMAR_STRATEGIES = {
    "permissive": build_permissive_grammar,
    "strict_json": build_strict_json_grammar,
    "typed": build_typed_grammar,
}
```

The core decides when to apply grammar, caching, and tool-choice strategy.

### 1.7 vLLM Configuration Ownership

The core owns vLLM defaults and configuration schema, but does not force orchestration.
Remora can load and pass configuration through:

```python
from remora_toolcore import VllmConfig

config = VllmConfig(
    model="function-gemma",
    dtype="bfloat16",
    max_model_len=4096,
)
```

**Optional**: a lightweight server helper that Remora can call, but not required.

### 1.8 Concrete Data Contracts (Sketch)

**Tool and result types**

```python
@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]
    call_id: str | None = None

@dataclass(frozen=True)
class ToolResult:
    name: str
    output: dict[str, Any] | str
    call_id: str | None = None
    is_error: bool = False
```

**Model response**

```python
@dataclass(frozen=True)
class ModelResult:
    text: str
    tool_calls: list[ToolCall]
```

**Kernel run result**

```python
@dataclass(frozen=True)
class KernelResult:
    text: str
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
```

**Kernel configuration**

```python
@dataclass(frozen=True)
class KernelConfig:
    model: str
    base_url: str
    timeout_s: float = 60
    max_retries: int = 2
    vllm: VllmConfig | None = None
```

**Tool backend protocol**

```python
class ToolBackend(Protocol):
    async def execute(
        self,
        tool_call: ToolCall,
        inputs: dict[str, Any],
    ) -> ToolResult: ...
```

**Model plugin protocol**

```python
class ModelPlugin(Protocol):
    name: str

    def build_messages(
        self,
        prompt: str,
        system: str | None,
        context: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]: ...

    def tool_choice(self, tools: list[dict[str, Any]]) -> str | dict: ...

    def grammar_strategy(self) -> str | None: ...

    def parse_response(self, response: dict[str, Any]) -> ModelResult: ...
```

### 1.9 Capability Matrix

| Capability | Tool Core | Remora |
|------------|-----------|--------|
| vLLM request/response | ✅ | ❌ |
| XGrammar enforcement | ✅ | ❌ |
| Tool-call parsing | ✅ | ❌ |
| `.pym` execution backend | ✅ | ❌ |
| Alternate tool backends | ✅ | ❌ |
| vLLM config schema | ✅ | ❌ |
| Orchestration + events | ❌ | ✅ |
| Tree-sitter discovery | ❌ | ✅ |
| Context management | ❌ | ✅ |

### 1.10 Open Questions, Options, and Recommendations

- **Boundary pressure**
  - Options:
    - Keep events in Remora only and treat the core as a pure kernel.
    - Add a small, optional callback interface in the core for progress updates.
  - Recommendation: keep events in Remora; add optional callbacks only if needed.

- **Plugin explosion**
  - Options:
    - Support a single “first‑class” plugin (FunctionGemma) in core, push others to contrib.
    - Support 2–3 plugins with a strict compatibility matrix.
  - Recommendation: ship FunctionGemma + one additional plugin to validate the interface.

- **`.pym` portability**
  - Options:
    - Require POSIX + Python, document constraints.
    - Add optional sandbox backends for Windows or containerized execution.
  - Recommendation: start with current POSIX model, design the backend interface for future portability.

- **Config ownership**
  - Options:
    - Core owns all vLLM config models and defaults.
    - Core owns schema, Remora owns defaults.
  - Recommendation: core owns schema and defaults; Remora overrides per workflow.

- **Testing strategy**
  - Options:
    - Unit test plugins + tool core; integration tests only in Remora.
    - Full end‑to‑end tests in core that start vLLM.
  - Recommendation: unit tests in core, E2E in Remora to avoid heavy infra in core.

- **Versioning**
  - Options:
    - Strict semver for core, Remora pins a compatible range.
    - Loose compatibility with fast iteration.
  - Recommendation: strict semver for core, Remora pins minor range.

---

## Part 2: Remora Refactor Around the Core

### 2.1 Core Architecture Changes

**Before (today)**

- Remora owns model request formatting, grammar enforcement, and tool parsing.
- `runner.py` mixes model interaction, tool dispatch, and event emission.
- Context manager and runner are tightly coupled.

**After (future)**

- Remora delegates model interaction and tool execution to the core.
- Remora focuses on orchestration, context, and developer UX.
- Tool parsing and `.pym` execution logic are removed from Remora.

### 2.2 Module-Level Refactor Plan

**New Remora dependencies**

- `remora_toolcore.ToolKernel`
- `remora_toolcore.plugins.ModelPlugin`
- `remora_toolcore.backends.ToolBackend` (optional override)
- `remora_toolcore.VllmConfig`

**Remora changes**

- Replace `FunctionGemmaRunner` with `KernelRunner` that:
  - Builds prompt context
  - Sends to the tool core
  - Streams events
  - Aggregates tool results

- Remove all grammar/tool-choice/prompt-format logic from Remora.
- Remove `.pym` execution code from Remora (now owned by core).

### 2.3 Before/After Developer Experience

**Before: Remora-owned tool execution**

```python
from remora.runner import FunctionGemmaRunner
from remora.tool_registry import GrailToolRegistry

runner = FunctionGemmaRunner(
    definition=definition,
    tool_registry=GrailToolRegistry.from_workspace(workspace),
    node=node,
    workspace_id=workspace_id,
)

result = await runner.run()
```

**After: Tool core–backed runner**

```python
from remora.runtime import KernelRunner
from remora_toolcore import ToolKernel, KernelConfig
from remora_toolcore.plugins import FunctionGemmaPlugin

kernel = ToolKernel(
    config=KernelConfig(model="function-gemma", base_url="http://localhost:8000"),
    plugin=FunctionGemmaPlugin(grammar_strategy="permissive"),
)

runner = KernelRunner(
    kernel=kernel,
    definition=definition,
    node=node,
    workspace_id=workspace_id,
)

result = await runner.run()
```

**Before: implicit model handling**

```python
# Model formatting and tool parsing are buried in FunctionGemmaRunner
runner = FunctionGemmaRunner(...)
```

**After: explicit plugin selection**

```python
kernel = ToolKernel(..., plugin=FunctionGemmaPlugin())
```

### 2.4 Additional Simplifications Enabled

**1) Runner decomposition**

- Split into small components:
  - `PromptBuilder`
  - `EventEmitter`
  - `KernelRunner`

**2) Context system simplification**

- Default to a single “recent actions” list.
- Make hub integration opt-in.
- Keep summarization optional.

**3) Remove redundant tool parsing**

- Tool parsing is owned by the tool core.
- Remora no longer has duplicated parsing logic.

**4) Event emission consolidation**

- Replace multiple `_emit_*` methods with a generic emitter.

### 2.5 Developer Experience Goals

- Developers think in terms of “use Remora to orchestrate agents.”
- Tool execution and structured outputs are handled by the core.
- Remora remains a clean, composable orchestration layer.

### 2.6 Migration Phases (High-Level)

1. Extract the tool core with `.pym` backend and plugin system.
2. Create `KernelRunner` to replace `FunctionGemmaRunner`.
3. Remove grammar/tool parsing and `.pym` execution from Remora.
4. Simplify context and event emission logic.
5. Add integration tests for Remora + tool core.

---

## Summary

A standalone structured tool orchestration core provides a clear contract: enforce grammar, parse tool calls, and execute `.pym` tools by default. Remora then becomes a pure orchestration layer that depends on this core. This makes the system easier to reason about, reduces cognitive overhead, and keeps model- and tool-specific logic out of Remora’s main codebase.
