# VLLM Extraction Refactor Brainstorm

Date: 2026-02-21

This document explores a two-part refactor:

1. Extract a standalone vLLM runtime library with pluggable model integrations.
2. Refactor Remora to depend on that library and simplify its architecture.

The goal is to reduce developer cognitive overhead, clarify boundaries, and make Remora easier to compose into custom agent workflows.

---

## Part 1: New Runtime Library Proposal

### 1.1 Goals

- Provide an opinionated, high-level runtime for vLLM that supports XGrammar EBNF structured outputs.
- Make model-specific behavior pluggable (prompt format, tool-call parsing, grammar strategy, default options).
- Offer a clean, stable Python API that Remora and other projects can depend on.
- Keep the surface area narrow: “run a model with tools + grammar, get tool calls + text.”

### 1.2 Recommended Packaging

- Package name: `remora-runtime` or `remora-vllm-runtime`.
- Optional extras:
  - `remora-runtime[vllm]` for server management.
  - `remora-runtime[xgrammar]` for grammar validation helpers.
  - `remora-runtime[harness]` for optional `.pym` harness integration.

### 1.3 Core Capabilities

**Runtime client API**

- Single, opinionated entry point for model execution.
- Encapsulates grammar enforcement, tool schemas, and model-specific quirks.

Example API sketch:

```python
from remora_runtime import RuntimeClient, RuntimeConfig
from remora_runtime.plugins import FunctionGemmaPlugin

client = RuntimeClient(
    config=RuntimeConfig(model="function-gemma", base_url="http://localhost:8000"),
    plugin=FunctionGemmaPlugin(grammar_strategy="permissive"),
)

result = await client.run(
    prompt="Summarize this file...",
    tools=tool_schemas,
)

print(result.text)
print(result.tool_calls)
```

**Plugin system**

- Model behaviors are isolated in plugins.
- Plugins define how to:
  - Build the chat prompt format
  - Choose tool-choice strategy
  - Parse tool calls
  - Provide default grammar strategy

Example plugin protocol:

```python
class ModelPlugin(Protocol):
    name: str

    def build_messages(self, prompt: str, system: str | None) -> list[dict]: ...
    def tool_choice(self, tools: list[dict]) -> str | dict: ...
    def grammar_strategy(self) -> str | None: ...
    def parse_response(self, response: dict) -> ModelResult: ...
```

**Grammar strategies**

- Grammar builder registry.
- EBNF strategies named and versioned.

```python
GRAMMAR_STRATEGIES = {
    "permissive": build_permissive_grammar,
    "strict_json": build_strict_json_grammar,
    "typed": build_typed_grammar,
}
```

**Server management**

- Optional server launcher and health checks.
- Designed to be opinionated: “run this model with these settings.”

```python
from remora_runtime.server import VllmServer

server = VllmServer(model="function-gemma", port=8000)
server.start()
server.wait_until_healthy()
```

### 1.4 Optional Harness Integration

The `.pym` harness and execution model are unique to Remora and might be better kept in Remora, but there are two viable options:

**Option A: Keep harness in Remora (recommended)**

- Runtime stays generic and focused on model interaction.
- Remora stays the place for Grail scripts and tool execution.
- Lower coupling and a clearer boundary.

**Option B: Put harness in runtime as an optional extra**

- Makes the runtime more opinionated and Remora-like.
- Might help other projects that want to reuse `.pym` tools.
- Increases complexity and surface area of runtime.

Recommendation: keep harness in Remora, but define a clean adapter interface so Remora can use the runtime without leaking tool-execution details into it.

### 1.5 Capability Matrix

| Capability | Runtime Library | Remora |
|------------|------------------|--------|
| vLLM request/response | ✅ | ❌ |
| Grammar generation | ✅ | ❌ |
| Model prompt formats | ✅ | ❌ |
| Tool call parsing | ✅ | ❌ |
| vLLM server lifecycle | ✅ | ❌ |
| `.pym` tool execution | ❌ | ✅ |
| Tree-sitter discovery | ❌ | ✅ |
| Orchestration + events | ❌ | ✅ |
| Context management | ❌ | ✅ |

