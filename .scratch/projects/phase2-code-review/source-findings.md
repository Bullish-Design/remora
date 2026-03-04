# Phase 2 Code Review — Source Findings

All source files in `src/remora/` (excluding `remora_demo/`) have been read and reviewed.

---

## CRITICAL Findings

### 1. Dual/Triple Agent Identity System
- **AgentNode** (Pydantic, in EventStore `nodes` table via projection) — the vision's intended single source of truth
- **AgentState** (dataclass, JSONL files in `.remora/agents/`) — used by `swarm_executor.py`, `agent_runner.py` (core)
- **AgentMetadata** (dataclass, in SwarmState's `agents` SQLite table) — used by `reconciler.py`, CLI `swarm list`

The vision doc says AgentNode/nodes table IS the agent registry. SwarmState and AgentState are pre-unification artifacts that were never consolidated.

### 2. Two Separate AgentRunner Implementations
- `core/agent_runner.py` (288 lines) — Core runner using SwarmExecutor, AgentState, EventStore triggers
- `lsp/runner.py` (674 lines) — LSP runner with its own LLMClient, tool dispatch, proposal system

These don't share code. The LSP runner uses EventStore for node lookup. The core runner uses AgentState JSONL.

---

## HIGH Findings

### 3. SwarmState `agents` Table Duplicates `nodes` Table
Both store: node_type, name, full_name, file_path, start_line, end_line, parent_id, status. Violates single-source-of-truth.

### 4. LSP Event Model Duplication
`lsp/models.py` defines its own Pydantic event hierarchy (AgentEvent, HumanChatEvent, etc.) that bridges to `core/events.py` frozen dataclasses via `to_core_event()`. Creates a parallel event system.

### 5. RemoraDB Has Own `events` Table
`lsp/db.py` stores LSP events in its own `events` table, separate from EventStore. `server.emit_event()` writes to BOTH. Dual-write pattern is fragile.

---

## MEDIUM Findings

### 6. Bugs
1. **`service/api.py` line 167 vs 186**: `get_subscriptions` defined twice — first as a property returning `SubscriptionRegistry | None`, then as an async method taking `agent_id`. The second shadows the first.
2. **`tools/swarm.py` line 140**: `SubscribeTool` sets `to_agent=agent_id` on the pattern, meaning the subscription only matches events where `to_agent` equals THIS agent — defeats the purpose of subscribing to other nodes' events.
3. **`lsp/__main__.py` hardcoded LLM config**: `base_url="http://remora-server:8000/v1"`, `model="Qwen/Qwen3-4B-Instruct-2507-FP8"` — should come from Config.

### 7. Dead/Stale Code
1. **`TreeSitterDiscoverer`** wrapper in `discovery.py` — compat shim, likely unused
2. **`NodeType`** enum in `discovery.py` — not used anywhere meaningful
3. **`AgentState`** + JSONL persistence — pre-unification, should be replaced by EventStore
4. **`SwarmState`** — should be consolidated into EventStore nodes table
5. **`render_tag`** in `ui/view.py` — marked as legacy
6. **Top-level `__init__.py`** re-exports `TreeSitterDiscoverer`, `AgentState`, `compute_node_id` — stale API surface

### 8. isinstance Usage
- `ui/projector.py` lines 75-87: `_event_kind()` uses isinstance dispatch (UI categorization, not business logic)
- `service/chat_service.py` lines 165-176: `stream_events()` uses isinstance (demo code)
- `core/projections.py`: isinstance dispatch (documented exception per REPO_RULES)

---

## LOW Findings

### 9. Code Quality
1. **CLI `cli/main.py`**: `swarm start` and `swarm reconcile` duplicate EventStore/SwarmState/SubscriptionRegistry setup (~30 lines each). Should extract a shared setup helper.
2. **`config.py`**: Inline import of ConfigError in `load_config` + module-level import — cleanup needed.
3. **`watcher.py`**: `_parse_fallback` has approximate end_line (always total_lines) — documented limitation.
4. **`lsp/graph.py`**: `_normalize_node` adds both `id` and `node_id` keys — compat hack that should be cleaned.

---

## Files Reviewed

### core/ (23 files)
- `agent_node.py` (254 lines), `events.py` (224), `projections.py` (130), `event_store.py` (508)
- `event_bus.py` (135), `subscriptions.py` (287), `agent_runner.py` (288)
- `swarm_executor.py` (375), `swarm_state.py` (197), `reconciler.py` (183), `discovery.py` (374)
- `agent_state.py` (84), `chat.py` (259), `cairn_bridge.py` (183), `cairn_externals.py` (71)
- `vcs.py` (35), `config.py` (165), `workspace.py` (191), `errors.py` (60)
- `tools/__init__.py` (7), `tools/grail.py` (145), `tools/swarm.py` (324)
- `__init__.py` (120)

### lsp/ (14 files)
- `server.py` (144), `__main__.py` (257), `db.py` (345), `graph.py` (199), `watcher.py` (283)
- `runner.py` (674), `notifications.py` (93), `models.py` (255)
- `handlers/documents.py` (169), `handlers/lens.py` (34), `handlers/hover.py` (25)
- `handlers/actions.py` (32), `handlers/commands.py` (201), `handlers/capabilities.py` (17)

### Other packages
- `extensions.py` (89), `service/api.py` (200), `service/handlers.py` (147)
- `service/datastar.py` (68), `service/chat_service.py` (243)
- `adapters/starlette.py` (138), `cli/main.py` (338), `models/__init__.py` (101)
- `utils/` — PathResolver, text truncation, managed_workspace, PathLike
- `nvim/server.py` (265), `ui/projector.py` (197), `ui/view.py` (144)
- `ui/components/` — base.py, layout.py, controls.py, data.py, dashboard.py
- Top-level `__init__.py` (117)
