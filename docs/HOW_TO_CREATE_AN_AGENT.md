# How to Create an Agent in Remora

This guide is the single source of truth for building agents with the Remora
reactive swarm stack. It covers the full picture: what agents *are* in Remora,
how they are wired together, how to write tools, how tools are discovered and
executed at runtime, and the events that drive everything.

**Tech stack at a glance:**

| Layer | Library | Version |
|-------|---------|---------|
| Sandboxed tool scripts | `grail` | 3.0.0 |
| Agent kernel / model loop | `structured-agents` | 0.3.4 |
| Swarm orchestration | `remora` | (this project) |

> **Prerequisites:** Python ≥ 3.13, a running OpenAI-compatible inference
> server (vLLM recommended), and a `remora.yaml` project config.

---

## Table of Contents

1. [The Remora Agent Model](#1-the-remora-agent-model)
2. [Core Components](#2-core-components)
3. [Architecture and Data Flow](#3-architecture-and-data-flow)
4. [Configuration: `remora.yaml`](#4-configuration-remotayaml)
5. [Bundle: `bundle.yaml`](#5-bundle-bundleyaml)
6. [Writing `.pym` Tool Scripts (Grail)](#6-writing-pym-tool-scripts-grail)
   - [File Structure](#61-file-structure)
   - [Declaring Inputs](#62-declaring-inputs)
   - [Declaring External Functions](#63-declaring-external-functions)
   - [Executable Code and Return Values](#64-executable-code-and-return-values)
   - [What Is and Isn't Allowed](#65-what-is-and-isnt-allowed)
7. [How Tools Are Loaded by Remora](#7-how-tools-are-loaded-by-remora)
   - [RemoraGrailTool](#71-remoragrailtools)
   - [Externals Available to All Tools](#72-externals-available-to-all-tools)
   - [The Virtual Filesystem](#73-the-virtual-filesystem)
8. [The Event and Subscription System](#8-the-event-and-subscription-system)
   - [Events](#81-events)
   - [Subscriptions and SubscriptionPattern](#82-subscriptions-and-subscriptionpattern)
9. [Agent State: `AgentState`](#9-agent-state-agentstate)
10. [How the Swarm Starts: Reconciliation](#10-how-the-swarm-starts-reconciliation)
11. [AgentRunner and SwarmExecutor](#11-agentrunner-and-swarmexecutor)
    - [AgentRunner](#111-agentrunner)
    - [SwarmExecutor](#112-swarmexecutor)
    - [Model Adapter and Kernel](#113-model-adapter-and-kernel)
12. [The `structured-agents` Kernel (AgentKernel)](#12-the-structured-agents-kernel-agentkernel)
    - [Tool Protocol](#121-tool-protocol)
    - [ModelAdapter and Response Parsing](#122-modeladapter-and-response-parsing)
    - [Structured Outputs (Optional)](#123-structured-outputs-optional)
    - [Observability](#124-observability)
13. [End-to-End Example: Writing a New Agent](#13-end-to-end-example-writing-a-new-agent)
14. [Project Filesystem Layout](#14-project-filesystem-layout)
15. [Debugging Checklist](#15-debugging-checklist)

---

## 1. The Remora Agent Model

Remora's agents are **not** manually instantiated objects that you create and
call. Instead, they are **reactive workers** that the swarm spins up in
response to events.

The mental model:

- Your **source code** is the data. Remora discovers it using tree-sitter and
  maps every function, class, or module to an **`AgentState`**.
- Each `AgentState` corresponds to one agent. The agent's identity is its
  `agent_id` (a content hash of the node), its type is `node_type`
  (e.g., `"function"`, `"class"`, `"module"`), and its position is `file_path`
  + `range`.
- Agents **subscribe** to events. When a matching event fires (e.g., a file
  changes, another agent sends a message), the `AgentRunner` picks up the
  trigger and runs an agent turn.
- During a turn, `SwarmExecutor` loads the agent's bundle, initialises the
  workspace, discovers Grail tools, and calls the `structured-agents`
  `AgentKernel` to run the LLM loop.

You create an agent by:

1. Writing a `bundle.yaml` that defines the system prompt and points to a
   tools directory.
2. Writing `.pym` tool scripts in that tools directory.
3. Adding an entry in `remora.yaml` under `bundle_mapping` to associate a
   `node_type` with your bundle.

That's it. Remora handles the rest.

---

## 2. Core Components

| Component | Where defined | Responsibility |
|-----------|--------------|----------------|
| `Config` | `remora.core.config` | Project-level settings from `remora.yaml` |
| `AgentState` | `remora.core.agent_state` | Per-agent runtime state (node info + chat history) |
| `SwarmState` | `remora.core.swarm_state` | SQLite registry of all agents in the swarm |
| `EventStore` | `remora.core.event_store` | Append-only event log + trigger queue |
| `SubscriptionRegistry` | `remora.core.subscriptions` | SQLite store of which agents listen to which events |
| `AgentRunner` | `remora.core.agent_runner` | Consumes triggers, enforces concurrency/depth limits |
| `SwarmExecutor` | `remora.core.swarm_executor` | Runs a single agent turn: workspace → tools → kernel |
| `RemoraGrailTool` | `remora.core.tools.grail` | Bridges a `.pym` script to the `structured-agents` `Tool` protocol |
| `AgentKernel` | `structured_agents.kernel` | The model loop: send messages, parse tool calls, run tools |
| `ModelAdapter` | `structured_agents.models.adapter` | Formats requests and parses model responses |
| `GrailScript` | `grail` | Loaded, validated, sandboxed `.pym` execution |

---

## 3. Architecture and Data Flow

```
  File change / human message / agent message
         │
         ▼
    EventStore (append)
         │
    SubscriptionRegistry.get_matching_agents(event)
         │
         ▼ (per matching agent)
    EventStore trigger queue
         │
         ▼
    AgentRunner.run_forever()
      │  Check cooldown, depth limit, semaphore
         │
         ▼
    SwarmExecutor.run_agent(state, trigger_event)
      │  Load bundle manifest
      │  Initialise CairnWorkspaceService
      │  Discover Grail tools (discover_grail_tools)
      │  Build prompt (file content + trigger context + history)
         │
         ▼
    AgentKernel.run(messages, tool_schemas, max_turns)
      │  ModelAdapter formats messages
      │  LLM returns tool calls
      │  RemoraGrailTool.execute() runs .pym scripts via Grail
      │  Tool results appended to message history
      │  Loop until max_turns or no more tool calls
         │
         ▼
    Response appended to AgentState.chat_history
    AgentCompleteEvent emitted to EventBus
```

---

## 4. Configuration: `remora.yaml`

Remora looks for `remora.yaml` in the current directory or any parent
directory (stopping at a `pyproject.toml` boundary). All fields have
sensible defaults.

```yaml
# remora.yaml

# Where to scan for source nodes
discovery_paths:
  - src/

# Supported languages (null = all)
discovery_languages: null

# Where bundle directories live
bundle_root: agents

# Map node_type → bundle subdirectory
bundle_mapping:
  function: function_agent
  class: class_agent
  module: module_agent

# Model server
model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B
model_api_key: ""

# Swarm storage (SQLite, state files)
swarm_root: .remora
swarm_id: swarm

# Concurrency and safety
max_concurrency: 4
max_turns: 8
max_trigger_depth: 5    # Max chained cascades
trigger_cooldown_ms: 1000

# Workspace
workspace_ignore_patterns:
  - .git
  - .remora
  - __pycache__
  - .venv
```

**Key fields:**

- `bundle_mapping` — maps a discovered `node_type` string (e.g., `"function"`)
  to a subdirectory under `bundle_root`. Each subdirectory must contain a
  `bundle.yaml`.
- `max_trigger_depth` — prevents infinite event cascades. If an agent emits
  an event that triggers itself more than this many times in the same
  correlation chain, the trigger is dropped.
- `trigger_cooldown_ms` — minimum milliseconds between two triggers for the
  *same* agent. Prevents thrashing.
- `max_turns` — default maximum LLM turns per agent run. Can be overridden
  per bundle.

---

## 5. Bundle: `bundle.yaml`

Each bundle packages the agent's prompt, model settings, and a pointer to its
tools. This is a `structured-agents` v0.3 `AgentManifest`.

```yaml
# agents/function_agent/bundle.yaml

name: function_agent

initial_context:
  system_prompt: |
    You are a code analysis assistant specialised in Python functions.
    You have access to tools to read files and submit your findings.
    Always call a tool to complete your task.

# Response parser (qwen is the default; also accepts function_gemma)
model: qwen

# Optional structured output grammar (top-level, not under model)
grammar:
  strategy: json_schema       # json_schema | structural_tag | ebnf
  allow_parallel_calls: false
  send_tools_to_api: true

# Directory containing .pym tools (relative to this bundle.yaml)
agents_dir: tools

max_turns: 10
```

> **`agents_dir`** is the only required field beyond `name` and
> `system_prompt`. If `agents_dir` is omitted or points to an empty directory,
> the agent runs in tool-less chat mode.

### Field reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | `"unnamed"` | Bundle identifier |
| `initial_context.system_prompt` | `str` | `""` | System message sent to the model every turn |
| `model` | `str` | `"qwen"` | Response parser key (`"qwen"` or `"function_gemma"`) |
| `grammar.strategy` | `str` | `null` | Structured output strategy |
| `grammar.send_tools_to_api` | `bool` | `false` | Whether tool schemas are sent to the model's API |
| `agents_dir` | `str` | `"agents"` | Relative path to tools directory |
| `max_turns` | `int` | `20` | Max LLM turns per agent run |

---

## 6. Writing `.pym` Tool Scripts (Grail)

Grail executes `.pym` files inside a sandboxed Python interpreter (Monty). A
`.pym` script is standard Python restricted to a specific grammar so the
runtime can parse and sanitise it safely.

**Core constraint:** scripts cannot import anything except `grail` and
`typing`. All database calls, filesystem access, and network I/O must go
through `@external` functions that Remora provides at runtime.

### 6.1 File Structure

Every `.pym` follows this order:

```python
# 1. Imports (grail and typing only)
from grail import external, Input
from typing import Any, Optional

# 2. Input declarations (values the model or host provides)
path: str = Input("path")

# 3. External function declarations (host provides the implementation)
@external
async def read_file(path: str) -> str:
    """Read a file from the agent's workspace."""
    ...

# 4. Executable logic
content = await read_file(path=path)

# 5. Return value (last expression)
{"content": content, "length": len(content)}
```

### 6.2 Declaring Inputs

Inputs are values the **model** (via tool arguments) or the host injects at
runtime. Every `Input()` must have a type annotation.

```python
# Required input
path: str = Input("path")

# Optional input with default
max_lines: int = Input("max_lines", default=50)
```

Rules:
- The variable name must match the `Input()` name string.
- Required inputs (no default) must always be provided by the model's tool
  call arguments.
- The generated `ToolSchema` for the `.pym` file is built automatically from
  these declarations — required inputs become required JSON schema properties.

### 6.3 Declaring External Functions

Externals are Python functions declared in the script but **implemented by
Remora** at runtime. The script sees a stub; Remora injects the real function.

```python
@external
async def read_file(path: str) -> str:
    """Read a project file."""
    ...

@external
async def write_file(path: str, content: str) -> None:
    """Write content to a project file."""
    ...
```

Rules:
- Body must be `...` (optionally preceded by a docstring). Real code raises
  `CheckError E007`.
- All parameters must have type annotations (`E006`).
- Return type annotation is required (`E006`).
- Both `async def` and `def` are supported.

### 6.4 Executable Code and Return Values

After the declarations, write business logic freely:

```python
content = await read_file(path=path)
lines = content.splitlines()

summary = []
for i, line in enumerate(lines[:max_lines]):
    summary.append(f"{i+1}: {line}")

result = {"path": path, "line_count": len(lines), "preview": summary}
result   # <-- last expression is the return value
```

The **last expression** in the file is the return value of `script.run()`. If
there's no trailing expression, the tool returns `None`.

### 6.5 What Is and Isn't Allowed

**Allowed:** variables, arithmetic, f-strings, `if/else`, `for`, `while`,
`try/except`, list/dict/generator comprehensions, `async/await`, helper
`def` functions (non-`@external`), type annotations, `print()` (captured),
`os.getenv()` (virtual env vars only), tuple unpacking, slicing.

**Forbidden (will raise an error at load time):**

| Code | Feature | Workaround |
|------|---------|-----------|
| E001 | `class` definitions | Use dicts or external functions |
| E002 | `yield` / generators | Return a list |
| E003 | `with` statements | Use `try/finally` or externals |
| E004 | `match` statements | Use `if/elif/else` |
| E005 | Any import except `grail`, `typing`, `__future__` | Move logic to externals |
| E009 | `global` | Use params/returns |
| E012 | `lambda` | Use `def` |

---

## 7. How Tools Are Loaded by Remora

### 7.1 `RemoraGrailTool`

`RemoraGrailTool` wraps a `.pym` script and implements the
`structured-agents` `Tool` protocol — it has a `.schema` property returning a
`ToolSchema` and an async `.execute()` method.

When `discover_grail_tools(agents_dir, ...)` is called:

1. It globs all `*.pym` files in the bundle's `agents_dir`.
2. For each file it calls `grail.load(path)` — this parses, validates, and
   compiles the script. If the script has any errors (E-codes) it logs a
   warning and skips the file.
3. It builds a `ToolSchema` automatically from the script's `Input()`
   declarations.
4. A `RemoraGrailTool` is created per script, holding the loaded
   `GrailScript`, externals dict, and a `files_provider` callable.

At execution time (`execute(arguments, context)`):

```
1. Call files_provider() → loads current workspace files as virtual FS
2. Filter externals to only those declared in the script
3. Call script.run(inputs=arguments, externals=filtered_externals, files=vfs)
4. Return ToolResult(output=json.dumps(result), is_error=False)
```

Errors from Grail (e.g., `ExecutionError`, `LimitError`) are caught and
returned as `ToolResult(is_error=True)` rather than propagated — the model
sees the error message and can react.

### 7.2 Externals Available to All Tools

Remora injects these externals into every tool script (only those declared
with `@external` in the script will actually be callable):

| External name | Signature | Description |
|--------------|-----------|-------------|
| `read_file` | `(path: str) → str` | Read a workspace file |
| `write_file` | `(path: str, content: str) → None` | Write a workspace file |
| `list_dir` | `(path: str) → list[str]` | List directory entries |
| `emit_event` | `(event_type: str, event_obj: Any) → None` | Emit a swarm event |
| `register_subscription` | `(agent_id: str, pattern: Any) → None` | Create a new subscription |
| `unsubscribe_subscription` | `(subscription_id: int) → str` | Remove a subscription |
| `broadcast` | `(to_pattern: str, content: str) → str` | Send a message to agents |
| `query_agents` | `(filter_type: str | None) → list` | Query swarm agent metadata |

**Workspace externals** (`read_file`, `write_file`, `list_dir`) are provided
by `CairnWorkspaceService` / `AgentWorkspace`.

**Swarm externals** (`emit_event`, `broadcast`, `query_agents`, etc.) are
injected directly by `SwarmExecutor.run_agent()` as closures over the swarm's
`EventStore`, `SubscriptionRegistry`, and `SwarmState`.

> **Important:** To use any of these in a `.pym` script you must declare them
> with `@external`. Remora populates only the externals that the script
> declares — extras are silently ignored (no `ExternalError`).

### 7.3 The Virtual Filesystem

Grail scripts cannot directly read real files. Instead, Remora populates a
*virtual filesystem* that Grail exposes inside the sandbox. Before each tool
execution, `CairnDataProvider.load_files(node)` fetches the agent's target
file (and any related files) from the Cairn workspace and passes them as the
`files` dict to `script.run()`.

Inside a `.pym` script, you can read these files via an `@external` like
`read_file`, which is implemented by Remora to look in the virtual FS.

---

## 8. The Event and Subscription System

Remora is **event-driven**. Agents do not poll for work; they react to events.

### 8.1 Events

All events inherit from `RemoraEvent`. Key event types:

| Event | When it fires | Notable fields |
|-------|--------------|----------------|
| `ContentChangedEvent` | A source file was modified | `path`, `diff` |
| `AgentMessageEvent` | One agent sent a message to another | `from_agent`, `to_agent`, `content` |
| `HumanInputRequestEvent` | Agent requests human input | `agent_id`, `prompt` |
| `HumanInputResponseEvent` | Human responded | `agent_id`, `content` |
| `AgentStartEvent` | An agent turn began | `agent_id`, `node_name` |
| `AgentCompleteEvent` | An agent turn finished | `agent_id`, `response` |
| `AgentErrorEvent` | An agent turn failed | `agent_id`, `error` |
| `KernelStartEvent` / `KernelEndEvent` | LLM kernel lifecycle | — |
| `ModelRequestEvent` / `ModelResponseEvent` | Per-turn model round-trip | — |
| `ToolCallEvent` / `ToolResultEvent` | Tool execution lifecycle | — |

Events are written to the `EventStore` via `event_store.append(swarm_id, event)`.

### 8.2 Subscriptions and `SubscriptionPattern`

A `Subscription` pairs an `agent_id` with a `SubscriptionPattern`. The
registry stores these in SQLite and uses them to route events to agents.

```python
from remora import SubscriptionPattern

# Match any AgentMessageEvent addressed to this agent
direct_msg = SubscriptionPattern(to_agent="my_agent_id")

# Match ContentChangedEvent for a specific file
file_changed = SubscriptionPattern(
    event_types=["ContentChangedEvent"],
    path_glob="src/my_module.py",
)

# Match a message from a specific agent with a tag
tagged = SubscriptionPattern(
    from_agents=["orchestrator"],
    tags=["priority"],
)
```

`SubscriptionPattern` fields:

| Field | Type | Meaning |
|-------|------|---------|
| `event_types` | `list[str] \| None` | Match if event class name is in this list |
| `from_agents` | `list[str] \| None` | Match if `event.from_agent` is in this list |
| `to_agent` | `str \| None` | Match if `event.to_agent == to_agent` |
| `path_glob` | `str \| None` | Match if `event.path` matches this glob |
| `tags` | `list[str] \| None` | Match if any tag overlaps |

`None` on any field means "match anything" for that field. All non-`None`
fields must match (logical AND). Multiple values in a list are OR.

**Default subscriptions** are registered automatically by
`reconcile_on_startup` for every newly discovered agent:
1. `SubscriptionPattern(to_agent=agent_id)` — direct messages.
2. `SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)` — its own source file.

Agents can register additional subscriptions at runtime by calling the
`register_subscription` external from a tool script.

---

## 9. Agent State: `AgentState`

`AgentState` is the runtime identity card for an agent. It is persisted as a
JSONL file at `.remora/agents/<id[:2]>/<id>/state.jsonl`. Each turn appends a
snapshot line.

```python
@dataclass
class AgentState:
    agent_id: str                          # Content-hash of the CST node
    node_type: str                         # "function", "class", "module", etc.
    name: str                              # Short name (e.g., "my_function")
    full_name: str                         # Qualified name (e.g., "module.MyClass.my_function")
    file_path: str                         # Absolute path to source file
    parent_id: str | None                  # Parent agent_id (if any)
    range: tuple[int, int] | None          # (start_line, end_line) in source file
    connections: dict[str, str]            # Named connections to other agents
    chat_history: list[dict[str, Any]]     # Last N turns of [role, content] pairs
    custom_subscriptions: list[SubscriptionPattern]
    last_updated: float                    # Unix timestamp of last save
```

**Chat history** is kept as a sliding window (last 10 entries). The
`SwarmExecutor` prepends up to 5 recent history entries into the prompt on
each turn so the agent has short-term memory of its recent interactions.

State is loaded before each turn and saved after (even on error). The state
file grows as a JSONL log; only the last line is used as the current state.

---

## 10. How the Swarm Starts: Reconciliation

When Remora starts (via its service layer), `reconcile_on_startup` is called:

```python
from remora import reconcile_on_startup

stats = await reconcile_on_startup(
    project_path=".",
    swarm_state=swarm_state,
    subscriptions=subscriptions,
    discovery_paths=["src/"],
    event_store=event_store,
)
# stats = {"created": N, "orphaned": M, "updated": K, "total": T}
```

What happens:

1. **Discover nodes** — tree-sitter parses all source files under
   `discovery_paths`. Each function, class, and module becomes a `CSTNode`.
2. **Diff against SwarmState** — new nodes get `AgentState` + `AgentMetadata`
   created; deleted nodes get marked `orphaned` and subscriptions removed.
3. **Register default subscriptions** — direct-message and source-file
   subscriptions are created for every new agent.
4. **Emit `ContentChangedEvent`** for files that changed while the daemon
   was offline (detected by comparing file mtime with `state.last_updated`).

You do not normally call `reconcile_on_startup` yourself — it is part of the
Remora service startup sequence. But you need to understand it to know why
agents appear and disappear as your source code changes.

---

## 11. AgentRunner and SwarmExecutor

### 11.1 `AgentRunner`

`AgentRunner` is the main reactive loop. It runs forever, consuming triggers
from the `EventStore` and dispatching agent turns.

```python
from remora import AgentRunner, EventStore, SubscriptionRegistry, SwarmState
from remora import load_config

config = load_config()
# ... initialise event_store, subscriptions, swarm_state ...

runner = AgentRunner(
    event_store=event_store,
    subscriptions=subscriptions,
    swarm_state=swarm_state,
    config=config,
    event_bus=event_bus,     # Optional: for emitting lifecycle events
    project_root=Path("."),
)

await runner.run_forever()  # Runs until cancelled
```

`AgentRunner` enforces:

- **Concurrency** via `asyncio.Semaphore(config.max_concurrency)`.
- **Cascade prevention** via a per `(agent_id, correlation_id)` depth counter.
  Once `max_trigger_depth` is reached, further triggers in that chain are
  dropped.
- **Cooldown** via `trigger_cooldown_ms` — minimum time between two triggers
  for the same agent.

### 11.2 `SwarmExecutor`

`SwarmExecutor` handles a single agent turn. `AgentRunner` creates one
instance and reuses it for all turns. You do not normally construct
`SwarmExecutor` directly; `AgentRunner` does it for you.

For each turn:

1. Load `AgentState` from disk.
2. Resolve the bundle path using `Config.bundle_mapping[state.node_type]`.
3. Load the bundle manifest (`load_manifest(bundle_path)`).
4. Initialise `CairnWorkspaceService` (lazily, once per executor lifetime).
5. Get an `AgentWorkspace` for this agent from the workspace service.
6. Build the `externals` dict (workspace functions + swarm functions).
7. Load files via `CairnDataProvider` → build virtual FS.
8. Build the user prompt string (target info + code context + trigger event +
   recent history).
9. Call `discover_grail_tools(manifest.agents_dir, ...)`.
10. Run `AgentKernel` → get `RunResult`.
11. Append the turn to `AgentState.chat_history` and save.
12. Emit `AgentCompleteEvent`.

### 11.3 Model Adapter and Kernel

Inside `SwarmExecutor._run_kernel()`, the model adapter and kernel are created
per-turn (fresh `AgentKernel` each time — Remora does not maintain a long-lived
kernel across turns):

```python
# (internal to SwarmExecutor — shown for understanding)
parser = get_response_parser(manifest.model)   # e.g. QwenResponseParser
pipeline = ConstraintPipeline(manifest.grammar_config) if manifest.grammar_config else None
adapter = ModelAdapter(name=manifest.model, response_parser=parser, constraint_pipeline=pipeline)
client = build_client({"base_url": ..., "api_key": ..., "model": ..., "timeout": ...})
kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)
result = await kernel.run(messages, tool_schemas, max_turns=max_turns)
await kernel.close()
```

---

## 12. The `structured-agents` Kernel (`AgentKernel`)

`AgentKernel` is the model loop from the `structured-agents` library. It:

1. Takes a list of `Message` objects and `ToolSchema` definitions.
2. Formats them via `ModelAdapter` and calls the inference server.
3. Parses tool calls from the model's response.
4. Dispatches each tool call to the matching `Tool.execute()`.
5. Appends tool results to the conversation and loops (up to `max_turns`).
6. Returns a `RunResult` with `final_message` and `history`.

### 12.1 Tool Protocol

Any object implementing this protocol can be used as a tool with the kernel:

```python
from dataclasses import dataclass
from typing import Any
from structured_agents.types import ToolCall, ToolResult, ToolSchema
from structured_agents.tools.protocol import Tool

@dataclass
class MyTool(Tool):
    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="do_something",
            description="Does something useful.",
            parameters={
                "type": "object",
                "properties": {"input": {"type": "string"}},
                "required": ["input"],
            },
        )

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        result = f"Processed: {arguments['input']}"
        return ToolResult(
            call_id=context.id if context else "",
            name=self.schema.name,
            output=result,
            is_error=False,
        )
```

`RemoraGrailTool` already implements this protocol — you only need to write a
raw `Tool` class if you are building tools outside of the standard Grail path.

### 12.2 `ModelAdapter` and Response Parsing

`ModelAdapter` wraps a `ResponseParser` that knows how to extract tool calls
from the model's output.

```python
from structured_agents import ModelAdapter, QwenResponseParser

adapter = ModelAdapter(
    name="qwen",
    response_parser=QwenResponseParser(),
)
```

`QwenResponseParser` handles both the native `tool_calls` field and the legacy
XML-style format that some Qwen variants emit.

For vLLM, configure your server with:
```
--tool-call-parser qwen3_xml
--enable-auto-tool-choice
```

### 12.3 Structured Outputs (Optional)

When you need strict JSON schema compliance from the model (e.g., for a
submit/terminate tool that must match a specific schema), enable a grammar
constraint:

```python
from structured_agents import DecodingConstraint, StructuredOutputModel
from structured_agents.grammar.pipeline import ConstraintPipeline

class SubmitResult(StructuredOutputModel):
    summary: str
    confidence: float

constraint = DecodingConstraint(strategy="json_schema", schema_model=SubmitResult)
pipeline = ConstraintPipeline(constraint)

adapter = ModelAdapter(
    name="qwen",
    response_parser=QwenResponseParser(),
    constraint_pipeline=pipeline,
)
```

Strategy options:
- `json_schema` — recommended. Standard JSON Schema constraint via vLLM's
  `structured_outputs`.
- `structural_tag` — experimental. Uses structural tags instead of schema.
- `ebnf` — advanced use only.

### 12.4 Observability

The kernel emits events for every model round-trip, tool call, and turn
completion. `SwarmExecutor` attaches an observer that appends these events to
the `EventStore`:

```python
class _EventStoreObserver:
    async def emit(self, event: Any) -> None:
        await self.store.append(self.swarm_id, event)

observer = _EventStoreObserver(event_store, swarm_id)
kernel = AgentKernel(client=client, adapter=adapter, tools=tools, observer=observer)
```

Standard events emitted by the kernel:
`KernelStartEvent`, `ModelRequestEvent`, `ModelResponseEvent`,
`ToolCallEvent`, `ToolResultEvent`, `TurnCompleteEvent`, `KernelEndEvent`.

You can attach your own observer (e.g., for logging or a dashboard) by
implementing a class with an async `emit(event)` method and injecting it via
`CompositeObserver`.

---

## 13. End-to-End Example: Writing a New Agent

Let's create a `"module"` agent that summarises a Python module.

### Step 1: Update `remora.yaml`

```yaml
# remora.yaml
bundle_mapping:
  module: module_summariser
```

### Step 2: Create `agents/module_summariser/bundle.yaml`

```yaml
# agents/module_summariser/bundle.yaml
name: module_summariser

initial_context:
  system_prompt: |
    You are a code documentation assistant. Your job is to analyse a Python
    module and produce a concise summary of its purpose, public API, and
    key behaviours. Always call the submit_summary tool when done.

model: qwen
agents_dir: tools
max_turns: 8
```

### Step 3: Create `agents/module_summariser/tools/read_module.pym`

```python
# agents/module_summariser/tools/read_module.pym
from grail import external, Input
from typing import Any

path: str = Input("path")

@external
async def read_file(path: str) -> str:
    """Read the module source file."""
    ...

content = await read_file(path=path)
lines = content.splitlines()

result = {
    "path": path,
    "total_lines": len(lines),
    "content": content,
}
result
```

### Step 4: Create `agents/module_summariser/tools/submit_summary.pym`

```python
# agents/module_summariser/tools/submit_summary.pym
from grail import external, Input

summary: str = Input("summary")

@external
async def emit_event(event_type: str, event_obj: Any) -> None:
    """Emit a swarm event."""
    ...

await emit_event(
    "AgentMessageEvent",
    {"content": summary, "tags": ["summary"]},
)

{"status": "submitted", "length": len(summary)}
```

### Step 5: Start the daemon and watch it work

When Remora's swarm starts and discovers your `*.py` files, it will
automatically create one `module_summariser` agent per module file. Each agent
will be triggered when its source file changes.

You can manually trigger an agent by appending a `ContentChangedEvent`:

```python
import asyncio
from remora import EventStore, load_config
from remora.core.events import ContentChangedEvent

async def trigger():
    config = load_config()
    store = EventStore(f"{config.swarm_root}/events.db")
    await store.append("swarm", ContentChangedEvent(
        path="src/my_module.py",
        diff="Initial run",
    ))

asyncio.run(trigger())
```

---

## 14. Project Filesystem Layout

```
your_project/
  remora.yaml                        # Project config
  agents/                            # bundle_root (configurable)
    function_agent/
      bundle.yaml
      tools/
        read_file.pym
        write_file.pym
        submit_result.pym
    module_agent/
      bundle.yaml
      tools/
        read_module.pym
        submit_summary.pym
  .remora/                           # swarm_root (runtime state, gitignored)
    events.db                        # EventStore (SQLite)
    subscriptions.db                 # SubscriptionRegistry (SQLite)
    swarm_state.db                   # SwarmState (SQLite)
    agents/
      ab/
        abcdef.../
          state.jsonl                # AgentState (JSONL log)
          workspace.db               # Cairn workspace (per agent)
  src/
    your_code.py                     # Discovered source files
```

Add `.remora/` to your `.gitignore`.

---

## 15. Debugging Checklist

### Agent is never triggered

- Check that `bundle_mapping` in `remora.yaml` has a key matching your node's
  `node_type` (e.g., `"function"`, `"class"`, `"module"`).
- Check that `SubscriptionRegistry` has entries for the agent. Run
  `reconcile_on_startup` and look for `"created": N > 0`.
- Verify the `ContentChangedEvent` is actually being emitted for the file.

### Tool is not discovered

- Check that the `.pym` file is in the bundle's `agents_dir` directory.
- Run `grail check path/to/tool.pym` to catch E-code errors that would prevent
  `grail.load()` from succeeding.
- Look for `"Failed to load <file>"` warnings in the logs.

### Model produces no tool calls

- Ensure the system prompt ends with an instruction like "Always call a
  function."
- Verify the vLLM server has `--tool-call-parser` and
  `--enable-auto-tool-choice` set.
- Make tool descriptions distinct and start with action verbs.
- Check `tool_schemas` is non-empty (it will be empty if `agents_dir` is
  missing or all tools failed to load).

### Cascade or depth limit messages

- `"Cascade limit reached"` means a chain of events triggered the same agent
  more than `max_trigger_depth` times. Review whether your tools are emitting
  events that loop back.
- Increase `max_trigger_depth` in `remora.yaml` if the depth is intentional.
- Check `trigger_cooldown_ms` if agents seem to be skipping triggers.

### Grail ExecutionError in tool output

- The tool result will have `is_error=True`. The error text is preserved and
  returned to the model. Check logs for the `.pym` file name and line number.
- Use `grail check` to pre-validate scripts.
- `LimitError` (memory/time) is separate from `ExecutionError` — check
  `Limits` settings if scripts are being killed.

---

## Quick Reference

```
remora.yaml           → Config (project settings)
bundle.yaml           → AgentManifest (prompt, model, tools dir)
*.pym                 → tool script (Grail sandboxed Python)
AgentState            → per-agent runtime state (JSONL)
SwarmState            → SQLite registry of all agents
SubscriptionRegistry  → SQLite store of event → agent routing
EventStore            → append-only event log + trigger queue
AgentRunner           → main loop: consume triggers → run turns
SwarmExecutor         → single turn: workspace → tools → kernel
RemoraGrailTool       → .pym ↔ Tool protocol bridge
AgentKernel           → structured-agents model loop
ModelAdapter          → formats requests, parses tool calls
```
