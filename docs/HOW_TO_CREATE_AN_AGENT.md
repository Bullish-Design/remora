# How to Create a Remora Agent

This guide explains how to create a complete Remora agent — from the YAML definition file to the `.pym` tool scripts. After reading this, you will understand the full lifecycle of an agent definition, how the system transforms it into LLM tool calls, and how to write effective prompts for the FunctionGemma 270M model.

> **Prerequisite:** Read [HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md](HOW_TO_CREATE_A_GRAIL_PYM_SCRIPT.md) first. This guide assumes you understand `.pym` file structure, `Input()` declarations, `@external` functions, `grail check`, and Cairn's external function API.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [The Subagent YAML File](#2-the-subagent-yaml-file)
3. [System Prompts for Small Models](#3-system-prompts-for-small-models)
4. [Node Context Templates](#4-node-context-templates)
5. [Defining Tools](#5-defining-tools)
6. [Enriching Tool Schemas with `inputs_override`](#6-enriching-tool-schemas-with-inputs_override)
7. [System-Injected Inputs](#7-system-injected-inputs)
8. [The `submit_result` Tool](#8-the-submit_result-tool)
9. [Context Providers](#9-context-providers)
10. [How the Pipeline Works End-to-End](#10-how-the-pipeline-works-end-to-end)
11. [Writing Effective `.pym` Tools for Agents](#11-writing-effective-pym-tools-for-agents)
12. [Registering Your Agent](#12-registering-your-agent)
13. [Debugging Agent Failures](#13-debugging-agent-failures)
14. [Complete Example: Building a New Agent](#14-complete-example-building-a-new-agent)

---

## 1. Architecture Overview

A Remora agent is a loop that alternates between two phases:

1. **LLM call:** The FunctionGemma model receives the conversation history and a list of available tools, then decides which tool to call (or calls `submit_result` to finish).
2. **Tool execution:** The runner dispatches the chosen tool by executing a `.pym` Grail script via Cairn, then feeds the result back into the conversation.

```
┌──────────────────────────────────────────────────────────────┐
│                    remora.yaml (config)                       │
│   operations:                                                │
│     lint:                                                    │
│       subagent: lint/lint_subagent.yaml                      │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│              Subagent YAML Definition                         │
│   • system_prompt    — who the agent is                      │
│   • node_context     — what code to work on (Jinja2)         │
│   • tools[]          — available tools (→ .pym scripts)      │
│   • inputs_override  — parameter descriptions for the model  │
└──────────┬───────────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────────────────────┐
│                  Loading Pipeline                             │
│   subagent.py → tool_registry.py → runner.py                 │
│                                                              │
│   1. Parse YAML, resolve paths                               │
│   2. Load .pym via Grail, read inputs.json                   │
│   3. Build OpenAI-format tool schemas                        │
│   4. Apply inputs_override (descriptions, enums, etc.)       │
│   5. Filter system-injected inputs from model view           │
│   6. Assemble messages: [system, user] + tools               │
│   7. Call vLLM → get tool_call → dispatch .pym → loop        │
└──────────────────────────────────────────────────────────────┘
```

The files involved:

| File | Role |
|------|------|
| `agents/<name>/<name>_subagent.yaml` | Agent definition: prompt, tools, overrides |
| `agents/<name>/tools/*.pym` | Tool implementations (Grail scripts) |
| `agents/<name>/context/*.pym` | Context providers (inject config into tools) |
| `.grail/agents/<tool>/inputs.json` | Auto-generated input schemas (from `grail check`) |
| `src/remora/subagent.py` | YAML parser and validator |
| `src/remora/tool_registry.py` | Builds OpenAI-format tool schemas from Grail |
| `src/remora/runner.py` | LLM call loop, tool dispatch, message management |
| `src/remora/config.py` | Operation → subagent mapping |

---

## 2. The Subagent YAML File

Every agent is defined by a single YAML file. Here is the full schema:

```yaml
name: my_agent              # Unique agent name (used in logs and events)
max_turns: 15               # Max LLM call rounds before timeout (default: 20)
model_id: null              # Override the default model (optional)

initial_context:
  system_prompt: |
    Concise description of the agent's role and behavior.
    Always end with: "Always call a function."
  node_context: |
    Jinja2 template rendered with the target code node.
    Available variables: {{ node_text }}, {{ node_name }},
    {{ node_type }}, {{ file_path }}

tools:
  - tool_name: my_tool           # Name the model sees (overrides .pym stem)
    pym: my_agent/tools/my_tool.pym  # Path to .pym script (relative to agents_dir)
    tool_description: |          # Description the model reads to decide when to call
      What this tool does and when to use it.
    inputs_override:             # Optional: enrich parameter schemas
      param_name:
        description: "What this parameter means."
    context_providers:           # Optional: .pym scripts that run before the tool
      - my_agent/context/config.pym

  - tool_name: submit_result     # REQUIRED: exactly one submit_result tool
    pym: my_agent/tools/submit.pym
    tool_description: Submit the final result.
```

### Required Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Agent identifier. Must be unique across all agents. |
| `initial_context.system_prompt` | string | yes | System message sent to the model. |
| `initial_context.node_context` | string | yes | Jinja2 template for the user message. |
| `tools` | list | yes | At least one tool, plus exactly one `submit_result`. |

### Optional Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_turns` | int | 20 | Safety cap on LLM call rounds. |
| `model_id` | string | null | Override model (e.g. a different LoRA adapter). |
| `tool_name` | string | .pym stem | Override the tool name derived from the script filename. |
| `inputs_override` | dict | {} | Add/override parameter descriptions, types, enums. |
| `context_providers` | list | [] | .pym scripts that run before the tool, providing extra context. |

---

## 3. System Prompts for Small Models

The FunctionGemma 270M model is a tiny model designed for structured function calling. It cannot handle the same prompts that work for large models like GPT-4. Follow these rules:

### Rules

1. **One sentence describing the role.** State what the agent IS, not what it can do in general.
2. **One sentence describing the action.** State what to do with the input.
3. **End with "Always call a function."** This prevents the model from responding with text instead of tool calls.
4. **No multi-paragraph instructions.** The model cannot follow complex instructions.
5. **No hypothetical or abstract language.** Avoid words like "might", "could", "consider".
6. **No role-play preamble.** Avoid "You are an intelligent AI assistant that..." — keep it concrete.

### Examples

**Good:**
```yaml
system_prompt: |
  You are a Python code linter. Given Python code, call the appropriate function
  to lint it, fix issues, or read the file. Always call a function.
```

**Bad:**
```yaml
system_prompt: |
  You are an intelligent coding assistant that helps users lint Python code.
  Given a request to analyze code, call the appropriate linting function.
  You can run linter, apply fixes, and read the file being analyzed.
  Consider the context of the code and choose the best approach.
```

The bad example has vague language ("intelligent", "helps users", "consider"), is longer, and doesn't end with "Always call a function." With a 270M model, this leads to text echoing, refusals, or repetition loops.

### Pattern

```
You are a [concrete tool role]. Given [input], call the appropriate function to [action]. Always call a function.
```

### Safety Triggers
Avoid words like "generator", "assistant", or "agent" if the model refuses to answer. Use "maintenance tool", "utility", or "engine" instead. For example:
- **Avoid:** "You are a docstring generator." (triggers "I cannot write documentation" refusals)
- **Use:** "You are a Python documentation maintenance tool."

---

## 4. Node Context Templates

The `node_context` field is a Jinja2 template that produces the first user message. It receives these variables from the code analysis pipeline:

| Variable | Type | Description |
|----------|------|-------------|
| `{{ node_text }}` | string | Full source code of the node (function, class, or module) |
| `{{ node_name }}` | string | Name of the node (e.g. `"greet"`, `"Greeter"`) |
| `{{ node_type }}` | string | Node type: `"function"`, `"class"`, or `"module"` |
| `{{ file_path }}` | string | Relative path to the source file |

### When to Include Each Variable

- **Always include `{{ node_text }}`** — this is the code the agent works on.
- **Include `{{ file_path }}` only if the tool needs it** — e.g. test generators need to know where to write test files relative to source.
- **Include `{{ node_name }}` and `{{ node_type }}` only if relevant** — e.g. docstring agents that need to know the function name for targeting.

### Examples

**Minimal (lint, docstring):**
```yaml
node_context: |
  Code to analyze:
  {{ node_text }}
```

**Full context (test, sample_data):**
```yaml
node_context: |
  Target file: {{ file_path }}
  Node: {{ node_name }} ({{ node_type }})
  {{ node_text }}

  Instructions: Analyze the code and call the appropriate function.
```

**Tip:** Adding an explicit "Instructions:" line at the end of the user message helps the 270M model focus on action rather than explanation.

Keep the template short. For a 270M model, every token in the context window competes with the space needed for tool schema understanding.

---

## 5. Defining Tools

Each tool entry in the YAML maps to a `.pym` script. The key fields are:

```yaml
- tool_name: run_linter                    # What the model calls
  pym: lint/tools/run_linter.pym           # Where the script lives
  tool_description: Run ruff linter...     # What the model reads
  inputs_override: { ... }                 # Parameter-level descriptions
  context_providers: [ ... ]               # Pre-execution context scripts
```

### Writing Good Tool Descriptions

The `tool_description` is the **single most important field** for model behavior. The 270M model uses this string to decide which tool to call. Rules:

1. **Start with a verb.** "Run", "Read", "Write", "Extract", "Submit".
2. **Say what it returns.** "...and return a list of issues found."
3. **One sentence.** Two at most.
4. **Use concrete nouns.** "ruff linter", "docstring text", "pytest results" — not "the tool" or "the data".

### Examples

| Good | Bad |
|------|-----|
| `Run ruff linter on the Python code and return a list of issues found.` | `Run the linter and return issues.` |
| `Read and return the full contents of the current Python file being analyzed.` | `Read the current file.` |
| `Write or replace a docstring on the current Python function or class.` | `Write the docstring to the file.` |
| `Submit the final linting result after all issues have been checked and optionally fixed.` | `Submit the result.` |

The "bad" examples are too terse for a 270M model to differentiate between tools. The "good" examples provide enough signal for the model to match user intent to the right tool.

---

## 6. Enriching Tool Schemas with `inputs_override`

This is the mechanism for adding human-readable descriptions to tool parameters. Without `inputs_override`, the model sees bare parameter names like `issue_code` with no explanation.

### How It Works

1. When you run `grail check` on a `.pym` file, Grail generates `.grail/agents/<tool>/inputs.json` with parameter names, types, and defaults.
2. `tool_registry.py` reads this file and builds an OpenAI-format `parameters` schema.
3. `inputs_override` entries from the YAML are merged into this schema — adding `description`, overriding `type`, etc.
4. `runner.py` then filters out system-injected parameters before sending the schema to the model.

### Supported Override Fields

| Field | Type | What It Does |
|-------|------|-------------|
| `description` | string | Adds a description to the parameter (most common use) |
| `type` | string | Overrides the JSON Schema type (e.g. `"string"` → `"integer"`) |
| `default` | any | Overrides the default value |
| `required` | bool | Overrides whether the parameter is required |

### Example

```yaml
inputs_override:
  issue_code:
    description: "The ruff issue code to fix, e.g. F401 or E501."
  line_number:
    description: "The line number where the issue occurs."
```

This transforms the tool schema the model sees from:

```json
{
  "type": "function",
  "function": {
    "name": "apply_fix",
    "description": "Apply an automatic fix for a specific lint issue.",
    "parameters": {
      "type": "object",
      "properties": {
        "issue_code": {"type": "string"},
        "line_number": {"type": "integer"}
      },
      "required": ["issue_code", "line_number"]
    }
  }
}
```

Into:

```json
{
  "type": "function",
  "function": {
    "name": "apply_fix",
    "description": "Apply an automatic fix for a specific lint issue.",
    "parameters": {
      "type": "object",
      "properties": {
        "issue_code": {
          "type": "string",
          "description": "The ruff issue code to fix, e.g. F401 or E501."
        },
        "line_number": {
          "type": "integer",
          "description": "The line number where the issue occurs."
        }
      },
      "required": ["issue_code", "line_number"]
    }
  }
}
```

**Always add descriptions to every model-facing parameter.** The 270M model struggles to infer parameter semantics from names alone.

---

## 7. System-Injected Inputs

The runner automatically injects several inputs into every tool call that the model never sees. These provide context to the `.pym` script without consuming model context tokens.

### Injected Inputs (Filtered from Model View)

| Input Name | Value | Purpose |
|------------|-------|---------|
| `node_text` | Full source code of the node | So the .pym script can work on the code |
| `target_file` | Relative path to the source file | So the .pym script knows which file to read/write |
| `workspace_id` | Agent workspace identifier | For tracking and submit_result |
| `node_text_input` | Same as `node_text` (alias) | Legacy compatibility |
| `target_file_input` | Same as `target_file` (alias) | Legacy compatibility |

These are defined in `FunctionGemmaRunner._base_tool_inputs()` and merged with the model's provided arguments in `_dispatch_tool()`. The filtering happens in `_call_model()`, where these keys are stripped from the `tools_payload` before sending to vLLM.

### What This Means for `.pym` Script Authors

Your `.pym` script should declare these system-injected inputs so it can receive them at runtime, but you should **not** expect the model to provide them. They are injected automatically.

```python
from grail import Input

# System-injected — always available, never provided by the model
target_file_input: str | None = Input("target_file", default=None)
node_text_input: str | None = Input("node_text", default=None)

# Model-provided — the model must supply these
issue_code: str = Input("issue_code")
line_number: int = Input("line_number")
```

### What This Means for YAML Authors

Only add `inputs_override` entries for **model-facing** parameters. Do not add descriptions for system-injected inputs — they are invisible to the model and the descriptions would be wasted.

```yaml
# CORRECT — only model-facing params
inputs_override:
  issue_code:
    description: "The ruff issue code to fix."
  line_number:
    description: "The line number where the issue occurs."

# WRONG — includes system-injected params the model can't see
inputs_override:
  issue_code:
    description: "The ruff issue code to fix."
  target_file_input:              # ← The model never sees this!
    description: "The file path."
```

---

## 8. The `submit_result` Tool

Every agent must include exactly one tool named `submit_result`. This is how the agent signals completion. The runner recognizes `submit_result` calls specially — instead of dispatching to Grail, it parses the arguments and builds an `AgentResult`.

### Requirements

1. The `tool_name` must be exactly `submit_result`.
2. There must be exactly one `submit_result` tool per agent (validated by `subagent.py`).
3. The `.pym` script must accept at minimum a `summary` input and a `changed_files` input.

### Standard Submit Script Pattern

```python
from grail import Input

summary: str = Input("summary")
changed_files: list[str] = Input("changed_files")
workspace_id: str | None = Input("workspace_id", default=None)

# Additional fields specific to this agent type
issues_fixed: int = Input("issues_fixed")
issues_remaining: int = Input("issues_remaining")

workspace_value = workspace_id or "unknown"

try:
    status = "success" if issues_remaining == 0 else "failed"
    result = {
        "status": status,
        "workspace_id": workspace_value,
        "changed_files": [str(path) for path in changed_files],
        "summary": str(summary),
        "details": {
            "issues_fixed": int(issues_fixed),
            "issues_remaining": int(issues_remaining),
        },
        "error": None,
    }
except Exception as exc:
    result = {
        "status": "failed",
        "workspace_id": workspace_value,
        "changed_files": [],
        "summary": "",
        "details": {},
        "error": str(exc),
    }

result
```

The `workspace_id` is system-injected and filtered from the model schema. The `summary`, `changed_files`, and any agent-specific fields (like `issues_fixed`) are model-facing and should have `inputs_override` descriptions.

---

## 9. Context Providers

Context providers are `.pym` scripts that run **before** a tool executes. Their output is prepended to the tool's result, giving the model additional context (like project configuration) without requiring the model to request it.

### How They Work

1. Each tool entry can list `context_providers` — paths to `.pym` scripts.
2. Before the tool's `.pym` runs, each context provider is executed with the system-injected base inputs (`node_text`, `target_file`, `workspace_id`).
3. Each provider's result is JSON-serialized and prepended to the tool's response.
4. The model sees the combined output as one tool result.

### Example: Ruff Config Provider

```yaml
tools:
  - tool_name: run_linter
    pym: lint/tools/run_linter.pym
    tool_description: Run ruff linter on the Python code.
    context_providers:
      - lint/context/ruff_config.pym    # Provides project ruff settings
```

The `ruff_config.pym` script might read the project's `ruff.toml` or `pyproject.toml` and return the relevant configuration. The model receives this config data alongside the linter results without needing a separate tool call.

### When to Use Context Providers

- **Project-specific configuration** (ruff config, pytest config, docstring style)
- **Existing data** that the model needs but shouldn't have to request (existing fixtures, existing tests)
- **Read-only information** — context providers should not modify files

### When NOT to Use Context Providers

- If the data changes based on model-provided arguments (use a regular tool instead)
- If the data is large and would overwhelm the context window
- If the model needs to see the data *before* deciding which tool to call (put it in `node_context` instead)

---

## 10. How the Pipeline Works End-to-End

Understanding the full pipeline helps you debug issues and design better agents.

### Step 1: YAML Loading (`subagent.py`)

```
lint_subagent.yaml → SubagentDefinition
```

- `load_subagent_definition()` reads the YAML, resolves relative `.pym` paths against `agents_dir`, and validates:
  - Exactly one `submit_result` tool exists
  - No duplicate tool names
  - Jinja2 template syntax is valid
  - All `.pym` files and context providers exist on disk

### Step 2: Tool Schema Generation (`tool_registry.py`)

```
.pym files → grail.load() → .grail/agents/*/inputs.json → OpenAI tool schemas
```

- `GrailToolRegistry.build_tool_catalog()` loads each `.pym` via `grail.load()`, runs `script.check()`, reads the generated `inputs.json`, and builds an OpenAI-format tool schema.
- `_build_parameters()` merges `inputs_override` with the Grail-extracted input specs.
- Each tool becomes a dict like:
  ```json
  {
    "type": "function",
    "function": {
      "name": "run_linter",
      "description": "...",
      "parameters": {
        "type": "object",
        "properties": { ... },
        "additionalProperties": false,
        "required": [ ... ]
      }
    }
  }
  ```

### Step 3: Message Assembly (`runner.py`)

```
system_prompt + rendered node_context → messages[]
```

- `__post_init__()` builds the initial message list:
  1. `{"role": "system", "content": system_prompt}`
  2. `{"role": "user", "content": rendered_node_context}`

### Step 4: Model Call (`runner.py`)

```
messages[] + filtered tool schemas → vLLM → tool_call or text
```

- `_call_model()` filters system-injected inputs (`node_text`, `target_file`, `workspace_id`, `node_text_input`, `target_file_input`) from the tool schemas before sending to vLLM.
- The model sees only model-facing parameters.
- vLLM returns a `ChatCompletionMessage` with either `tool_calls` or plain `content`.

### Step 5: Tool Dispatch (`runner.py`)

```
tool_call → merge base_inputs + model_args → execute .pym via Grail
```

- `_dispatch_tool()` parses the tool call, merges `_base_tool_inputs()` (system-injected values) with the model's provided arguments, and executes the `.pym` script.
- Context providers run first, their results prepended to the tool output.
- The tool output is appended to `messages[]` as a `{"role": "tool", ...}` message.

### Step 6: Loop or Submit

- If the model calls `submit_result`, the runner builds an `AgentResult` and returns.
- If the model calls any other tool, the result is fed back and the model is called again.
- If the model produces no tool calls, the runner handles it as a no-op or error.
- If `max_turns` is exceeded, an `AgentError` is raised.

---

## 11. Writing Effective `.pym` Tools for Agents

The `.pym` scripts in your agent's `tools/` directory are what the model actually invokes. Here are patterns specific to agent tools (see the PYM guide for general `.pym` authoring):

### Pattern 1: Accept System-Injected Inputs Defensively

Always use `default=None` for system-injected inputs and fall back to workspace files:

```python
from grail import Input, external

target_file_input: str | None = Input("target_file", default=None)

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

@external
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    ...

async def _read_optional(path: str) -> str | None:
    if await file_exists(path=path):
        return await read_file(path=path)
    return None

async def _resolve_target_file() -> str | None:
    if target_file_input:
        return target_file_input.strip()
    stored = await _read_optional(path=".remora/target_file")
    if stored:
        return stored.strip()
    return None
```

This pattern appears in every existing agent tool. The fallback to `.remora/target_file` supports cases where the tool is run independently of the agent loop.

### Pattern 2: Always Return a Dict

Tool results are JSON-serialized and appended to the conversation. Always return a dict with consistent keys:

```python
# Success
result = {"issues": issues, "total": len(issues), "fixable_count": fixable_count}

# Error
result = {"error": str(exc)}
```

The model uses the structure of the response to decide what to do next. If you return inconsistent shapes, the model may get confused.

### Pattern 3: Keep Tool Results Concise

The tool result goes into the conversation context. Large results consume tokens and can push the model past its context window. Strategies:

- **Summarize.** Return counts and key details, not raw data.
- **Truncate.** If reading a file, consider returning only the relevant section.
- **Structure.** Use a flat dict with clear key names, not nested objects.

### Pattern 4: Wrap Everything in try/except

Agent tools should never crash — a crash aborts the entire agent run. Always wrap the executable section:

```python
try:
    # ... do work ...
    result = {"success": True, "data": processed_data}
except Exception as exc:
    result = {"error": str(exc)}

result
```

### Pattern 5: Separate Commands from Queries

Design tools so each one either reads or writes, not both. This gives the model clearer choices:

| Tool | Purpose |
|------|---------|
| `read_current_file` | Read-only: return file contents |
| `run_linter` | Read-only: return list of issues |
| `apply_fix` | Write: apply a specific fix |
| `submit_result` | Signal: agent is done |

Avoid "do everything" tools that read, process, and write in one call. The model cannot reason about tools with mixed effects.

---

## 12. Registering Your Agent

To make your agent available in Remora, add it to `remora.yaml`:

```yaml
operations:
  my_operation:
    subagent: my_agent/my_agent_subagent.yaml
    enabled: true
    auto_accept: false
    priority: normal          # low, normal, or high
    # Any extra keys are passed through to the subagent
    custom_setting: "value"
```

### Directory Structure

```
agents/
  my_agent/
    my_agent_subagent.yaml        # Agent definition
    tools/
      analyze.pym                 # Tool: analyze code
      transform.pym               # Tool: apply transformation
      submit.pym                  # Tool: submit result
    context/
      project_config.pym          # Context provider: project settings
```

### Validation

After creating your files, run `grail check` to validate all `.pym` scripts:

```bash
grail check agents/my_agent/tools/analyze.pym
grail check agents/my_agent/tools/transform.pym
grail check agents/my_agent/tools/submit.pym
grail check agents/my_agent/context/project_config.pym
```

This generates the `.grail/agents/*/inputs.json` files that `tool_registry.py` needs.

---

## 13. Debugging Agent Failures

### Symptom: Model echoes input back

**Cause:** System prompt is too vague. The model doesn't understand it should call a function.

**Fix:** Rewrite the system prompt following Section 3. End with "Always call a function."

### Symptom: Model says "I cannot assist with..."

**Cause:** The model's training data includes refusal patterns, and the prompt is triggering them. This happens when the system prompt uses language like "You are an intelligent AI assistant that helps users..."

**Fix:** Use a concrete role ("You are a Python linter.") instead of an abstract one ("You are an intelligent coding assistant that helps users lint Python code.").

### Symptom: Model produces infinite repetition (degenerate loop)

**Cause:** The model ran out of useful patterns to generate and fell into a repetition loop. Usually caused by:
- Too many tokens in the system+user messages, leaving little room for generation
- Tool schemas without descriptions, giving the model no signal to latch onto

**Fix:**
- Reduce system prompt length
- Reduce `node_context` to only essential variables
- Add `inputs_override` descriptions to all model-facing parameters
- Lower `max_tokens` in `runner` config

### Symptom: Model calls the wrong tool

**Cause:** Tool descriptions are too similar or too vague.

**Fix:** Make each tool description distinct. Start with a unique verb. Include what the tool returns.

### Symptom: Model provides wrong argument types

**Cause:** The parameter schema lacks `description` fields, so the model guesses.

**Fix:** Add `inputs_override` with clear descriptions for every model-facing parameter.

### Checking the Actual Schema Sent to the Model

Enable event stream logging in `remora.yaml`:

```yaml
event_stream:
  enabled: true
  include_payloads: true
```

Then look for `model_request` events in the event log. These contain the full `messages` and `tools` payloads sent to vLLM.

Enable LLM conversation logging for human-readable transcripts:

```yaml
llm_log:
  enabled: true
```

---

## 14. Complete Example: Building a New Agent

Let's build a `complexity` agent that analyzes Python functions and reports their cyclomatic complexity.

### Step 1: Plan the Tools

| Tool | Purpose | Model-facing inputs |
|------|---------|-------------------|
| `analyze_complexity` | Count branches in the code | (none — uses system-injected node_text) |
| `submit_result` | Report the result | `summary`, `complexity_score` |

### Step 2: Write the `.pym` Scripts

**`agents/complexity/tools/analyze_complexity.pym`:**
```python
from grail import Input, external

node_text_input: str | None = Input("node_text", default=None)

@external
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    ...

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

async def _read_optional(path: str) -> str | None:
    if await file_exists(path=path):
        return await read_file(path=path)
    return None

async def _load_node_text() -> str:
    if node_text_input:
        return node_text_input
    stored = await _read_optional(path=".remora/node_text")
    if stored:
        return stored
    return ""

# Simple branch counting
try:
    source = await _load_node_text()
    lines = source.splitlines()

    branch_keywords = ["if ", "elif ", "for ", "while ", "except ", "and ", "or "]
    branch_count = 0
    for line in lines:
        stripped = line.strip()
        for keyword in branch_keywords:
            if stripped.startswith(keyword) or f" {keyword}" in stripped:
                branch_count += 1

    complexity = branch_count + 1  # base complexity of 1
    result = {
        "complexity": complexity,
        "branch_count": branch_count,
        "line_count": len(lines),
    }
except Exception as exc:
    result = {"error": str(exc)}

result
```

**`agents/complexity/tools/submit.pym`:**
```python
from grail import Input

summary: str = Input("summary")
complexity_score: int = Input("complexity_score")
workspace_id: str | None = Input("workspace_id", default=None)

workspace_value = workspace_id or "unknown"

try:
    status = "success" if complexity_score <= 10 else "warning"
    result = {
        "status": status,
        "workspace_id": workspace_value,
        "changed_files": [],
        "summary": str(summary),
        "details": {"complexity_score": int(complexity_score)},
        "error": None,
    }
except Exception as exc:
    result = {
        "status": "failed",
        "workspace_id": workspace_value,
        "changed_files": [],
        "summary": "",
        "details": {},
        "error": str(exc),
    }

result
```

### Step 3: Run `grail check`

```bash
grail check agents/complexity/tools/analyze_complexity.pym
grail check agents/complexity/tools/submit.pym
```

This creates `.grail/agents/analyze_complexity/inputs.json` and `.grail/agents/submit/inputs.json`.

### Step 4: Write the YAML Definition

**`agents/complexity/complexity_subagent.yaml`:**
```yaml
name: complexity_agent
max_turns: 5

initial_context:
  system_prompt: |
    You are a Python code complexity analyzer. Given Python code, call the
    appropriate function to measure its complexity. Always call a function.
  node_context: |
    Code to analyze:
    {{ node_text }}

tools:
  - tool_name: analyze_complexity
    pym: complexity/tools/analyze_complexity.pym
    tool_description: Count branches and calculate cyclomatic complexity of the Python code.

  - tool_name: submit_result
    pym: complexity/tools/submit.pym
    tool_description: Submit the final complexity analysis result.
    inputs_override:
      summary:
        description: "A short summary of the complexity analysis."
      complexity_score:
        description: "The cyclomatic complexity score as an integer."
```

### Step 5: Register in Config

Add to `remora.yaml`:

```yaml
operations:
  complexity:
    subagent: complexity/complexity_subagent.yaml
    enabled: true
    priority: low
```

### Step 6: Test

Run the agent against a sample file and verify:
1. The model calls `analyze_complexity` on the first turn
2. After receiving the result, the model calls `submit_result` with appropriate `summary` and `complexity_score`
3. No text echoing, refusals, or repetition loops

---

## Appendix: Quick Reference

### Minimal Agent YAML

```yaml
name: my_agent
max_turns: 10

initial_context:
  system_prompt: |
    You are a [role]. Given [input], call the appropriate function to [action]. Always call a function.
  node_context: |
    Code:
    {{ node_text }}

tools:
  - tool_name: my_tool
    pym: my_agent/tools/my_tool.pym
    tool_description: Do something specific and return the result.

  - tool_name: submit_result
    pym: my_agent/tools/submit.pym
    tool_description: Submit the final result.
```

### System-Injected Input Names (Filtered from Model)

```
node_text, target_file, workspace_id, node_text_input, target_file_input
```

### `inputs_override` Template

```yaml
inputs_override:
  param_name:
    description: "What this parameter means and valid values."
```

### Checklist for New Agents

- [ ] System prompt is concise with "Always call a function."
- [ ] Every tool has a descriptive `tool_description` starting with a verb
- [ ] Every model-facing parameter has an `inputs_override` description
- [ ] Exactly one `submit_result` tool exists
- [ ] All `.pym` scripts pass `grail check`
- [ ] System-injected inputs (`node_text`, `target_file`, `workspace_id`) use `default=None`
- [ ] All tool scripts wrap executable code in `try/except`
- [ ] Agent is registered in `remora.yaml` under `operations`
