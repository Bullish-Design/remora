# Architecture

> How Remora works internally: the reactive loop, data model, and component interactions.

## Table of Contents

1. [System Overview](#system-overview) -- The major components and how they connect
2. [Discovery](#discovery) -- Tree-sitter parsing and node identification
3. [The AgentNode Model](#the-agentnode-model) -- The universal data model for all agents
4. [EventStore](#eventstore) -- The append-only event log and single source of truth
5. [Events and the Reactive Loop](#events-and-the-reactive-loop) -- How events drive agent behavior
6. [Subscriptions](#subscriptions) -- How agents register interest in specific events
7. [Reconciliation](#reconciliation) -- Syncing discovered code with known agents
8. [Agent Execution](#agent-execution) -- How an agent turn runs (SwarmExecutor + Kernel)
9. [Extensions](#extensions) -- Data-driven specialization of agents
10. [Tools](#tools) -- Grail scripts and the tool protocol
11. [The LSP Layer](#the-lsp-layer) -- How Remora integrates with Neovim
12. [Data Flow Diagram](#data-flow-diagram) -- End-to-end flow from edit to agent reaction

---

## System Overview

Remora has three layers:

```
+---------------------------+
|   Editor (Neovim + LSP)   |  <-- User interaction: lenses, hover, chat, proposals
+---------------------------+
|   Reactive Core           |  <-- EventStore, EventBus, Subscriptions, Runner
+---------------------------+
|   Discovery + Execution   |  <-- Tree-sitter parsing, SwarmExecutor, LLM kernel
+---------------------------+
```

**Editor layer**: The `RemoraLanguageServer` (pygls-based) provides LSP features. It communicates with Neovim through the standard LSP protocol and with the core through the EventStore and RemoraDB.

**Reactive core**: The `EventStore` is an append-only SQLite log of all events. The `NodeProjection` materializes events into a `nodes` table for fast queries. The `EventBus` provides in-memory pub/sub for real-time delivery. The `AgentRunner` polls the trigger queue and dispatches agent turns.

**Discovery and execution**: The `ASTWatcher` uses tree-sitter to parse files and emit `CSTNode` structures. The `SwarmExecutor` runs individual agent turns by building prompts, discovering tools, and calling the LLM via `AgentKernel`.

### Key Design Principles

- **EventStore is the single source of truth.** Every state change is an event. The `nodes` table is a read-optimized projection, not an independent store.
- **AgentNode is the single data model.** There are no subclasses. Specialization is data-driven through extensions.
- **No global mutable state.** Components communicate through events and explicit dependency injection.

## Discovery

Discovery is the process of parsing source files to identify code nodes that become agents.

### How It Works

1. The `ASTWatcher` receives a file path and its content.
2. It selects a tree-sitter parser based on the file extension (`.py` -> Python, `.md` -> Markdown, `.toml` -> TOML).
3. It loads `.scm` query files from `src/remora/queries/<language>/remora_core/`. Each query file targets a specific node type.
4. Tree-sitter runs the queries against the parsed AST and returns matches.
5. Each match becomes a `CSTNode` with: `node_id`, `node_type`, `name`, `full_name`, `file_path`, `text`, `start_line`, `end_line`, `start_byte`, `end_byte`.

### Built-in Node Types

**Python** (`src/remora/queries/python/remora_core/`):
- `function.scm` -- top-level functions and methods
- `class.scm` -- class definitions
- `file.scm` -- whole-file nodes

**Markdown** (`src/remora/queries/markdown/remora_core/`):
- `section.scm` -- headings and their content
- `todo.scm` -- checkbox items (`- [ ] ...` and `- [x] ...`)
- `frontmatter.scm` -- YAML frontmatter blocks
- `file.scm` -- whole-file nodes

**TOML** (`src/remora/queries/toml/remora_core/`):
- `table.scm` -- top-level tables and subtables
- `file.scm` -- whole-file nodes

### Node Identity

Each node gets a deterministic `node_id` based on its file path and structural position. The `full_name` includes the file path prefix (e.g., `src/utils.py::calculate_total`). This identity is stable across edits as long as the node's name and file don't change.

## The AgentNode Model

`AgentNode` is a Pydantic `BaseModel` representing any agent. It has ~20 fields:

**Identity** (from CSTNode via event projection):

| Field | Type | Purpose |
|-------|------|---------|
| `node_id` | `str` | Unique identifier (hash of file path + name + type) |
| `node_type` | `str` | `function`, `class`, `method`, `file`, `section`, `todo`, `table` |
| `name` | `str` | Short name (e.g., `calculate_total`) |
| `full_name` | `str` | Qualified name (e.g., `src/utils.py::calculate_total`) |
| `file_path` | `str` | Absolute path to source file |
| `source_code` | `str` | The node's source text |
| `source_hash` | `str` | Hash of the source text (for change detection) |
| `start_line` / `end_line` | `int` | Line range in the file |
| `start_byte` / `end_byte` | `int` | Byte range in the file |

**Graph context** (from edges table):

| Field | Type | Purpose |
|-------|------|---------|
| `parent_id` | `str \| None` | ID of containing node (e.g., file for a function) |
| `caller_ids` | `list[str]` | IDs of nodes that call this one |
| `callee_ids` | `list[str]` | IDs of nodes this one calls |

**Runtime state** (from event projections):

| Field | Type | Purpose |
|-------|------|---------|
| `status` | `str` | `idle`, `running`, `pending_approval`, `error` |
| `last_trigger_event` | `str` | ID of the event that last triggered this agent |
| `last_completed_at` | `float \| None` | Timestamp of last completed execution |

**Specialization** (from extension config matching):

| Field | Type | Purpose |
|-------|------|---------|
| `extension_name` | `str \| None` | Name of the matched extension |
| `custom_system_prompt` | `str` | Custom system prompt (from extension) |
| `mounted_workspaces` | `list[str]` | Workspace paths available to this agent |
| `extra_tools` | `list[ToolSchema]` | Additional tools (from extension) |
| `extra_subscriptions` | `list[SubscriptionPattern]` | Event subscriptions (from extension) |

AgentNode provides rendering methods used by the LSP layer:
- `to_code_lens()` -- generates code lens annotations
- `to_hover()` -- generates hover information
- `to_code_actions()` -- generates available code actions
- `to_document_symbol()` -- generates document outline entries
- `to_system_prompt()` -- generates the agent's system prompt for LLM calls

## EventStore

The EventStore is an append-only SQLite database at `.remora/events/events.db`. It stores every event that occurs in the system.

### Tables

- **`events`** -- the append-only event log. Columns: `id`, `graph_id`, `event_type`, `payload` (JSON), `timestamp`, `created_at`, `from_agent`, `to_agent`, `correlation_id`, `tags`.
- **`nodes`** -- a materialized projection of the current agent state. Updated automatically when `NodeDiscoveredEvent` or `NodeRemovedEvent` events are appended. This is a read-optimized view, not an independent store.

### Key Operations

- **`append(graph_id, event)`** -- writes an event and triggers projection updates + subscription matching.
- **`get_node(node_id)`** -- reads an agent from the `nodes` projection.
- **`list_nodes()`** -- lists all known agents.
- **`get_recent_events(agent_id, limit)`** -- retrieves recent events for an agent (used for chat history).

### The Projection

`NodeProjection` listens for `NodeDiscoveredEvent` and `NodeRemovedEvent`. On discovery, it upserts a row into the `nodes` table with all `AgentNode` fields serialized. On removal, it deletes the row. This means the `nodes` table always reflects the current state of the codebase, derived from the event log.

## Events and the Reactive Loop

Events are frozen Pydantic models. The main event types:

| Event | When It Fires |
|-------|---------------|
| `NodeDiscoveredEvent` | A new or changed node is found during reconciliation |
| `NodeRemovedEvent` | A previously-known node is no longer found |
| `ContentChangedEvent` | A file's content changed (from editor save or external edit) |
| `AgentMessageEvent` | One agent sends a message to another |
| `ScaffoldRequestEvent` | An agent requests creation of a new scaffold node |

**Kernel-level events** (emitted during LLM turns):
- `KernelStartEvent`, `KernelEndEvent`
- `ModelRequestEvent`, `ModelResponseEvent`
- `ToolCallEvent`, `ToolResultEvent`
- `TurnCompleteEvent`

### The Reactive Loop

1. An event is appended to the EventStore.
2. The EventStore checks all registered subscriptions for matches.
3. Matching subscriptions produce trigger entries in the trigger queue.
4. The `AgentRunner` polls the trigger queue and dispatches agent turns.
5. Each agent turn may produce new events (messages, tool calls, content changes).
6. Those events re-enter step 1, creating a cascade.

Safety mechanisms prevent runaway cascades:
- **`max_trigger_depth`** (default: 5) -- limits how deep a cascade can go.
- **`trigger_cooldown_ms`** (default: 1000) -- minimum delay between triggers for the same agent.
- **`max_concurrency`** (default: 4) -- limits parallel agent executions.

## Subscriptions

A subscription is a pattern that an agent registers to express interest in certain events. The `SubscriptionRegistry` stores subscriptions in the `subscriptions` table within the EventStore database (`.remora/events/events.db`). In shared mode (the default), it reuses the EventStore's SQLite connection.

Subscriptions match on:
- **Event type** (e.g., `ContentChangedEvent`)
- **Source agent** (e.g., "any function in `utils.py`")
- **Tags** and other metadata

Agents can register subscriptions at runtime via the `subscribe` tool, or have them configured statically through extensions.

When an event is appended to the EventStore, the subscription index performs O(1) lookups to find matching subscriptions and enqueues agent triggers.

## Reconciliation

Reconciliation syncs the discovered code structure with the EventStore's known agents.

1. Run tree-sitter discovery across all configured `discovery_paths`.
2. Compare discovered nodes against existing nodes in the EventStore.
3. For new nodes: emit `NodeDiscoveredEvent` (which the projection materializes into a `nodes` row).
4. For removed nodes: emit `NodeRemovedEvent` (which the projection deletes from `nodes`).
5. For changed nodes (same identity, different content): emit a new `NodeDiscoveredEvent` which upserts the row.

Reconciliation runs:
- At startup (`remora swarm start` or `remora swarm reconcile`)
- When a file is saved (the LSP `textDocument/didSave` handler triggers re-parsing of that file)

## Agent Execution

When an agent is triggered, the `SwarmExecutor` runs a single turn:

1. **Resolve bundle** -- look up the `bundle_mapping` in `remora.yaml` to find the agent's bundle directory based on `node_type`.
2. **Load manifest** -- parse `bundle.yaml` for system prompt, model settings, tool config, and grammar config.
3. **Resolve model** -- check `bundle.yaml` for a model override (`model.id`, `model.name`, or `model.model`), fall back to `config.model_default`.
4. **Build prompt** -- construct a markdown prompt containing:
   - The agent's identity (full name, file, line range)
   - The agent's source code
   - The trigger event (type and content)
   - Recent chat history (last N messages)
   - Scaffold context (for scaffold nodes: parent source, siblings, intent)
5. **Discover tools** -- load Grail `.pym` scripts from the bundle's `agents_dir`.
6. **Create kernel** -- instantiate an `AgentKernel` with the resolved model, tools, observer, and connection-pooled HTTP client.
7. **Run** -- send the system prompt + chat history + user prompt to the kernel. The kernel runs up to `max_turns` iterations of LLM call -> tool execution -> response.
8. **Return result** -- extract the final response text, truncate to `truncation_limit`, and return it.

### Connection Pooling

The `SwarmExecutor` creates a single HTTP client at initialization and reuses it for all agent turns. This avoids the overhead of establishing a new connection for every LLM call.

## Extensions

Extensions specialize agents without subclassing `AgentNode`. They live in `.remora/models/*.py` and are Python classes that subclass `AgentExtension`.

```python
# .remora/models/00_todo_tracker.py
from remora.extensions import AgentExtension

class TodoTracker(AgentExtension):
    @staticmethod
    def matches(node_type, name, *, file_path="", source_code=""):
        return node_type == "todo"

    @staticmethod
    def get_extension_data():
        return {
            "system_prompt": "You are a TODO item tracker. Monitor completion status.",
            "tags": ("todo", "tracking"),
        }
```

### How Extensions Are Applied

1. During reconciliation, after a node is discovered, Remora loads extensions from `.remora/models/`.
2. Extensions are sorted alphabetically by filename. **First match wins** -- so you control priority via naming (e.g., `00_specific.py` before `50_generic.py`).
3. The matching extension's `get_extension_data()` return value is merged into the `AgentNode` fields.
4. Extensions are cached with mtime-based invalidation, so editing an extension file takes effect on the next reconciliation.

### The `matches()` API

```python
@staticmethod
def matches(
    node_type: str,    # "function", "class", "file", "section", "todo", etc.
    name: str,         # Short name of the node
    *,
    file_path: str = "",     # Absolute path to the file
    source_code: str = "",   # The node's source text
) -> bool:
```

This allows matching on any combination of node type, name patterns, file paths, or even source code content.

## Tools

Agents can call tools during their LLM turns. Tools follow the `Tool` protocol from `structured-agents`:

```python
class Tool(Protocol):
    @property
    def schema(self) -> ToolSchema: ...

    async def execute(self, arguments: dict, context: ToolCall | None) -> ToolResult: ...
```

### Grail Tools

The primary way to define tools is through Grail `.pym` scripts. These are Python-like scripts that declare inputs and produce outputs:

```python
# agents/my_bundle/tools/add_numbers.pym
from grail import Input

a: int = Input("a", description="First number")
b: int = Input("b", description="Second number")

result = {"sum": a + b, "a": a, "b": b}
result
```

Grail tools are discovered automatically from the bundle's `agents_dir`. Each `.pym` file becomes a tool with a schema derived from its `Input` declarations. The script's final expression is the tool's return value.

### Built-in Agent Tools

Beyond Grail scripts, agents have access to context-dependent tools:

**Swarm tools** (from `remora.core.tools.swarm`):
- **`send_message`** -- send a message to a specific agent
- **`subscribe`** -- register a subscription to future events
- **`unsubscribe`** -- remove a subscription
- **`broadcast`** -- send a message to children, siblings, or file-scoped agents
- **`query_agents`** -- list agents filtered by node type

**LSP tools** (from `remora.core.tools.lsp`):
- **`rewrite_self`** -- propose a rewrite of the agent's own source code
- **`message_node`** -- send a message to another agent (with LSP context)
- **`read_node`** -- read another agent's source code

**Other tools**:
- **`spawn_child`** -- create a new child node under this agent

These are wired through the `AgentContext` passed to the executor.

## Workspaces

### CairnWorkspaceService (`remora.core.cairn_bridge`)

Manages stable and per-agent workspaces backed by Cairn (AgentFS):

- **Stable workspace**: `.remora/stable.db` -- a synced snapshot of the project files, used as the base layer.
- **Agent workspaces**: `.remora/agents/<id>/workspace.db` -- per-agent copy-on-write workspaces layered on top of the stable workspace.

This provides isolation: each agent can read/write files without affecting the project or other agents. Changes can be reviewed and merged back via proposals.

## The LSP Layer

The `RemoraLanguageServer` (based on pygls) provides:

- **`textDocument/codeLens`** -- shows agent status above each node
- **`textDocument/hover`** -- shows agent metadata, tools, and subscriptions
- **`textDocument/codeAction`** -- provides chat and rewrite actions
- **`workspace/executeCommand`** -- handles chat requests, proposal accept/reject
- **`textDocument/didOpen`** / **`textDocument/didSave`** -- triggers re-parsing and reconciliation

The LSP server holds references to the `EventStore` and `SubscriptionRegistry` and operates on the same SQLite databases as the headless swarm.

### RemoraDB

`RemoraDB` manages LSP-specific operational tables. In the default shared mode, these tables live in the same `events.db` database (created by `EventStore.initialize()`). It can also operate standalone with its own SQLite file for backward compatibility.

The operational tables:
- **`edges`** -- relationships between nodes (parent-child, imports, calls)
- **`proposals`** -- pending rewrite proposals
- **`cursor_focus`** -- current editor cursor position
- **`command_queue`** -- pending LSP commands
- **`activation_chain`** -- cascade tracking for visualization

These tables are logically separate from the EventStore's event log and node projection, keeping LSP concerns distinct even though they share a database connection.

## Data Flow Diagram

Here is the end-to-end flow from a code edit to an agent reaction:

```
User edits code in Neovim
        |
        v
LSP receives textDocument/didSave
        |
        v
ASTWatcher re-parses the file (tree-sitter)
        |
        v
Reconciler compares discovered nodes with EventStore
        |
        v
NodeDiscoveredEvent emitted for changed nodes
        |
        v
EventStore.append() writes event + updates NodeProjection
        |
        v
SubscriptionRegistry checks for matching subscriptions
        |
        v
Matching agents are enqueued in the trigger queue
        |
        v
AgentRunner picks up triggers (respecting concurrency limits)
        |
        v
SwarmExecutor.run_agent() for each triggered agent:
  1. Resolve bundle + load manifest
  2. Build prompt (identity + source + trigger + history)
  3. Discover Grail tools
  4. Create AgentKernel with model config
  5. kernel.run() -> LLM call -> tool execution -> response
        |
        v
Agent response may:
  - Emit new events (AgentMessageEvent, ContentChangedEvent)
  - Propose rewrites (shown as diagnostics in Neovim)
  - Subscribe to future events
  - Broadcast to other agents
        |
        v
New events re-enter the loop (cascade, up to max_trigger_depth)
```
