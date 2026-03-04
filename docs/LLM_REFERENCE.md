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

### 4.6 Config

Pydantic `BaseSettings` subclass (`env_prefix="REMORA_"`). Defined in `remora.core.config`.

| Field | Type | Default |
|-------|------|---------|
| `project_path` | `str` | `"."` |
| `discovery_paths` | `tuple[str, ...]` | `("src/",)` |
| `discovery_languages` | `tuple[str, ...] \| None` | `None` (all) |
| `discovery_max_workers` | `int` | `4` |
| `bundle_root` | `str` | `"agents"` |
| `bundle_mapping` | `dict[str, str]` | `{}` — maps node_type → bundle subdir |
| `bundle_mapping_tools` | `dict[str, str]` | `{}` |
| `model_base_url` | `str` | `"http://localhost:8000/v1"` |
| `model_default` | `str` | `"Qwen/Qwen3-4B"` |
| `model_api_key` | `str` | `""` |
| `swarm_root` | `str` | `".remora"` |
| `swarm_id` | `str` | `"swarm"` |
| `max_concurrency` | `int` | `4` |
| `max_turns` | `int` | `8` |
| `truncation_limit` | `int` | `1024` |
| `timeout_s` | `float` | `300.0` |
| `max_trigger_depth` | `int` | `5` |
| `trigger_cooldown_ms` | `int` | `1000` |
| `chat_history_limit` | `int` | `5` |
| `workspace_ignore_patterns` | `tuple[str, ...]` | `.agentfs, .git, .jj, .mypy_cache, .pytest_cache, .remora, .tox, .venv, __pycache__, node_modules, venv` |
| `workspace_ignore_dotfiles` | `bool` | `True` |
| `nvim_enabled` | `bool` | `False` |
| `nvim_socket` | `str` | `".remora/nvim.sock"` |

**`load_config(path=None) -> Config`** — loads `remora.yaml`. If `path` is None, searches cwd upward until `pyproject.toml` is found (stops there). Returns defaults if no file found. Calls `_expand_env_vars()` on parsed YAML, then passes to `Config(**expanded)`.

**Env var expansion**: `${VAR:-default}` and `${VAR}` patterns in string values are recursively expanded via `os.environ.get()`.

**`serialize_config(config) -> dict`** — `config.model_dump(mode="json")` (tuples become lists).

### 4.7 EventStore

SQLite-backed event store. Defined in `remora.core.event_store`. Constructor: `EventStore(db_path, subscriptions=None, event_bus=None, projection=None)`.

**`initialize()`** — creates 8 tables (events, nodes, subscriptions, edges, activation_chain, proposals, cursor_focus, command_queue) + WAL mode + NORMAL synchronous + indexes + migration for routing fields (from_agent, to_agent, correlation_id, tags, start_byte, end_byte, file_path on proposals).

**`append(graph_id, event) -> int`** — core write path:
1. Serialize event → JSON payload
2. Extract routing fields (from_agent, to_agent, correlation_id, tags) via `getattr()`
3. INSERT into events table
4. `projection.apply(conn, event)` within same transaction
5. COMMIT
6. `subscriptions.get_matching_agents(event)` → enqueue `(agent_id, event_id, event)` to trigger_queue
7. `event_bus.emit(event)` for UI

**`replay(graph_id, *, event_types, since, until, after_id) -> AsyncIterator[dict]`** — filtered SELECT, ordered by timestamp ASC.

**`get_recent_events(agent_id, limit=5) -> list[dict]`** — events where from_agent or to_agent = agent_id, newest first.

**`get_events_for_correlation(correlation_id) -> list[dict]`** — all events in a chain, chronological.

**`get_node(node_id) -> AgentNode | None`** — SELECT from nodes by PK.

**`list_nodes(*, file_path, node_type, columns) -> list[AgentNode]`** — optional filters, ordered by file_path + start_line. `columns` param for SELECT optimization.

**`get_node_at_position(file_path, line) -> AgentNode | None`** — narrowest node containing line: `ORDER BY (end_line - start_line) ASC LIMIT 1`.

**`set_node_status(node_id, status)`** — direct UPDATE on nodes table.

**`remove_nodes_for_file(file_path) -> int`** — DELETE all nodes for file.

