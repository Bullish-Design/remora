# FunctionGemma Subagents: Concept

## Overview

FunctionGemma subagents are a next-generation execution model for remora's specialized agents. Instead of each specialized agent being a monolithic `.pym` script that implements its full logic imperatively, each agent becomes a **tiny, locally-running, fine-tuned language model** that reasons about its task, decides which tools to call, inspects the results, and iterates — all within an isolated Cairn workspace.

The model is [FunctionGemma](https://huggingface.co/google/functiongemma-4b), Google's 270M parameter model purpose-built for structured tool calling. At ~288MB quantized, it runs on a single CPU core with no API dependency, no network calls, and no data leaving the machine.

---

## The Problem with Monolithic Agents

In the current architecture, `lint_agent.pym`, `test_generator_agent.pym`, and friends are monolithic: their logic is fully encoded in the `.pym` script and executed once. This works for deterministic operations ("run ruff, apply fixes, done") but breaks down for anything requiring multi-step reasoning:

- What if ruff finds an issue that can only be fixed by understanding broader context?
- What if a generated test fails because a fixture is missing?
- What if a docstring needs to reference a related function elsewhere in the file?

A monolithic `.pym` agent has no feedback loop. It cannot inspect its own outputs and decide what to do next.

FunctionGemma subagents solve this with a **multi-turn tool calling loop**: the model examines the situation, calls a tool, inspects the result, and continues until it determines the task is complete.

---

## Architecture: Pattern C

Each FunctionGemma subagent is defined by a **YAML definition file** that combines three things:

1. **Static initial context** — the system prompt, domain knowledge, and the CST node to operate on; set once at spawn time
2. **Tool catalog** — a set of coarse-grained tools the model can invoke, each backed by a `.pym` script
3. **Per-tool context providers** — optional `.pym` scripts that inject additional context into the conversation at the moment a specific tool is invoked

```
Subagent Definition (YAML)
├── model:          Fine-tuned FunctionGemma GGUF path
├── initial_context:
│   ├── system_prompt  (static domain knowledge)
│   └── node_context   (injected at runtime from CSTNode)
└── tools:
    ├── tool_a
    │   ├── pym:              Cairn .pym script to execute
    │   ├── description:      What the model sees
    │   ├── parameters:       JSON Schema for arguments
    │   └── context_providers: [optional .pym scripts that
    │                           enrich context before this tool]
    ├── tool_b ...
    └── submit_result         (always present; terminates the loop)
```

### Why Pattern C

**Initial context** gives the model a stable foundation: what it is, what the task is, and the code it is operating on. This is loaded once and never changes.

**Per-tool context** handles information that is only relevant at a specific decision point. For example, a test generator does not need the project's `pytest.ini` loaded upfront — it needs it at the moment it calls `generate_test`, so a context provider fetches it then and injects it into the conversation. This keeps the initial context minimal and the context window focused.

---

## Execution Model

### Multi-Turn Tool Calling Loop

The FunctionGemma runner executes a standard multi-turn loop, identical in structure to the pattern documented in the Cerebras tool calling reference:

```
1. Build initial messages (system prompt + node context + task description)
2. Call model with tool catalog → model responds with tool_calls or plain text
3. If tool_calls:
   a. For each tool call:
      - Run any per-tool context providers (inject into messages)
      - Execute the tool's .pym script in the Cairn workspace
      - Append tool result to messages
   b. Go to step 2
4. If no tool_calls: task is complete; extract final result from message
```

The model decides when it is done by calling `submit_result` (the terminal tool) or by producing a plain text response. The loop does not terminate until one of these occurs or a turn limit is reached.

### Relationship to Cairn

Each FunctionGemma subagent run gets **one Cairn workspace** (`agent-{operation}-{node-id}.db`). Every `.pym` tool the model invokes executes inside this workspace. This preserves all existing Cairn guarantees:

- Sandboxed execution — `.pym` tools cannot access the host filesystem directly
- Copy-on-write isolation — the stable workspace is never touched during execution
- Human review gate — workspace changes flow into the existing accept/reject workflow

The FunctionGemma runner is a new layer _above_ the `.pym` execution layer, not a replacement for it. The sandbox remains intact.

```
┌─────────────────────────────────────────────────────────────┐
│  FunctionGemma Runner (new)                                  │
│  - Loads subagent definition                                 │
│  - Builds initial context from CSTNode                       │
│  - Runs multi-turn loop                                      │
│  - Dispatches tool calls → .pym execution                    │
└──────────────────────────┬──────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────┐
│  Cairn Execution Layer (unchanged)                           │
│  - .pym tool scripts execute in sandbox                      │
│  - Single workspace per subagent run                         │
│  - Submit result → REVIEWING state                           │
│  - Human accept/reject → stable workspace                    │
└─────────────────────────────────────────────────────────────┘
```

---

## Subagent Definition Format

```yaml
# agents/lint/lint_subagent.yaml

name: lint_agent
model: models/lint_functiongemma_q8.gguf

initial_context:
  system_prompt: |
    You are a Python linting specialist. Your job is to analyze the provided
    code for style violations, apply safe auto-fixes, and report any issues
    that require manual attention. Be conservative: only apply fixes that
    are guaranteed to preserve semantics. Do not rewrite logic.

  # {{ node_text }} is injected at runtime from the CSTNode
  node_context: |
    Code to analyze:
    ```python
    {{ node_text }}
    ```

tools:
  - name: run_linter
    pym: agents/lint/tools/run_linter.pym
    description: >
      Run the configured linter on the current code and return a list of
      issues with their line numbers and codes.
    parameters:
      type: object
      properties:
        check_only:
          type: boolean
          description: "If true, report issues without applying fixes."
      additionalProperties: false

  - name: apply_fix
    pym: agents/lint/tools/apply_fix.pym
    description: >
      Apply a fix for a specific lint issue code. Only call this for issues
      the linter confirmed are auto-fixable.
    parameters:
      type: object
      properties:
        issue_code:
          type: string
          description: "The lint rule code to fix (e.g. E501, F401)."
        line_number:
          type: integer
          description: "Line number of the issue."
      required: [issue_code, line_number]
      additionalProperties: false
    context_providers:
      # Fetches the project ruff config and injects it into the conversation
      # so the model understands project-specific rule overrides.
      - agents/lint/context/ruff_config.pym

  - name: read_current_file
    pym: agents/lint/tools/read_file.pym
    description: "Read the current state of the file being analyzed."
    parameters:
      type: object
      properties: {}
      additionalProperties: false

  - name: submit_result
    pym: agents/lint/tools/submit.pym
    description: >
      Submit the final linting results and end the task. Call this when
      all fixable issues have been addressed or you have determined no
      changes are needed.
    parameters:
      type: object
      properties:
        summary:
          type: string
          description: "Human-readable summary of what was done."
        issues_fixed:
          type: integer
        issues_remaining:
          type: integer
        changed_files:
          type: array
          items:
            type: string
      required: [summary, issues_fixed, issues_remaining, changed_files]
      additionalProperties: false
```

---

## Tool Design: Coarse-Grained

Each subagent has **4–8 tools**, tuned to the domain. Tools are coarse enough that the model does not need to compose many low-level primitives, but fine enough that multi-turn reasoning adds real value.

**Guiding principles:**

- Each tool corresponds to a meaningful step in the task workflow
- Tool names and descriptions are written for the model, not the programmer
- The `submit_result` tool is always the terminal action and is always present
- Tools that mutate workspace files are distinct from tools that only read

**Example tool sets by subagent:**

| Subagent | Tools |
|---|---|
| `lint_agent` | `run_linter`, `apply_fix`, `read_current_file`, `submit_result` |
| `test_agent` | `analyze_signature`, `read_existing_tests`, `write_test_file`, `run_tests`, `submit_result` |
| `docstring_agent` | `read_current_docstring`, `read_type_hints`, `write_docstring`, `submit_result` |
| `sample_data_agent` | `analyze_signature`, `write_fixture_file`, `submit_result` |

---

## Context Lifecycle

### Static Initial Context (loaded once at spawn)

At spawn time, the runner builds the initial message list from the subagent definition:

```
messages = [
    {role: "system",  content: system_prompt},
    {role: "user",    content: rendered_node_context},
]
```

`{{ node_text }}` and other template variables are resolved from the `CSTNode` passed to the runner. This context does not change during execution.

### Per-Tool Context Injection (loaded on demand)

When the model calls a tool that has `context_providers`, the runner executes each provider `.pym` script before dispatching the tool. Provider output is injected into the messages as an assistant note:

```
messages.append({
    role: "assistant",
    content: f"[Context] {provider_output}"
})
```

This lets domain-specific context (project config, related functions, type stubs) enter the conversation exactly when it is relevant, without bloating the initial context window.

---

## State: Static MVP → Hybrid

### MVP: Static State

For the initial implementation, all subagent state is **static and defined in the YAML file**. The model has no memory between runs; each invocation starts from the same initial context. This is sufficient to validate the architecture and measure accuracy.

### Future: Hybrid State

After the MVP is validated, subagents can evolve toward hybrid state:

- **Short-term memory**: Tool call history from the current run is already in `messages` (the multi-turn loop provides this naturally)
- **Cross-run memory**: A lightweight KV store in the agent workspace can persist observations between runs (e.g., "this file consistently uses NumPy docstring style")
- **Learned patterns**: Patterns extracted from accepted results can be injected as additional initial context on subsequent runs

State evolution is additive — the YAML definition format remains the foundation; memory is layered on top.

---

## Integration with Remora's Coordinator

FunctionGemma subagents slot into the existing coordinator pattern as a new agent execution mode. The coordinator continues to receive a `CSTNode` and a list of operations. For each operation, instead of spawning a monolithic `.pym`, it spawns a `FunctionGemmaRunner`:

```
Current:
  Coordinator → spawn lint_agent.pym (monolithic)

With FunctionGemma:
  Coordinator → spawn FunctionGemmaRunner(lint_subagent.yaml, node)
                    └→ FunctionGemma model runs multi-turn loop
                         ├→ run_linter.pym   (tool call 1)
                         ├→ apply_fix.pym    (tool call 2)
                         ├→ apply_fix.pym    (tool call 3)
                         └→ submit_result.pym (terminal)
```

The coordinator does not need to know whether a subagent is a monolithic `.pym` or a FunctionGemma runner. Both implement the same output contract:

```python
{
    "status": "success" | "failed" | "skipped",
    "workspace_id": str,
    "changed_files": list[str],
    "summary": str,
    "details": dict,
    "error": str | None
}
```

---

## Local Execution

FunctionGemma subagents run entirely locally:

- **Model format**: GGUF (quantized), loaded via `llama.cpp` or an equivalent runtime
- **Model size**: ~288MB per subagent model (Q8 quantization of the 270M parameter base)
- **Inference speed**: ~125 tokens/second on a single CPU core
- **Concurrency**: Multiple subagent models can run simultaneously (one per operation, matching the existing coordinator concurrency model)
- **No network dependency**: No API keys, no external calls, no data egress

The GGUF files live alongside the subagent YAML definitions:

```
agents/
├── lint/
│   ├── lint_subagent.yaml
│   ├── models/
│   │   └── lint_functiongemma_q8.gguf
│   ├── tools/
│   │   ├── run_linter.pym
│   │   ├── apply_fix.pym
│   │   ├── read_file.pym
│   │   └── submit.pym
│   └── context/
│       └── ruff_config.pym
├── test/
│   ├── test_subagent.yaml
│   ├── models/
│   │   └── test_functiongemma_q8.gguf
│   └── tools/ ...
├── docstring/
│   └── ...
└── sample_data/
    └── ...
```

---

## Workspace Layout

Each FunctionGemma subagent run maps to exactly one Cairn workspace, consistent with the single-workspace-per-agent model used throughout remora:

```
.agentfs/
├── stable.db                                  # Original codebase (never touched during runs)
├── coordinator-{node-id}.db                   # Coordinator workspace
├── lint-{node-id}.db                          # lint_agent workspace
│   └── (all run_linter.pym and apply_fix.pym writes land here)
├── test-{node-id}.db                          # test_agent workspace
├── docstring-{node-id}.db                     # docstring_agent workspace
└── sample_data-{node-id}.db                   # sample_data_agent workspace
```

Every `.pym` tool invoked by the FunctionGemma model during a run writes into the same workspace for that operation. The human review and accept/reject flow is unchanged.

---

## Strict Mode

All tool calls use **strict mode** (`strict: true` in the tool schema, `additionalProperties: false` on all parameter objects). This guarantees that the model's tool call arguments exactly match the defined schema — no extra fields, no wrong types, no missing required parameters — which is essential for reliable `.pym` dispatch.

---

## Design Decisions Summary

| Dimension | Decision | Rationale |
|---|---|---|
| Architectural pattern | C — Hybrid initial + per-tool context | Focused initial context; domain context arrives when needed |
| State lifecycle | Static (MVP) → Hybrid (future) | Validates architecture before adding complexity |
| Context strategy | Hybrid — static initial + per-tool providers | Right information at the right moment |
| Tool granularity | Coarse-grained (4–8 per subagent) | Reduces required training data; simpler for model |
| Cairn integration | One workspace per subagent run | Consistent with existing remora model |
| Execution | Local GGUF via llama.cpp | No API dependency; runs anywhere |
| Tool arguments | Strict mode | Reliable dispatch to .pym scripts |
| Concurrency | Sequential tool calls within a run | Determinism; matches parallel_tool_calls=False |
