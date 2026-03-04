# EventBased Architecture Concept

> **Status:** Authoritative design document  
> **Supersedes:** `NEOVIM_DEMO_V21_FINAL_CONCEPT.md` (retained for LSP protocol details)  
> **Companion docs:** `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md` (design decisions), `docs/plans/2026-03-01-architectural-unification.md` (implementation plan)

Remora is a reactive agent swarm system where **code nodes become autonomous AI agents that communicate via events**. Every function, class, method, section, and table in your codebase is discovered by tree-sitter, assigned a deterministic identity, and paired with an LLM-powered agent. These agents react to events — file changes, cursor movements, messages from other agents, even the internal kernel events of other agents' LLM turns — forming a self-organizing swarm that assists, modifies, and reasons about your code.

This document describes the EventBased architecture from five perspectives: the **user** sitting in Neovim, the **developer** building applications with Remora, the **agent** as an autonomous participant in the swarm, the **node** as a concrete instance living through its lifecycle, and the **environment** as the observable output of a swarm in action.

---

## Table of Contents

1. [Architecture Core](#1-architecture-core)
   - [The EventLog](#11-the-eventlog)
   - [Events](#12-events)
   - [Subscriptions](#13-subscriptions)
   - [Discovery](#14-discovery)
   - [The Reactive Loop](#15-the-reactive-loop)
   - [Cascade Safety](#16-cascade-safety)
   - [The AgentNode Model](#17-the-agentnode-model)
2. [Perspective 1: The User](#2-perspective-1-the-user)
3. [Perspective 2: The Developer](#3-perspective-2-the-developer)
4. [Perspective 3: The Agent](#4-perspective-3-the-agent)
5. [Perspective 4: The Node](#5-perspective-4-the-node)
6. [Perspective 5: The Environment](#6-perspective-5-the-environment)
7. [LSP Integration](#7-lsp-integration)
8. [Future: Custom CSTNode Types](#8-future-custom-cstnode-types)

---

## 1. Architecture Core

The EventBased architecture has one central principle: **the EventLog is the single source of truth**. Every state change in the system — a file saved, an agent completing a turn, an LLM emitting a tool call, a user moving their cursor — is recorded as an immutable event in a SQLite append-only log. Everything else is derived.

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Neovim     │     │  File System │     │  Agent Kernels   │
│  (LSP Client)│     │  (watchers)  │     │  (LLM turns)     │
└──────┬───────┘     └──────┬───────┘     └────────┬─────────┘
       │                    │                      │
       │  LSP requests      │  inotify             │  kernel events
       │  cursor events     │  file saves          │  tool calls
       │                    │                      │  model responses
       ▼                    ▼                      ▼
┌──────────────────────────────────────────────────────────────┐
│                        EventLog                              │
│              (SQLite append-only table)                       │
│                                                              │
│  id | timestamp | event_type | agent_id | payload (JSON)     │
└──────────────────────────┬───────────────────────────────────┘
                           │
                    ┌──────┴──────┐
                    │  Subscription │
                    │  Matching     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ Agent A  │ │ Agent B  │ │ Agent C  │
        │ (trigger)│ │ (trigger)│ │ (trigger)│
        └──────────┘ └──────────┘ └──────────┘
```

### 1.1 The EventLog

The EventLog is a single SQLite table (`events`) with append-only semantics. Every event gets a monotonically increasing `id`, a `timestamp`, an `event_type` string, and a JSON `payload`. There are no updates, no deletes. The log is the history of everything that has happened.

Consumers read the log by polling with a cursor (last-seen `id`) or by subscribing to in-process notifications for zero-latency triggering. The EventLog replaces three components from the previous architecture:

| Old Component | What It Did | EventLog Equivalent |
|---------------|-------------|---------------------|
| `EventBus` (in-memory pub/sub) | Routed events to SSE + UI projector | In-process subscriber notifications on EventLog append |
| `EventStore` (append-only + trigger queue) | Stored events + matched subscriptions | EventLog table + subscription matching on append |
| `SwarmState` (agent metadata registry) | Tracked which agents exist | Derived from `nodes` table (discovery results) |

### 1.2 Events

Events are frozen Pydantic classes. They carry the minimum data needed to describe what happened. There are four categories:

**Agent lifecycle events** — emitted by the AgentRunner when an agent starts, completes, or errors:

| Event | Key Fields | When |
|-------|-----------|------|
| `AgentStartEvent` | `graph_id`, `agent_id`, `node_name` | Agent turn begins |
| `AgentCompleteEvent` | `graph_id`, `agent_id`, `result_summary`, `response` | Agent turn succeeds |
| `AgentErrorEvent` | `graph_id`, `agent_id`, `error` | Agent turn fails |

**Human-in-the-loop events** — for agents that need human input:

| Event | Key Fields | When |
|-------|-----------|------|
| `HumanInputRequestEvent` | `agent_id`, `request_id`, `question`, `options` | Agent blocks for input |
| `HumanInputResponseEvent` | `request_id`, `response` | Human provides answer |

**Reactive swarm events** — the primary communication layer between agents and the outside world:

| Event | Key Fields | When |
|-------|-----------|------|
| `AgentMessageEvent` | `from_agent`, `to_agent`, `content`, `tags`, `correlation_id` | Agent-to-agent message |
| `FileSavedEvent` | `path` | File written to disk |
| `ContentChangedEvent` | `path`, `diff` | File content modified |
| `ManualTriggerEvent` | `to_agent`, `reason` | User manually triggers agent |

**Kernel events** — re-exported from `structured-agents`, emitted during every LLM turn. In the EventBased architecture, these receive **full event treatment** — subscription matching runs on them just like any other event:

| Event | When |
|-------|------|
| `KernelStartEvent` | LLM turn begins |
| `KernelEndEvent` | LLM turn ends |
| `ToolCallEvent` | Model requests a tool call |
| `ToolResultEvent` | Tool returns a result |
| `ModelRequestEvent` | Request sent to LLM API |
| `ModelResponseEvent` | Response received from LLM API |
| `TurnCompleteEvent` | Full multi-turn loop finishes |

All events are collected into the `RemoraEvent` union type for pattern matching.

The decision to give kernel events full subscription treatment is deliberate. It enables **meta-agents**: an agent can subscribe to `ToolCallEvent` from another agent and react to what tools that agent is using. A monitoring agent can watch `ModelResponseEvent` to audit LLM outputs. A coordinator agent can observe `TurnCompleteEvent` to orchestrate multi-agent workflows. This is how agent-to-agent reactivity scales beyond explicit messaging.

### 1.3 Subscriptions

A `SubscriptionPattern` defines what events an agent cares about. It has five optional dimensions — if a dimension is `None`, it matches anything:

```python
@dataclass
class SubscriptionPattern:
    event_types: list[str] | None = None    # e.g., ["ContentChangedEvent", "AgentMessageEvent"]
    from_agents: list[str] | None = None    # e.g., ["a1b2c3d4e5f6"]
    to_agent: str | None = None             # e.g., "f6e5d4c3b2a1"
    path_glob: str | None = None            # e.g., "src/**/*.py"
    tags: list[str] | None = None           # e.g., ["review", "urgent"]
```

Matching is conjunctive (all non-None dimensions must match) with disjunctive lists (any element in a list can match). A subscription with all `None` fields matches every event.

The `SubscriptionRegistry` is SQLite-backed and persistent across restarts. Every agent gets two **default subscriptions** on creation:

1. **Direct message**: `SubscriptionPattern(to_agent=agent_id)` — matches any event addressed to this agent
2. **Source file changes**: `SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)` — matches changes to the agent's own file

Agents can dynamically add or remove subscriptions at runtime using the built-in `subscribe` and `unsubscribe` tools. This is how agents evolve their behavior: a function agent might subscribe to `AgentCompleteEvent` from its parent class agent to coordinate refactoring.

### 1.4 Discovery

Discovery is the process of scanning source files with tree-sitter and producing `CSTNode` objects — the identity of every code element that will become an agent.

A `CSTNode` is a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class CSTNode:
    node_id: str        # SHA256(file_path:name:start_line:end_line)[:16]
    node_type: str      # "function", "class", "file", "section", "table", "method"
    name: str           # e.g., "calculate_total"
    full_name: str      # e.g., "function:calculate_total"
    file_path: str      # absolute path to source file
    text: str           # raw source text of the node
    start_line: int     # 1-based
    end_line: int       # 1-based
    start_byte: int
    end_byte: int
```

Discovery works by loading language-specific tree-sitter queries from `.scm` files in `queries/{language}/remora_core/`. Currently supported:

| Language | Query Files | Node Types Discovered |
|----------|------------|----------------------|
| Python | `function.scm`, `class.scm`, `file.scm` | `function`, `method` (inside class), `class`, `file` |
| Markdown | `section.scm`, `file.scm` | `section` (ATX headings), `code_block`, `file` |
| TOML | `table.scm`, `file.scm` | `table`, `array_table`, `file` |

The `discover()` function accepts paths (files or directories), auto-detects language from file extension, and returns `CSTNode` objects sorted by file path and line number. It uses a thread pool for parallel parsing.

The `node_id` is deterministic: `SHA256(file_path:name:start_line:end_line)[:16]`. This means the same code element produces the same ID across restarts, enabling stable agent identity. When code moves (refactoring), the ID changes, and reconciliation handles the transition.

#### From CSTNode to AgentNode

`CSTNode` is the **input** to the system — a raw tree-sitter result. The EventLog projection transforms it into an `AgentNode` (see [Section 1.7](#17-the-agentnode-model)):

```
Source file → tree-sitter → CSTNode → NodeDiscoveredEvent → EventLog
    → projection writes nodes table row (with extension matching)
    → AgentNode.from_row(row) hydrates the read model
```

Every node type produces a `CSTNode`, including file-level nodes. A Python file always generates at least one `file`-type `CSTNode` (representing the entire file), plus `function`, `class`, and `method` nodes for its contents. This means **every file has an agent** — a file-level `AgentNode` that can manage exports, coordinate its child function/class agents, or (with the right extension) render Jinja templates to scaffold new code.

Discovery also produces file nodes for non-Python files when tree-sitter queries exist for their language. A `README.md` produces a `file` node plus `section` nodes for each heading. A `pyproject.toml` produces a `file` node plus `table` nodes for each TOML table. All of these become `AgentNode` instances with type-appropriate extensions.

### 1.5 The Reactive Loop

The reactive loop is the heartbeat of the swarm. It connects events to agents:

```
1. Something happens (file save, cursor move, agent message, kernel event)
2. An event is appended to the EventLog
3. Subscription matching runs: for each subscription in the registry,
   check if the new event matches
4. For each matching agent_id, a trigger is enqueued
 5. AgentRunner picks up the trigger (respecting concurrency semaphore)
 6. AgentRunner loads the AgentNode from the nodes table via AgentNode.from_row()
 7. SwarmExecutor resolves the bundle (via bundle_mapping[agent.node_type])
8. SwarmExecutor loads the structured-agents manifest
 9. SwarmExecutor builds the prompt via agent.to_system_prompt():
    - Identity (agent name, ID, file, line range)
    - Source code (from AgentNode.source_code)
    - Graph context (parent, callers, callees from AgentNode fields)
    - Specialization (custom_system_prompt if extension matched)
    - Trigger event details (type + content)
    - Recent chat history (from EventLog: last N ModelRequest/ModelResponse events)
10. SwarmExecutor discovers Grail tools (.pym scripts) + swarm tools + agent.extra_tools
11. AgentKernel runs the LLM loop (model request → response → tool calls → ...)
12. Kernel events (ToolCallEvent, ModelResponseEvent, etc.) are written
    to the EventLog by _EventStoreObserver
13. Those kernel events trigger subscription matching (step 3 again)
14. Agent completes → AgentCompleteEvent appended → may trigger other agents
```

This is a closed loop. An agent's output events become input events for other agents. The swarm is self-sustaining once events start flowing.

### 1.6 Cascade Safety

Unbounded reactivity would create infinite loops. The AgentRunner implements three safety mechanisms:

1. **Correlation ID tracking** — every event chain carries a `correlation_id`. When agent A triggers agent B triggers agent C, they all share the same correlation ID. The runner tracks depth per correlation.

2. **Depth limits** — `max_trigger_depth` (default 5) caps how deep a single event chain can go. If agent A → B → C → D → E → F, the 6th trigger is dropped.

3. **Cooldown** — `trigger_cooldown_ms` (default 1000ms) prevents the same agent from being triggered too frequently. If an agent just completed a turn, it won't be triggered again for 1 second.

4. **Concurrency semaphore** — `max_concurrency` (default 4) limits how many agent turns execute simultaneously.

These values are configurable in `remora.yaml`.

### 1.7 The AgentNode Model

The `AgentNode` is a single Pydantic `BaseModel` that serves as the **unified read model** for every agent in the system. It replaces the previous split across four representations (`CSTNode`, `AgentState`, `ASTAgentNode`, `ExtensionNode`) with one model that fulfills three roles simultaneously:

1. **Database schema** — `AgentNode.model_dump()` serializes directly to/from the `nodes` table
2. **Agent prompt context** — `AgentNode.to_system_prompt()` generates the LLM system prompt
3. **LSP protocol data** — `.to_hover()`, `.to_code_lens()`, `.to_code_actions()`, `.to_document_symbol()` convert directly to LSP types for Neovim

```python
from pydantic import BaseModel, ConfigDict, Field

class AgentNode(BaseModel):
    """Unified agent model: DB row, LLM prompt, and LSP response in one object."""
    model_config = ConfigDict(frozen=False)

    # --- Identity (populated from CSTNode via event projection) ---
    node_id: str                    # SHA256(file_path:name:start_line:end_line)[:16]
    node_type: str                  # "function", "class", "method", "file", "section", "table"
    name: str                       # e.g., "calculate_total"
    full_name: str                  # e.g., "function:calculate_total"
    file_path: str                  # absolute path to source file
    start_line: int                 # 1-based
    end_line: int                   # 1-based
    source_code: str                # raw source text
    source_hash: str                # SHA256 of source_code for change detection

    # --- Graph context (populated from edges table) ---
    parent_id: str | None = None
    caller_ids: list[str] = Field(default_factory=list)
    callee_ids: list[str] = Field(default_factory=list)

    # --- Runtime state (derived from event projections) ---
    status: str = "idle"            # "idle", "running", "error", "pending_approval"
    last_trigger_event: str = ""    # event_type that last triggered this agent
    last_completed_at: float | None = None

    # --- Specialization (populated from extension config matching) ---
    extension_name: str | None = None       # e.g., "TestFunction", "ApiRoute", "ConfigTable"
    custom_system_prompt: str = ""           # appended to bundle system prompt
    mounted_workspaces: list[str] = Field(default_factory=list)
    extra_tools: list[ToolSchema] = Field(default_factory=list)
    extra_subscriptions: list[SubscriptionPattern] = Field(default_factory=list)
```

#### Three Roles, One Object

**Role 1: Database schema.** The EventLog projection writes `AgentNode` fields to the `nodes` table. Reading them back is a single query:

```python
@classmethod
def from_row(cls, row: sqlite3.Row) -> AgentNode:
    """Hydrate from a nodes table row."""
    data = dict(row)
    # JSON columns are stored as strings
    data["caller_ids"] = json.loads(data.get("caller_ids", "[]"))
    data["callee_ids"] = json.loads(data.get("callee_ids", "[]"))
    data["extra_tools"] = [ToolSchema(**t) for t in json.loads(data.get("extra_tools", "[]"))]
    data["extra_subscriptions"] = [
        SubscriptionPattern(**s) for s in json.loads(data.get("extra_subscriptions", "[]"))
    ]
    data["mounted_workspaces"] = json.loads(data.get("mounted_workspaces", "[]"))
    return cls(**data)
```

**Role 2: Agent prompt context.** The system prompt is built from identity, source code, graph context, and specialization — all fields on the same object:

```python
def to_system_prompt(self) -> str:
    prompt = f"""You are an autonomous AI agent embodying a Python {self.node_type}: `{self.name}`

# Identity
- Node ID: {self.node_id}
- Location: {self.file_path}:{self.start_line}-{self.end_line}
- Parent: {self.parent_id or "None (top-level)"}

# Your Source Code
```python
{self.source_code}
```

# Graph Context
- Called by: {", ".join(self.caller_ids) or "None"}
- You call: {", ".join(self.callee_ids) or "None"}

# Core Rules
1. You may ONLY edit your own body using `rewrite_self()`.
2. To request changes elsewhere, use `message_node(target_id, request)`.
3. All edits are proposals—the human must approve before they apply.
"""
    if self.custom_system_prompt:
        prompt += f"\n# Specialization ({self.extension_name})\n{self.custom_system_prompt}\n"

    if self.mounted_workspaces:
        prompt += f"\n# Available Workspaces\n" + "\n".join(f"- {w}" for w in self.mounted_workspaces) + "\n"

    return prompt
```

**Role 3: LSP protocol data.** The same object converts directly to Neovim LSP responses:

```python
def to_code_lens(self) -> lsp.CodeLens:
    status_icon = {"idle": "\u25cf", "running": "\u25b6", "pending_approval": "\u23f8", "error": "\u25cb"}
    return lsp.CodeLens(
        range=lsp.Range(
            start=lsp.Position(line=self.start_line - 1, character=0),
            end=lsp.Position(line=self.start_line - 1, character=0),
        ),
        command=lsp.Command(
            title=f"{status_icon.get(self.status, '?')} {self.node_id}",
            command="remora.selectAgent",
            arguments=[self.node_id],
        ),
    )

def to_hover(self, recent_events: list | None = None) -> lsp.Hover:
    lines = [
        f"## {self.name}",
        f"**ID:** `{self.node_id}`  **Type:** {self.node_type}  **Status:** {self.status}",
        f"**Parent:** `{self.parent_id or 'None'}`",
        f"**Callers:** {', '.join(f'`{c}`' for c in self.caller_ids) or 'None'}",
        f"**Callees:** {', '.join(f'`{c}`' for c in self.callee_ids) or 'None'}",
    ]
    if self.extension_name:
        lines.append(f"**Extension:** {self.extension_name}")
    if recent_events:
        lines.extend(["", "---", "", "### Recent Events"])
        for ev in recent_events:
            lines.append(f"- `{ev.event_type}` {ev.summary}")
    return lsp.Hover(
        contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value="\n".join(lines)),
        range=self.to_range(),
    )

def to_code_actions(self) -> list[lsp.CodeAction]:
    actions = [
        lsp.CodeAction(title="Chat with this agent", kind=lsp.CodeActionKind.Empty,
                        command=lsp.Command(title="Chat", command="remora.chat", arguments=[self.node_id])),
        lsp.CodeAction(title="Ask agent to rewrite itself", kind=lsp.CodeActionKind.RefactorRewrite,
                        command=lsp.Command(title="Rewrite", command="remora.requestRewrite", arguments=[self.node_id])),
        lsp.CodeAction(title="Message another agent", kind=lsp.CodeActionKind.Empty,
                        command=lsp.Command(title="Message", command="remora.messageNode", arguments=[self.node_id])),
    ]
    # Extension-provided tools appear as additional code actions
    for tool in self.extra_tools:
        actions.append(tool.to_code_action(self.node_id))
    return actions
```

#### Specialization via Data, Not Subclasses

There is no `TestAgentNode` subclass or `RouteAgentNode` subclass. Every agent in the system is an `AgentNode` instance. Behavioral differences come from **different field values**, populated by extension configs at discovery time.

An extension config is a Python class that declares what it matches and what data it contributes:

```python
# .remora/models/test_agent.py
from remora.extensions import AgentExtension, ToolSchema, SubscriptionPattern

class TestFunctionExtension(AgentExtension):
    """Specializes agents for test functions."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestFunction",
            "custom_system_prompt": (
                "You are a test function. Your job is to verify the correctness of the "
                "code under test. When your source file changes, re-examine your assertions. "
                "When the implementation you test changes, evaluate whether your tests still "
                "cover the right behavior and propose updates if needed."
            ),
            "extra_tools": [
                ToolSchema(
                    name="run_test",
                    description="Run this specific test with pytest",
                    parameters={"type": "object", "properties": {"verbose": {"type": "boolean"}}}
                ),
            ],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/*.py"),
            ],
        }
```

When the projection processes a `NodeDiscoveredEvent`, it checks each extension config:

```python
# Inside EventLog projection
def project_node_discovered(self, event, db):
    row = {
        "node_id": event.node_id,
        "node_type": event.node_type,
        "name": event.name,
        # ... identity fields from CSTNode ...
    }
    # Match extension configs (data-driven, not inheritance)
    for ext in self.extension_configs:
        if ext.matches(row["node_type"], row["name"]):
            row.update(ext.get_extension_data())
            break  # first match wins

    db.execute("INSERT OR REPLACE INTO nodes (...) VALUES (...)", row)
```

Here are more extension configs showing the range of specializations — all producing the same `AgentNode` type with different data:

```python
# .remora/models/init_file.py
class InitFileExtension(AgentExtension):
    """Specializes file-level agents for __init__.py modules."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name == "__init__.py"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "InitFile",
            "custom_system_prompt": (
                "You are a Python package's __init__.py. You manage the package's public API. "
                "When functions or classes in sibling modules change, update __all__ and "
                "re-exports to keep the package interface consistent. When new modules are "
                "added to your directory, add appropriate imports."
            ),
            "extra_subscriptions": [
                # React when any .py file in the same directory changes
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/*.py"),
                # React when sibling modules' agents complete (they may have added exports)
                SubscriptionPattern(event_types=["AgentCompleteEvent"]),
            ],
        }
```

```python
# .remora/models/template_scaffold.py
class TemplateScaffoldExtension(AgentExtension):
    """Specializes file agents for Jinja template scaffolding."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name.endswith(".py.j2")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TemplateScaffold",
            "custom_system_prompt": (
                "You are a Jinja2 template file. Your source code is a template that generates "
                "Python modules. When triggered, read the project spec and any context variables, "
                "then render yourself using the render_template tool to produce the output .py file. "
                "If the spec changes, re-render. If your template source changes, re-render."
            ),
            "extra_tools": [
                ToolSchema(
                    name="render_template",
                    description="Render this Jinja2 template with the given context variables",
                    parameters={
                        "type": "object",
                        "properties": {
                            "output_path": {"type": "string", "description": "Where to write the rendered output"},
                            "context": {"type": "object", "description": "Template variables"},
                        },
                        "required": ["output_path"],
                    },
                ),
                ToolSchema(
                    name="read_spec",
                    description="Read the project spec file for template context",
                    parameters={"type": "object", "properties": {"spec_path": {"type": "string"}}},
                ),
            ],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/SPEC.md"),
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/*.j2"),
            ],
        }
```

```python
# .remora/models/directory_node.py
class DirectoryExtension(AgentExtension):
    """Specializes file-level agents that represent directory README/index files."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name in ("README.md", "INDEX.md", "__init__.py")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "DirectoryManager",
            "custom_system_prompt": (
                "You represent a directory in the project. You are aware of all files in your "
                "directory and their agents. Your job is to maintain structural coherence: "
                "ensure files are organized logically, naming conventions are followed, and "
                "the directory's documentation reflects its current contents. When files are "
                "added or removed, update your documentation accordingly."
            ),
            "mounted_workspaces": ["."],  # mount the directory itself
            "extra_tools": [
                ToolSchema(
                    name="list_directory",
                    description="List all files in this directory",
                    parameters={"type": "object", "properties": {"recursive": {"type": "boolean"}}},
                ),
                ToolSchema(
                    name="create_file",
                    description="Create a new file in this directory",
                    parameters={
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "content": {"type": "string"},
                            "template": {"type": "string", "description": "Optional .j2 template to render"},
                        },
                        "required": ["filename"],
                    },
                ),
            ],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["FileSavedEvent"]),
                SubscriptionPattern(event_types=["AgentCompleteEvent"], tags=["scaffold"]),
            ],
        }
```

The result: a `test_calculate_total` function, a `get_user` function, an `__init__.py` file, a `models.py.j2` template, and a directory's `README.md` are all `AgentNode` instances. The test function has `extension_name="TestFunction"` with a `run_test` tool. The init file has `extension_name="InitFile"` and subscribes to sibling module changes. The template has `extension_name="TemplateScaffold"` with a `render_template` tool and subscribes to spec changes. The README has `extension_name="DirectoryManager"` with tools for listing and creating files. The plain `get_user` function has `extension_name=None` and just the default behavior. Same model type, same table, same conversion methods. Different data.

#### Why Data Over Subclasses

Three reasons this design fits the EventBased architecture:

1. **Events are the behavioral mechanism.** Agents don't differ in how they process Python method calls — they differ in what events they subscribe to, what tools they have, and what their system prompt says. All of these are data.

2. **Hot-reload works.** Extension configs in `.remora/models/` are Python files loaded with mtime-based caching. Changing a config and re-running discovery updates the `nodes` table rows. No class identity issues, no stale instances.

3. **DB serialization is trivial.** Every `AgentNode` has the same schema. One table, flat fields (with JSON columns for lists). No discriminator column, no type registry, no polymorphic deserialization.

---

## 2. Perspective 1: The User

You are a developer working in Neovim. You have a Python project — maybe a web API, a data pipeline, or a CLI tool. You've installed Remora and configured it with a `remora.yaml` at your project root. You open Neovim.

### What You See

When Neovim starts, Remora connects as an LSP server. The initial experience is subtle:

**Code lenses appear above functions and classes.** Each code lens shows the agent status for that code element — typically "idle" when nothing is happening. Clicking a code lens opens a menu of agent actions: "Run agent", "View history", "Send message".

```python
# [agent: idle] [1 subscription]           ← code lens
def calculate_total(items: list[Item]) -> Decimal:
    """Calculate the total price of all items."""
    return sum(item.price * item.quantity for item in items)
```

**Diagnostics appear as proposals.** When an agent finishes a turn and produces a rewrite proposal, it shows up as a diagnostic (warning-level) on the relevant lines. The diagnostic message describes what the agent wants to change. Accepting the diagnostic applies the rewrite.

```python
def calculate_total(items: list[Item]) -> Decimal:
    # ⚠ Agent proposal: Add input validation for empty list
    # ⚠ Suggested: if not items: raise ValueError("items cannot be empty")
    return sum(item.price * item.quantity for item in items)
```

**Hover shows agent context.** Hovering over a function name shows the agent's current state: its ID, subscriptions, last trigger event, and recent chat history summary.

### What You Do

**You write code normally.** When you save a file, Remora detects the change. A `ContentChangedEvent` is appended to the EventLog. Any agent subscribed to changes in that file wakes up. If you modified a function, the function's agent sees the diff and may respond — perhaps by updating its docstring, checking for type errors, or notifying related agents.

**You move your cursor.** Remora debounces cursor position (200ms stable) and emits a cursor focus event. Agents subscribed to cursor activity can react — for example, a "context agent" might preload relevant documentation when you focus on a function that calls an external API.

**You trigger agents manually.** Via code actions (Neovim's `vim.lsp.buf.code_action()`), you can explicitly trigger any agent. You might tell a function's agent: "Add error handling for network timeouts." The agent runs, proposes a rewrite, and it appears as a diagnostic.

**You interact with agents in the sidebar.** A Nui-based sidebar shows real-time agent activity via SSE. You see which agents are running, what tools they're calling, and what they're producing. If an agent requests human input (via `HumanInputRequestEvent`), a prompt appears in the sidebar.

### What You Don't See

You don't see the EventLog. You don't see subscription matching. You don't see the reactive loop churning through triggers. You don't see agents messaging each other behind the scenes. The swarm is invisible infrastructure — you see its effects (diagnostics, code lenses, sidebar updates) but not its mechanics.

The exception is the graph viewer: a d3 force-directed visualization (accessible via browser) that shows all agents as nodes and their communication as edges. This is a debugging/monitoring tool, not part of the primary Neovim workflow.

---

## 3. Perspective 2: The Developer

You are building an application that uses Remora as its agent infrastructure. Maybe you're creating a code review tool, a documentation generator, or a test scaffold system. You configure Remora to match your domain.

### Project Structure

```
my-project/
├── remora.yaml                  # Project-level config
├── agents/                      # Bundle root (configurable)
│   ├── python_function/         # Bundle for function agents
│   │   ├── bundle.yaml          # Agent manifest
│   │   └── tools/               # Grail tool scripts
│   │       ├── read_file.pym
│   │       ├── write_file.pym
│   │       └── run_tests.pym
│   ├── python_class/            # Bundle for class agents
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       └── refactor.pym
│   ├── markdown_section/        # Bundle for markdown section agents
│   │   ├── bundle.yaml
│   │   └── tools/
│   │       └── format_docs.pym
│   └── monitor/                 # Bundle for a custom meta-agent
│       ├── bundle.yaml
│       └── tools/
│           └── alert.pym
├── .remora/                     # Swarm runtime directory
│   ├── models/                  # Extension config definitions
│   │   └── review_node.py       # Custom agent specialization
│   └── db/                      # SQLite databases
│       └── remora.db            # EventLog + nodes table + subscriptions
└── src/                         # Your source code (discovery target)
    └── myapp/
        ├── __init__.py
        ├── models.py
        └── api.py
```

### Configuration: `remora.yaml`

```yaml
# What to discover
discovery_paths:
  - src/
discovery_languages:            # optional: limit to specific languages
  - python
  - markdown
discovery_max_workers: 4

# How to map discovered node types to agent bundles
bundle_root: agents
bundle_mapping:
  function: python_function
  method: python_function       # methods use the same bundle as functions
  class: python_class
  section: markdown_section
  file: python_function         # file-level agents use function bundle

# LLM backend
model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B
model_api_key: ""

# Swarm behavior
swarm_root: .remora
max_concurrency: 4
max_turns: 8
max_trigger_depth: 5
trigger_cooldown_ms: 1000
timeout_s: 300.0
```

The `bundle_mapping` is the key configuration. It says: "when a `function` node is discovered, use the `agents/python_function/` bundle to run its agent." Different node types get different system prompts, tools, and behavior.

### Writing a Bundle: `bundle.yaml`

A bundle is a `structured-agents` manifest that defines how an agent behaves:

```yaml
# agents/python_function/bundle.yaml
name: python-function-agent
version: "1.0"

system_prompt: |
  You are an AI agent responsible for a single Python function.
  Your job is to maintain, improve, and document this function.

  When triggered by a file change, review the diff and decide if action is needed.
  When triggered by a message from another agent, respond helpfully.
  When triggered manually, follow the user's instructions.

  You have access to tools for reading and writing files, running tests,
  and communicating with other agents in the swarm.

  Always explain your reasoning before taking action.

model:
  id: Qwen/Qwen3-4B

agents_dir: tools

max_turns: 5
requires_context: true
```

The `agents_dir` field points to the directory containing `.pym` Grail tool scripts. The `system_prompt` is injected as the first message in every LLM turn. The `model.id` can override the default model from `remora.yaml`.

### Writing Tools: `.pym` Scripts

Tools are sandboxed Python scripts using the Grail format. They declare inputs, use externals (injected dependencies), and return results:

```python
# agents/python_function/tools/write_file.pym
"""Write content to a file in the workspace."""

# --- inputs ---
path: str       # Relative path to write
content: str    # Content to write

# --- externals ---
write_file = external("write_file")  # Injected by workspace service

# --- execute ---
result = write_file(path, content)
return f"Wrote {len(content)} bytes to {path}"
```

```python
# agents/python_function/tools/run_tests.pym
"""Run pytest on a specific file or directory."""

# --- inputs ---
target: str = "."   # File or directory to test

# --- externals ---
run_command = external("run_command")

# --- execute ---
output = run_command(f"python -m pytest {target} -v --tb=short")
return output
```

Tools are discovered automatically from the `agents_dir`. Every agent also gets the five built-in swarm tools without any configuration:

| Tool | Purpose |
|------|---------|
| `send_message` | Send a direct message to another agent by ID |
| `subscribe` | Dynamically add a subscription pattern |
| `unsubscribe` | Remove a subscription by ID |
| `broadcast` | Send a message to multiple agents (`children`, `siblings`, `file:/path`) |
| `query_agents` | List agents in the swarm, optionally filtered by node type |

### Writing Extension Configs: `.remora/models/`

Extension configs customize agent behavior for specific code patterns. They are Python files placed in `.remora/models/` that declare what they match and what data they contribute to the `AgentNode` (see [Section 1.7](#17-the-agentnode-model)). Extension configs produce **data, not behavior** — they return dictionaries of field values that get merged into the `AgentNode` at discovery time.

```python
# .remora/models/review_node.py
from remora.extensions import AgentExtension, ToolSchema, SubscriptionPattern


class ReviewFunctionExtension(AgentExtension):
    """Specializes agents for functions marked for review."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "function" and "review" in name.lower()

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "ReviewFunction",
            "custom_system_prompt": (
                "This function is marked for review. Your primary job is to "
                "analyze it for correctness, performance, and style issues. "
                "Produce a structured review with severity ratings."
            ),
            "extra_tools": [
                ToolSchema(
                    name="rate_severity",
                    description="Rate an issue's severity",
                    parameters={
                        "type": "object",
                        "properties": {
                            "issue": {"type": "string"},
                            "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                        },
                        "required": ["issue", "severity"],
                    },
                )
            ],
        }
```

Here are several more examples showing different kinds of specialization:

**API route agents** — functions decorated with Flask/FastAPI route decorators:

```python
# .remora/models/api_route.py
class ApiRouteExtension(AgentExtension):
    """Specializes agents for API endpoint handler functions."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        # Matches common REST handler naming conventions
        prefixes = ("get_", "post_", "put_", "delete_", "patch_", "handle_")
        return node_type == "function" and any(name.startswith(p) for p in prefixes)

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "ApiRoute",
            "custom_system_prompt": (
                "You are an API endpoint handler. You are responsible for request validation, "
                "business logic, and response formatting. When your implementation changes, "
                "verify that error responses follow the project's error schema. When a model "
                "you depend on changes, check that your request/response types still match."
            ),
            "extra_tools": [
                ToolSchema(
                    name="test_endpoint",
                    description="Send a test HTTP request to this endpoint",
                    parameters={
                        "type": "object",
                        "properties": {
                            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
                            "body": {"type": "object"},
                            "headers": {"type": "object"},
                        },
                    },
                ),
                ToolSchema(
                    name="validate_schema",
                    description="Validate request/response against OpenAPI schema",
                    parameters={"type": "object", "properties": {"schema_path": {"type": "string"}}},
                ),
            ],
            "extra_subscriptions": [
                # React when data models change
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/models.py"),
                # React when the API schema changes
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/openapi.yaml"),
            ],
        }
```

**TOML config table agents** — individual tables within configuration files:

```python
# .remora/models/config_table.py
class ConfigTableExtension(AgentExtension):
    """Specializes agents for TOML configuration tables."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "table"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "ConfigTable",
            "custom_system_prompt": (
                "You are a configuration table in a TOML file. You define settings that "
                "other parts of the codebase depend on. When your values change, notify "
                "the agents that consume this configuration. When you detect invalid values "
                "(wrong types, missing required keys, out-of-range numbers), report them "
                "as diagnostics."
            ),
            "extra_tools": [
                ToolSchema(
                    name="validate_config",
                    description="Validate this config table against its JSON Schema",
                    parameters={"type": "object", "properties": {"schema_path": {"type": "string"}}},
                ),
            ],
            "extra_subscriptions": [
                # React when Python code that reads this config changes
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/*.py"),
            ],
        }
```

**Jinja template file agents** — template files that scaffold code when rendered:

```python
# .remora/models/jinja_template.py
class JinjaTemplateExtension(AgentExtension):
    """Specializes file agents for Jinja2 templates that generate code."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name.endswith(".j2")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "JinjaTemplate",
            "custom_system_prompt": (
                "You are a Jinja2 template file that generates source code. Your source text "
                "contains Jinja2 syntax ({{ variables }}, {% blocks %}, etc.). When triggered, "
                "read the project spec or context file, then render yourself to produce the "
                "output file. If the spec changes, re-render. If your template changes, re-render. "
                "Validate that your rendered output is syntactically valid for its target language."
            ),
            "extra_tools": [
                ToolSchema(
                    name="render_template",
                    description="Render this Jinja2 template with context variables and write output",
                    parameters={
                        "type": "object",
                        "properties": {
                            "output_path": {"type": "string", "description": "Where to write rendered output"},
                            "context": {"type": "object", "description": "Template variables"},
                        },
                        "required": ["output_path"],
                    },
                ),
                ToolSchema(
                    name="validate_output",
                    description="Check that the rendered output is syntactically valid",
                    parameters={"type": "object", "properties": {"file_path": {"type": "string"}}},
                ),
            ],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/SPEC.md"),
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/*.j2"),
                SubscriptionPattern(event_types=["AgentCompleteEvent"], tags=["scaffold"]),
            ],
        }
```

**Package init file agents** — `__init__.py` files that manage public APIs:

```python
# .remora/models/init_file.py
class InitFileExtension(AgentExtension):
    """Specializes file agents for __init__.py package management."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name == "__init__.py"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "PackageInit",
            "custom_system_prompt": (
                "You are a Python package's __init__.py. You manage the public API surface. "
                "When functions or classes in sibling modules change, update __all__ and "
                "re-export statements to keep the package interface consistent and importable. "
                "When new modules are added to your directory, add appropriate imports. "
                "When modules are deleted, remove stale imports."
            ),
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/*.py"),
                SubscriptionPattern(event_types=["AgentCompleteEvent"]),
            ],
        }
```

**Monitor agents** — meta-agents that observe other agents' kernel events:

```python
# .remora/models/monitor_agent.py
class MonitorExtension(AgentExtension):
    """Specializes file agents as swarm monitors (attach to a MONITOR.md file)."""

    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return node_type == "file" and name == "MONITOR.md"

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "SwarmMonitor",
            "custom_system_prompt": (
                "You are a swarm monitoring agent. You observe what other agents are doing "
                "by watching their kernel events. When you see an agent making a tool call "
                "to write_file on a production path, flag it. When you see an agent erroring "
                "repeatedly, summarize the failure pattern. Produce periodic status reports "
                "as diagnostics on your own file."
            ),
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ToolCallEvent"]),
                SubscriptionPattern(event_types=["AgentErrorEvent"]),
                SubscriptionPattern(event_types=["AgentCompleteEvent"]),
            ],
        }
```

Extension configs are loaded from `.remora/models/` on demand with mtime-based caching. When a file changes, the next discovery pass picks up the new config and re-projects affected nodes. All configs produce the same `AgentNode` type — just with different field values.

### The Developer's Mental Model

As a developer, you think in terms of:

1. **Discovery** — what code elements will tree-sitter find? (functions, classes, files, sections, tables)
2. **Mapping** — which bundle handles each node type? (`bundle_mapping` in `remora.yaml`)
3. **Behavior** — what does the system prompt tell the agent to do? (bundle's `system_prompt`)
4. **Tools** — what can the agent actually do? (Grail `.pym` scripts + swarm tools)
5. **Extensions** — which code patterns get specialized `AgentNode` data? (extension configs in `.remora/models/`)
6. **Subscriptions** — what events should agents react to? (defaults + extension-provided + runtime dynamic)

Every agent in the swarm is an `AgentNode` instance (see [Section 1.7](#17-the-agentnode-model)). You don't manage individual agents. You don't start or stop them. You define the rules — discovery paths, bundle mappings, extension configs — and the swarm instantiates and runs agents automatically based on what it finds in the codebase.

---

## 4. Perspective 3: The Agent

An agent is an autonomous participant in the swarm. Its identity comes from a `CSTNode`, its data lives in an `AgentNode` (see [Section 1.7](#17-the-agentnode-model)), its behavior is defined by a bundle plus extension config, and its awareness comes from subscriptions. It communicates by emitting events and reacts by consuming them.

### Agent Identity

Every agent's identity comes from a discovered `CSTNode`, projected into an `AgentNode`. The pipeline is:

```
Source code element → tree-sitter → CSTNode → NodeDiscoveredEvent → EventLog
    → projection (with extension matching) → nodes table row → AgentNode.from_row()
```

The `agent_id` is the `CSTNode.node_id` — a deterministic hash of the file path, name, start line, and end line. This means:

- The same function always gets the same agent ID (stable identity)
- Renaming a function creates a new agent (new identity)
- Moving code within a file may create a new agent (line numbers change)
- Reconciliation handles the transition when identities change

The `AgentNode` carries everything the system needs to interact with this agent: identity fields from discovery, graph context from the edges table, runtime status from event projections, and specialization data from extension config matching. When the LSP server needs to show a code lens, it reads an `AgentNode` and calls `.to_code_lens()`. When the kernel needs a system prompt, it calls `.to_system_prompt()`. One object, three roles.

### Agent Communication

Agents communicate through events. There are three patterns:

**1. Direct messaging** — one agent sends a message to another by ID:

```
Agent A calls send_message(to_agent="f6e5d4c3", content="Your return type changed")
    → AgentMessageEvent(from_agent="a1b2c3d4", to_agent="f6e5d4c3", content=...)
    → EventLog
    → Subscription matching finds Agent B (to_agent="f6e5d4c3")
    → Agent B triggered
```

**2. Broadcasting** — one agent sends a message to a group:

```
Class agent calls broadcast(to_pattern="children", content="Refactoring interface")
    → Resolves children from nodes table (parent_id = this agent's node_id)
    → AgentMessageEvent emitted per child
    → Each child method agent triggered
```

**3. Implicit observation** — agents subscribe to events from other agents without the sender knowing:

```
Monitor agent subscribes to: SubscriptionPattern(
    event_types=["ToolCallEvent"],
    from_agents=["a1b2c3d4"]  # the function agent
)

When Agent A makes a tool call:
    → ToolCallEvent appended to EventLog
    → Subscription matching finds Monitor agent
    → Monitor agent triggered with the ToolCallEvent as context
```

This third pattern is what makes the EventBased architecture powerful. Agents don't need to explicitly "publish" to other agents. Any event they produce — even internal kernel events — can be observed by any other agent with a matching subscription. This enables:

- **Monitoring agents** that watch what tools other agents use
- **Coordinator agents** that observe `TurnCompleteEvent` to orchestrate workflows
- **Learning agents** that study `ModelResponseEvent` patterns across the swarm
- **Safety agents** that watch for specific tool calls (e.g., `write_file` to production paths)

### Multi-Agent Chains

Consider a concrete example: a user moves their cursor to a function that calls `wikipedia.search()`.

```
1. CursorFocusEvent(path="src/research.py", line=42)
   → Matches: context_agent subscription (event_types=["CursorFocusEvent"])

2. context_agent triggers → examines the function → finds wikipedia API call
   → Calls send_message(to_agent=wiki_agent_id, content="User is looking at wikipedia search")

3. AgentMessageEvent(from="context_agent", to="wiki_agent_id")
   → Matches: wiki_agent subscription (to_agent=self)

4. wiki_agent triggers → does a graph search on Wikipedia
   → AgentCompleteEvent(agent_id="wiki_agent_id", response="Found 3 relevant articles...")

5. meta_agent has subscription: SubscriptionPattern(
       event_types=["AgentCompleteEvent"],
       from_agents=["wiki_agent_id"]
   )
   → meta_agent triggers → reads wiki_agent response → does deeper web searches
   → Produces refined article selection

6. The refined results propagate back to the user via diagnostics/sidebar
```

Each step is a separate event in the EventLog. Each agent runs independently with its own LLM turn. The chain emerges from subscriptions, not from hardcoded orchestration.

### CSTNode Types: Current System

Currently, CSTNodes have a flat `node_type` string: `"function"`, `"class"`, `"file"`, `"section"`, `"table"`, `"method"`. The type determines which bundle is used (via `bundle_mapping`) and what default subscriptions are created.

The node types are derived from tree-sitter query capture names. For example, in `queries/python/remora_core/function.scm`:
- `@method.def` captures methods inside classes → `node_type = "method"`
- `@function.def` captures standalone functions → `node_type = "function"`

In `queries/markdown/remora_core/section.scm`:
- `@section.def` captures ATX headings → `node_type = "section"`
- `@code_block.def` captures fenced code blocks → `node_type = "code_block"`

The extension config system adds a second layer of specialization. After discovery, extension configs loaded from `.remora/models/` are checked: if `matches(node_type, name)` returns `True`, the extension's data (system prompt, tools, subscriptions) is merged into the `AgentNode`'s fields in the `nodes` table. See [Section 1.7](#17-the-agentnode-model) for the full model definition and [Section 3: Writing Extension Configs](#writing-extension-configs-remoramodels) for examples.

This two-layer system (tree-sitter queries for structural discovery + extension configs for behavioral specialization via data) is sufficient for many use cases but has limitations — see [Section 8: Future](#8-future-custom-cstnode-types).

---

## 5. Perspective 4: The Node

A node is a specific `AgentNode` instance — one particular function in one particular file, living through its lifecycle in the swarm. Let's follow a single node from birth to action.

### Birth: Discovery

The file `src/myapp/api.py` is saved. The `discover()` function scans it with tree-sitter and finds:

```python
# src/myapp/api.py, lines 15-28
def get_user(user_id: int) -> User:
    """Fetch a user by ID from the database."""
    db = get_connection()
    row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"User {user_id} not found")
    return User(**dict(row))
```

Tree-sitter produces a `CSTNode`:

```
CSTNode(
    node_id="3a7f2b1c9e0d4f8a",  # SHA256("src/myapp/api.py:get_user:15:28")[:16]
    node_type="function",
    name="get_user",
    full_name="function:get_user",
    file_path="src/myapp/api.py",
    text="def get_user(user_id: int) -> User:\n    ...",
    start_line=15,
    end_line=28,
    start_byte=...,
    end_byte=...
)
```

### Identity Assignment: Projection to AgentNode

The `CSTNode` is wrapped in a `NodeDiscoveredEvent` and appended to the EventLog. The projection processes it — matching extension configs and writing a row to the `nodes` table:

```python
# Inside the EventLog projection
NodeDiscoveredEvent(
    node_id="3a7f2b1c9e0d4f8a",
    node_type="function",
    name="get_user",
    full_name="function:get_user",
    file_path="src/myapp/api.py",
    source_code="def get_user(user_id: int) -> User:\n    ...",
    source_hash="a9c1e4...",
    start_line=15,
    end_line=28,
    parent_id="b8c9d0e1f2a3b4c5",  # the file-level agent for api.py
)
```

The projection checks extension configs. `get_user` doesn't match any extension (it's not a test function, not a route handler, not a template), so it gets plain defaults:

```sql
INSERT OR REPLACE INTO nodes (
    node_id, node_type, name, full_name, file_path,
    start_line, end_line, source_code, source_hash,
    parent_id, caller_ids, callee_ids,
    status, extension_name, custom_system_prompt,
    mounted_workspaces, extra_tools, extra_subscriptions
) VALUES (
    '3a7f2b1c9e0d4f8a', 'function', 'get_user', 'function:get_user', 'src/myapp/api.py',
    15, 28, 'def get_user(user_id: int) -> User:\n    ...', 'a9c1e4...',
    'b8c9d0e1f2a3b4c5', '[]', '["c4d5e6f7a8b9c0d1"]',
    'idle', NULL, '',
    '[]', '[]', '[]'
);
```

Anywhere in the system that needs this agent's data reads it back as an `AgentNode`:

```python
row = db.execute("SELECT * FROM nodes WHERE node_id = ?", ("3a7f2b1c9e0d4f8a",)).fetchone()
agent = AgentNode.from_row(row)

# agent.node_id == "3a7f2b1c9e0d4f8a"
# agent.node_type == "function"
# agent.extension_name == None  (no extension matched)
# agent.status == "idle"
# agent.callee_ids == ["c4d5e6f7a8b9c0d1"]  (the get_connection function)
```

There is no separate `AgentState` file. The `nodes` table row *is* the agent's state. Chat history stays in the `events` table as `ModelRequestEvent`/`ModelResponseEvent` entries — the EventLog is already an append-only history log.

### Subscription Registration

The `SubscriptionRegistry` creates two default subscriptions:

```sql
-- Subscription 1: Direct messages
INSERT INTO subscriptions (agent_id, pattern_json, is_default)
VALUES ('3a7f2b1c9e0d4f8a',
        '{"to_agent": "3a7f2b1c9e0d4f8a"}',
        1);

-- Subscription 2: Source file changes
INSERT INTO subscriptions (agent_id, pattern_json, is_default)
VALUES ('3a7f2b1c9e0d4f8a',
        '{"event_types": ["ContentChangedEvent"], "path_glob": "src/myapp/api.py"}',
        1);
```

The node is now alive in the swarm. It won't do anything until an event matches one of its subscriptions.

### First Trigger: File Change

The developer edits `src/myapp/api.py` and saves. A `ContentChangedEvent` is appended:

```python
ContentChangedEvent(
    path="src/myapp/api.py",
    diff="@@ -20,1 +20,3 @@\n-    row = db.execute(...).fetchone()\n+    try:\n+        row = db.execute(...).fetchone()\n+    except DatabaseError as e:",
    timestamp=1709337700.0
)
```

Subscription matching runs. The node's subscription 2 matches (event type is `ContentChangedEvent`, path matches `src/myapp/api.py`). A trigger is enqueued.

### Execution: Agent Turn

The `AgentRunner` picks up the trigger:

1. **Load agent**: Queries the `nodes` table and hydrates an `AgentNode`:
   ```python
   row = db.execute("SELECT * FROM nodes WHERE node_id = ?", (trigger.agent_id,)).fetchone()
   agent = AgentNode.from_row(row)
   ```
2. **Resolve bundle**: `bundle_mapping[agent.node_type]` → `agents/python_function/`
3. **Load manifest**: Reads `agents/python_function/bundle.yaml`
4. **Build workspace**: Cairn workspace service loads file contents
5. **Build prompt**: The bundle's system prompt is combined with agent-specific context via `agent.to_system_prompt()`:

````
# System Prompt (from bundle.yaml + AgentNode)

You are an autonomous AI agent embodying a Python function: `get_user`

## Identity
- Node ID: 3a7f2b1c9e0d4f8a
- Location: src/myapp/api.py:15-28
- Parent: b8c9d0e1f2a3b4c5

## Your Source Code
```python
def get_user(user_id: int) -> User:
    """Fetch a user by ID from the database."""
    try:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except DatabaseError as e:
    ...
```

## Graph Context
- Called by: e1f2a3b4c5d6e7f8
- You call: c4d5e6f7a8b9c0d1

## Trigger Event
Type: ContentChangedEvent
Content: @@ -20,1 +20,3 @@ ...
````

6. **Discover tools**: Grail scripts from `agents/python_function/tools/` + 5 swarm tools + `agent.extra_tools` (empty for this unspecialized agent)
7. **Load chat history**: Recent `ModelRequestEvent`/`ModelResponseEvent` entries for this agent from the EventLog (replacing the old JSONL chat history)
8. **Run kernel**: AgentKernel sends system prompt + history + prompt to LLM

The LLM might respond:

> "The function now has a try/except for DatabaseError but the except clause is empty. I should add proper error handling."

And then call the `write_file` tool to add a `raise` or `logging.error()` in the except block.

8. **Kernel events flow**: During this LLM turn, `ModelRequestEvent`, `ModelResponseEvent`, `ToolCallEvent` (for `write_file`), and `ToolResultEvent` are all appended to the EventLog. Any agent subscribed to these events will be triggered.

9. **Status updates via projection**: While the agent runs, the projection updates the `nodes` table:
   ```python
   # On AgentStartEvent:
   db.execute("UPDATE nodes SET status = 'running', last_trigger_event = ? WHERE node_id = ?",
              ("ContentChangedEvent", "3a7f2b1c9e0d4f8a"))

   # On AgentCompleteEvent:
   db.execute("UPDATE nodes SET status = 'idle', last_completed_at = ? WHERE node_id = ?",
              (timestamp, "3a7f2b1c9e0d4f8a"))

   # On AgentErrorEvent:
   db.execute("UPDATE nodes SET status = 'error' WHERE node_id = ?", ("3a7f2b1c9e0d4f8a",))
   ```
   These status updates are what the LSP server reads when generating code lenses — `agent.to_code_lens()` shows the current status icon.

10. **Completion**: `AgentCompleteEvent` is appended. The `nodes` table row is updated. Other agents subscribed to this agent's completion are triggered.

### Evolution: Dynamic Subscriptions

During a later turn, the `get_user` agent realizes it depends on the `User` class definition. It calls the `subscribe` tool:

```json
{
    "event_types": ["ContentChangedEvent"],
    "path_glob": "src/myapp/models.py"
}
```

Now subscription 3 is registered:

```sql
INSERT INTO subscriptions (agent_id, pattern_json, is_default)
VALUES ('3a7f2b1c9e0d4f8a',
        '{"event_types": ["ContentChangedEvent"], "path_glob": "src/myapp/models.py"}',
        0);
```

If someone modifies the `User` model in `models.py`, the `get_user` agent will be triggered — even though `models.py` isn't its own source file. The agent has evolved its awareness.

### Death: Code Removal

The developer deletes the `get_user` function. On the next discovery pass:

1. The `CSTNode` for `get_user` is no longer in the results
2. The reconciler detects the missing agent, emits a `NodeRemovedEvent`
3. The projection processes the removal:
   ```python
   # Remove subscriptions
   db.execute("DELETE FROM subscriptions WHERE agent_id = ?", ("3a7f2b1c9e0d4f8a",))
   # Remove from nodes table
   db.execute("DELETE FROM nodes WHERE node_id = ?", ("3a7f2b1c9e0d4f8a",))
   ```
4. The EventLog retains all historical events for this agent — they're immutable. The agent is gone from the live swarm but its history is auditable.
5. Any agent that had a subscription to events from `3a7f2b1c9e0d4f8a` will simply stop matching — the source agent no longer emits events

---

## 6. Perspective 5: The Environment

The environment perspective shows the observable output of a running swarm. Let's walk through a concrete, detailed example: **spawning a Python library from minimal input**.

### Scenario

A developer creates a new project and wants Remora to scaffold a Python library for handling configuration files. They provide a single description file:

```markdown
<!-- src/SPEC.md -->
# Config Library

A Python library for reading, validating, and merging configuration files.

## Requirements
- Support YAML, TOML, and JSON formats
- Schema validation using JSON Schema
- Deep merge of multiple config sources
- Environment variable interpolation
- Type-safe access with dot notation
```

The swarm's job is to react to this spec and generate a complete library: directory structure, interfaces, implementations, tests, and documentation.

### Agent Types in This Swarm

The developer has configured these bundles:

#### 1. Scaffold Agent

```yaml
# agents/scaffold/bundle.yaml
name: scaffold-agent
version: "1.0"

system_prompt: |
  You are a project scaffolding agent. When triggered by a new spec file
  or a section describing requirements, analyze the requirements and
  generate the project directory structure.

  Output a plan of files to create, then use the write_file tool to
  create each file with appropriate boilerplate (empty functions with
  docstrings, __init__.py exports, etc).

  Follow Python best practices:
  - src/ layout with proper packaging
  - Separate modules for distinct concerns
  - __init__.py with __all__ exports
  - py.typed marker for type checking

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 8
```

Subscription (configured via extension config, see [Section 1.7](#17-the-agentnode-model)):
```python
SubscriptionPattern(
    event_types=["ContentChangedEvent", "FileSavedEvent"],
    path_glob="src/SPEC.md"
)
```

#### 2. Interface Agent

```yaml
# agents/interface/bundle.yaml
name: interface-agent
version: "1.0"

system_prompt: |
  You are an interface design agent. When triggered by a scaffold agent's
  completion or by changes to a module file, examine the file and generate
  proper type signatures, protocols, and abstract base classes.

  Your goal is to define the public API of each module before implementation.
  Use typing module fully: generics, protocols, TypeVar, overloads.

  Do NOT implement function bodies. Write signatures with docstrings only.
  Use `...` or `raise NotImplementedError()` as placeholders.

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 6
```

Subscription:
```python
SubscriptionPattern(
    event_types=["AgentCompleteEvent"],
    tags=["scaffold"]
)
```

#### 3. Implementation Agent

```yaml
# agents/implementation/bundle.yaml
name: implementation-agent
version: "1.0"

system_prompt: |
  You are an implementation agent. When triggered, you receive a Python
  file with function signatures and docstrings but no implementations.
  Your job is to implement every function body.

  Read the existing signatures carefully. Do not change the API.
  Use the read_file tool to check imports and dependencies.
  Write clean, well-documented code.

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 8
```

Subscription:
```python
SubscriptionPattern(
    event_types=["AgentCompleteEvent"],
    tags=["interface"]
)
```

#### 4. Test Agent

```yaml
# agents/test_gen/bundle.yaml
name: test-generation-agent
version: "1.0"

system_prompt: |
  You are a test generation agent. When triggered by implementation
  completion, read the implemented module and generate comprehensive
  pytest tests.

  For each public function and class:
  - Happy path tests
  - Edge cases (empty input, None, boundary values)
  - Error cases (invalid input, missing files)
  - Integration tests where modules interact

  Use pytest fixtures, parametrize where appropriate.
  Place tests in tests/ mirroring the src/ structure.

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 10
```

Subscription:
```python
SubscriptionPattern(
    event_types=["AgentCompleteEvent"],
    tags=["implementation"]
)
```

#### 5. Validation Agent

```yaml
# agents/validation/bundle.yaml
name: validation-agent
version: "1.0"

system_prompt: |
  You are a validation agent. When triggered by test generation,
  run the test suite and analyze results.

  If tests fail:
  - Identify the root cause
  - Send a message to the implementation agent with the failure details
  - Include the specific test name, error message, and your analysis

  If tests pass:
  - Send a message to the docs agent to generate documentation
  - Report the success summary

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 6
```

Subscription:
```python
SubscriptionPattern(
    event_types=["AgentCompleteEvent"],
    tags=["test"]
)
```

#### 6. Docs Agent

```yaml
# agents/docs/bundle.yaml
name: documentation-agent
version: "1.0"

system_prompt: |
  You are a documentation agent. When triggered by validation success,
  generate or update documentation:

  - Module-level docstrings
  - README.md with usage examples
  - API reference in docs/api.md
  - CHANGELOG.md entry

  Read the implemented code and tests to understand behavior.
  Write docs that match what the code actually does.

model:
  id: Qwen/Qwen3-4B

agents_dir: tools
max_turns: 6
```

Subscription:
```python
SubscriptionPattern(
    event_types=["AgentMessageEvent"],
    tags=["validation-passed"]
)
```

### The `remora.yaml` for This Swarm

```yaml
discovery_paths:
  - src/

bundle_root: agents
bundle_mapping:
  function: implementation
  method: implementation
  class: interface
  file: scaffold
  section: scaffold

model_base_url: http://localhost:8000/v1
model_default: Qwen/Qwen3-4B

swarm_root: .remora
max_concurrency: 4
max_turns: 8
max_trigger_depth: 8        # deeper chain for scaffold→interface→impl→test→validate→docs
trigger_cooldown_ms: 500     # faster reactions for automated flow
```

### The Event Chain

Here's what happens when the developer saves `src/SPEC.md`:

```
T=0ms    FileSavedEvent(path="src/SPEC.md")
         → subscription match: scaffold agent (path_glob="src/SPEC.md")

T=50ms   AgentStartEvent(agent_id="scaffold_1")
         Scaffold agent reads SPEC.md, plans structure, starts writing files:

T=200ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/__init__.py", ...})
T=250ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/loader.py", ...})
T=300ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/schema.py", ...})
T=350ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/merge.py", ...})
T=400ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/interpolate.py", ...})
T=450ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/accessor.py", ...})

T=500ms  AgentCompleteEvent(agent_id="scaffold_1", tags=["scaffold"])
         → subscription match: interface agent (event_types=["AgentCompleteEvent"], tags=["scaffold"])

T=550ms  AgentStartEvent(agent_id="interface_1")
         Interface agent reads each scaffolded file, writes type signatures:

T=800ms  ToolCallEvent(tool="write_file", args={path: "src/configlib/loader.py", content: "def load(...) -> Config: ..."})
         ...for each module...

T=1200ms AgentCompleteEvent(agent_id="interface_1", tags=["interface"])
         → subscription match: implementation agent (tags=["interface"])

T=1250ms AgentStartEvent(agent_id="impl_1")
         Implementation agent reads interfaces, writes function bodies:

T=2500ms AgentCompleteEvent(agent_id="impl_1", tags=["implementation"])
         → subscription match: test agent (tags=["implementation"])

T=2550ms AgentStartEvent(agent_id="test_1")
         Test agent reads implementations, generates pytest files:

T=4000ms AgentCompleteEvent(agent_id="test_1", tags=["test"])
         → subscription match: validation agent (tags=["test"])

T=4050ms AgentStartEvent(agent_id="validate_1")
         Validation agent runs `pytest`, analyzes results:

         Option A: Tests pass →
T=4500ms    AgentMessageEvent(from="validate_1", to="docs_1", content="All 47 tests passed", tags=["validation-passed"])
            → subscription match: docs agent
T=4550ms    AgentStartEvent(agent_id="docs_1")
T=5500ms    AgentCompleteEvent(agent_id="docs_1", tags=["docs"])
            → Chain complete.

         Option B: Tests fail →
T=4500ms    AgentMessageEvent(from="validate_1", to="impl_1", content="3 tests failed: test_merge_nested...")
            → subscription match: implementation agent (to_agent=self)
T=4550ms    AgentStartEvent(agent_id="impl_1")
            → Implementation agent fixes the code
T=5500ms    AgentCompleteEvent(agent_id="impl_1", tags=["implementation"])
            → Test agent triggers again...
            → Retry loop until tests pass or depth limit reached
```

### What the Developer Sees

In Neovim, the developer saves `src/SPEC.md` and watches the sidebar:

```
[12:00:01] scaffold_1: Reading spec... planning 6 files
[12:00:01] scaffold_1: Writing src/configlib/__init__.py
[12:00:01] scaffold_1: Writing src/configlib/loader.py
[12:00:01] scaffold_1: Writing src/configlib/schema.py
[12:00:01] scaffold_1: Writing src/configlib/merge.py
[12:00:01] scaffold_1: Writing src/configlib/interpolate.py
[12:00:01] scaffold_1: Writing src/configlib/accessor.py
[12:00:01] scaffold_1: ✓ Complete — 6 files created

[12:00:02] interface_1: Designing interfaces for 6 modules
[12:00:02] interface_1: loader.py — 3 functions, 1 protocol
[12:00:02] interface_1: schema.py — 2 classes, 4 functions
[12:00:03] interface_1: ✓ Complete — 18 signatures defined

[12:00:03] impl_1: Implementing loader.py (3 functions)
[12:00:04] impl_1: Implementing schema.py (4 functions)
[12:00:06] impl_1: ✓ Complete — all functions implemented

[12:00:06] test_1: Generating tests for 6 modules
[12:00:09] test_1: ✓ Complete — 47 tests in 6 files

[12:00:09] validate_1: Running pytest...
[12:00:11] validate_1: ✓ All 47 tests passed
[12:00:11] validate_1: Notifying docs agent

[12:00:11] docs_1: Generating documentation
[12:00:13] docs_1: ✓ README.md, API reference, CHANGELOG updated
```

The entire chain — from spec to documented, tested library — happened automatically. The developer wrote one markdown file.

### What the EventLog Contains

After the chain completes, the EventLog contains roughly:

- 1 `FileSavedEvent`
- 6 `AgentStartEvent` + 6 `AgentCompleteEvent`
- ~30 `ToolCallEvent` + `ToolResultEvent` pairs (file writes, test runs)
- ~12 `ModelRequestEvent` + `ModelResponseEvent` pairs (LLM turns)
- 2-3 `AgentMessageEvent` (validation → docs, or validation → impl for retries)
- ~60 `KernelStartEvent`/`KernelEndEvent`/`TurnCompleteEvent`

Every single event is queryable, auditable, and replayable. You can reconstruct exactly what happened, in what order, and why.

### What the AgentNode Instances Look Like

Every agent in the chain above is an `AgentNode` instance with different field values. Here's what three key agents look like at the moment they're triggered — same type, different data:

**The spec file agent** — a file-level `AgentNode` with the `TemplateScaffold` extension. This is the agent attached to `src/SPEC.md` (a `file`-type node):

```python
AgentNode(
    node_id="f1a2b3c4d5e6f7a8",
    node_type="file",
    name="SPEC.md",
    full_name="file:SPEC.md",
    file_path="src/SPEC.md",
    start_line=1,
    end_line=12,
    source_code="# Config Library\n\nA Python library for reading...",
    source_hash="b2e4f6...",
    parent_id=None,
    caller_ids=[],
    callee_ids=[],
    status="idle",
    extension_name="TemplateScaffold",
    custom_system_prompt="You are a Jinja2 template file that generates source code...",
    extra_tools=[ToolSchema(name="render_template", ...), ToolSchema(name="read_spec", ...)],
    extra_subscriptions=[
        SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/SPEC.md"),
    ],
)
```

**A scaffolded function agent** — after the scaffold agent creates `src/configlib/loader.py`, discovery runs on the new file and finds `load_config()`. The function is plain — no extension matches:

```python
AgentNode(
    node_id="a8b9c0d1e2f3a4b5",
    node_type="function",
    name="load_config",
    full_name="function:load_config",
    file_path="src/configlib/loader.py",
    start_line=8,
    end_line=22,
    source_code="def load_config(path: str) -> Config:\n    ...",
    source_hash="c3d5e7...",
    parent_id="d6e7f8a9b0c1d2e3",  # the file-level agent for loader.py
    caller_ids=[],
    callee_ids=["e4f5a6b7c8d9e0f1"],  # calls validate_schema
    status="idle",
    extension_name=None,              # no extension matched
    custom_system_prompt="",          # plain agent, bundle prompt only
    extra_tools=[],
    extra_subscriptions=[],
)
```

**A test function agent** — after the test agent creates `tests/test_loader.py`, discovery finds `test_load_yaml()`. The `TestFunction` extension matches:

```python
AgentNode(
    node_id="b0c1d2e3f4a5b6c7",
    node_type="function",
    name="test_load_yaml",
    full_name="function:test_load_yaml",
    file_path="tests/test_loader.py",
    start_line=15,
    end_line=28,
    source_code="def test_load_yaml(tmp_path):\n    ...",
    source_hash="d4e6f8...",
    parent_id="c2d3e4f5a6b7c8d9",  # the file-level agent for test_loader.py
    caller_ids=[],
    callee_ids=["a8b9c0d1e2f3a4b5"],  # calls load_config (the function under test)
    status="idle",
    extension_name="TestFunction",
    custom_system_prompt="You are a test function. Your job is to verify the correctness of the code under test...",
    extra_tools=[ToolSchema(name="run_test", description="Run this specific test with pytest", ...)],
    extra_subscriptions=[
        SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/*.py"),
    ],
)
```

Same `AgentNode` class. Same `nodes` table. Same `.from_row()` and `.to_system_prompt()` methods. The test agent has a `run_test` tool and watches source changes. The plain function agent has neither. The file agent has `render_template` and watches spec changes. All differences are in the data.

### Jinja Template Bootstrapping in the Chain

The scenario above used a spec file and procedural agents. Here's how the same chain works with **Jinja templates** as the scaffolding mechanism instead.

The developer places template files in `.remora/templates/`:

```jinja2
{# .remora/templates/module.py.j2 #}
"""{{ module_doc }}"""
from __future__ import annotations

{% for import in imports %}
from {{ import.module }} import {{ import.names | join(", ") }}
{% endfor %}

{% for func in functions %}
def {{ func.name }}({{ func.params }}) -> {{ func.return_type }}:
    """{{ func.doc }}"""
    ...

{% endfor %}
```

When the scaffold agent creates files, instead of writing raw Python, it calls `render_template`:

```
T=200ms  ToolCallEvent(tool="render_template", args={
    template: ".remora/templates/module.py.j2",
    output_path: "src/configlib/loader.py",
    context: {
        module_doc: "Configuration file loading utilities.",
        imports: [{module: "pathlib", names: ["Path"]}, {module: "typing", names: ["Any"]}],
        functions: [
            {name: "load_config", params: "path: str | Path", return_type: "Config", doc: "Load and parse a config file."},
            {name: "detect_format", params: "path: str | Path", return_type: "str", doc: "Detect config file format from extension."},
            {name: "load_yaml", params: "stream: IO[bytes]", return_type: "dict[str, Any]", doc: "Parse YAML content."},
        ]
    }
})
```

The template's own `AgentNode` (with `extension_name="JinjaTemplate"`) monitors for spec changes and re-renders when needed. The rendered `.py` files are then discovered normally — each function gets its own `AgentNode`, the interface/implementation/test chain proceeds as before.

### Directory Nodes Coordinating Structure

As the scaffold agent creates files, discovery also produces **directory-level agents**. The `__init__.py` files in `src/configlib/` get file-type `CSTNode`s that match the `DirectoryManager` extension:

```python
AgentNode(
    node_id="e5f6a7b8c9d0e1f2",
    node_type="file",
    name="__init__.py",
    full_name="file:__init__.py",
    file_path="src/configlib/__init__.py",
    start_line=1,
    end_line=8,
    source_code='"""configlib — Configuration file handling."""\nfrom .loader import load_config\n...',
    source_hash="f5a7b9...",
    parent_id=None,
    status="idle",
    extension_name="DirectoryManager",
    custom_system_prompt="You represent a directory in the project. You are aware of all files in your directory and their agents...",
    mounted_workspaces=["src/configlib/"],
    extra_tools=[
        ToolSchema(name="list_directory", ...),
        ToolSchema(name="create_file", ...),
    ],
    extra_subscriptions=[
        SubscriptionPattern(event_types=["FileSavedEvent"]),
        SubscriptionPattern(event_types=["AgentCompleteEvent"], tags=["scaffold"]),
    ],
)
```

This directory agent watches for `FileSavedEvent`s. As the scaffold, interface, and implementation agents create and modify files in `src/configlib/`, the directory agent is triggered. It updates `__init__.py`'s `__all__` list and re-export statements to keep the package interface consistent — without any other agent needing to coordinate with it explicitly. The reactive loop handles the coordination through events.

---

## 7. LSP Integration

Remora connects to Neovim as an LSP (Language Server Protocol) server using `pygls`. The LSP layer translates between editor interactions and the EventBased architecture.

For the full LSP protocol specification — including request/response formats, notification types, capability declarations, and Neovim client configuration — see `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`.

Here is a summary of how LSP features map to the EventBased architecture:

| LSP Feature | Editor Interaction | EventBased Mechanism |
|-------------|-------------------|---------------------|
| **Code Lens** | Inline agent status above functions/classes | Query `nodes` table → `AgentNode.from_row()` → `.to_code_lens()` |
| **Hover** | Hover on identifier shows agent info | Query `nodes` table → `AgentNode.from_row()` → `.to_hover(recent_events)` |
| **Code Actions** | Quick-fix menu with agent actions | Query `nodes` table → `AgentNode.from_row()` → `.to_code_actions()` |
| **Diagnostics** | Warning squiggles for agent proposals | Agent produces `RewriteProposal` → converted to LSP diagnostic with code action to apply |
| **Did Save** | File save notification | Emit `FileSavedEvent` + `ContentChangedEvent` to EventLog |
| **Did Change** | Live editing notifications | Debounced; used for incremental tree-sitter re-parsing |
| **Custom: Cursor** | Cursor position tracking | Debounced (200ms stable) → cursor focus event to EventLog |
| **SSE (Server-Sent Events)** | Nui sidebar real-time updates | In-process subscriber on EventLog → SSE stream via Starlette adapter |

### The LSP ↔ AgentNode Bridge

The `AgentNode` model (see [Section 1.7](#17-the-agentnode-model)) serves as the direct bridge between the `nodes` table and LSP JSON-RPC responses. There is no intermediate model — the LSP server hydrates `AgentNode` instances and calls their conversion methods:

```python
# Inside the LSP server — textDocument/codeLens handler
def handle_code_lens(params: lsp.CodeLensParams) -> list[lsp.CodeLens]:
    file_path = uri_to_path(params.text_document.uri)
    rows = db.execute(
        "SELECT * FROM nodes WHERE file_path = ? ORDER BY start_line",
        (file_path,)
    ).fetchall()

    return [AgentNode.from_row(row).to_code_lens() for row in rows]
```

```python
# textDocument/hover handler
def handle_hover(params: lsp.HoverParams) -> lsp.Hover | None:
    file_path = uri_to_path(params.text_document.uri)
    line = params.position.line + 1  # LSP is 0-based, nodes are 1-based

    row = db.execute(
        "SELECT * FROM nodes WHERE file_path = ? AND start_line <= ? AND end_line >= ?",
        (file_path, line, line)
    ).fetchone()
    if row is None:
        return None

    agent = AgentNode.from_row(row)

    # Fetch recent events for this agent from the EventLog
    recent = db.execute(
        "SELECT * FROM events WHERE json_extract(payload, '$.agent_id') = ? "
        "ORDER BY id DESC LIMIT 10",
        (agent.node_id,)
    ).fetchall()

    return agent.to_hover(recent_events=recent)
```

```python
# textDocument/codeAction handler
def handle_code_actions(params: lsp.CodeActionParams) -> list[lsp.CodeAction]:
    file_path = uri_to_path(params.text_document.uri)
    start_line = params.range.start.line + 1
    end_line = params.range.end.line + 1

    rows = db.execute(
        "SELECT * FROM nodes WHERE file_path = ? AND start_line <= ? AND end_line >= ?",
        (file_path, end_line, start_line)
    ).fetchall()

    actions = []
    for row in rows:
        agent = AgentNode.from_row(row)
        actions.extend(agent.to_code_actions())
    return actions
```

The pattern is consistent: **query nodes table → hydrate AgentNode → call conversion method**. Extension-provided tools appear as additional code actions automatically — if an agent has `extra_tools` (e.g., a `TestFunction` agent has `run_test`), those tools show up in the code action menu via `agent.to_code_actions()` without any LSP-specific configuration.

`RewriteProposal` remains a separate data structure carried in events — it's not part of `AgentNode` because proposals are transient (they exist until accepted or dismissed), while `AgentNode` represents the persistent state of the agent.

---

## 8. Future: Custom CSTNode Types

The current system discovers nodes with generic types (`function`, `class`, `file`, `section`, `table`) and uses extension configs (see [Section 1.7](#17-the-agentnode-model)) for behavioral specialization via data. This works but has limitations:

1. **No semantic awareness at discovery time** — a Python function that's a Flask route handler and a plain utility function are both `node_type="function"`. Extension configs differentiate them using name-based heuristics (`name.startswith("get_")`) which is fragile.

2. **No cross-language node types** — a TOML table defining database config and a Python class implementing database access are unrelated in the current model, even though they're semantically linked.

3. **No custom tree-sitter queries** — developers can't define new node types without modifying Remora's query files.

### Aspirational: Developer-Defined Node Types

The future architecture allows developers to define custom node types with semantic meaning, while preserving the data-driven `AgentNode` model.

**Custom query packs** in `.remora/queries/`:

```scheme
;; .remora/queries/python/flask_routes/route.scm
;; Capture Flask route decorators and their functions
(decorated_definition
  (decorator
    (call
      function: (attribute
        object: (identifier) @_app
        attribute: (identifier) @_method)
      (#match? @_app "app|blueprint")
      (#match? @_method "route|get|post|put|delete")))
  definition: (function_definition
    name: (identifier) @route.name)
  ) @route.def
```

This would discover `node_type="route"` nodes — Flask route handlers get their own node type, which feeds into both `bundle_mapping` and extension config matching.

**Richer extension configs via custom discovery.** With custom tree-sitter queries producing richer `CSTNode` data, extension configs can move beyond name heuristics. The `NodeDiscoveredEvent` carries the full tree-sitter capture data, so extensions can match on structural patterns:

```python
# .remora/models/flask_route.py
class FlaskRouteExtension(AgentExtension):
    """Specializes agents for Flask route handlers discovered via custom query pack."""

    @staticmethod
    def matches(node_type: str, name: str, **metadata) -> bool:
        # With custom queries, node_type is "route" — no name heuristics needed
        return node_type == "route"

    @staticmethod
    def get_extension_data(**metadata) -> dict:
        # metadata comes from tree-sitter captures: http_method, url_pattern, etc.
        http_method = metadata.get("http_method", "GET")
        url_pattern = metadata.get("url_pattern", "/")
        return {
            "extension_name": "FlaskRoute",
            "custom_system_prompt": (
                f"You are a Flask {http_method} route handler for `{url_pattern}`. "
                "You handle HTTP requests, validate input, execute business logic, "
                "and return responses. When your implementation changes, verify that "
                "error responses follow the project's error schema."
            ),
            "extra_tools": [
                ToolSchema(
                    name="test_endpoint",
                    description=f"Send a test {http_method} request to {url_pattern}",
                    parameters={
                        "type": "object",
                        "properties": {
                            "body": {"type": "object"},
                            "headers": {"type": "object"},
                        },
                    },
                ),
            ],
            "extra_subscriptions": [
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/**/models.py"),
                SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="**/openapi.yaml"),
            ],
        }
```

The result is still an `AgentNode` — same model, same table, same conversion methods. But the `custom_system_prompt` is richer because the extension has structural metadata from tree-sitter, not just name patterns.

**Semantic links across languages:**

```python
# Future: Cross-language node relationships stored in edges table
# Discovered from TOML config + Python source by custom query packs
EdgeType.CONFIGURES: ("toml:table:database", "python:class:DatabasePool")
EdgeType.IMPLEMENTS: ("python:function:get_user", "python:class:UserProtocol")
EdgeType.TESTS: ("python:function:test_get_user", "python:function:get_user")
```

These semantic relationships would be stored in the `edges` table (via LazyGraph/rustworkx) and populated into `AgentNode.caller_ids` / `AgentNode.callee_ids` by the projection. Agents would see their cross-language dependencies in their graph context, enabling richer coordination — a database config table agent could notify the connection pool class agent when credentials change.

**Per-type subscription defaults:**

```yaml
# Future remora.yaml extension
subscription_defaults:
  route:
    - event_types: [ContentChangedEvent]
      path_glob: "src/**/*.py"
    - event_types: [AgentCompleteEvent]
      from_types: [test]          # react when tests complete
    - event_types: [ContentChangedEvent]
      path_glob: "config/*.toml"  # react when config changes
  
  test:
    - event_types: [AgentCompleteEvent]
      from_types: [function, class, route]  # react when implementations change
```

These defaults would be merged with extension-provided `extra_subscriptions`, giving three layers of subscription configuration: per-type defaults (from `remora.yaml`), extension-provided (from `AgentExtension.get_extension_data()`), and runtime dynamic (from agent `subscribe` tool calls).

The key insight is that **custom node types enrich the data flowing through the same architecture**. Discovery produces richer `CSTNode`s, projections write richer `nodes` table rows, and `AgentNode.from_row()` hydrates richer instances. But the model, the table, the conversion methods, and the reactive loop are all unchanged. Extensibility is additive, not structural.

---

*This document describes the architecture as designed. For implementation status and task breakdown, see `docs/plans/2026-03-01-architectural-unification.md`. For detailed design decisions and rationale, see `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md`. For the full LSP protocol specification, see `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`.*