**`_serialize_event(event) -> str`** — tries `model_dump()` → `asdict()` → `vars()` → `str()`.

**`_row_to_dict(row) -> dict`** — promotes payload fields: parses stored JSON, uses model's `event_type` over DB column, separates meta keys from nested payload sub-dict for Lua panel compatibility.

### 4.8 NodeProjection

Materializes events into the `nodes` table. Defined in `remora.core.projections`. Constructor: `NodeProjection(extension_configs=None)`.

**`apply(conn, event)`** — dispatches by event type:
- `NodeDiscoveredEvent` → `_project_node_discovered()`: builds row dict, runs extension matching (first match wins, injects ext fields as JSON), UPSERT with `ON CONFLICT(node_id) DO UPDATE`. Status uses `CASE WHEN nodes.status IN ('running', 'error') THEN nodes.status ELSE excluded.status END` to preserve lifecycle state during re-discovery.
- `NodeRemovedEvent` → DELETE by node_id.
- `AgentStartEvent` → UPDATE status='running', last_trigger_event.
- `AgentCompleteEvent` → UPDATE status='idle', last_completed_at.
- `AgentErrorEvent` → UPDATE status='error'.

**Stub detection**: `_is_stub(source_code) -> bool` — returns True for empty, whitespace-only, comments-only, `class Foo: pass`, `def foo(): ...`, or block form with optional docstring. Detected stubs get status `"scaffold"` instead of `"idle"`.

### 4.9 Reconciler

Startup discovery diff. Defined in `remora.core.reconciler`.

**`reconcile_on_startup(project_path, subscriptions, discovery_paths, languages, event_store, swarm_id) -> dict`**:
1. `discover([project_path / p for p in discovery_paths])` → CSTNode list
2. `event_store.list_nodes()` → existing AgentNodes
3. Diff: `new_ids = discovered - existing`, `deleted_ids = existing - discovered`, `common_ids = discovered & existing`
4. New nodes: emit `NodeDiscoveredEvent` + `subscriptions.register_defaults(node_id, relative_path)`
5. Deleted nodes: emit `NodeRemovedEvent` + `subscriptions.unregister_all(node_id)`
6. Changed nodes (common with different `source_hash`): emit `NodeDiscoveredEvent` (re-upsert) + `ContentChangedEvent`
7. Returns `{created, orphaned, updated, total}`

**Helpers**: `get_agent_dir(swarm_root, agent_id) -> Path` (`.../agents/{id[:2]}/{id}`), `get_agent_workspace_path(...)` (appends `/workspace.db`), `_compute_source_hash(text) -> str` (SHA256[:16]).

### 4.10 Tools

Four tool systems in `remora.core.tools`.

**(a) Grail .pym tools** (`remora.core.tools.grail`):
- `RemoraGrailTool(script_path, *, externals, files_provider, limits, grail_dir)` — wraps `grail.load(script_path)`. Schema built via `_build_parameters()` from `script.inputs` (Input() declarations → JSON Schema type map). `execute()` calls `script.run(inputs, externals, files, limits)`.
- `build_virtual_fs(files) -> dict` — normalizes paths (backslash→forward, strip leading `/`).
- `discover_grail_tools(agents_dir, *, context, files_provider) -> list` — globs `*.pym` from agents_dir, creates `RemoraGrailTool` per script using `context.as_externals()` for flat dict, then appends `build_swarm_tools(context)`.

**(b) Swarm tools** (`remora.core.tools.swarm`):
Base class `SwarmTool` with `schema` property and `execute()` method. 5 tools:

| Tool | Params | Action |
|------|--------|--------|
| `SendMessageTool` | to_agent, content | Emits `AgentMessageEvent` via ctx |
| `SubscribeTool` | event_types?, from_agents?, path_glob? | Registers `SubscriptionPattern` via ctx |
| `UnsubscribeTool` | subscription_id | Removes subscription by ID via ctx |
| `BroadcastTool` | to_pattern, content | Patterns: `children`, `siblings`, `file:{path}` — emits `AgentMessageEvent` to each match |
| `QueryAgentsTool` | filter_type? | Lists agents, optional node_type filter |

`build_swarm_tools(ctx) -> list[SwarmTool]` — constructs all 5.