---

## Part 2: Remora Refactor Around the Runtime

### 2.1 Core Architecture Changes

**Before (today)**

- Remora owns vLLM request construction, grammar enforcement, and FunctionGemma-specific handling.
- `runner.py` handles tool parsing + execution + prompt assembly + events.
- Context manager is tightly coupled to the runner.

**After (future)**

- Remora delegates all model interactions to the runtime library.
- `Runner` becomes a thin orchestration layer.
- Model-specific details move into runtime plugins.

### 2.2 Module-Level Refactor Plan

**New Remora dependencies**

- `remora_runtime.RuntimeClient`
- `remora_runtime.plugins.ModelPlugin`
- `remora_runtime.server.VllmServer` (optional)

**Remora changes**

- Replace `FunctionGemmaRunner` with `RuntimeRunner` that:
  - Builds prompt context
  - Sends to runtime
  - Dispatches tool calls
  - Emits events

- Delete or move all grammar/tool-choice/prompt-format logic out of Remora.

### 2.3 Before/After Developer Experience

**Before: manual runner setup**

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

**After: runtime-backed runner**

```python
from remora.runtime import RuntimeRunner
from remora_runtime import RuntimeClient, RuntimeConfig
from remora_runtime.plugins import FunctionGemmaPlugin

client = RuntimeClient(
    config=RuntimeConfig(model="function-gemma", base_url="http://localhost:8000"),
    plugin=FunctionGemmaPlugin(grammar_strategy="permissive"),
)

runner = RuntimeRunner(
    runtime_client=client,
    definition=definition,
    tool_registry=tool_registry,
    node=node,
    workspace_id=workspace_id,
)

result = await runner.run()
```

**Before: implicit model choices**

```python
# Prompt formatting and tool choice are buried in FunctionGemmaRunner
runner = FunctionGemmaRunner(...)
```

**After: explicit model plugin**

```python
# Explicit model behavior via plugin
client = RuntimeClient(..., plugin=FunctionGemmaPlugin())
```

### 2.4 Additional Simplifications Enabled

**1) Runner decomposition**

- Split into small components:
  - `PromptBuilder`
  - `ToolDispatcher`
  - `EventEmitter`
  - `RuntimeRunner`

**2) Context system simplification**

- Convert to a single “recent actions” list by default.
- Make hub integration opt-in.
- Keep summarization optional.

**3) Tool dispatch refactor**

- Extract to its own class with a clean interface:

```python
class ToolDispatcher:
    async def dispatch(self, tool_call: ToolCall, inputs: dict) -> ToolResult: ...
```

**4) Event emission consolidation**

- Replace multiple `_emit_*` methods with a small event builder.

**5) Remove legacy and defensive code paths**

- Delete tool parsing logic duplicated across runner methods.
- Remove “no tool calls” fallback if grammar enforcement is the standard.

### 2.5 Developer Experience Goals

- “Model interaction” is not a Remora concern.
- Developers only need to understand:
  - How to define tools and operations
  - How to construct a `RuntimeClient`
  - How to run Remora orchestration

### 2.6 Migration Phases (high-level)

1. Extract runtime library with a minimal plugin interface.
2. Create a `RuntimeRunner` that replaces `FunctionGemmaRunner`.
3. Delete FunctionGemma-specific grammar and prompt logic from Remora.
4. Refactor context and tool execution layers for simplicity.
5. Add simple integration tests for runtime + Remora interaction.

---

## Summary

A standalone runtime library with a plugin system cleanly separates model-specific behavior from Remora’s orchestration and tool execution. This should reduce cognitive overhead by giving developers a smaller, more consistent surface area to learn, while making it easy to adopt new models and grammar strategies. The most important design decision is keeping the runtime’s API small and opinionated, with Remora retaining the harness/tool execution pieces.
