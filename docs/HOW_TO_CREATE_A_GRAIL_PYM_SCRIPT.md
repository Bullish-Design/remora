# How to Create a Grail `.pym` Script

Grail is the library that powers safe code execution inside Monty — a minimal, sandboxed Python interpreter written in Rust. This guide explains how to write `.pym` files for use in Remora agents and standalone Cairn scripts.

> **See also:** [HOW_TO_CREATE_AN_AGENT.md](HOW_TO_CREATE_AN_AGENT.md) for the full agent creation workflow — YAML definitions, prompt engineering, tool schemas, and the end-to-end pipeline.

---

## Table of Contents

1. [What is a `.pym` File?](#1-what-is-a-pym-file)
2. [Two Modes: Remora Tool vs. Standalone Agent](#2-two-modes-remora-tool-vs-standalone-agent)
3. [File Structure](#3-file-structure)
4. [Declaring Inputs](#4-declaring-inputs)
5. [Declaring External Functions](#5-declaring-external-functions)
6. [Executable Code](#6-executable-code)
7. [Return Value](#7-return-value)
8. [Supported Python Features](#8-supported-python-features)
9. [Unsupported Python Features](#9-unsupported-python-features)
10. [External Function API](#10-external-function-api)
11. [Validating with `grail check`](#11-validating-with-grail-check)
12. [Error Handling](#12-error-handling)
13. [Resource Limits](#13-resource-limits)
14. [Remora Tool Patterns](#14-remora-tool-patterns)
15. [Examples — Remora Tools](#15-examples--remora-tools)
    - [Read-Only Tool: Read Current Docstring](#read-only-tool-read-current-docstring)
    - [Write Tool: Apply Lint Fix](#write-tool-apply-lint-fix)
    - [Submit Tool: Lint Result](#submit-tool-lint-result)
    - [Context Provider: Ruff Config](#context-provider-ruff-config)
16. [Examples — Standalone Cairn Agents](#16-examples--standalone-cairn-agents)
    - [Simple: Echo Task Description](#simple-echo-task-description)
    - [Simple: List and Log Directory Contents](#simple-list-and-log-directory-contents)
    - [Intermediate: Search and Report](#intermediate-search-and-report)
    - [Intermediate: Read, Transform, Write](#intermediate-read-transform-write)
    - [Complex: Full Agent — Refactor and Submit](#complex-full-agent--refactor-and-submit)

---

## 1. What is a `.pym` File?

A `.pym` (Python for Monty) file is a valid Python file that runs inside the Monty interpreter. Monty is a restricted, sandboxed subset of Python — it provides safety guarantees for executing untrusted or AI-generated code.

Key characteristics:

- `.pym` files are **valid Python** — IDEs provide syntax highlighting, autocomplete, and type checking.
- They run inside **Monty**, not CPython, so only a subset of Python is available.
- They declare their external dependencies (inputs and functions) explicitly at the top of the file, making the interface transparent and checkable before execution.
- In Remora, `.pym` scripts serve as individual **tools** that an LLM agent calls in a loop.
- In standalone Cairn mode, a single `.pym` script can be a complete **agent** that does all the work itself.

---

## 2. Two Modes: Remora Tool vs. Standalone Agent

`.pym` scripts are used in two distinct ways. Understanding the difference is critical for writing effective scripts.

### Remora Tool Scripts

In Remora, an LLM agent (e.g. FunctionGemma 270M) decides which tools to call. Each tool is a separate `.pym` file that does **one thing**:

```
LLM decides → calls run_linter.pym → gets result →
LLM decides → calls apply_fix.pym → gets result →
LLM decides → calls submit_result.pym → done
```

**Characteristics of Remora tool scripts:**

| Property | Value |
|----------|-------|
| Size | Small (30–150 lines) |
| Inputs | System-injected (`node_text`, `target_file`) + model-provided (`issue_code`, etc.) |
| External functions | Only the ones the tool needs (typically 2–4) |
| Return value | Dict with result data — fed back to the LLM as a tool response |
| `submit_result` | A **separate** `.pym` script, not an `@external` call |
| Error handling | `try/except` wrapper — never crash, return a Two-Track error payload |

### Standalone Cairn Agent Scripts

In standalone mode (without an LLM loop), a single `.pym` script receives a `task_description`, does everything, and calls `submit_result()` as an `@external` function:

```
Cairn injects task_description → agent.pym does all work →
calls submit_result() externally → returns final dict
```

**Characteristics of standalone scripts:**

| Property | Value |
|----------|-------|
| Size | Larger (100–300 lines) |
| Inputs | `task_description` (str) + custom inputs |
| External functions | Usually all 8 Cairn externals |
| Return value | Dict with summary — secondary to `submit_result()` |
| `submit_result` | An `@external` function called within the script |
| Error handling | Can use either pattern |

Both modes use the same `.pym` syntax, the same Grail tooling, and the same Monty interpreter. The difference is in how they're orchestrated.

---

## 3. File Structure

A `.pym` file has two clear sections:

```python
from grail import external, Input
from typing import Any

# ─── Declarations Section ────────────────────────────────────────────────────
# Declare inputs and external functions here.
# These are read by grail tooling to generate type stubs and validate the file.
# They execute as no-ops inside Monty — the real values are injected at runtime.

task_description: str = Input("task_description")

@external
async def log(message: str) -> bool:
    """Log a message."""
    ...

# ─── Executable Section ──────────────────────────────────────────────────────
# Everything below is the actual Monty code that runs.

await log(message=f"Received task: {task_description}")

{"done": True}
```

**Rules:**

1. The file must be syntactically valid Python 3.10+.
2. All imports must be `from grail import ...` or `from typing import ...`. No other imports are allowed.
3. `@external` functions must have complete type annotations on all parameters and the return type.
4. `@external` function bodies must be `...` (Ellipsis) — never an implementation.
5. `Input()` calls must have a type annotation on the left-hand side.
6. The final expression in the file is the script's return value.

---

## 4. Declaring Inputs

Inputs are values that the host injects at runtime. Declare them with `Input()`:

```python
from grail import Input

# Required input — must be provided at runtime, no default
task_description: str = Input("task_description")

# Optional input — uses default if not provided
max_results: int = Input("max_results", default=100)
verbose: bool = Input("verbose", default=False)
```

**Supported input types:** `str`, `int`, `float`, `bool`, `list[T]`, `dict[K, V]`, `None`, `Any`, and unions like `str | None`.

### Remora Tool Inputs

In Remora, tools receive two categories of inputs:

**System-injected inputs** — provided automatically by the runner, never by the model:

| Name | Type | Description |
|------|------|-------------|
| `node_text` / `node_text_input` | `str \| None` | Source code of the target node |
| `target_file` / `target_file_input` | `str \| None` | Relative path to the source file |
| `workspace_id` | `str \| None` | Agent workspace identifier |

**Model-provided inputs** — arguments the LLM chooses to pass:

| Example | Type | Description |
|---------|------|-------------|
| `issue_code` | `str` | A ruff issue code like `F401` |
| `line_number` | `int` | Line number for a fix |
| `docstring` | `str` | Docstring text to write |
| `check_only` | `bool` | Whether to only check without fixing |

Always declare system-injected inputs with `default=None` so they work both in the agent loop (where they're injected) and in standalone testing (where they might not be):

```python
# System-injected — always use default=None
node_text_input: str | None = Input("node_text", default=None)
target_file_input: str | None = Input("target_file", default=None)

# Model-provided — required (no default) unless optional
issue_code: str = Input("issue_code")
line_number: int = Input("line_number")
```

### Standalone Cairn Inputs

In standalone Cairn mode, every agent receives one standard input:

| Name | Type | Description |
|------|------|-------------|
| `task_description` | `str` | The task the agent was asked to complete |

---

## 5. Declaring External Functions

External functions are callable capabilities provided by the host at runtime. Declare them with `@external`:

```python
from grail import external
from typing import Any

@external
async def read_file(path: str) -> str:
    """Read the contents of a file."""
    ...

@external
async def write_file(path: str, content: str) -> bool:
    """Write content to a file."""
    ...
```

**Rules for `@external`:**

- The decorator is `@external`, imported from `grail`.
- The function signature must have complete type annotations on every parameter and the return type.
- The body must be `...` (a bare Ellipsis literal — not a string, not a `pass`).
- The function can be `async def` (most tools are async) or `def`.
- The docstring (optional but recommended) becomes hover documentation in your IDE.

Only declare externals you actually call. Declared-but-unused externals produce a `W002` warning from `grail check`.

### Remora vs. Standalone Usage

In **Remora tools**, declare only the externals your specific tool needs. A read-only tool might only need `read_file` and `file_exists`. A submit tool might not need any externals at all.

In **standalone Cairn agents**, you typically declare most or all of the available externals since your script handles the entire workflow.

---

## 6. Executable Code

After the declarations section, write the executable logic. This runs directly in Monty at the top level — there is no `main()` function to define.

```python
# Call external functions with await
data = await read_file(path="config.json")

# Use f-strings
await log(message=f"Read {len(data)} bytes")

# For loops
results = []
for item in some_list:
    processed = await process_item(item=item)
    results.append(processed)

# List comprehensions
names = [m["name"] for m in members]

# Dict comprehensions
index = {item["id"]: item for item in items}

# Conditionals
if len(results) == 0:
    await log(message="No results found")
else:
    await log(message=f"Found {len(results)} results")

# try/except
try:
    content = await read_file(path="missing.txt")
except Exception as e:
    await log(message=f"File not found: {e}")
    content = ""

# Helper functions (closures are supported)
async def process(item: dict) -> str:
    name = item.get("name", "unknown")
    return f"processed:{name}"

result = await process({"name": "example"})
```

---

## 7. Return Value

The last expression in the file is the script's return value. It can be any value — a dict, a list, a string, a bool, or `None`.

```python
# The final expression is the return value
{
    "status": "ok",
    "results": results,
    "count": len(results),
}
```

### Return Values in Remora Tools

In Remora, the return value is JSON-serialized and sent back to the LLM as a tool response message. The LLM reads this to decide what to do next. Design return values with the model in mind:

- **Be concise.** Large return values waste context tokens.
- **Use flat dicts.** Avoid deep nesting.
- **Include actionable data.** Return information the model needs for its next decision.

#### Two-Track Return Contract (Remora Tools)

When Two-Track Memory is enabled, tools must return a structured dict that supports both tracks:

```python
{
    "result": { ... },              # Full raw output (Long Track only)
    "summary": "Fixed 3 errors",    # Short outcome summary (Short Track)
    "knowledge_delta": {            # Structured state updates
        "errors_remaining": 2,
        "files_modified": ["foo.py"],
    },
    "outcome": "success",           # success | error | partial
    "error": None,                  # Optional error message
}
```

**Key points:**
- `summary`, `knowledge_delta`, and `outcome` are required for the Decision Packet.
- `result` can be large because it stays in the Long Track.
- Tools must build this dict inline — `.pym` scripts cannot import helpers from `remora.context.*`.

#### Summarizers (Fallback Path)

Remora can also attach **summarizers** in the runner when a tool does not provide a `summary` or `knowledge_delta`.
Summarizers live in regular Python modules (not in `.pym` scripts) and are registered in the runner via
`get_default_summarizers()`.

Use summarizers when:
- You are migrating legacy tools that still return raw results.
- You need to keep a `.pym` tool minimal, but its output shape is stable and easy to interpret.

How it works:
1. The `.pym` tool returns a raw dict (for example `{"passed": 10, "failed": 2}`).
2. The runner applies a summarizer for that tool name (e.g., `run_tests`).
3. The summarizer generates `summary` and `knowledge_delta` for the Decision Packet.

**Important:** Tool-side summaries are preferred. Summarizers are a fallback, not the primary path.
If you rely on summarizers, keep the raw result structure stable so the summarizer can parse it.

### Return Values in Standalone Cairn Agents

In standalone mode, the return value is logged but not used for agent review. The primary output channel is `submit_result()`, which must be called before the script ends.

---

## 8. Supported Python Features

Monty supports a practical subset of Python:

| Feature                | Example                                          |
|------------------------|--------------------------------------------------|
| Async/await            | `result = await fetch(url="...")`                |
| For loops              | `for x in items: ...`                            |
| While loops            | `while condition: ...`                           |
| If/elif/else           | `if x > 0: ... elif x < 0: ... else: ...`       |
| Try/except/finally     | `try: ... except ValueError as e: ...`          |
| Functions (closures)   | `async def helper(x: int) -> str: ...`          |
| List comprehensions    | `[x * 2 for x in nums if x > 0]`                |
| Dict comprehensions    | `{k: v for k, v in pairs}`                      |
| Set comprehensions     | `{x.lower() for x in words}`                    |
| Generator expressions  | `sum(x for x in nums)`                          |
| F-strings              | `f"Hello {name}, you have {count} items"`        |
| Basic data types       | `int`, `float`, `str`, `bool`, `None`           |
| Collections            | `list`, `dict`, `tuple`, `set`                  |
| Type annotations       | `x: int = 5`                                    |
| Augmented assignment   | `total += item["amount"]`                       |
| Boolean operators      | `x and y`, `x or y`, `not x`                    |
| Comparison operators   | `==`, `!=`, `<`, `>`, `<=`, `>=`, `in`, `not in`|
| Slicing                | `items[1:5]`, `items[::-1]`                     |
| Tuple unpacking        | `first, *rest = items`                          |

---

## 9. Unsupported Python Features

These Python features are **not available** in Monty. `grail check` will report errors if you use them:

| Feature              | Error Code | Notes                                        |
|----------------------|-----------|----------------------------------------------|
| Class definitions    | E001      | `class Foo: ...` is not supported            |
| Generators / `yield` | E002      | Use list comprehensions instead              |
| `with` statements    | E003      | Use external functions for resource access   |
| `match` statements   | E004      | Use `if/elif/else` chains instead            |
| Arbitrary imports    | E005      | Only `from grail import ...` and `from typing import ...` |
| `lambda`             | —         | Use a named `def` instead                   |
| Standard library     | E005      | No `os`, `json`, `re`, `pathlib`, etc.      |
| `eval` / `exec`      | —         | Not supported in Monty's sandbox            |

**Common workarounds:**

```python
# Instead of: import json; json.loads(text)
# Use an external function:
@external
async def parse_json(text: str) -> dict[str, Any]:
    """Parse JSON string to dict."""
    ...

data = await parse_json(text=raw_text)

# Instead of: with open(path) as f: content = f.read()
# Use the read_file external:
content = await read_file(path="data.txt")

# Instead of: class Config: pass
# Use a plain dict:
config = {"max_size": 100, "mode": "fast"}
```

---

## 10. External Function API

These external functions are available to `.pym` scripts at runtime. In **Remora tools**, declare only the ones you use. In **standalone agents**, you may declare most or all of them.

### `read_file`

```python
@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...
```

- `path`: Relative path (no leading `/`, no `..`).
- Returns: Full file contents as a string.
- Raises if the file does not exist.
- Reads from the agent's workspace first, then falls back to the stable (project) workspace.

### `write_file`

```python
@external
async def write_file(path: str, content: str) -> bool:
    """Write text content to a file."""
    ...
```

- `path`: Relative path. Intermediate directories are created automatically.
- `content`: String content to write (up to 10 MB).
- Returns `True` on success.
- Writes to the agent's isolated workspace — the stable workspace is only modified if the agent is accepted.

### `list_dir`

```python
@external
async def list_dir(path: str = ".") -> list[str]:
    """List file names in a directory."""
    ...
```

- `path`: Relative directory path. Defaults to `"."` (the project root).
- Returns: A list of entry names (not full paths) in the directory.

### `file_exists`

```python
@external
async def file_exists(path: str) -> bool:
    """Check if a file exists."""
    ...
```

- `path`: Relative path.
- Returns `True` if the file exists in either the agent workspace or stable workspace.

### `search_files`

```python
@external
async def search_files(pattern: str) -> list[str]:
    """Find files matching a glob pattern."""
    ...
```

- `pattern`: A glob pattern, e.g. `"**/*.py"`, `"src/**/*.ts"`, `"*.json"`.
- Returns: A list of relative file paths matching the pattern.

### `search_content`

```python
@external
async def search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]:
    """Search file contents for a regex pattern."""
    ...
```

- `pattern`: A regular expression pattern.
- `path`: Directory to search in. Defaults to `"."`.
- Returns: A list of match objects, each with:
  - `"file"`: Relative file path (str)
  - `"line"`: Line number (int, 1-indexed)
  - `"text"`: The matching line content (str)

### `run_command`

```python
@external
async def run_command(command: str) -> dict[str, Any]:
    """Execute a shell command and return its output."""
    ...
```

- `command`: The shell command to execute.
- Returns: A dict with:
  - `"stdout"`: Standard output (str)
  - `"stderr"`: Standard error (str)
  - `"returncode"`: Exit code (int)
- Commands run in the agent's workspace directory.

### `submit_result` (standalone Cairn agents only)

```python
@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for human review."""
    ...
```

- `summary`: Human-readable description of what the agent did.
- `changed_files`: List of relative paths to files that were created or modified.
- Returns `True` on success.
- **Must be called before the script ends.** Without a call to `submit_result`, the orchestrator will not transition the agent to the reviewing state.

> **Note:** In Remora, `submit_result` is a separate `.pym` **tool** — it is NOT declared as an `@external` in other tools. See [HOW_TO_CREATE_AN_AGENT.md](HOW_TO_CREATE_AN_AGENT.md#8-the-submit_result-tool) for the Remora submit pattern.

### `log`

```python
@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...
```

- `message`: The message to log.
- Returns `True` always.
- Use for progress updates and debugging. Messages appear in the orchestrator's output.

---

## 11. Validating with `grail check`

Before running a script, validate it:

```bash
# Check all .pym files in the current directory (recursive)
grail check

# Check a specific file
grail check my_agent.pym

# Strict mode — warnings become errors (good for CI)
grail check --strict my_agent.pym

# JSON output for programmatic processing
grail check --format json my_agent.pym
```

**Error codes:**

| Code  | Severity | Meaning                                            |
|-------|----------|----------------------------------------------------
| E001  | Error    | Class definition (not supported in Monty)         |
| E002  | Error    | Generator / `yield` (not supported)               |
| E003  | Error    | `with` statement (not supported)                  |
| E004  | Error    | `match` statement (not supported)                 |
| E005  | Error    | Forbidden import                                   |
| E006  | Error    | `@external` function missing type annotations     |
| E007  | Error    | `@external` function body is not `...`            |
| E008  | Error    | `Input()` without type annotation                 |
| E1xx  | Error    | Type checker errors from Monty's `ty` checker     |
| W001  | Warning  | Bare dict/list as final expression                |
| W002  | Warning  | Declared `@external` never called                 |
| W003  | Warning  | Declared `Input()` never used                     |
| W004  | Warning  | Script exceeds 200 lines                          |

After running `grail check`, inspect `.grail/<script_name>/` for generated artifacts:

- `stubs.pyi` — generated type stubs for Monty's type checker
- `check.json` — validation results
- `externals.json` — extracted external function signatures
- `inputs.json` — extracted input declarations (used by Remora's `tool_registry.py` to build tool schemas)
- `monty_code.py` — the actual code sent to Monty (declarations stripped)
- `run.log` — stdout/stderr from the last execution

> **Remora integration:** The `inputs.json` file is critical. Remora's `tool_registry.py` reads it to build the OpenAI-format tool schema that the LLM sees. Always run `grail check` after modifying a `.pym` file to regenerate this file.

---

## 12. Error Handling

### In the Script

Use `try/except` to handle errors from external functions gracefully:

```python
try:
    content = await read_file(path="config.json")
except Exception as e:
    await log(message=f"Could not read config.json: {e}")
    content = "{}"
```

### Remora Tool Pattern

In Remora tools, always wrap the entire executable section so the tool never crashes. A crash aborts the entire agent run:

```python
try:
    # ... do work ...
    raw_result = {"success": True, "data": processed_data}
    result = {
        "result": raw_result,
        "summary": "Completed processing",
        "knowledge_delta": {"items_processed": len(processed_data)},
        "outcome": "success",
    }
except Exception as exc:
    result = {
        "result": None,
        "summary": f"Error: {exc}",
        "knowledge_delta": {},
        "outcome": "error",
        "error": str(exc),
    }

result
```

### Error Types from the Host

When `grail.load()` or `script.run()` is called, these exceptions may be raised:

| Exception              | Trigger                                             |
|------------------------|-----------------------------------------------------|
| `grail.ParseError`     | Syntax errors in the `.pym` file                   |
| `grail.CheckError`     | Malformed `@external` or `Input()` declarations    |
| `grail.InputError`     | Missing required input at runtime                  |
| `grail.ExternalError`  | Missing external function implementation           |
| `grail.ExecutionError` | Runtime error inside Monty                         |
| `grail.LimitError`     | Resource limit exceeded (memory, time, recursion)  |
| `grail.OutputError`    | Output failed `output_model` validation            |

Errors reference the original `.pym` file with line numbers — not the generated `monty_code.py`.

---

## 13. Resource Limits

Monty enforces resource limits to prevent runaway scripts. Cairn's defaults (from `ExecutorSettings`):

| Resource         | Cairn Default |
|------------------|---------------|
| Execution time   | 60 seconds    |
| Memory           | 100 MB        |
| Recursion depth  | 1000 frames   |

If a script exceeds a limit, a `ResourceLimitError` or `TimeoutError` is raised.

To avoid hitting limits:

- Avoid deep recursion — use loops instead of recursive helpers.
- Process data incrementally rather than loading everything into memory.
- Keep helper functions shallow and focused.
- In Remora tools, keep scripts small and focused on one task — this naturally avoids limit issues.

---

## 14. Remora Tool Patterns

These patterns appear throughout Remora's existing tool scripts. Follow them when writing new tools.

### Pattern 1: Defensive Input Resolution

System-injected inputs may or may not be present (e.g. during testing). Always provide a fallback chain:

```python
from grail import Input, external

target_file_input: str | None = Input("target_file", default=None)
node_text_input: str | None = Input("node_text", default=None)

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

@external
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    ...

# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _read_optional(path: str) -> str | None:
    """Read a file if it exists, otherwise return None."""
    if await file_exists(path=path):
        return await read_file(path=path)
    return None


async def _resolve_target_file() -> str | None:
    """Resolve target file from injected input or workspace file."""
    if target_file_input:
        return target_file_input.strip()
    stored = await _read_optional(path=".remora/target_file")
    if stored:
        return stored.strip()
    return None


async def _load_node_text() -> str:
    """Load node text from injected input, workspace file, or target file."""
    if node_text_input:
        return node_text_input
    stored = await _read_optional(path=".remora/node_text")
    if stored:
        return stored
    target_file = await _resolve_target_file()
    if target_file and await file_exists(path=target_file):
        return await read_file(path=target_file)
    return ""
```

This resolution chain tries three sources in order:
1. The injected input (provided by the runner during normal operation)
2. A workspace file (`.remora/target_file` or `.remora/node_text`) for testing/debugging
3. Direct file read as a last resort

### Pattern 2: Try/Except Wrapper

Every Remora tool must wrap its executable section:

```python
try:
    # All tool logic here
    source = await _load_node_text()
    # ... process ...
    result = {"data": processed, "count": len(processed)}
except Exception as exc:
    result = {"error": str(exc)}

result
```

### Pattern 3: Two-Track Return Shape

Every Remora tool should return the Two-Track structure so the ContextManager can update the Decision Packet:

```python
try:
    # ... do work ...
    raw_result = {"items": items, "count": len(items)}
    result = {
        "result": raw_result,
        "summary": f"Found {len(items)} items",
        "knowledge_delta": {"items_found": len(items)},
        "outcome": "success",
    }
except Exception as exc:
    result = {
        "result": None,
        "summary": f"Error: {exc}",
        "knowledge_delta": {},
        "outcome": "error",
        "error": str(exc),
    }

result
```

### Pattern 4: Concise, Flat Return Dicts

Return values go into the LLM's context window. Keep them small and flat:

```python
# Good — concise, flat, actionable
result = {
    "issues": [
        {"code": "F401", "line": 5, "fixable": True},
        {"code": "E501", "line": 12, "fixable": False},
    ],
    "total": 2,
    "fixable_count": 1,
}

# Bad — verbose, nested, wastes tokens
result = {
    "analysis": {
        "results": {
            "issues": {
                "critical": [...],
                "warnings": [...],
            }
        }
    }
}
```

### Pattern 5: One Tool, One Job

Each `.pym` tool should either read or write, not both. This gives the LLM clearer choices:

| Tool Purpose | Does | Doesn't |
|----------|------|---------|
| `read_current_docstring.pym` | Reads and extracts docstring | Modify the file |
| `write_docstring.pym` | Writes/replaces docstring in file | Return analysis |
| `run_linter.pym` | Runs ruff and returns issues | Apply fixes |
| `apply_fix.pym` | Applies a specific fix | Run full linting |

### Pattern 6: Use `run_command` for External Tooling

When you need to invoke an external tool (linter, test runner, formatter), use the `run_command` external:

```python
@external
async def run_command(command: str) -> dict[str, Any]:
    """Execute a shell command and return its output."""
    ...

result = await run_command(command=f"ruff check --select {issue_code} {target_file}")
stdout = result["stdout"]
returncode = result["returncode"]
```

Parse the stdout/stderr from the command to build your tool's return dict.

---

## 15. Examples — Remora Tools

These examples show the patterns used in Remora agent tools — small, focused `.pym` scripts that the LLM calls individually.

> **Two-Track note:** Each example’s final `result = {...}` should be wrapped in the Two-Track return shape shown above (Pattern 3). Keep the tool’s core logic the same, but return `{"result": raw_result, "summary": ..., "knowledge_delta": ..., "outcome": ...}` instead of a bare dict.

---

### Read-Only Tool: Read Current Docstring

Reads and extracts the existing docstring from a Python function or class. Does not modify any files.

**`read_current_docstring.pym`:**
```python
from grail import Input, external

node_text_input: str | None = Input("node_text", default=None)
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


async def _load_node_text() -> str:
    if node_text_input:
        return node_text_input
    stored = await _read_optional(path=".remora/node_text")
    if stored:
        return stored
    target_file = await _resolve_target_file()
    if target_file and await file_exists(path=target_file):
        return await read_file(path=target_file)
    return ""


def _find_definition(lines: list[str]) -> tuple[int, int] | None:
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("async def ") or stripped.startswith("def ") or stripped.startswith("class "):
            indent = len(line) - len(line.lstrip())
            return index, indent
    return None


def _extract_docstring(lines: list[str], start_index: int, base_indent: int) -> str | None:
    for index in range(start_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if indent <= base_indent:
            return None
        if stripped.startswith('"""') or stripped.startswith("'''"):
            quote = stripped[:3]
            remainder = stripped[3:]
            if remainder.endswith(quote):
                return remainder[: -3].strip()
            content_lines: list[str] = []
            if remainder:
                content_lines.append(remainder)
            for inner_index in range(index + 1, len(lines)):
                inner_line = lines[inner_index]
                if quote in inner_line:
                    before = inner_line.split(quote, 1)[0]
                    content_lines.append(before)
                    return "\n".join(content_lines).strip()
                content_lines.append(inner_line.strip())
            return "\n".join(content_lines).strip()
        return None
    return None


try:
    source = await _load_node_text()
    lines = source.splitlines()
    definition = _find_definition(lines)
    if not definition:
        result = {"error": "No docstring-capable node found in node text."}
    else:
        index, indent = definition
        docstring = _extract_docstring(lines, index, indent)
        result = {"docstring": docstring, "has_docstring": bool(docstring)}
except Exception as exc:
    result = {"error": str(exc)}

result
```

**What this demonstrates:**
- Defensive input resolution (`_load_node_text`, `_resolve_target_file`)
- Read-only — no `write_file` declared
- String parsing in pure Python (no `re` or `ast` available)
- Concise return dict with `has_docstring` flag for easy LLM interpretation
- Full `try/except` wrapper

---

### Write Tool: Apply Lint Fix

Applies a ruff autofix for a specific issue code at a specific line. Takes model-provided arguments.

**`apply_fix.pym`:**
```python
from grail import Input, external
from typing import Any

issue_code: str = Input("issue_code")
line_number: int = Input("line_number")
target_file_input: str | None = Input("target_file", default=None)


@external
async def run_command(command: str) -> dict[str, Any]:
    """Execute a shell command and return its output."""
    ...


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


try:
    target_file = await _resolve_target_file()
    if not target_file:
        raise ValueError("Target file not found.")

    cmd = f"ruff check --select {issue_code} --fix {target_file}"
    run_result = await run_command(command=cmd)

    updated_content = await read_file(path=target_file)

    result = {
        "success": run_result["returncode"] == 0,
        "issue_code": issue_code,
        "line_number": line_number,
        "stdout": run_result["stdout"],
        "file_content_after": updated_content[:500],  # Truncate for context
    }
except Exception as exc:
    result = {"error": str(exc)}

result
```

**What this demonstrates:**
- Model-provided inputs (`issue_code`, `line_number`) alongside system-injected inputs
- Using `run_command` for external tooling (ruff)
- Truncating large outputs to preserve context tokens
- Write operation — modifies the file via ruff

---

### Submit Tool: Lint Result

The submit tool that the LLM calls when linting is complete. All arguments are model-provided except `workspace_id`.

**`submit.pym`:**
```python
from grail import Input

summary: str = Input("summary")
issues_fixed: int = Input("issues_fixed")
issues_remaining: int = Input("issues_remaining")
changed_files: list[str] = Input("changed_files")
workspace_id: str | None = Input("workspace_id", default=None)

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

**What this demonstrates:**
- No `@external` functions needed — submit is pure data assembly
- `workspace_id` is system-injected (filtered from model view), all others are model-provided
- Status is derived from the data (`issues_remaining == 0`)
- Error path always returns a valid dict

---

### Context Provider: Ruff Config

Context providers run before a tool and inject additional context. This one reads the project's ruff configuration.

**`ruff_config.pym`:**
```python
from grail import Input, external

target_file_input: str | None = Input("target_file", default=None)


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


# Check common ruff config locations
config_content = None
for config_path in ["ruff.toml", ".ruff.toml", "pyproject.toml"]:
    content = await _read_optional(path=config_path)
    if content:
        config_content = content
        break

if config_content:
    result = {"ruff_config": config_content[:1000], "config_source": config_path}
else:
    result = {"ruff_config": None, "config_source": None}

result
```

**What this demonstrates:**
- Context provider pattern — no model-provided inputs, only system-injected
- Reads project config files
- Truncates large config content
- Result is prepended to the main tool's output

---

## 16. Examples — Standalone Cairn Agents

These examples show the standalone Cairn agent pattern — a single `.pym` that handles the entire workflow. This pattern is useful for self-contained tasks that don't need LLM-guided decision making.

---

### Simple: Echo Task Description

The minimal valid standalone Cairn agent script. Declares the standard `task_description` input and `submit_result` external, logs what it received, and submits.

**`echo_task.pym`:**
```python
from grail import external, Input

# ─── Declarations ─────────────────────────────────────────────────────────────

task_description: str = Input("task_description")

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# ─── Executable ───────────────────────────────────────────────────────────────

await log(message=f"Agent received task: {task_description}")

summary = f"Echo agent completed. Task was: {task_description}"
await submit_result(summary=summary, changed_files=[])

{"status": "ok", "task": task_description}
```

**What this demonstrates:**
- Standard `Input("task_description")` pattern
- Minimal `@external` declarations (`log`, `submit_result`)
- f-string usage
- Calling `submit_result` before the return expression

---

### Simple: List and Log Directory Contents

Explore the project structure by listing a directory, then logging each entry.

**`list_project.pym`:**
```python
from grail import external, Input

# ─── Declarations ─────────────────────────────────────────────────────────────

task_description: str = Input("task_description")

@external
async def list_dir(path: str = ".") -> list[str]:
    """List file names in a directory."""
    ...

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# ─── Executable ───────────────────────────────────────────────────────────────

await log(message="Listing project root...")

entries = await list_dir(path=".")
await log(message=f"Found {len(entries)} entries in project root")

for entry in entries:
    await log(message=f"  - {entry}")

# Check the src directory if it exists
src_entries = await list_dir(path="src")
py_files = [e for e in src_entries if e.endswith(".py")]
await log(message=f"Found {len(py_files)} Python files in src/")

summary = (
    f"Listed project structure. "
    f"Root has {len(entries)} entries, src/ has {len(py_files)} Python files."
)
await submit_result(summary=summary, changed_files=[])

{
    "root_entries": entries,
    "src_py_files": py_files,
}
```

**What this demonstrates:**
- `list_dir` with a specific path
- For loop iteration over results
- List comprehension with a filter (`if e.endswith(".py")`)
- Multi-line string with parentheses

---

### Intermediate: Search and Report

Search the codebase for a pattern, build a report, and write it to a file.

**`find_todos.pym`:**
```python
from grail import external, Input
from typing import Any

# ─── Declarations ─────────────────────────────────────────────────────────────

task_description: str = Input("task_description")
search_pattern: str = Input("search_pattern", default="TODO|FIXME|HACK")
output_path: str = Input("output_path", default="reports/todos.md")

@external
async def search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]:
    """Search file contents for a regex pattern."""
    ...

@external
async def write_file(path: str, content: str) -> bool:
    """Write text content to a file."""
    ...

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# ─── Executable ───────────────────────────────────────────────────────────────

await log(message=f"Searching for pattern: {search_pattern}")

matches = await search_content(pattern=search_pattern, path=".")
await log(message=f"Found {len(matches)} matches")

# Group matches by file
by_file: dict[str, list[dict[str, Any]]] = {}
for match in matches:
    file_path = match["file"]
    if file_path not in by_file:
        by_file[file_path] = []
    by_file[file_path].append(match)

# Build a Markdown report
lines = [
    f"# TODO/FIXME Report",
    f"",
    f"Pattern: `{search_pattern}`",
    f"Total matches: {len(matches)}",
    f"Files affected: {len(by_file)}",
    f"",
]

for file_path in sorted(by_file.keys()):
    file_matches = by_file[file_path]
    lines.append(f"## `{file_path}` ({len(file_matches)} matches)")
    lines.append("")
    for m in file_matches:
        lines.append(f"- Line {m['line']}: `{m['text'].strip()}`")
    lines.append("")

report = "\n".join(lines)

await write_file(path=output_path, content=report)
await log(message=f"Report written to {output_path}")

summary = (
    f"Found {len(matches)} occurrences of '{search_pattern}' "
    f"across {len(by_file)} files. Report written to {output_path}."
)
await submit_result(summary=summary, changed_files=[output_path])

{
    "matches_found": len(matches),
    "files_affected": len(by_file),
    "report_path": output_path,
}
```

**What this demonstrates:**
- Multiple `Input()` declarations including optional ones with defaults
- `search_content` with a regex pattern
- Accessing dict keys on results (`match["file"]`, `match["line"]`, `match["text"]`)
- Building up a dict of lists (grouping by file)
- `sorted()` on dict keys
- Multi-line list construction and `"\n".join()`
- Calling `write_file` to produce output
- Reporting the changed file in `submit_result`

---

### Intermediate: Read, Transform, Write

Read a configuration file, update a value, and write it back. Demonstrates file existence checking and defensive read patterns.

**`update_version.pym`:**
```python
from grail import external, Input

# ─── Declarations ─────────────────────────────────────────────────────────────

task_description: str = Input("task_description")
new_version: str = Input("new_version")
config_path: str = Input("config_path", default="pyproject.toml")

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

@external
async def write_file(path: str, content: str) -> bool:
    """Write text content to a file."""
    ...

@external
async def file_exists(path: str) -> bool:
    """Check if a file exists."""
    ...

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# ─── Executable ───────────────────────────────────────────────────────────────

await log(message=f"Updating version to {new_version} in {config_path}")

# Check file exists before reading
exists = await file_exists(path=config_path)
if not exists:
    error_msg = f"Config file not found: {config_path}"
    await log(message=error_msg)
    await submit_result(summary=f"Failed: {error_msg}", changed_files=[])
    {"status": "error", "message": error_msg}

# Read the current content
content = await read_file(path=config_path)
lines = content.splitlines()

updated_lines = []
version_updated = False

for line in lines:
    stripped = line.strip()
    # Match lines like: version = "1.2.3"  or  version = '1.2.3'
    if stripped.startswith("version") and "=" in stripped and not version_updated:
        # Preserve any leading whitespace
        prefix = line[: len(line) - len(line.lstrip())]
        updated_lines.append(f'{prefix}version = "{new_version}"')
        version_updated = True
        await log(message=f"Updated version line: {stripped} -> version = \"{new_version}\"")
    else:
        updated_lines.append(line)

if not version_updated:
    await log(message="Warning: no version field found in file")

new_content = "\n".join(updated_lines)
if content.endswith("\n"):
    new_content = new_content + "\n"

await write_file(path=config_path, content=new_content)
await log(message=f"Wrote updated config to {config_path}")

summary = (
    f"Updated version to {new_version} in {config_path}. "
    f"Version field {'found and updated' if version_updated else 'not found'}."
)
await submit_result(summary=summary, changed_files=[config_path])

{
    "status": "ok",
    "version_updated": version_updated,
    "path": config_path,
    "new_version": new_version,
}
```

**What this demonstrates:**
- `file_exists` guard before reading
- `splitlines()` on file content for line-by-line processing
- String methods: `.strip()`, `.startswith()`, `.lstrip()`, `.endswith()`
- Tracking whether a mutation was applied (`version_updated` flag)
- Preserving trailing newlines
- Early return pattern (submitting an error result when preconditions fail)

---

### Complex: Full Agent — Refactor and Submit

A multi-phase agent that searches for files matching a pattern, reads each one, applies a transformation, writes the results back, and submits a comprehensive summary. This example showcases most available external functions and advanced control flow.

**`refactor_imports.pym`:**
```python
from grail import external, Input
from typing import Any

# ─── Declarations ─────────────────────────────────────────────────────────────

task_description: str = Input("task_description")
# The old import to replace, e.g. "from old_module import"
old_import: str = Input("old_import")
# The new import to replace it with, e.g. "from new_module import"
new_import: str = Input("new_import")
# Glob pattern for files to search, e.g. "**/*.py"
file_pattern: str = Input("file_pattern", default="**/*.py")
# Directory to restrict the search (default: entire project)
search_root: str = Input("search_root", default=".")
# Dry run — log changes without writing them
dry_run: bool = Input("dry_run", default=False)

@external
async def search_files(pattern: str) -> list[str]:
    """Find files matching a glob pattern."""
    ...

@external
async def search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]:
    """Search file contents for a regex pattern."""
    ...

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

@external
async def write_file(path: str, content: str) -> bool:
    """Write text content to a file."""
    ...

@external
async def file_exists(path: str) -> bool:
    """Check if a file exists."""
    ...

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# ─── Helper functions ──────────────────────────────────────────────────────────

async def replace_in_file(path: str, old: str, new: str) -> tuple[bool, int]:
    """
    Read a file, replace all occurrences of `old` with `new`, and write it back.
    Returns (was_changed, replacement_count).
    """
    content = await read_file(path=path)
    count = content.count(old)
    if count == 0:
        return False, 0
    updated = content.replace(old, new)
    if not dry_run:
        await write_file(path=path, content=updated)
    return True, count


async def summarize_matches(matches: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Group search matches by file, returning file -> [line_numbers]."""
    by_file: dict[str, list[int]] = {}
    for m in matches:
        f = m["file"]
        if f not in by_file:
            by_file[f] = []
        by_file[f].append(m["line"])
    return by_file

# ─── Executable ───────────────────────────────────────────────────────────────

await log(message=f"Starting import refactor: '{old_import}' -> '{new_import}'")
await log(message=f"File pattern: {file_pattern}, search root: {search_root}")
if dry_run:
    await log(message="DRY RUN mode — no files will be written")

# Phase 1: Find candidate files using search_content
await log(message="Phase 1: Searching for files containing the old import...")

matches = await search_content(pattern=old_import, path=search_root)
candidates_by_file = await summarize_matches(matches)

await log(message=f"Found {len(matches)} occurrences across {len(candidates_by_file)} files")

if len(candidates_by_file) == 0:
    summary = f"No occurrences of '{old_import}' found. Nothing to do."
    await log(message=summary)
    await submit_result(summary=summary, changed_files=[])
    {"status": "ok", "files_changed": 0, "total_replacements": 0}

# Phase 2: Apply replacements
await log(message="Phase 2: Applying replacements...")

changed_files = []
total_replacements = 0
errors = []

for file_path in sorted(candidates_by_file.keys()):
    line_count = len(candidates_by_file[file_path])
    await log(message=f"  Processing {file_path} ({line_count} matching lines)...")

    try:
        was_changed, count = await replace_in_file(
            path=file_path,
            old=old_import,
            new=new_import,
        )
        if was_changed:
            total_replacements += count
            changed_files.append(file_path)
            mode_label = "[DRY RUN] Would update" if dry_run else "Updated"
            await log(message=f"    {mode_label}: {count} replacement(s)")
        else:
            await log(message=f"    Skipped: no replacements needed")
    except Exception as e:
        error_msg = f"Error processing {file_path}: {e}"
        await log(message=f"    ERROR: {error_msg}")
        errors.append(error_msg)

# Phase 3: Verify changes (skip in dry run)
verified_files = []
if not dry_run and len(changed_files) > 0:
    await log(message="Phase 3: Verifying changes...")

    for file_path in changed_files:
        verification = await search_content(pattern=old_import, path=file_path)
        if len(verification) == 0:
            verified_files.append(file_path)
            await log(message=f"  Verified: {file_path}")
        else:
            remaining = len(verification)
            await log(message=f"  Warning: {file_path} still has {remaining} occurrence(s)")

# Phase 4: Build summary and submit
await log(message="Phase 4: Submitting results...")

status_parts = [
    f"Replaced '{old_import}' with '{new_import}'.",
    f"Files modified: {len(changed_files)}.",
    f"Total replacements: {total_replacements}.",
]
if dry_run:
    status_parts.append("(DRY RUN — no files were written)")
if errors:
    status_parts.append(f"Errors encountered: {len(errors)}.")
    for err in errors:
        status_parts.append(f"  - {err}")

summary = " ".join(status_parts)
files_to_report = changed_files if not dry_run else []

await submit_result(summary=summary, changed_files=files_to_report)
await log(message=f"Done. {summary}")

{
    "status": "ok" if not errors else "partial",
    "dry_run": dry_run,
    "files_changed": len(changed_files),
    "total_replacements": total_replacements,
    "changed_files": changed_files,
    "verified_files": verified_files,
    "errors": errors,
}
```

**What this demonstrates:**
- Six inputs, including booleans and strings with defaults
- Most Cairn external functions declared and used
- Helper functions (closures) defined between declarations and executable code
- A helper that returns a `tuple[bool, int]`
- Multi-phase agent workflow (search → replace → verify → submit)
- `try/except` error collection without aborting the whole script
- Early exit pattern using a final expression before the main loop
- Conditional writes (dry run mode)
- Building a human-readable multi-sentence summary
- Rich return dict with status, metrics, and file lists

---

## Appendix: Quick Reference

### Minimal Remora Tool Template

```python
from grail import Input, external

node_text_input: str | None = Input("node_text", default=None)
target_file_input: str | None = Input("target_file", default=None)

@external
async def read_file(path: str) -> str:
    """Read the text contents of a file."""
    ...

@external
async def file_exists(path: str) -> bool:
    """Check if a file or directory exists."""
    ...

# Your logic here
try:
    # ... do work with node_text_input or target_file_input ...
    raw_result = {"success": True}
    result = {
        "result": raw_result,
        "summary": "Completed tool operation",
        "knowledge_delta": {},
        "outcome": "success",
    }
except Exception as exc:
    result = {
        "result": None,
        "summary": f"Error: {exc}",
        "knowledge_delta": {},
        "outcome": "error",
        "error": str(exc),
    }

result
```

### Minimal Standalone Agent Template

```python
from grail import external, Input

task_description: str = Input("task_description")

@external
async def log(message: str) -> bool:
    """Emit a log message."""
    ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool:
    """Submit the agent's result for review."""
    ...

# Your logic here
await log(message=f"Starting: {task_description}")

# ... do work ...

await submit_result(summary="Task complete.", changed_files=[])
{"status": "ok"}
```

### All External Function Signatures

```python
from grail import external
from typing import Any

@external
async def read_file(path: str) -> str: ...

@external
async def write_file(path: str, content: str) -> bool: ...

@external
async def list_dir(path: str = ".") -> list[str]: ...

@external
async def file_exists(path: str) -> bool: ...

@external
async def search_files(pattern: str) -> list[str]: ...

@external
async def search_content(pattern: str, path: str = ".") -> list[dict[str, Any]]: ...

@external
async def run_command(command: str) -> dict[str, Any]: ...

@external
async def submit_result(summary: str, changed_files: list[str]) -> bool: ...  # standalone only

@external
async def log(message: str) -> bool: ...
```

### System-Injected Inputs (Remora)

These are automatically provided by the runner and filtered from the LLM's tool schema view:

```python
node_text_input: str | None = Input("node_text", default=None)      # Source code of target node
target_file_input: str | None = Input("target_file", default=None)  # Relative path to source file
workspace_id: str | None = Input("workspace_id", default=None)      # Agent workspace ID
```

### `grail check` Cheat Sheet

```bash
grail check                        # Check all .pym files
grail check my_tool.pym            # Check one file
grail check --strict my_tool.pym   # Warnings as errors
grail check --format json          # JSON output for CI
grail watch                        # Auto-check on file changes
grail clean                        # Remove .grail/ artifacts
```