**(c) LSP built-in tools** (defined inline in `AgentRunner.get_agent_tools()`):
3 tools as OpenAI function-calling dicts:
- `rewrite_self(new_source)` → creates proposal (pending_approval)
- `message_node(target_id, message)` → sends message + triggers target (supports `"parent"` symbolic resolution)
- `read_node(target_id)` → returns JSON `{name, type, source, file}` of target

Plus `agent.extra_tools` appended via `tool.to_llm_tool()`.

**(d) SpawnChildTool** (`remora.core.tools.spawn_child`):
Params: `node_type` (class/function/file), `name`, `intent`, `file_path`. Writes stub to disk (templates: `class {name}: pass`, `def {name}(): pass`, empty file), emits `NodeDiscoveredEvent` + `ScaffoldRequestEvent`, returns `{node_id, file_path, node_type, name}`.

### 4.11 Workspace

Defined in `remora.core.workspace`.

**`AgentWorkspace(workspace, agent_id, stable_workspace=None, *, ensure_file_synced, lock, stable_lock)`** — wraps a Cairn workspace with fallback chain:
- `read(path)` — try agent workspace → stable workspace → `ensure_file_synced` callback + retry stable → raise `FileNotFoundError`
- `write(path, content)` — writes to agent workspace (CoW isolated)
- `exists(path)` — checks agent workspace, then stable
- `list_dir(path)` — merges entries from both workspaces (sorted, deduplicated)

**`_is_missing_file_error(exc) -> bool`** — checks `FileNotFoundError`, `.code` in `{FS_NOT_FOUND, ENOENT}`, `.context.agentfs_code == "ENOENT"`, `.errno == 2`.

**`CairnDataProvider(workspace, resolver)`** — data provider for Grail virtual FS:
- `load_files(node, related=None) -> dict[str, str]` — loads target file via workspace (with disk fallback via `_load_from_disk`), plus related files. Maps both workspace and original paths.

### 4.12 SwarmExecutor

Single agent turn executor for CLI/headless mode. Defined in `remora.core.swarm_executor`.

**Constructor**: `SwarmExecutor(config, event_bus, event_store, subscriptions, swarm_id, project_root)` — builds `PathResolver`, `CairnWorkspaceService`, reusable LLM client via `build_client()`.

**`run_agent(node, trigger_event=None) -> str`**:
1. `_resolve_bundle_path(node)` → `bundle_root / bundle_mapping[node_type]`
2. `load_manifest(bundle_path)` (structured-agents)
3. Init workspace service (lazy), get agent workspace + Cairn externals
4. Build `AgentContext` with closures: `_emit_event`, `_register_sub`, `_unsubscribe_subscription`, `_broadcast` (children/siblings/file: patterns), `_query_agents`
5. `CairnDataProvider.load_files(cst_node)` → file dict
6. Get chat history from `event_store.get_recent_events()`
7. `_build_prompt()` → markdown prompt
8. `discover_grail_tools()` (if manifest.agents_dir set)
9. `_resolve_model_name()` → bundle.yaml `model.id` override or `config.model_default`
10. `_run_kernel()` → create kernel, build Message list (system + history + user prompt), run with tool_schemas + max_turns
11. Extract response text, truncate to `config.truncation_limit`

**`_build_prompt(node, cst_node, files, ...)`** — sections: target info (full_name, file, lines), code block, trigger event (type + content), recent chat history, scaffold context (parent source, siblings, intent).

**`_run_kernel(manifest, prompt, tools, *, chat_history, model_name)`** — creates `_EventStoreObserver` wrapping event_store for kernel events, calls `create_kernel()`, builds Message list, `kernel.run(messages, tool_schemas, max_turns)`.

### 4.13 AgentRunner

Async execution coordinator for LSP + headless. Defined in `remora.lsp.runner`.

**Constructor**: `AgentRunner(server, llm=None, *, max_trigger_depth, trigger_cooldown_ms, max_concurrency)` — server is `RemoraLanguageServer` or `_HeadlessServer` stub.

**`create_headless(event_store, llm, ...) -> AgentRunner`** — wraps EventStore in `_HeadlessServer` (with `_HeadlessDB` stub for chain/proposals/commands).

**`run_forever()`** — dequeues `Trigger` objects from async queue, calls `execute_turn()`. Background task: `poll_command_queue()`.

