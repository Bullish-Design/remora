# Remora — LLM Reference

> Dense, machine-optimized reference. Structure: why → theory → concepts → components → API.

## Table of Contents

1. **Why Remora** — Problem statement; what Remora provides; when to use it.
2. **Theory of Operation** — Event-sourced reactive swarm; single source of truth; closed-loop execution.
3. **High-Level Concepts**
   - 3.1 EventStore (append-only SQLite log + projections)
   - 3.2 Discovery (tree-sitter → CSTNode → NodeDiscoveredEvent)
   - 3.3 AgentNode (unified read model: DB row + LLM prompt + LSP)
   - 3.4 Subscriptions (5-dimension pattern matching, default + dynamic)
   - 3.5 Reactive Loop (event → match → trigger → execute → emit)
   - 3.6 Cascade Safety (correlation IDs, depth limits, cooldowns, semaphore)
4. **Detailed Core Components**
   - 4.1 CSTNode — frozen Pydantic model from discovery
   - 4.2 AgentNode — unified agent model with status, extensions, prompts
   - 4.3 Events — all event types (agent lifecycle, human, swarm, node, kernel)
   - 4.4 SubscriptionPattern & SubscriptionRegistry
   - 4.5 Extensions — AgentExtension base class, matching, data injection
   - 4.6 Config — remora.yaml schema, env vars, Pydantic BaseSettings
   - 4.7 EventStore — tables, append/replay, projections, trigger queue
   - 4.8 NodeProjection — event-to-table projection logic
   - 4.9 Reconciler — startup discovery diff, event emission
   - 4.10 Tools — Grail .pym tools, swarm tools, LSP built-in tools, spawn_child
   - 4.11 Workspace — Cairn-backed AgentWorkspace, CairnDataProvider
   - 4.12 SwarmExecutor — single agent turn execution
   - 4.13 AgentRunner — async execution coordinator (LSP + headless modes)
   - 4.14 ChatSession — single-agent chat wrapper
   - 4.15 Bundles — structured-agents manifests
5. **API Reference**
   - 5.1 Public exports (`remora.__init__`)
   - 5.2 Key function signatures
   - 5.3 CLI commands
   - 5.4 Configuration keys (remora.yaml)
   - 5.5 Event type catalog

---

## 1. Why Remora

Remora turns every code node (function, class, method, file, markdown section, todo) into an autonomous AI agent. Each agent has identity (source code, file position), can observe events (file changes, messages from other agents), and can act (rewrite itself, message peers, subscribe to new events). The result is a reactive swarm where code maintains itself: a change to one function can trigger downstream agents to adapt, all mediated through an event-sourced log with human-in-the-loop approval for code edits.

Use Remora when you want: (1) per-node AI agents that understand their own scope and graph context, (2) event-driven reactive code maintenance across a codebase, (3) an LSP server that overlays agent status, proposals, and chat directly in Neovim, or (4) a CLI swarm that runs agent turns in response to file changes and inter-agent messages.

---

## 2. Theory of Operation

**Event sourcing with projections.** All state changes are immutable events appended to a single SQLite database (WAL mode). The `events` table is the append-only log. The `nodes` table is a materialized projection maintained atomically within the same transaction as each event INSERT. There is no separate write model — the EventStore IS the source of truth.

**Reactive closed loop.** The execution cycle is:
1. **Event arrives** (file saved, message sent, manual trigger, node discovered)
2. **EventStore.append()** persists the event and applies projections (updates `nodes` table)
3. **Subscription matching** — SubscriptionRegistry checks all registered patterns against the event
4. **Trigger queue** — matching agent IDs are enqueued as `(agent_id, event_id, event)` tuples
5. **AgentRunner** dequeues triggers, applies cascade safety checks (depth limit, cooldown, semaphore), then executes agent turns via SwarmExecutor (CLI) or LLMClient (LSP)
6. **Agent execution** — the agent sees its source code, graph context, trigger event, and chat history; it can call tools (rewrite_self, message_node, read_node, send_message, subscribe, broadcast, query_agents)
7. **New events emitted** by the agent's actions feed back into step 1

