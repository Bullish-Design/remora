# Customization

> Writing custom tools, queries, extensions, and bundles for your Remora project.

## Table of Contents

1. [Overview](#overview) -- What you can customize and where it lives
2. [Writing Grail Tool Scripts](#writing-grail-tool-scripts) -- Creating `.pym` tools for your agents
3. [Bundle Configuration](#bundle-configuration) -- Configuring agent bundles with `bundle.yaml`
4. [Adding Tree-Sitter Queries](#adding-tree-sitter-queries) -- Discovering new node types with `.scm` files
5. [Writing Agent Extensions](#writing-agent-extensions) -- Customizing agent behavior with `AgentExtension` subclasses
6. [Project Layout Reference](#project-layout-reference) -- Where all the pieces go

---

## Overview

Remora is designed to be extended at several levels. Out of the box, it discovers Python functions, classes, Markdown sections, and TOML tables, and assigns them to default agent bundles. You can customize:

| What | How | Where |
|------|-----|-------|
| Agent tools | Write `.pym` Grail scripts | `agents/<bundle>/tools/` |
| Agent behavior | Configure `bundle.yaml` | `agents/<bundle>/bundle.yaml` |
| Node discovery | Add tree-sitter `.scm` queries | `.remora/queries/<language>/` |
| Agent field overrides | Write `AgentExtension` subclasses | `.remora/models/*.py` |

The `agents/` directory (or whatever `bundle_root` is set to in `remora.yaml`) holds bundles. The `.remora/` directory holds runtime state, custom queries, and extensions.

---

## Writing Grail Tool Scripts

Grail is the sandboxed execution engine that powers agent tools. Each tool is a `.pym` file -- a restricted Python script that runs inside a secure sandbox (Monty). The LLM calls tools by name, and Remora executes the corresponding `.pym` script.

### File Structure

Every `.pym` file follows this order:

```python
# 1. Imports (only grail and typing are allowed)
from grail import external, Input
from typing import Any

# 2. Input declarations (values the LLM provides as tool arguments)
path: str = Input("path")
max_lines: int = Input("max_lines", default=50)

# 3. External function declarations (Remora provides the implementation)
@external
async def read_file(path: str) -> str:
    """Read a file from the agent's workspace."""
    ...

# 4. Executable logic
content = await read_file(path=path)
lines = content.splitlines()[:max_lines]

# 5. Return value (last expression)
{"path": path, "line_count": len(lines), "preview": lines}
```

### Inputs

Inputs declare the arguments the LLM will pass when calling this tool. They become the tool's JSON schema automatically.

```python
# Required input (LLM must provide it)
query: str = Input("query")

# Optional input (has a default)
limit: int = Input("limit", default=10)
```

The variable name must match the `Input()` name string. Type annotations are required.

### External Functions

Externals are functions your script can call but does not implement. Remora injects the real implementations at runtime. The script only declares the signature:

```python
@external
async def read_file(path: str) -> str:
    """Read a workspace file."""
    ...

@external
async def emit_event(event_type: str, event_obj: Any) -> None:
    """Emit a swarm event."""
    ...
```

The body must be `...` (ellipsis). All parameters need type annotations. Both `async def` and `def` are supported.

### Available Externals

Remora provides these externals to all tool scripts (you must declare any you want to use with `@external`):

| External | Signature | Description |
|----------|-----------|-------------|
| `read_file` | `(path: str) -> str` | Read a file from the agent's workspace |
| `write_file` | `(path: str, content: str) -> None` | Write a file to the workspace |
| `list_dir` | `(path: str) -> list[str]` | List directory entries |
| `emit_event` | `(event_type: str, event_obj: Any) -> None` | Emit a swarm event |
| `register_subscription` | `(agent_id: str, pattern: Any) -> None` | Create a new event subscription |
| `unsubscribe_subscription` | `(subscription_id: int) -> str` | Remove a subscription |
| `broadcast` | `(to_pattern: str, content: str) -> str` | Send a message to matching agents |
| `query_agents` | `(filter_type: str \| None) -> list` | Query swarm agent metadata |

### What Is Allowed and Forbidden

**Allowed:** variables, arithmetic, f-strings, `if/else`, `for`, `while`, `try/except`, comprehensions, `async/await`, helper functions, type annotations, `print()` (captured), `os.getenv()` (virtual env vars only).

**Forbidden:** `class` definitions, `yield`/generators, `with` statements, `match` statements, imports other than `grail`/`typing`/`__future__`, `global`/`nonlocal`, `lambda`, `del`.

Use `grail check path/to/tool.pym` from the command line to validate a script before running.

### Example: A Custom Analysis Tool

```python
# agents/function_agent/tools/analyze_complexity.pym
from grail import external, Input
from typing import Any

path: str = Input("path")

@external
async def read_file(path: str) -> str:
    """Read the source file."""
    ...

content = await read_file(path=path)
lines = content.splitlines()

# Count nesting depth as a rough complexity metric
max_depth = 0
current_depth = 0
for line in lines:
    stripped = line.lstrip()
    if stripped == "":
        continue
    indent = len(line) - len(stripped)
    depth = indent // 4
    if depth > max_depth:
        max_depth = depth

result = {
    "path": path,
    "total_lines": len(lines),
    "max_nesting_depth": max_depth,
    "complexity": "high" if max_depth > 5 else "moderate" if max_depth > 3 else "low",
}
result
```

---

## Bundle Configuration

A bundle defines an agent type: its system prompt, model settings, and tools directory. Bundles live in subdirectories of `bundle_root` (default: `agents/`).

### `bundle.yaml` Reference

```yaml
# agents/function_agent/bundle.yaml
name: function_agent

initial_context:
  system_prompt: |
    You are a code analysis assistant specialized in Python functions.
    You have access to tools to read files and submit your findings.
    Always call a tool to complete your task.

# Response parser (qwen is the default)
model: qwen

# Optional structured output grammar
grammar:
  strategy: json_schema
  allow_parallel_calls: false
  send_tools_to_api: true

# Directory containing .pym tools (relative to this bundle.yaml)
agents_dir: tools

# Maximum LLM turns per agent run
max_turns: 10
```

### Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `"unnamed"` | Bundle identifier |
| `initial_context.system_prompt` | `str` | `""` | System message sent to the model every turn |
| `model` | `str` | `"qwen"` | Response parser key (`"qwen"` or `"function_gemma"`) |
| `grammar.strategy` | `str` | `null` | Structured output strategy (`json_schema`, `structural_tag`, `ebnf`) |
| `grammar.send_tools_to_api` | `bool` | `false` | Whether tool schemas are sent to the model's API |
| `agents_dir` | `str` | `"agents"` | Relative path to the tools directory |
| `max_turns` | `int` | `20` | Max LLM turns per agent run |

### Per-Bundle Model Override

A bundle can override the project-wide model settings from `remora.yaml`:

```yaml
# agents/specialized_agent/bundle.yaml
name: specialized_agent

model:
  id: my-custom-model
  name: qwen
  model: Qwen/Qwen3-32B

initial_context:
  system_prompt: |
    You are a specialized agent that uses a larger model.

agents_dir: tools
```

The `model.id`, `model.name`, and `model.model` fields in `bundle.yaml` override the project's `model_default` when resolving which model to use for this bundle's agents. The resolution order:

1. `bundle.yaml` `model.model` (most specific)
2. `bundle.yaml` `model.name` or `model.id`
3. `remora.yaml` `model_default`
4. `REMORA_MODEL_DEFAULT` environment variable

### Mapping Bundles to Node Types

In `remora.yaml`, the `bundle_mapping` field controls which bundle handles which node type:

```yaml
# remora.yaml
bundle_root: agents

bundle_mapping:
  function: function_agent
  class: class_agent
  module: module_agent
  section: notes_agent        # Markdown sections
  todo: todo_agent            # Markdown todos
```

Each key is a `node_type` string (as discovered by tree-sitter queries). Each value is a subdirectory under `bundle_root` that must contain a `bundle.yaml`.

---

## Adding Tree-Sitter Queries

Remora discovers code nodes using tree-sitter query files (`.scm` format). Built-in queries cover:

| Language | Node Types |
|----------|-----------|
| Python | `function`, `class`, `file` |
| Markdown | `section`, `heading`, `todo`, `frontmatter`, `code_block`, `file` |
| TOML | `table`, `file` |

You can add custom queries to discover new node types or override built-in ones.

### Query Location

Place custom queries in `.remora/queries/<language>/<bundle_name>/`:

```
.remora/
  queries/
    python/
      my_bundle/
        decorator.scm       # Discover decorated functions as a special type
    javascript/
      js_bundle/
        function.scm         # Add JavaScript support
```

### Query Syntax

Tree-sitter queries use S-expression syntax. Each query defines captures that Remora uses to create agent nodes. The key captures are:

- `@<type>.def` -- Defines the full extent of the node (start/end lines)
- `@<type>.name` -- Captures the name of the node

Example: discovering Python functions decorated with `@agent`:

```scheme
; .remora/queries/python/custom_bundle/agent_function.scm
(decorated_definition
  (decorator
    (identifier) @_dec_name)
  (function_definition
    name: (identifier) @agent_function.name))
  @agent_function.def

(#eq? @_dec_name "agent")
```

This query would match:

```python
@agent
def my_handler():
    pass
```

And create a node with type `agent_function` and name `my_handler`.

### Adding New Language Support

To add support for a language Remora does not currently handle:

1. Ensure the tree-sitter grammar is installed for that language.
2. Add the language to `discovery_languages` in `remora.yaml` (or leave it as `null` for all).
3. Add the file extension to the Neovim LSP `filetypes` config.
4. Create `.scm` query files in `.remora/queries/<language>/`.

---

## Writing Agent Extensions

Agent extensions customize the behavior of discovered agents by overriding fields on the `AgentNode`. They are Python files in `.remora/models/` that subclass `AgentExtension`.

### How Extensions Work

1. Remora loads all `.py` files from `.remora/models/`, sorted alphabetically.
2. For each discovered node, Remora calls `matches()` on each extension in order.
3. **First match wins.** The matching extension's `get_extension_data()` is called to get field overrides.
4. These overrides are applied to the `AgentNode`.

Control priority via filename: `00_specific.py` runs before `50_generic.py`.

### Extension Structure

```python
# .remora/models/00_api_functions.py
from remora.extensions import AgentExtension


class ApiAgentExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        """Match functions in the API module."""
        return node_type == "function" and "api/" in file_path

    @staticmethod
    def get_extension_data() -> dict:
        """Override AgentNode fields for API functions."""
        return {
            "system_prompt_override": "You are an API endpoint specialist. Focus on HTTP semantics, validation, and error handling.",
            "max_turns": 15,
        }
```

### The `matches()` Method

```python
@staticmethod
def matches(
    node_type: str,        # "function", "class", "section", etc.
    name: str,             # The node's name (function name, heading text, etc.)
    *,
    file_path: str = "",   # Full file path of the source file
    source_code: str = "", # The node's source code
) -> bool:
```

Return `True` if this extension should apply to the given node. You can match on any combination of the arguments:

```python
# Match by node type
return node_type == "class"

# Match by name pattern
return name.startswith("test_")

# Match by file path
return "models/" in file_path

# Match by source code content
return "@deprecated" in source_code

# Combine conditions
return node_type == "function" and "utils/" in file_path
```

### The `get_extension_data()` Method

Returns a dict of field names to override on the `AgentNode`. Common fields:

```python
@staticmethod
def get_extension_data() -> dict:
    return {
        "system_prompt_override": "Custom system prompt for this agent type.",
        "max_turns": 20,
        "bundle_override": "specialized_bundle",
    }
```

### Example: Different Prompts for Test Functions

```python
# .remora/models/10_test_functions.py
from remora.extensions import AgentExtension


class TestFunctionExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
        return node_type == "function" and name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "system_prompt_override": (
                "You are a test function agent. Focus on test coverage, "
                "edge cases, and assertion quality. When proposing rewrites, "
                "ensure all assertions are specific and meaningful."
            ),
        }
```

### Caching Behavior

Extensions are cached based on file modification times. When you edit a file in `.remora/models/`, Remora detects the change and reloads extensions on the next reconciliation. You do not need to restart the swarm.

---

## Project Layout Reference

Here is a complete layout showing all customization points:

```
your_project/
  remora.yaml                          # Project configuration
  agents/                              # bundle_root (configurable)
    function_agent/                    # Bundle for "function" node type
      bundle.yaml                      # Agent manifest
      tools/                           # agents_dir (from bundle.yaml)
        read_file.pym                  # Grail tool script
        analyze.pym
        submit_result.pym
    class_agent/                       # Bundle for "class" node type
      bundle.yaml
      tools/
        ...
  .remora/                             # Runtime state + customization
    models/                            # Agent extensions
      00_api_functions.py              # Specific extensions (matched first)
      50_generic.py                    # Generic fallback extension
    queries/                           # Custom tree-sitter queries
      python/
        my_bundle/
          custom_node.scm
    events.db                          # EventStore (SQLite, auto-created)
    subscriptions.db                   # SubscriptionRegistry (auto-created)
    agents/                            # Per-agent state (auto-created)
      ab/
        abcdef.../
          state.jsonl
  src/
    your_code.py                       # Discovered source files
```

Add `.remora/` to your `.gitignore`. The `models/` and `queries/` subdirectories are your customization; everything else under `.remora/` is runtime state.