**`trigger(agent_id, correlation_id, context=None)`** — checks:
1. Cooldown (per-agent ms timer)
2. In-memory depth limit (`_correlation_depth` dict)
3. DB-backed chain depth (`server.db.get_activation_chain`) — `MAX_CHAIN_DEPTH=10`
4. Cycle detection (agent_id already in chain)
Then enqueues `Trigger(agent_id, correlation_id, context)`.

**`execute_turn(trigger)`** — under semaphore:
1. Increment depth tracking
2. Set node status='running', refresh CodeLens
3. Add to DB activation chain
4. Get AgentNode from EventStore
5. `apply_extensions(agent)` — reload extensions from `.remora/models/`, first match wins
6. Build messages: system prompt + correlation events (HumanChat → user, AgentMessage → user) + rejection feedback
7. `get_agent_tools(agent)` → 3 built-in tools + extra_tools
8. Tool call loop up to `MAX_TOOL_ROUNDS=5`: LLM chat → `handle_response()` → if tool_results, append + continue; else break
9. Finally: decrement depth, set status='idle', refresh CodeLens

**`handle_response(agent, response, correlation_id) -> list[dict]`** — dispatches tool calls:
- `rewrite_self` → `create_proposal()` (side-effect only)
- `message_node` → `message_node()` which triggers target (side-effect only, supports `"parent"` resolution)
- `read_node` → returns JSON dict (feeds back to LLM)
- Unknown → `execute_extension_tool()`
- Text-only response → emits `AgentTextResponse` event
- Fallback: `_extract_text_tool_calls()` parses `<tool_call>{JSON}</tool_call>` XML from content (for models like Qwen)

**`poll_command_queue()`** — 1s poll loop, dispatches: `chat` → emit HumanChatEvent + trigger, `approve_proposal` → accept, `reject_proposal` → emit rejection + trigger with feedback, `execute_tool` → run extension tool.

### 4.14 ChatSession

Single-agent chat wrapper. Defined in `remora.core.chat`.

**`ChatConfig`** — Pydantic model: `workspace_path`, `system_prompt`, `tool_presets` (default `["file_ops"]`), `model_name`, `model_base_url`, `model_api_key`, `max_turns` (default 10). Factory: `from_config(config, *, workspace_path, system_prompt)`.

**`Message`** — Pydantic model: `id`, `role`, `content`, `timestamp`, `tool_calls: list[dict]`. Class methods: `user(content)`, `assistant(content, tool_calls)`.

**`AgentResponse`** — Pydantic model: `message: Message`, `turn_count: int`.

**`ChatSession(session_id, config, event_bus)`**:
- `create(config, event_bus) -> ChatSession` — factory: generates session_id, calls `_initialize()` which creates `CairnWorkspaceService`, gets agent workspace, builds tools.
- `send(content) -> AgentResponse` — appends user Message to history, builds kernel messages (system + full history), creates kernel via `create_kernel()`, `kernel.run(messages, tool_schemas, max_turns)`, extracts response, appends assistant Message.
- `history` — returns copy of message list.
- `reset()` — clears history.

**`build_chat_tools(agent_workspace, project_root) -> list[FunctionTool]`** — 6 tools:

| Tool | Signature | Action |
|------|-----------|--------|
| `read_file` | `(path: str) -> str` | `workspace.read(path)` |
| `write_file` | `(path: str, content: str) -> bool` | `workspace.write(path, content)` |
| `list_dir` | `(path: str = ".") -> list[str]` | `workspace.list_dir(path)` |
| `file_exists` | `(path: str) -> bool` | `workspace.exists(path)` |
| `search_files` | `(pattern: str) -> list[str]` | `project_root.rglob(pattern)` |
| `discover_symbols` | `(path: str = ".") -> list[dict]` | `discover([target])` → `{name, type, file, line}` |

**`FunctionTool(func)`** — wraps async callable, auto-generates `ToolSchema` from function signature + type hints via `_params_schema()`.

### 4.15 Bundles

Structured-agents manifest format for agent configuration. Bundle path resolved via `Config.bundle_mapping[node_type]` under `Config.bundle_root`. Manifest loaded by `structured_agents.agent.load_manifest(bundle_path)`.

