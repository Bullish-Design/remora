# Companion Refactor Concept: Node-Resident Agents

**Status:** Concept / Design Doc
**Replaces:** `GUIDE_COMPANION.md` (integration approach)
**No backwards compatibility target.**

---

## Table of Contents

1. [The Paradigm Shift](#1-the-paradigm-shift) — from global pipeline to node-resident agents
2. [Cairn as Required Infrastructure](#2-cairn-as-required-infrastructure) — Cairn is the foundation, not an option
3. [The NodeAgent Model](#3-the-nodeagent-model) — what a node-resident agent is and owns
4. [Node Workspace Layout](#4-node-workspace-layout) — what lives inside each node's Cairn workspace
5. [Chat Refactored as One Input Channel](#5-chat-refactored-as-one-input-channel) — message → agent → swarms
6. [MicroSwarms: Knowledge Organization](#6-microswarms-knowledge-organization) — automatic post-exchange processing
7. [User Interaction POV](#7-user-interaction-pov) — what the experience looks like end to end
8. [Cross-Node Linking](#8-cross-node-linking) — how agents reference each other's workspaces
9. [New Architecture Sketch](#9-new-architecture-sketch) — components, responsibilities, event flow
10. [What Gets Deleted vs. Kept](#10-what-gets-deleted-vs-kept) — clean break inventory
11. [LSP Integration Changes](#11-lsp-integration-changes) — protocol surface changes
12. [Opportunities Unlocked](#12-opportunities-unlocked) — what this makes possible

---

## 1. The Paradigm Shift

### Current Model (Global Pipeline)

```
Cursor moves anywhere in any file
    ↓
CompanionDispatcher (one global instance)
    ↓
ContextExtractorHandler → TaskInferrerHandler → SidebarComposerHandler
    ↓
Sidebar shows "what's at cursor" — ephemeral, stateless
```

The current companion is a **signal processing pipeline**. It reacts to cursor position, extracts context, runs analysis, composes a sidebar. When you move your cursor, the previous context is thrown away. Nothing persists. There is no memory. The companion knows nothing about this function from last week's session.

### New Model (Node-Resident Agents)

```
Cursor moves to `process_items()` in payments.py
    ↓
NodeAgentRouter resolves "process_items" → loads NodeAgent(node_id="payments.process_items")
    ↓
NodeAgent wakes from its Cairn workspace (notes, history, links — all still there)
    ↓
Sidebar shows THIS function's accumulated knowledge: past conversations, notes, connections
    ↓
User types a message → NodeAgent responds → MicroSwarms run to organize the exchange
    ↓
Knowledge accumulates in Cairn — persists forever across sessions
```

The new companion is a **network of persistent agents**, one per CST node. Each function, class, method, and file section has its own agent that **remembers everything**. Moving your cursor is navigating a living knowledge graph.

### The Core Invariant

> Every CST node is an `AgentNode`. Every `AgentNode` has a Cairn workspace. That workspace is the canonical, persistent memory for everything ever known about that node.

---

## 2. Cairn as Required Infrastructure

Cairn is no longer an optional enhancement. It is the storage backbone of the entire companion system.

### Why Required

The companion's value proposition changes completely with persistence. Without Cairn:
- Each session starts from scratch
- Notes exist nowhere
- Chat history is lost
- Node connections are re-discovered every time
- The sidebar is a momentary display, not a knowledge store

With Cairn as required:
- First visit to a function: fresh workspace, agent introduces itself
- Hundredth visit: full history, notes, recommendations, known tests, linked docs

### Initialization (Required at Startup)

```python
# In src/remora/lsp/__main__.py — Cairn required, no cairn_service=None fallback

from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.config import Config
from remora.companion.node_agent_registry import NodeAgentRegistry

async def _prepare():
    root = Path.cwd()
    swarm_path = root / ".remora"

    config = Config(bundle_root=str(swarm_path), ...)
    cairn_service = CairnWorkspaceService(config, project_root=root)
    await cairn_service.initialize(sync_mode=SyncMode.FULL)

    event_bus = EventBus()
    event_store = EventStore(swarm_path / "events" / "events.db")
    await event_store.initialize()
    event_store.set_event_bus(event_bus)

    registry = NodeAgentRegistry(cairn_service, event_store, event_bus)
    await registry.start()

    return event_store, subscriptions, event_bus, registry
```

### Per-Node Workspace Path Convention

```
.remora/
  nodes/
    ab/
      ab3f7c92d1.../    ← first 2 chars of node_id = sharding
        workspace.db    ← node's Cairn workspace
    e9/
      e9a12f...
        workspace.db
```

The node_id is already stable (derived from file path + node name in `AgentNode`). Cairn workspace paths are deterministic and survive restarts.

---

## 3. The NodeAgent Model

A `NodeAgent` is an `AgentNode` that is **alive** — it has a loaded Cairn workspace, an active conversation context, and can receive messages.

```python
class NodeAgent:
    """
    A persistent, per-CST-node agent.

    Identity comes from AgentNode (node_id, file_path, node_type, etc).
    Memory lives in a Cairn workspace keyed by node_id.
    Receives messages, triggers MicroSwarms, composes its own sidebar.
    """

    node: AgentNode                    # identity + graph context
    workspace: AgentWorkspace          # Cairn workspace (persistent)
    _history: list[NodeMessage]        # in-memory cache of recent exchanges
    _last_visited: float               # for LRU eviction from registry
    _status: Literal["idle", "active", "processing"]
```

### Lifecycle

```
CSTNode discovered by discovery module
    ↓
AgentNode row written to DB (existing behavior)
    ↓
On first cursor focus: NodeAgentRegistry.get_or_create(node_id)
    ↓
NodeAgent instantiated, Cairn workspace opened
    ↓
NodeAgent loads persisted state from workspace (notes, history index)
    ↓
NodeAgent responds to events: cursor_focus, message, file_saved
    ↓
On eviction from registry (LRU): workspace flushed, agent GC'd
    ↓
On next visit: re-instantiated from same workspace — nothing lost
```

### What a NodeAgent Does

| Trigger | What NodeAgent Does |
|---------|---------------------|
| `CursorFocusEvent` | Refreshes context, composes sidebar, marks `_last_visited` |
| `ContentChangedEvent` (this node's file) | Summarizes edits, updates workspace `edits/` log |
| `FileSavedEvent` (this node's file) | Re-indexes node content, checks if node boundaries changed |
| User message (`NodeMessage`) | Runs agent response, triggers MicroSwarms |
| `NodeMessageEvent` (from another agent) | Processes inter-agent message, writes to `inbox/` |

---

## 4. Node Workspace Layout

Every node's Cairn workspace follows this convention. All paths are relative within the workspace.

```
workspace.db (Cairn AgentFS virtual filesystem)
│
├── meta.json                   ← node_id, node_type, name, file_path, first_seen
│
├── notes/
│   ├── user_notes.md           ← user-written notes about this node
│   └── agent_notes.md          ← agent's own observations and recommendations
│
├── chat/
│   ├── index.json              ← [{id, timestamp, summary, tags, turn_count}]
│   └── {session_id}.md         ← full conversation for that session
│
├── guides/
│   ├── understanding.md        ← agent-authored "what this node does and why"
│   ├── refactoring.md          ← agent-authored refactoring recommendations
│   └── pitfalls.md             ← known gotchas, edge cases, failure modes
│
├── links/
│   └── links.json              ← [{target_node_id, relationship, note, confidence}]
│
├── scripts/
│   └── {name}.py               ← agent-created utility scripts/tools for this node
│
├── context/
│   ├── latest_extraction.json  ← cached CompanionContextExtracted payload
│   └── source_snapshot.md      ← most recent source code snapshot
│
└── inbox/
    └── {from_node_id}_{ts}.md  ← inter-agent messages from other NodeAgents
```

### Workspace Conventions

- `meta.json` is written on first creation, updated when node boundaries change.
- `chat/index.json` is the searchable index — full conversations are in separate files (lazy-loaded).
- `links/links.json` is append-only during a session; de-duped on write.
- `guides/` files are always agent-generated, never user-written (there are `notes/` for that).
- `scripts/` stores executable artifacts the agent creates for this node's context.

---

## 5. Chat Refactored as One Input Channel

### Current Architecture

`ChatSession` is a standalone object with its own `CairnWorkspaceService`, its own tool set, its own history list. It is completely disconnected from the companion pipeline.

### New Architecture

Chat is `NodeAgent.send(message: str) -> NodeAgentResponse`. That's it.

The `NodeAgent` owns:
- The conversation history (loaded from `chat/` in its workspace)
- The system prompt (generated from `AgentNode.to_system_prompt()` + workspace context)
- The tool set (workspace file ops + inter-agent messaging + project search)

```python
class NodeAgent:
    async def send(self, content: str) -> NodeAgentResponse:
        """Accept a user message. Respond. Trigger MicroSwarms."""

        user_msg = NodeMessage.user(content)
        self._history.append(user_msg)

        # Build system prompt from live AgentNode state + workspace notes
        system = self._build_system_prompt()

        # Run LLM with workspace-aware tools
        result = await self._kernel.run(system, self._history, self._tools)

        assistant_msg = NodeMessage.assistant(result.content)
        self._history.append(assistant_msg)

        # Persist exchange to workspace
        await self._persist_exchange(user_msg, assistant_msg)

        # Dispatch MicroSwarms (async, non-blocking)
        asyncio.create_task(self._run_post_exchange_swarms(user_msg, assistant_msg))

        return NodeAgentResponse(message=assistant_msg)
```

### System Prompt Construction

The node's system prompt is assembled from three sources:

1. **Identity layer** — from `AgentNode.to_system_prompt()` (already implemented): node_id, source code, callers/callees, node_type.
2. **Memory layer** — loaded from workspace: `notes/agent_notes.md`, recent chat summaries from `chat/index.json`, linked node names from `links/links.json`.
3. **Context layer** — latest `context/latest_extraction.json` if fresh (< 30s).

This means the agent's first response in a new session is already informed by everything from previous sessions.

### Tool Set for NodeAgent

| Tool | What it does |
|------|-------------|
| `read_workspace_file(path)` | Read any file in this node's workspace |
| `write_workspace_file(path, content)` | Write to this node's workspace (notes, guides, scripts) |
| `list_workspace(path)` | Browse workspace directory |
| `message_node(node_id, message)` | Send a message to another node's agent |
| `read_node_workspace(node_id, path)` | Read a file from another node's workspace (read-only) |
| `search_project(query)` | Search project files via vector index |
| `get_node_info(node_id)` | Get AgentNode metadata for any node in the graph |
| `find_linked_nodes(relationship)` | Get nodes linked with a given relationship type |
| `create_script(name, content)` | Save a script to `scripts/` in this workspace |

---

## 6. MicroSwarms: Knowledge Organization

After every agent exchange (user message + agent response), a set of small, focused micro-swarms runs asynchronously. These are lightweight: single-turn LLM calls with narrow prompts. They write their outputs directly into the node's Cairn workspace.

### MicroSwarm Pipeline

```
NodeAgent.send() completes
    ↓
asyncio.create_task(_run_post_exchange_swarms(user_msg, assistant_msg))
    ↓
┌─────────────────────────────────────────────────────┐
│  Parallel MicroSwarm execution:                     │
│                                                     │
│  SummarizerSwarm                                    │
│  ├── input: (user_msg, assistant_msg, node context) │
│  └── output: chat/index.json entry (summary, tags)  │
│                                                     │
│  CategorizerSwarm                                   │
│  ├── input: (user_msg, assistant_msg)               │
│  └── output: tags added to chat/index.json          │
│       e.g. ["bug", "edge_case", "refactor_needed"]  │
│                                                     │
│  LinkerSwarm                                        │
│  ├── input: (exchange, node source, node graph)     │
│  └── output: new entries in links/links.json        │
│       e.g. {target: "test_process_items",           │
│              relationship: "tested_by",             │
│              note: "mentioned in exchange"}         │
│                                                     │
│  ReflectionSwarm                                    │
│  ├── input: (exchange, existing agent_notes.md)     │
│  └── output: appends insight to notes/agent_notes.md│
│       (only if exchange revealed something new)     │
└─────────────────────────────────────────────────────┘
    ↓
NodeAgent re-composes sidebar → push $/remora/companionSidebarUpdated
```

### MicroSwarm Design Principles

- Each swarm is a **single async function** that takes a context dict and returns nothing (writes to workspace).
- Swarms **never block** the user-facing response path.
- Swarms run **in parallel** via `asyncio.gather()`.
- A swarm that fails logs and exits — no retry, no crash.
- Swarms are **idempotent**: running twice on the same exchange produces the same output.

### MicroSwarm Event Model

Each swarm emits a typed event to the EventBus when it completes:

```python
class NodeAgentExchangeIndexed(_FrozenEvent):
    node_id: str
    session_id: str
    summary: str
    tags: tuple[str, ...]
    timestamp: float

class NodeAgentLinkDiscovered(_FrozenEvent):
    source_node_id: str
    target_node_id: str
    relationship: str
    confidence: float
    timestamp: float

class NodeAgentNoteUpdated(_FrozenEvent):
    node_id: str
    note_type: str     # "agent_notes" | "guide" | "pitfall"
    timestamp: float
```

These events are observable — the LSP server can push sidebar updates in response to any of them.

---

## 7. User Interaction POV

### Session Start: Opening a File

User opens `src/remora/runner/agent_runner.py` in Neovim.

- Remora LSP discovers (or loads from DB) all CST nodes in this file.
- No agents are instantiated yet — lazy loading.
- Sidebar shows project-level context.

### Cursor Navigation: First Visit to a Function

User places cursor inside `async def run_agent(...)`.

```
Sidebar updates to show:

# run_agent
src/remora/runner/agent_runner.py:45-112

*First visit. I'm the agent for this function.*

## Notes
(no notes yet)

## Connections
(none discovered yet)

## Source
```python
async def run_agent(node: AgentNode, ...):
    ...
```

---
*Say something to start a conversation.*
```

### Cursor Navigation: Returning to a Known Function

Same user, two weeks later, cursor on `async def run_agent(...)` again.

```
Sidebar updates to show:

# run_agent
src/remora/runner/agent_runner.py:45-112

*Last visited 14 days ago. 3 conversations.*

## Agent Notes
- This function owns the agent execution loop. The `max_turns` guard
  has triggered 2 known infinite-loop scenarios (see chat 2026-02-21).
- Refactoring opportunity: the retry logic in lines 78-95 could be
  extracted to a shared utility (noted 2026-02-28).

## Connections
- ← called by: `service/api.py:handle_rewrite_request` (calls)
- → calls: `kernel_factory.create_kernel` (calls)
- test: `tests/unit/test_agent_runner.py:test_run_agent_timeout` (tested_by)
- doc: `docs/architecture.md#agent-execution` (documented_by)

## Recent Conversation (2026-02-28)
> You: "why does this sometimes loop forever?"
> Agent: "The `max_turns` guard is checked after each tool call, but
>   if a tool call raises and is swallowed, the turn counter isn't..."
```

### Chat Interaction

User types: "Can you write a script that logs every time this function starts and exits?"

```
Agent responds:
"Sure. I'll write that to scripts/trace_run_agent.py in my workspace..."

[Agent writes the script using write_workspace_file tool]

Background (invisible to user, swarms run):
  SummarizerSwarm → adds to chat/index.json:
    {summary: "User asked for a tracing script; agent created scripts/trace_run_agent.py", tags: ["tooling", "debugging"]}
  ReflectionSwarm → appends to notes/agent_notes.md:
    "User is debugging execution flow; tracing interest suggests a reliability concern."
  LinkerSwarm → no new links found in this exchange
```

Sidebar auto-updates 2 seconds later:

```
## Scripts
- trace_run_agent.py (created just now)

## Agent Notes
- ...
- User is debugging execution flow; tracing interest suggests reliability concern.
```

### Inter-Agent Messaging

User asks `run_agent`'s agent: "Who tests you?"

Agent uses `find_linked_nodes(relationship="tested_by")` → finds `test_run_agent_timeout`.

Agent can then use `read_node_workspace("test_run_agent_timeout", "notes/agent_notes.md")` to read what the test node's agent knows.

Agent responds: "Your test node at `tests/unit/test_agent_runner.py:test_run_agent_timeout` knows about you. Here's what it says about itself..."

---

## 8. Cross-Node Linking

### Link Types

| Relationship | Direction | Example |
|-------------|-----------|---------|
| `calls` | A → B | `run_agent` → `create_kernel` |
| `called_by` | B ← A | `create_kernel` ← `run_agent` |
| `tested_by` | function → test | `run_agent` → `test_run_agent_timeout` |
| `tests` | test → function | `test_run_agent_timeout` → `run_agent` |
| `documented_by` | code → doc | `run_agent` → `docs/architecture.md#agent-execution` |
| `documents` | doc → code | `docs/architecture.md#...` → `run_agent` |
| `similar_to` | A ↔ B | `run_agent` ↔ `execute_task` (similar pattern) |
| `imported_by` | module → importer | `agent_runner` → `service/api` |
| `imports` | importer → module | `service/api` → `agent_runner` |
| `related_to` | freeform | anything the agent or user creates manually |

### How Links Are Created

1. **Automatic (graph-derived)**: `calls` / `called_by` / `imports` / `imported_by` come from `AgentNode.caller_ids` / `callee_ids` — already in the DB.
2. **Automatic (discovery)**: When a test file is parsed, the `IndexingHandler` can infer `tests` / `tested_by` links from test function names (`test_<function_name>`).
3. **Agent-discovered (MicroSwarms)**: `LinkerSwarm` scans each exchange for mentions of other nodes and suggests links.
4. **Agent-created (tool use)**: The agent can call `link_node(target_id, relationship, note)` during a conversation.
5. **User-created**: The Neovim companion plugin exposes a command `CompanionLink <node_id> <relationship>`.

### Link Storage and Resolution

Links are stored in `links/links.json` within each node's workspace. The `LinksResolver` service (new) aggregates links from all node workspaces to build the global connection graph on demand.

```python
class LinksResolver:
    """Aggregates cross-node links from individual workspace link.json files.
    Not a database — queries workspace files directly. Suitable for sidebar display.
    """

    async def get_links(self, node_id: str) -> list[NodeLink]: ...
    async def get_backlinks(self, node_id: str) -> list[NodeLink]: ...
    async def find_path(self, from_id: str, to_id: str) -> list[str]: ...
```

---

## 9. New Architecture Sketch

### Components

```
src/remora/companion/
├── __init__.py
├── config.py                 ← CompanionConfig (Cairn required, no optional)
├── events.py                 ← NodeAgent event types (replace Companion* events)
│
├── registry.py               ← NodeAgentRegistry (replaces CompanionDispatcher)
├── router.py                 ← NodeAgentRouter (CursorFocusEvent → NodeAgent)
│
├── node_agent.py             ← NodeAgent class (core)
├── node_message.py           ← NodeMessage, NodeAgentResponse types
├── node_workspace.py         ← workspace conventions, layout constants
│
├── swarms/
│   ├── __init__.py
│   ├── base.py               ← MicroSwarm base class / protocol
│   ├── summarizer.py         ← SummarizerSwarm
│   ├── categorizer.py        ← CategorizerSwarm
│   ├── linker.py             ← LinkerSwarm
│   └── reflection.py         ← ReflectionSwarm
│
├── links/
│   ├── __init__.py
│   ├── resolver.py           ← LinksResolver
│   └── types.py              ← NodeLink, LinkRelationship
│
└── sidebar/
    ├── __init__.py
    └── composer.py           ← NodeAgentSidebarComposer (reads workspace, composes markdown)
```

### Event Flow (New)

```
[CursorFocusEvent]
    ↓
NodeAgentRouter.on_cursor_focus(event)
    ↓
NodeAgentRegistry.get_or_create(node_id)  ← lazy-loads from Cairn
    ↓
NodeAgent.on_cursor_focus(event)
    ↓
NodeAgentSidebarComposer.compose(workspace)
    ↓
emit NodeAgentSidebarReady(markdown=..., node_id=...)
    ↓
LSP server pushes $/remora/companionSidebarUpdated

[User message via LSP executeCommand]
    ↓
companion.sendMessage {node_id, content}
    ↓
NodeAgentRegistry.get(node_id).send(content)
    ↓
NodeAgent._kernel.run(system_prompt, history, tools)
    ↓
NodeAgent._persist_exchange(...)
    ↓
asyncio.create_task(NodeAgent._run_swarms(...))   ← non-blocking
    ↓
return NodeAgentResponse → LSP executeCommand response
    (sidebar push follows ~2s later from swarm completion)
```

### NodeAgentRegistry

```python
class NodeAgentRegistry:
    """
    Manages the pool of live NodeAgents.

    - Lazy-loads agents from Cairn on first access.
    - LRU eviction: keeps at most N agents in memory (default 20).
    - Thread-safe (asyncio.Lock per node_id).
    """

    def __init__(self, cairn_service, event_store, event_bus, max_active=20): ...

    async def start(self) -> None:
        """Subscribe to EventBus events."""
        self._bus.subscribe(CursorFocusEvent, self._router.on_cursor_focus)
        self._bus.subscribe(ContentChangedEvent, self._on_content_changed)
        self._bus.subscribe(FileSavedEvent, self._on_file_saved)

    async def get_or_create(self, node_id: str) -> NodeAgent: ...
    async def get(self, node_id: str) -> NodeAgent | None: ...
    async def evict(self, node_id: str) -> None: ...
```

---

## 10. What Gets Deleted vs. Kept

### Delete (No Backwards Compat)

| File | Reason |
|------|--------|
| `companion/dispatcher.py` | Replaced by `NodeAgentRegistry` + `NodeAgentRouter` |
| `companion/state.py` | Each NodeAgent owns its own state |
| `companion/startup.py` | Replaced by `NodeAgentRegistry.start()` |
| `companion/handlers/context_extractor.py` | Merged into `NodeAgent.on_cursor_focus()` |
| `companion/handlers/sidebar_composer.py` | Replaced by `NodeAgentSidebarComposer` |
| `companion/handlers/task_inferrer.py` | Replaced by `ReflectionSwarm` |
| `companion/handlers/claim_checker.py` | Can be a MicroSwarm if needed; not core |
| `companion/handlers/connection_finder.py` | Replaced by `LinkerSwarm` + `LinksResolver` |
| `companion/handlers/search_handler.py` | Merged into NodeAgent tool: `search_project()` |
| `companion/handlers/edit_summarizer.py` | Merged into `NodeAgent.on_content_changed()` |
| `companion/handlers/indexing_handler.py` | Merged into `NodeAgent.on_file_saved()` |
| `companion/handlers/base.py` | Replaced by `NodeAgent` base class |
| `core/agents/chat.py` `ChatSession` | Replaced by `NodeAgent.send()` |
| All `Companion*` event classes in `events.py` | Replaced by `NodeAgent*` events |
| `remora_demo/companion/` (entire directory) | Historical artifact — delete |

### Keep and Evolve

| File | What Changes |
|------|-------------|
| `core/agents/agent_node.py` `AgentNode` | Unchanged — still the identity model |
| `core/agents/cairn_bridge.py` `CairnWorkspaceService` | Unchanged — still the workspace manager |
| `core/agents/workspace.py` `AgentWorkspace` | Unchanged — still the file abstraction |
| `core/events/event_bus.py` | Unchanged |
| `core/events/event_store.py` | Unchanged |
| `core/events/interaction_events.py` | Unchanged (CursorFocusEvent, ContentChangedEvent, FileSavedEvent) |
| `companion/indexing_service.py` | Kept — `NodeAgent` uses it for `search_project()` |
| `companion/config.py` | Rewritten — Cairn required, sidebar_output_path removed |

---

## 11. LSP Integration Changes

### New Commands (workspace/executeCommand)

| Command | Arguments | Returns |
|---------|-----------|---------|
| `companion.getSidebar` | `{}` | `{markdown, node_id, timestamp}` |
| `companion.sendMessage` | `{node_id, content}` | `{message: {role, content}, turn_count}` |
| `companion.getNodeInfo` | `{node_id}` | full workspace meta + links |
| `companion.writeNote` | `{node_id, note}` | `{ok: true}` |
| `companion.getLinks` | `{node_id}` | `[{target_node_id, relationship, note}]` |
| `companion.addLink` | `{source_node_id, target_node_id, relationship, note}` | `{ok: true}` |
| `companion.listHistory` | `{node_id}` | `[{session_id, summary, tags, timestamp}]` |
| `companion.getHistory` | `{node_id, session_id}` | `{markdown: full_conversation}` |

### Server Push Notifications

| Notification | When |
|-------------|------|
| `$/remora/companionSidebarUpdated` | After cursor focus, after message exchange, after any swarm completes |
| `$/remora/companionNodeLinked` | When LinkerSwarm discovers a new cross-node connection |

### Removed

- `companion.getState` — no longer meaningful (state is per-node, in workspace)

---

## 12. Opportunities Unlocked

### Persistent Institutional Memory

Every function, class, and method accumulates knowledge over the project's lifetime. Developers who join the project can browse the companion sidebar on any node and see years of conversations, agent observations, and discovered connections. The codebase becomes self-documenting — not through docstrings, but through a living knowledge layer.

### The Living Documentation Graph

Doc sections can be CST nodes too (Markdown headings are already parsed). When `docs/architecture.md#agent-execution` is a NodeAgent, and `agent_runner.py:run_agent` is a NodeAgent, and they are linked via `documents` / `documented_by` — you get bidirectional navigation. Open the function, see the doc. Open the doc, see the functions it covers.

### Test-Function Symbiosis

Tests are CST nodes. Functions are CST nodes. Auto-linking via naming conventions (`test_process_items` ↔ `process_items`) means every function can immediately navigate to its tests, and vice versa. A function's agent can read its test node's workspace to understand what edge cases are tested.

### Agent-Created Scripts and Tools

The agent can write executable scripts into its workspace. A debugging script for a specific function lives there permanently — not in a scratch file that gets deleted. When the user returns to that function six months later, the script is still there.

### Cross-Agent Collaboration

The `message_node(node_id, message)` tool allows an agent to send a message to any other node's agent. An agent working on a refactor can ask its downstream callee agents for context: "I'm changing my signature — what do you need from me?" The callee agent's response is written to their inbox and visible the next time the user visits that node.

### Searchable Conversation History

Because every exchange is indexed by `SummarizerSwarm` with tags and summaries, a future command — `companion.searchHistory(query)` — can search across all node workspaces for past conversations that match. "When did we talk about the timeout issue?" returns a list of dated exchanges with summaries.

### Knowledge Archaeology

Each node's agent knows the full edit history (via `ContentChangedEvent` summaries) and conversation history. It can answer "how did this function evolve?" by reconstructing a narrative from its workspace.

### Agent Recommendations Without Hallucination

Because the agent's notes (`agent_notes.md`) are explicitly written and confirmed during real conversations — not generated speculatively — they represent ground truth about the node. When the agent recommends a refactoring, it can cite "as I noted on 2026-02-28 after we discussed the timeout issue..."

### Micro-economy of Attention

The registry evicts idle agents from memory. But Cairn workspaces persist. Frequently visited nodes have rich, deep workspaces. Rarely visited nodes have sparse workspaces. This creates a natural signal about where developer attention has been concentrated — potentially surfaceable as a project health metric.

---

*End of concept document.*
*Next step: convert this into a PLAN.md with ordered implementation steps.*
