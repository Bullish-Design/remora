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

Events are frozen Python dataclasses. They carry the minimum data needed to describe what happened. There are four categories:

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

### 1.5 The Reactive Loop

The reactive loop is the heartbeat of the swarm. It connects events to agents:

```
1. Something happens (file save, cursor move, agent message, kernel event)
2. An event is appended to the EventLog
3. Subscription matching runs: for each subscription in the registry,
   check if the new event matches
4. For each matching agent_id, a trigger is enqueued
5. AgentRunner picks up the trigger (respecting concurrency semaphore)
6. AgentRunner loads the agent's AgentState from JSONL
7. SwarmExecutor resolves the bundle (via bundle_mapping[node_type])
8. SwarmExecutor loads the structured-agents manifest
9. SwarmExecutor builds the prompt:
   - Target info (agent name, file, line range)
   - Code context (from workspace/cairn)
   - Trigger event details (type + content)
   - Recent chat history (last 5 entries)
10. SwarmExecutor discovers Grail tools (.pym scripts) + swarm tools
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
│   ├── models/                  # ExtensionNode definitions
│   │   └── review_node.py       # Custom node behavior
│   ├── agents/                  # AgentState JSONL files
│   │   ├── a1b2c3d4.jsonl
│   │   └── e5f6a7b8.jsonl
│   └── db/                      # SQLite databases
│       └── remora.db
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

### Writing Extension Nodes: `.remora/models/`

Extension nodes customize agent behavior for specific code patterns. They are Pydantic models placed in `.remora/models/`:

```python
# .remora/models/review_node.py
from remora.lsp.extensions import ExtensionNode
from remora.lsp.models import ToolSchema


class ReviewFunctionNode(ExtensionNode):
    """Custom behavior for functions with 'review' in their docstring."""

    @classmethod
    def matches(cls, node_type: str, name: str) -> bool:
        return node_type == "function" and "review" in name.lower()

    @property
    def system_prompt(self) -> str:
        return (
            "This function is marked for review. Your primary job is to "
            "analyze it for correctness, performance, and style issues. "
            "Produce a structured review with severity ratings."
        )

    def get_tool_schemas(self) -> list[ToolSchema]:
        return [
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
        ]
```

Extension nodes are loaded from disk on demand with mtime-based caching. The `matches()` classmethod determines which discovered nodes get this extended behavior. When a match is found, the extension's `system_prompt` is appended to the bundle's system prompt, and its tool schemas are added to the agent's tool set.

### The Developer's Mental Model

As a developer, you think in terms of:

1. **Discovery** — what code elements will tree-sitter find?
2. **Mapping** — which bundle handles each node type?
3. **Behavior** — what does the system prompt tell the agent to do?
4. **Tools** — what can the agent actually do? (Grail scripts + swarm tools)
5. **Extensions** — do any specific code patterns need special behavior?
6. **Subscriptions** — what events should agents react to? (defaults + custom)

You don't manage individual agents. You don't start or stop them. You define the rules, and the swarm instantiates and runs agents automatically based on what it discovers in the codebase.

---

## 4. Perspective 3: The Agent

An agent is an autonomous participant in the swarm. It has an identity (derived from a CSTNode), behavior (defined by a bundle), memory (AgentState with chat history), and awareness (subscriptions). It communicates by emitting events and reacts by consuming them.

### Agent Identity

Every agent's identity comes from a discovered `CSTNode`. The mapping is:

```
Source code element → tree-sitter → CSTNode → AgentState → Agent
```

The `agent_id` is the `CSTNode.node_id` — a deterministic hash of the file path, name, start line, and end line. This means:

- The same function always gets the same agent ID (stable identity)
- Renaming a function creates a new agent (new identity)
- Moving code within a file may create a new agent (line numbers change)
- Reconciliation handles the transition when identities change

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
    → Resolves children from SwarmState
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

The `ExtensionNode` system adds a second layer of specialization. After discovery, extension nodes loaded from `.remora/models/` are checked: if `ExtensionNode.matches(node_type, name)` returns `True`, the extension's system prompt and tools are merged into the agent's configuration.

This two-layer system (tree-sitter queries for structural discovery + extension nodes for behavioral specialization) is sufficient for many use cases but has limitations — see [Section 8: Future](#8-future-custom-cstnode-types).

---

## 5. Perspective 4: The Node

A node is a specific instance of a CSTNode — one particular function in one particular file, living through its lifecycle in the swarm. Let's follow a single node from birth to action.

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

### Identity Assignment

The reconciler compares discovered nodes against existing `AgentState` records. This is a new node, so it creates:

```
AgentState(
    agent_id="3a7f2b1c9e0d4f8a",
    node_type="function",
    name="get_user",
    full_name="function:get_user",
    file_path="src/myapp/api.py",
    parent_id="b8c9d0e1f2a3b4c5",  # the class or file containing this function
    range=(15, 28),
    connections={},
    chat_history=[],
    custom_subscriptions=[],
    last_updated=1709337600.0
)
```

This state is persisted to `.remora/agents/3a7f2b1c9e0d4f8a.jsonl`.

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

1. **Load state**: Reads `.remora/agents/3a7f2b1c9e0d4f8a.jsonl` (last line)
2. **Resolve bundle**: `bundle_mapping["function"]` → `agents/python_function/`
3. **Load manifest**: Reads `agents/python_function/bundle.yaml`
4. **Build workspace**: Cairn workspace service loads file contents
5. **Build prompt**:

````
# Target: function:get_user
File: src/myapp/api.py
Lines: 15-28

## Code
```python
def get_user(user_id: int) -> User:
    """Fetch a user by ID from the database."""
    try:
        row = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    except DatabaseError as e:
    ...