**Bundle YAML** (`{bundle_root}/{mapping}/bundle.yaml`):
- `name` — bundle identifier
- `system_prompt` — sourced from `initial_context` field in manifest
- `model` — dict with `id`/`name`/`model` keys for model override
- `grammar_config` — optional constrained decoding config (`send_tools_to_api` flag)
- `agents_dir` — directory for `.pym` tool discovery (None = no tools, e.g. chat bundles)
- `max_turns` — per-bundle turn limit override (falls back to `Config.max_turns`)

**Resolution flow**: `SwarmExecutor._resolve_bundle_path(node)` → `bundle_root / bundle_mapping[node.node_type]`. `_resolve_model_name(bundle_path, manifest)` → reads `bundle.yaml`, checks `model.id` / `model.name` / `model.model` → falls back to `Config.model_default`.

**Kernel integration**: `create_kernel()` in `remora.core.kernel_factory` — builds `AgentKernel` with `build_client()`, `ModelAdapter` (with response parser + optional constraint pipeline), and tools/observer. Used by both `SwarmExecutor._run_kernel()` and `ChatSession.send()`.

---

## 5. API Reference

### 5.1 Public Exports (`remora.__init__`)

```python
# Config
Config, load_config, serialize_config, ConfigError

# Discovery
CSTNode, LANGUAGE_EXTENSIONS, compute_node_id, discover

# Events
AgentStartEvent, AgentCompleteEvent, AgentErrorEvent,
HumanInputRequestEvent, HumanInputResponseEvent,
AgentMessageEvent, FileSavedEvent, ContentChangedEvent, ManualTriggerEvent,
NodeDiscoveredEvent, NodeRemovedEvent, ScaffoldRequestEvent,
KernelStartEvent, KernelEndEvent, ModelRequestEvent, ModelResponseEvent,
ToolCallEvent, ToolResultEvent, TurnCompleteEvent,
RemoraEvent  # Union of all event types

# Core infrastructure
EventBus, EventHandler, EventStore
SubscriptionPattern, SubscriptionRegistry, Subscription

# Execution
AgentRunner, SwarmExecutor

# Workspace
AgentWorkspace, CairnDataProvider, CairnWorkspaceService, CairnExternals

# Tools
RemoraGrailTool, build_virtual_fs, discover_grail_tools

# Reconciliation
reconcile_on_startup, get_agent_dir, get_agent_workspace_path

# Context
AgentContext

# Utilities
PathResolver, to_project_relative

# Errors
RemoraError, ConfigError, DiscoveryError, ExecutionError, WorkspaceError
```

### 5.2 Key Function Signatures

```python
# Discovery
def discover(paths: list[Path], *, languages: list[str] | None = None) -> list[CSTNode]
def compute_node_id(file_path: str, name: str, start_line: int, end_line: int) -> str

# Config
def load_config(path: PathLike | None = None) -> Config
def serialize_config(config: Config) -> dict[str, Any]

# EventStore
async def EventStore.initialize() -> None
async def EventStore.append(graph_id: str, event: StructuredEvent | RemoraEvent) -> int
async def EventStore.replay(graph_id, *, event_types, since, until, after_id) -> AsyncIterator[dict]
async def EventStore.get_node(node_id: str) -> AgentNode | None
async def EventStore.list_nodes(*, file_path=None, node_type=None, columns=None) -> list[AgentNode]
async def EventStore.get_node_at_position(file_path: str, line: int) -> AgentNode | None

# Reconciliation
async def reconcile_on_startup(
    project_path, subscriptions, discovery_paths=None,
    languages=None, event_store=None, swarm_id="swarm"
) -> dict  # {created, orphaned, updated, total}

# Subscriptions
async def SubscriptionRegistry.register(agent_id, pattern, is_default=False) -> Subscription
async def SubscriptionRegistry.get_matching_agents(event) -> list[str]

# Execution
async def SwarmExecutor.run_agent(node: AgentNode, trigger_event=None) -> str
async def AgentRunner.trigger(agent_id: str, correlation_id: str, context=None) -> None
AgentRunner.create_headless(event_store, llm=None, **kwargs) -> AgentRunner

# Chat
async def ChatSession.create(config: ChatConfig, event_bus=None) -> ChatSession
async def ChatSession.send(content: str) -> AgentResponse

# Kernel factory
def create_kernel(*, model_name, base_url, api_key, timeout=300.0,
                  tools=None, observer=None, grammar_config=None, client=None) -> AgentKernel
```

