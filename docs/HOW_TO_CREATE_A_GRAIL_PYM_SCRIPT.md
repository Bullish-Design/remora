# How to Create a Grail `.pym` Script

This guide is the definitive reference for writing Grail `.pym` scripts that run inside `structured-agents`. It explains how Grail scripts are discovered, how they execute, and how they connect to tool schemas, bundles, and the `AgentKernel`.

> **See also:** [HOW_TO_CREATE_AN_AGENT.md](HOW_TO_CREATE_AN_AGENT.md) for the end-to-end agent workflow (bundles, prompts, kernel configuration).

---

## Table of Contents

1. [What Is a `.pym` Script?](#1-what-is-a-pym-script)
2. [How `.pym` Scripts Are Used](#2-how-pym-scripts-are-used)
3. [Grail Architecture (in `structured-agents`)](#3-grail-architecture-in-structured-agents)
4. [File Structure and Rules](#4-file-structure-and-rules)
5. [Declaring Inputs](#5-declaring-inputs)
6. [Declaring External Functions](#6-declaring-external-functions)
7. [Executable Code](#7-executable-code)
8. [Return Values](#8-return-values)
9. [Context Providers](#9-context-providers)
10. [Validation with `grail check`](#10-validation-with-grail-check)
11. [Resource Limits and Errors](#11-resource-limits-and-errors)
12. [Grail Registry and Schema Generation](#12-grail-registry-and-schema-generation)
13. [Working with `structured-agents` Bundles](#13-working-with-structured-agents-bundles)
14. [Examples](#14-examples)

---

## 1. What Is a `.pym` Script?

A `.pym` script is a Python file executed by the Grail runtime. Grail provides a sandboxed Python subset designed for safe, deterministic execution. In `structured-agents`, `.pym` scripts act as **tools**: they are invoked when the model selects a tool call.

Key properties:

- `.pym` files are syntactically valid Python (3.10+).
- They run inside Grail, not CPython, so only a restricted subset of Python is allowed.
- Inputs and external functions are **declared** at the top of the file so Grail can validate and generate a tool schema.
- The last expression in the file becomes the tool’s return value.

---

## 2. How `.pym` Scripts Are Used

`structured-agents` uses a **registry + backend** model for tools:

1. `GrailRegistry` scans an agents/tools directory for `.pym` files and loads schemas.
2. `GrailBackend` executes a selected `.pym` script inside an isolated process.
3. The `AgentKernel` provides context (if any), passes model arguments, and consumes the tool result.

You can integrate `.pym` scripts in two ways:

- **Bundles** (`bundle.yaml`): specify tool names and a Grail registry; the bundle loader resolves `.pym` tools automatically.
- **Direct `AgentKernel` usage**: manually construct `ToolSchema` objects pointing to `.pym` files.

---

## 3. Grail Architecture (in `structured-agents`)

This section describes Grail’s execution model as it is used by `structured-agents`.

### High-Level Flow

```
.pym file → grail.load() → script.check() → script.run(inputs, limits, externals)
```

- **`grail.load()`** parses the `.pym` file and builds a script object.
- **`script.check()`** validates declarations (inputs, externals, supported syntax).
- **`script.run()`** executes the Monty bytecode with provided inputs, externals, and limits.

### How `structured-agents` Uses Grail

`GrailBackend` runs `.pym` files in a **separate process** and always performs the following steps:

1. Load and validate the script (`grail.load()` + `script.check()`).
2. Merge runtime context with model arguments to create the input payload.
3. Inject externals from an optional `externals_factory`.
4. Run the script with configured limits.
5. Return the tool output or a structured error.

### Tool Schema Generation

`GrailRegistry` reads `.grail/<tool_name>/inputs.json`, which is produced by `grail check`. This file defines the inputs and their types so `structured-agents` can build OpenAI-compatible tool schemas.

### Execution Limits

`GrailBackend` enforces limits passed into `script.run()`:

- `max_memory_mb`
- `max_duration_s`
- `max_recursion`

The backend itself also enforces a top-level timeout for the full execution.

### Architecture Diagram

```
           ┌─────────────────────┐
           │      .pym file       │
           └─────────┬───────────┘
                     │
                     ▼
              grail.load()
                     │
                     ▼
               script.check()
                     │
     inputs + externals + limits
                     │
                     ▼
               script.run()
                     │
                     ▼
             Tool output (dict)
                     │
                     ▼
    GrailBackend → ToolResult JSON
```

---

## 4. File Structure and Rules

A `.pym` file has two sections: declarations and executable code.

```python
from grail import Input, external
from typing import Any

# ─── Declarations ─────────────────────────────────────────────────────────────

task_name: str = Input("task_name")

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

# ─── Executable Code ──────────────────────────────────────────────────────────

await log(message=f"Running: {task_name}")

{"status": "ok", "task": task_name}
```

Rules:

1. File must be valid Python 3.10+.
2. Imports are limited to `from grail import ...` and `from typing import ...`.
3. Inputs must use `Input()` with a type annotation on the left-hand side.
4. `@external` functions must be fully annotated and have `...` as the body.
5. The last expression is the return value.

---

## 5. Declaring Inputs

Inputs are values injected at runtime (from the model call or host context). Declare them with `Input()`:

```python
from grail import Input

# Required input (model must supply)
query: str = Input("query")

# Optional input with default
max_results: int = Input("max_results", default=5)
```

Supported input types include:

- `str`, `int`, `float`, `bool`, `None`
- `list[T]`, `dict[K, V]`
- unions like `str | None`

### Host-Provided Context

Unlike Remora/Cairn, `structured-agents` does **not** define a fixed set of system-injected inputs. Any context passed by the consumer is merged with model arguments when executing the tool.

If you expect host-provided inputs, declare them with defaults to keep scripts testable:

```python
workspace_path: str | None = Input("workspace_path", default=None)
```

---

## 6. Declaring External Functions

External functions are capabilities supplied by the host (not by Grail). Declare them with `@external`:

```python
from grail import external

@external
async def read_file(path: str) -> str:
    """Read text content from a file."""
    ...
```

Rules:

- Must use `@external` from Grail.
- All parameters and return type must be annotated.
- The body must be `...` (Ellipsis).

### Important: Externals Are Host-Defined

`structured-agents` does not define a fixed external API. Externals are injected by the consumer via `GrailBackend`’s `externals_factory`. Document the externals you provide in your own project and keep tool scripts aligned with them.

---

## 7. Executable Code

All executable logic lives at the top level (no `main()` function). You can use basic Python constructs supported by Grail:

```python
results: list[str] = []
for item in items:
    if item.startswith("A"):
        results.append(item)

{"count": len(results), "items": results}
```

Common supported features:

- `if/elif/else`, `for`, `while`
- list/dict/set comprehensions
- f-strings
- basic exceptions (`try/except`)

Unsupported features include:

- classes
- `with` statements
- `match` statements
- arbitrary imports (standard library imports are disallowed)

Use external functions for anything that would normally require imports.

---

## 8. Return Values

The final expression in the file is the tool’s output. It should be JSON-serializable because `structured-agents` will serialize the result before it is attached to the conversation.

Recommended pattern:

- Always return a dict.
- Return a concise, flat structure.
- Include an `"error"` field in error cases.

```python
try:
    result = {"status": "ok", "count": len(items)}
except Exception as exc:
    result = {"error": str(exc)}

result
```

---

## 9. Context Providers

Context providers are `.pym` scripts that run **before** the main tool. Their outputs are prepended (as JSON lines) to the tool output. They are useful for injecting configuration or project metadata.

Context providers are configured at the **tool schema** level (in bundles or when constructing `ToolSchema`). When the tool runs, `GrailBackend` executes each provider with the same context as the tool itself.

Guidelines:

- Keep context providers read-only.
- Return concise dicts so the model receives useful context without flooding tokens.

---

## 10. Validation with `grail check`

Always validate `.pym` files with Grail:

```bash
# Check one file
grail check path/to/tool.pym

# Check all .pym files under a directory
grail check
```

`grail check` generates `.grail/<tool_name>/inputs.json` alongside the `.pym` file. `GrailRegistry` reads this file to build an OpenAI-compatible tool schema.

If `inputs.json` is missing, the registry falls back to a minimal schema with no parameters. Always run `grail check` after editing scripts.

---

## 11. Resource Limits and Errors

`GrailBackend` enforces limits when running tools:

- `max_memory_mb`: 512
- `max_duration_s`: 60
- `max_recursion`: 100
- backend timeout: 300 seconds

Errors from Grail are returned as tool errors. Your script can also return its own error payloads.

---

## 12. Grail Registry and Schema Generation

`GrailRegistry` discovers tools by scanning for `.pym` files under `agents_dir`.

Resolution order:

1. Read `.grail/<tool_name>/inputs.json` and build a schema.
2. If `use_grail_check` is enabled, run `grail check` (validation only).
3. Otherwise, return a minimal schema with no parameters.

This means your tool schema is only as rich as your `inputs.json` file. Always keep it up to date by running `grail check`.

---

## 13. Working with `structured-agents` Bundles

Bundles are the recommended packaging mechanism for tools and prompts. A Grail bundle typically looks like this:

```
my_bundle/
  bundle.yaml
  tools/
    read_file.pym
    write_file.pym
```

In `bundle.yaml`, declare the tools by name and registry:

```yaml
name: "docstring_writer"
model:
  plugin: "function_gemma"
initial_context:
  system_prompt: "You are a docstring tool. Always call a function."
  user_template: "{{ input }}"
max_turns: 5
tools:
  - name: "read_file"
    registry: "grail"
  - name: "write_file"
    registry: "grail"
registries:
  - type: "grail"
    config:
      agents_dir: "tools"
```

When you load the bundle, `structured-agents` resolves the `.pym` scripts via `GrailRegistry` and executes them via `GrailBackend`.

---

## 14. Examples

### Example 1: Minimal Tool

```python
from grail import Input

name: str = Input("name")

try:
    result = {"greeting": f"Hello, {name}!"}
except Exception as exc:
    result = {"error": str(exc)}

result
```

### Example 2: Tool with an External

```python
from grail import Input, external

path: str = Input("path")

@external
async def read_file(path: str) -> str:
    """Read a file's contents."""
    ...

try:
    content = await read_file(path=path)
    result = {"path": path, "length": len(content)}
except Exception as exc:
    result = {"error": str(exc)}

result
```

### Example 3: Context Provider

```python
from grail import Input

project_name: str = Input("project_name", default="demo")

try:
    result = {"project": project_name}
except Exception as exc:
    result = {"error": str(exc)}

result
```

---

## Grail Cheat Sheet

- **Validate scripts:** `grail check path/to/tool.pym`
- **Generated schema:** `.grail/<tool_name>/inputs.json`
- **Schema source:** `GrailRegistry` reads `inputs.json`
- **Execution runtime:** `GrailBackend` runs scripts in separate processes
- **Externals:** host-defined via `GrailBackend` `externals_factory`
- **Limits:** `max_memory_mb`, `max_duration_s`, `max_recursion`, plus backend timeout
- **Return value:** last expression, JSON-serializable dict recommended