**Discovery → agents.** At startup, `reconcile_on_startup()` runs tree-sitter discovery over configured paths, diffs the results against the existing `nodes` table, and emits NodeDiscoveredEvent (new/changed), NodeRemovedEvent (deleted), and ContentChangedEvent (modified content). Each NodeDiscoveredEvent is projected into the `nodes` table by NodeProjection, which also applies extension matching (first match wins) to inject custom system prompts, extra tools, and extra subscriptions. Default subscriptions are registered for each node: direct messages (to_agent=node_id) and source file changes (ContentChangedEvent for the node's file).

**Two execution modes.** (1) **LSP mode**: AgentRunner with RemoraLanguageServer — agents show as CodeLens in Neovim, edits are proposals requiring human approval, built-in tools are rewrite_self/message_node/read_node. (2) **CLI/headless mode**: AgentRunner.create_headless() + SwarmExecutor — uses structured-agents kernel with Grail .pym tools + 5 built-in swarm tools (send_message, subscribe, unsubscribe, broadcast, query_agents).

---

## 3. High-Level Concepts

### 3.1 EventStore

Single SQLite database (WAL mode, NORMAL synchronous). Contains 8 tables:

| Table | Purpose |
|-------|---------|
| `events` | Append-only event log. Columns: id, graph_id, event_type, payload (JSON), timestamp, created_at, from_agent, to_agent, correlation_id, tags |
| `nodes` | Materialized projection of agent state. Columns: node_id (PK), node_type, name, full_name, file_path, start_line, end_line, start_byte, end_byte, source_code, source_hash, parent_id, caller_ids, callee_ids, status, last_trigger_event, last_completed_at, extension_name, custom_system_prompt, mounted_workspaces, extra_tools, extra_subscriptions |
| `subscriptions` | Agent event subscriptions. Columns: id, agent_id, pattern_json, is_default, created_at, updated_at |
| `edges` | Node graph edges. Columns: from_id, to_id, edge_type (composite PK) |
| `activation_chain` | Cascade tracking. Columns: correlation_id, agent_id, depth, timestamp |
| `proposals` | Rewrite proposals pending approval. Columns: proposal_id (PK), agent_id, old_source, new_source, diff, status, created_at, file_path |
| `cursor_focus` | Editor cursor position (singleton). Columns: id (=1), agent_id, file_path, line, timestamp |
| `command_queue` | Pending commands from UI. Columns: id, command_type, agent_id, payload, status, created_at, processed_at |

Key behavior: `append()` persists event + applies NodeProjection + commits atomically, then asynchronously matches subscriptions and populates trigger queue.

### 3.2 Discovery

Tree-sitter parses source files into CSTNode objects. Pipeline: `discover(paths)` → parallel `_parse_file()` per file → load `.scm` queries from `remora/queries/<language>/remora_core/*.scm` → execute queries → `_collect_captures()` → build CSTNode per capture.

**Supported languages** (by extension): `.py` (python), `.md` (markdown), `.toml`, `.yaml`/`.yml`, `.json`, `.js`, `.ts`, `.go`, `.rs`.

**Node types produced**: `function`, `class`, `method`, `file`, `section`, `heading`, `code_block`, `table`, `note`, `todo`.

**Markdown post-processing**: Files with YAML frontmatter (`---` delimited) produce a `note` CSTNode (or `todo` if `type: todo` in frontmatter). Checkbox items (`- [ ]`, `- [x]`) produce individual `todo` CSTNodes.

**Node ID**: deterministic SHA256 of `file_path:name:start_line:end_line`, truncated to 16 hex chars.

### 3.3 AgentNode

Unified read model — no subclasses. One Pydantic model serves as: DB row (`from_row()`/`to_row()`), LLM system prompt (`to_system_prompt()`), and LSP protocol response (`to_code_lens()`, `to_hover()`, `to_code_actions()`, `to_document_symbol()`).

**Specialization is data, not inheritance.** Extension configs inject `extension_name`, `custom_system_prompt`, `mounted_workspaces`, `extra_tools`, `extra_subscriptions` at projection time and at runtime (re-applied each turn).

**Status values**: `idle`, `running`, `error`, `scaffold`, `pending_approval`.

**Scaffold detection**: NodeProjection checks if source code is a stub (empty, pass-only, `...`-only) and sets status to `scaffold` instead of `idle`.

### 3.4 Subscriptions

`SubscriptionPattern` has 5 optional dimensions:

| Dimension | Type | Semantics |
|-----------|------|-----------|
| `event_types` | `list[str] \| None` | Match if event class name is in list |
| `from_agents` | `list[str] \| None` | Match if event.from_agent is in list |
| `to_agent` | `str \| None` | Match if event.to_agent equals value |
| `path_glob` | `str \| None` | Match if event.path matches glob |
| `tags` | `list[str] \| None` | Match if any event tag is in list |

**Matching logic**: conjunctive across dimensions (all non-None dimensions must match), disjunctive within lists (any value in list matches). `None` = wildcard (matches everything).

**Default subscriptions** (registered per node at reconciliation): (1) direct messages: `SubscriptionPattern(to_agent=node_id)`, (2) source file changes: `SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob=file_path)`.

**Dynamic subscriptions**: agents can add/remove subscriptions at runtime via `subscribe`/`unsubscribe` tools.

**Cache**: SubscriptionRegistry maintains an in-memory cache indexed by event_type for O(1) lookup. Cache invalidated on any mutation (register/unregister).

### 3.5 Reactive Loop

```
Event → EventStore.append()
      → NodeProjection.apply() [in same transaction]
      → commit
      → SubscriptionRegistry.get_matching_agents(event)
      → trigger_queue.put(agent_id, event_id, event) for each match
      → EventBus.emit(event) [for UI updates]

AgentRunner.run_forever()
      → dequeue trigger
      → cascade safety checks (depth, cooldown, semaphore)
      → execute_turn(trigger)
      → LLM call with tools → tool results → repeat up to MAX_TOOL_ROUNDS(5)
      → emitted events feed back into EventStore.append()
```

### 3.6 Cascade Safety

Four mechanisms prevent infinite agent activation loops:

1. **Correlation ID**: every trigger chain shares a correlation_id. All events in a chain can be traced via `get_events_for_correlation()`.
2. **Depth limit**: per `(agent_id, correlation_id)` counter. Checked before each trigger. Default `max_trigger_depth=5` (Config) or `MAX_CHAIN_DEPTH=10` (LSP runner).
3. **Cooldown**: per-agent timestamp tracking. Agent cannot be re-triggered within `trigger_cooldown_ms` (default 1000ms) of last trigger.
4. **Concurrency semaphore**: `asyncio.Semaphore(max_concurrency)` limits parallel agent turns (default 4).

Additionally, DB-backed activation_chain table tracks which agents have been activated in each correlation chain, preventing cycles (same agent_id appearing twice in one chain).

---

## 4. Detailed Core Components

### 4.1 CSTNode

Frozen Pydantic model (`model_config = ConfigDict(frozen=True)`) representing a discovered code element. Defined in `remora.core.discovery`.

| Field | Type | Notes |
|-------|------|-------|
| `node_id` | `str` | SHA256(`file_path:name:start_line:end_line`)[:16] |
| `node_type` | `str` | `function`, `class`, `method`, `file`, `section`, `heading`, `code_block`, `table`, `note`, `todo` |
| `name` | `str` | Extracted from `.name` capture or child identifier node |
| `full_name` | `str` | `"{node_type}:{name}"` |
| `file_path` | `str` | Absolute path to source file |
| `text` | `str` | Raw source text of the node |
| `start_line` | `int` | 1-indexed |
| `end_line` | `int` | 1-indexed |
| `start_byte` | `int` | Byte offset from file start |
| `end_byte` | `int` | Byte offset from file start |

`__hash__` overridden to hash only by `node_id` — two nodes with same ID but different text hash equally.

`compute_node_id(file_path, name, start_line, end_line) -> str` — standalone function for deterministic ID generation.

### 4.2 AgentNode

Unified mutable Pydantic model (`frozen=False`). Serves as DB row, LLM prompt, and LSP protocol response. No subclasses. Defined in `remora.core.agent_node`.

**Identity fields** (from CSTNode via projection): `node_id`, `node_type`, `name`, `full_name`, `file_path`, `start_line`, `end_line`, `start_byte` (=0), `end_byte` (=0), `source_code`, `source_hash`.

**Graph context** (from edges table): `parent_id: str | None`, `caller_ids: list[str]`, `callee_ids: list[str]`.

**Runtime state** (from event projections): `status: str = "idle"` (idle|running|error|scaffold|pending_approval), `last_trigger_event: str`, `last_completed_at: float | None`.

**Specialization** (from extension matching): `extension_name: str | None`, `custom_system_prompt: str`, `mounted_workspaces: list[str]`, `extra_tools: list[ToolSchema]`, `extra_subscriptions: list[SubscriptionPattern]`.

**Key methods:**
- `to_row() -> dict` — serializes JSON list/object fields for SQLite INSERT
- `from_row(row) -> AgentNode` — class method, deserializes JSON fields back to Python types
- `to_system_prompt() -> str` — generates LLM system prompt with identity, source code, graph context, core rules, specialization, workspaces
- `to_code_lens() -> CodeLens` — LSP status icon + node_id, click selects agent
- `to_hover(recent_events) -> Hover` — markdown with ID, type, status, parent, callers, callees, extension, recent events
- `to_code_actions() -> list[CodeAction]` — chat, rewrite, message actions + extra_tools as code actions
- `to_document_symbol() -> DocumentSymbol` — symbol kind from `kind_map` (function→Function, class→Class, note→File, todo→Event, etc.)

### 4.3 Events

All events are frozen Pydantic models (base `_FrozenEvent` with `ConfigDict(frozen=True)`). Defined in `remora.core.events`.

**Agent lifecycle:**

| Event | Key Fields |
|-------|------------|
| `AgentStartEvent` | graph_id, agent_id, node_name, trigger_event_type, timestamp |
| `AgentCompleteEvent` | graph_id, agent_id, result_summary, response, timestamp |
| `AgentErrorEvent` | graph_id, agent_id, error, timestamp |

**Human-in-the-loop:**

| Event | Key Fields |
|-------|------------|
| `HumanInputRequestEvent` | graph_id, agent_id, request_id, question, options: tuple[str,...]\|None, timestamp |
| `HumanInputResponseEvent` | request_id, response, timestamp |

**Reactive swarm:**

| Event | Key Fields |
|-------|------------|
| `AgentMessageEvent` | from_agent, to_agent, content, tags: tuple[str,...], correlation_id\|None, timestamp |
| `FileSavedEvent` | path, timestamp |
| `ContentChangedEvent` | path, diff\|None, timestamp |
| `ManualTriggerEvent` | to_agent, reason, timestamp |

**Node lifecycle:**

| Event | Key Fields |
|-------|------------|
| `NodeDiscoveredEvent` | node_id, node_type, name, full_name, file_path, start_line, end_line, start_byte, end_byte, source_code, source_hash, parent_id\|None, timestamp |
| `ScaffoldRequestEvent` | node_id, node_type, parent_id\|None, intent, timestamp |
| `NodeRemovedEvent` | node_id, timestamp |

**Kernel re-exports** (from `structured_agents.events`): `KernelStartEvent`, `KernelEndEvent`, `ModelRequestEvent`, `ModelResponseEvent`, `ToolCallEvent`, `ToolResultEvent`, `TurnCompleteEvent`.

**Union type**: `RemoraEvent` — type alias union of all above event types for pattern matching.

### 4.4 SubscriptionPattern & SubscriptionRegistry

**`SubscriptionPattern`** — Pydantic model with 5 optional dimensions (all `None` = wildcard):
- `event_types: list[str] | None` — match event class name in list
- `from_agents: list[str] | None` — match `event.from_agent` in list
- `to_agent: str | None` — match `event.to_agent` equals
- `path_glob: str | None` — match `event.path` via `PurePath.match()`
- `tags: list[str] | None` — match if any event tag in list

`matches(event) -> bool` — conjunctive across dimensions, disjunctive within lists.

**`SubscriptionRegistry`** — SQLite-backed with in-memory cache. Two modes:
- **Standalone**: pass `db_path`, opens own SQLite connection, creates `subscriptions` table
- **Shared**: pass `connection` + `lock` from EventStore, table already exists

**Methods:**
- `register(agent_id, pattern, is_default=False) -> Subscription` — INSERT + invalidate cache
- `register_defaults(agent_id, file_path) -> list[Subscription]` — registers direct-message + file-change subscriptions
- `unregister(subscription_id) -> bool` — DELETE by ID + invalidate cache
- `unregister_all(agent_id) -> int` — DELETE all for agent + invalidate cache
- `get_matching_agents(event) -> list[str]` — cache lookup by event_type key, then pattern.matches() filter. Wildcards (no event_types) stored under key `""`.

**Cache**: `dict[str, list[tuple[str, SubscriptionPattern]]]` — indexed by event_type string. `None` means invalidated, rebuilt on next `get_matching_agents`.

### 4.5 Extensions

**`AgentExtension`** — base class in `remora.extensions`. Two static methods:
- `matches(node_type, name, *, file_path="", source_code="") -> bool` — returns True if extension applies
- `get_extension_data() -> dict` — returns AgentNode field overrides (extension_name, custom_system_prompt, mounted_workspaces, extra_tools, extra_subscriptions)

**`extension_matches(ext, node_type, name, *, file_path, source_code) -> bool`** — wrapper that calls `ext.matches()` with kwargs, falls back to 2-arg call for old signatures (catches TypeError).

**`load_extensions(models_dir, *, cache=None) -> list[Type[AgentExtension]]`** — loads `.py` files from directory (typically `.remora/models/`). Uses mtime-based cache (`dict[str, (mtimes_dict, extensions_list)]`). Files sorted alphabetically — first match wins, so naming controls priority (e.g. `00_specific.py` before `50_generic.py`). Finds all `AgentExtension` subclasses in each module.