### 5.3 CLI Commands

Entry point: `remora` (via `remora.cli.main:main`). Click-based.

| Command | Options | Description |
|---------|---------|-------------|
| `remora swarm start` | `--project-root`, `--config`, `--lsp` | Start reactive swarm. `--lsp` launches LSP server for Neovim. Without `--lsp`, runs headless AgentRunner + EventStore trigger bridge. |
| `remora swarm reconcile` | `--project-root`, `--config` | Run discovery diff only — emits events but does not start runner. |
| `remora swarm list` | `--project-root` | List agents in nodes table (reads `.remora/events/events.db`). |
| `remora swarm emit EVENT_TYPE [DATA]` | `--project-root` | Emit event manually. Supports `AgentMessageEvent`, `ContentChangedEvent`. DATA is JSON string. |
| `remora serve` | `--host` (0.0.0.0), `--port` (8420), `--project-root`, `--config` | Start HTTP API server via Starlette + uvicorn. |

### 5.4 Configuration Keys (remora.yaml)

```yaml
project_path: "."
discovery_paths: ["src/"]
discovery_languages: null  # or ["python", "markdown"]
discovery_max_workers: 4
bundle_root: "agents"
bundle_mapping:
  function: "function-agent"
  class: "class-agent"
bundle_mapping_tools: {}
model_base_url: "http://localhost:8000/v1"
model_default: "Qwen/Qwen3-4B"
model_api_key: ""
swarm_root: ".remora"
swarm_id: "swarm"
max_concurrency: 4
max_turns: 8
truncation_limit: 1024
timeout_s: 300.0
max_trigger_depth: 5
trigger_cooldown_ms: 1000
chat_history_limit: 5
workspace_ignore_patterns: [".agentfs", ".git", ".jj", ".mypy_cache",
  ".pytest_cache", ".remora", ".tox", ".venv", "__pycache__",
  "node_modules", "venv"]
workspace_ignore_dotfiles: true
nvim_enabled: false
nvim_socket: ".remora/nvim.sock"
```

All keys map 1:1 to `Config` fields. Environment variables: `REMORA_<FIELD_UPPER>` (e.g. `REMORA_MODEL_DEFAULT`). String values support `${VAR:-default}` expansion.

### 5.5 Event Type Catalog

| Event | Category | Key Fields | Emitted By |
|-------|----------|------------|------------|
| `NodeDiscoveredEvent` | node | node_id, node_type, name, full_name, file_path, start_line, end_line, source_code, source_hash, parent_id | reconciler, spawn_child |
| `NodeRemovedEvent` | node | node_id | reconciler |
| `ScaffoldRequestEvent` | node | node_id, node_type, parent_id, intent | spawn_child |
| `ContentChangedEvent` | swarm | path, diff | reconciler, file watcher |
| `FileSavedEvent` | swarm | path | editor/LSP |
| `AgentMessageEvent` | swarm | from_agent, to_agent, content, tags, correlation_id | send_message, broadcast, message_node |
| `ManualTriggerEvent` | swarm | to_agent, reason | CLI emit, UI |
| `AgentStartEvent` | lifecycle | graph_id, agent_id, node_name, trigger_event_type | runner |
| `AgentCompleteEvent` | lifecycle | graph_id, agent_id, result_summary, response | runner |
| `AgentErrorEvent` | lifecycle | graph_id, agent_id, error | runner |
| `HumanInputRequestEvent` | human | graph_id, agent_id, request_id, question, options | agent |
| `HumanInputResponseEvent` | human | request_id, response | UI/CLI |
| `KernelStartEvent` | kernel | (re-export from structured_agents) | kernel |
| `KernelEndEvent` | kernel | (re-export) | kernel |
| `ModelRequestEvent` | kernel | (re-export) | kernel |
| `ModelResponseEvent` | kernel | (re-export) | kernel |
| `ToolCallEvent` | kernel | (re-export) | kernel |
| `ToolResultEvent` | kernel | (re-export) | kernel |
| `TurnCompleteEvent` | kernel | (re-export) | kernel |

Union type: `RemoraEvent = NodeDiscoveredEvent | NodeRemovedEvent | ScaffoldRequestEvent | ... | TurnCompleteEvent`