```

## Trigger Event
Type: ContentChangedEvent
Content: @@ -20,1 +20,3 @@ ...
````

6. **Discover tools**: Grail scripts from `agents/python_function/tools/` + 5 swarm tools
7. **Run kernel**: AgentKernel sends system prompt + history + prompt to LLM

The LLM might respond:

> "The function now has a try/except for DatabaseError but the except clause is empty. I should add proper error handling."

And then call the `write_file` tool to add a `raise` or `logging.error()` in the except block.

8. **Kernel events flow**: During this LLM turn, `ModelRequestEvent`, `ModelResponseEvent`, `ToolCallEvent` (for `write_file`), and `ToolResultEvent` are all appended to the EventLog. Any agent subscribed to these events will be triggered.

9. **Completion**: `AgentCompleteEvent` is appended. Chat history is updated. State is saved.

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
2. The reconciler detects the missing agent
3. All subscriptions for `3a7f2b1c9e0d4f8a` are removed
4. The `AgentState` JSONL file is archived or deleted
5. The agent is gone from the swarm

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

Subscription (configured via reconciler or extension node):
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

---

## 7. LSP Integration

Remora connects to Neovim as an LSP (Language Server Protocol) server using `pygls`. The LSP layer translates between editor interactions and the EventBased architecture.

For the full LSP protocol specification — including request/response formats, notification types, capability declarations, and Neovim client configuration — see `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`.

Here is a summary of how LSP features map to the EventBased architecture:

| LSP Feature | Editor Interaction | EventBased Mechanism |
|-------------|-------------------|---------------------|
| **Code Lens** | Inline agent status above functions/classes | Query `nodes` table for agents, show status from last `AgentCompleteEvent` or `AgentStartEvent` |
| **Hover** | Hover on identifier shows agent info | Query `AgentState` + last N events for that agent from EventLog |
| **Code Actions** | Quick-fix menu with agent actions | Emit `ManualTriggerEvent` → agent runs → proposals stored → presented as code actions |
| **Diagnostics** | Warning squiggles for agent proposals | Agent produces `RewriteProposal` → converted to LSP diagnostic with code action to apply |
| **Did Save** | File save notification | Emit `FileSavedEvent` + `ContentChangedEvent` to EventLog |
| **Did Change** | Live editing notifications | Debounced; used for incremental tree-sitter re-parsing |
| **Custom: Cursor** | Cursor position tracking | Debounced (200ms stable) → cursor focus event to EventLog |
| **SSE (Server-Sent Events)** | Nui sidebar real-time updates | In-process subscriber on EventLog → SSE stream via Starlette adapter |

The Pydantic models in `remora.lsp.models` serve as the bridge: `ASTAgentNode` represents an agent in LSP responses, `RewriteProposal` carries proposed code changes, and event wrapper classes handle serialization between the core frozen dataclasses and LSP JSON-RPC.

---

## 8. Future: Custom CSTNode Types

The current system discovers nodes with generic types (`function`, `class`, `file`, `section`, `table`) and uses `ExtensionNode.matches()` for behavioral specialization. This works but has limitations:

1. **No semantic awareness** — a Python function that's a Flask route handler and a plain utility function are both `node_type="function"`. The developer must use `ExtensionNode.matches()` with name-based heuristics to differentiate.

2. **No cross-language node types** — a TOML table defining database config and a Python class implementing database access are unrelated in the current model, even though they're semantically linked.

3. **No custom tree-sitter queries** — developers can't define new node types without modifying Remora's query files.

### Aspirational: Developer-Defined Node Types

The future architecture allows developers to define custom node types with semantic meaning:

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

This would discover `node_type="route"` nodes — Flask route handlers get their own agent type, their own bundle, their own behavior.

**Custom CSTNode subtypes** with typed metadata:

```python
# Future API (aspirational)
@dataclass(frozen=True, slots=True)
class RouteCSTNode(CSTNode):
    """A Flask route handler with HTTP method metadata."""
    http_method: str      # "GET", "POST", etc.
    url_pattern: str      # "/users/<int:id>"
    auth_required: bool   # parsed from decorators
```

**Semantic links across languages:**

```python
# Future: Cross-language node relationships
# Discovered from TOML config + Python source
EdgeType.CONFIGURES: ("toml:table:database", "python:class:DatabasePool")
EdgeType.IMPLEMENTS: ("python:function:get_user", "python:class:UserProtocol")
EdgeType.TESTS: ("python:function:test_get_user", "python:function:get_user")
```

These semantic relationships would be stored in the `edges` table (via LazyGraph/rustworkx) and available to agents via the `query_agents` tool, enabling agents to understand not just *what* code exists but *how* it relates.

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

The key insight is that **node types are the junction between discovery and behavior**. Richer node types mean agents can be more specialized, more aware of their context, and more precisely subscribed to the events that matter to them. The EventBased architecture supports this naturally — more node types just mean more entries in `bundle_mapping` and more specific subscription patterns.

---

*This document describes the architecture as designed. For implementation status and task breakdown, see `docs/plans/2026-03-01-architectural-unification.md`. For detailed design decisions and rationale, see `docs/plans/EVENT_ARCHITECTURE_ALIGNMENT.md`. For the full LSP protocol specification, see `NEOVIM_DEMO_V21_FINAL_CONCEPT.md`.*
