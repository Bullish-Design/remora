# EventBased Concept Gap Analysis

> **Project:** event-concept-gap-analysis  
> **Compares:** `docs/EventBased_Concept.md` (2120 lines) against actual codebase  
> **Date:** 2026-03-03

## Table of Contents

1. [Section 1.1-1.2: EventLog & Events](#1-section-11-12-eventlog--events)
2. [Section 1.3: Subscriptions](#2-section-13-subscriptions)
3. [Section 1.4: Discovery](#3-section-14-discovery)
4. [Section 1.5: The Reactive Loop](#4-section-15-the-reactive-loop)
5. [Section 1.6: Cascade Safety](#5-section-16-cascade-safety)
6. [Section 1.7: The AgentNode Model](#6-section-17-the-agentnode-model)
7. [Section 3: Developer Perspective (Config, Bundles, Tools)](#7-section-3-developer-perspective)
8. [Section 7: LSP Integration](#8-section-7-lsp-integration)
9. [Section 8: Future / Custom CSTNode Types](#9-section-8-future)
10. [Two Runner Problem](#10-two-runner-problem)
11. [Summary: Gap Priority Matrix](#11-summary-gap-priority-matrix)

---

## 1. Section 1.1-1.2: EventLog & Events

**Verdict: MOSTLY ALIGNED** — minor naming/structural diffs, no functional gaps.

### What the concept says

- Single SQLite `events` table, append-only, monotonic `id`.
- Events are **frozen Pydantic classes** (concept says `@dataclass` in examples but also says "frozen Pydantic").
- Four event categories: agent lifecycle, human-in-the-loop, reactive swarm, kernel re-exports.
- All events collected into `RemoraEvent` union type.

### What exists

- `src/remora/core/event_store.py` — `EventStore` with SQLite append-only `events` table. Has `append()`, `replay()`, `get_triggers()`, `get_node()`, `list_nodes()`, `get_recent_events()`, subscription matching on append. **Matches concept.**
- `src/remora/core/events.py` — All four event categories present:
  - Agent lifecycle: `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`
  - Human-in-the-loop: `HumanInputRequestEvent`, `HumanInputResponseEvent`
  - Reactive swarm: `AgentMessageEvent`, `FileSavedEvent`, `ContentChangedEvent`, `ManualTriggerEvent`
  - Kernel re-exports: `KernelStartEvent`, `KernelEndEvent`, `ToolCallEvent`, `ToolResultEvent`, `ModelRequestEvent`, `ModelResponseEvent`, `TurnCompleteEvent`
  - Node lifecycle: `NodeDiscoveredEvent`, `NodeRemovedEvent`
  - **Extra** (not in concept): `ScaffoldRequestEvent` — addition for scaffold/spawn workflow.
- Events use **Pydantic BaseModel** (not dataclasses). Concept uses `@dataclass` in examples but describes them as "frozen Pydantic classes." Code uses `model_config = ConfigDict(frozen=True)`.
- `RemoraEvent` union type exists as a type alias.

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| 1 | Concept doc shows `CSTNode` as `@dataclass(frozen=True, slots=True)`. Code uses `pydantic.BaseModel` with `frozen=True`. Functionally equivalent but doc/code mismatch. | **Cosmetic** |
| 2 | `ScaffoldRequestEvent` exists in code but not in concept doc. Not a gap — it's an addition. | **N/A** |

---

## 2. Section 1.3: Subscriptions

**Verdict: ALIGNED** — no functional gaps.

### What the concept says

- `SubscriptionPattern` with 5 dimensions: `event_types`, `from_agents`, `to_agent`, `path_glob`, `tags`.
- Conjunctive matching (all non-None must match), disjunctive lists.
- SQLite-backed `SubscriptionRegistry`, persistent across restarts.
- Two default subscriptions per agent: direct message + source file changes.
- Agents can dynamically `subscribe`/`unsubscribe` at runtime.

### What exists

- `src/remora/core/subscriptions.py` — `SubscriptionPattern` with all 5 dimensions. `SubscriptionRegistry` is SQLite-backed with in-memory cache. `register_defaults()` creates the 2 default subs. `register()` and `remove()` for dynamic management.
- `src/remora/core/tools/swarm.py` — `SubscribeTool` and `UnsubscribeTool` exist and are functional.

### Gaps

None.

---

## 3. Section 1.4: Discovery

**Verdict: PARTIALLY ALIGNED** — significant gap in query-pack architecture.

### What the concept says

- Discovery uses **tree-sitter queries from `.scm` files** in `queries/{language}/remora_core/`.
- Three languages: Python (`function.scm`, `class.scm`, `file.scm`), Markdown (`section.scm`, `file.scm`), TOML (`table.scm`, `file.scm`).
- `discover()` function with thread pool, returns `CSTNode` objects.
- `CSTNode` is a frozen dataclass with `node_id = SHA256(file_path:name:start_line:end_line)[:16]`.

### What exists

**Two separate discovery systems:**

1. **Core discovery** (`src/remora/core/discovery.py`):
   - `CSTNode` as frozen Pydantic model (not dataclass).
   - `discover()` with thread pool. Supports Python, Markdown, TOML + more via extension map.
   - Uses `tree_sitter` and `tree_sitter_python` directly — **hardcoded AST traversal**, not `.scm` query files.
   - Has markdown frontmatter post-processing for note/todo types.

2. **LSP watcher** (`src/remora/lsp/watcher.py`):
   - `ASTWatcher.parse_and_inject_ids()` — another tree-sitter-based parser.
   - Also uses hardcoded AST traversal (not `.scm` files).
   - Python: extracts functions, classes, methods, file nodes.
   - Non-Python: file-level nodes only (no section/table decomposition).
   - Has a regex fallback when tree-sitter unavailable.

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| 3 | **No `queries/` directory exists.** The concept doc describes `.scm` query files. Code uses hardcoded tree-sitter AST traversal instead. This means adding new node types requires code changes, not just adding `.scm` files. | **Medium** — works functionally but doesn't match the described extensibility model. |
| 4 | **Two separate discovery implementations.** Core `discover()` and LSP `ASTWatcher` duplicate tree-sitter parsing logic. The concept describes a single `discover()` function. | **Medium** — maintenance burden, potential for divergence. |
| 5 | **Markdown/TOML decomposition incomplete in LSP path.** `ASTWatcher._parse_file_only()` creates file-level nodes only for non-Python files. The concept says Markdown should produce `section` nodes for headings, TOML should produce `table` nodes. Core `discover()` has more complete support, but the LSP `ASTWatcher` doesn't. | **Medium** — non-Python files get only file-level agents in LSP mode. |

---

## 4. Section 1.5: The Reactive Loop

**Verdict: PARTIALLY ALIGNED** — the loop exists but with structural differences.

### What the concept says (14-step loop)

1. Event happens → appended to EventLog
2. Subscription matching runs on append
3. Matching agent_ids get triggers enqueued
4. AgentRunner picks up trigger (concurrency semaphore)
5. Loads AgentNode from nodes table via `AgentNode.from_row()`
6. SwarmExecutor resolves bundle via `bundle_mapping[agent.node_type]`
7. SwarmExecutor loads structured-agents manifest
8. SwarmExecutor builds prompt via `agent.to_system_prompt()`
9. Discovers Grail tools + swarm tools + agent.extra_tools
10. AgentKernel runs LLM loop
11. Kernel events written to EventLog by `_EventStoreObserver`
12. Those kernel events trigger subscription matching (step 3 again)
13. Agent completes → `AgentCompleteEvent` → may trigger other agents

### What exists

**Two separate runner implementations:**

1. **Core/CLI runner** (`src/remora/core/swarm_executor.py`):
   - `SwarmExecutor.run_agent()` — resolves bundle, loads manifest, builds workspace, builds prompt, discovers Grail tools, runs structured-agents kernel with `_EventStoreObserver`.
   - Follows steps 6-12 closely.
   - Uses `structured_agents.kernel` for the actual LLM loop.
   - `_EventStoreObserver` writes kernel events to EventStore.

2. **LSP runner** (`src/remora/lsp/runner.py`):
   - `AgentRunner` — has its own trigger queue, `execute_turn()`, `handle_response()`.
   - **Does NOT use SwarmExecutor.** Instead, has its own LLM client (`LLMClient`) wrapping `structured_agents.client.build_client()`.
   - Has its own tool loop (`MAX_TOOL_ROUNDS = 5`), its own tool dispatch (match/case on tool names), its own event emission.
   - Tools: `rewrite_self`, `message_node`, `read_node`, plus `agent.extra_tools`.
   - Does NOT use bundle resolution / `bundle_mapping`. Instead, applies extensions directly and uses `agent.to_system_prompt()` for the prompt.
   - Does NOT run the `_EventStoreObserver` pattern — kernel events are NOT written to the EventLog during LSP execution.

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| 6 | **Two separate runner implementations that don't share code.** `SwarmExecutor` (core/CLI) and `AgentRunner` (LSP) are completely independent. The concept describes one unified loop. | **High** — the LSP and CLI paths behave differently. |
| 7 | **LSP runner doesn't use bundle_mapping.** The concept says step 6 is "resolve bundle via `bundle_mapping[agent.node_type]`". The LSP `AgentRunner` skips this entirely — it applies extensions directly and generates the prompt from `agent.to_system_prompt()` without loading a bundle manifest. | **High** — agent behavior differs between LSP and CLI execution. |
| 8 | **LSP runner doesn't write kernel events to EventLog.** The concept says step 11 is "kernel events written to EventLog by `_EventStoreObserver`". The LSP runner emits `LspAgentEvent` objects for UI display but does NOT write structured kernel events (`ToolCallEvent`, `ModelResponseEvent`, etc.) to the EventStore. | **High** — no audit trail for LSP-triggered agent turns, subscription matching on kernel events doesn't work. |
| 9 | **LSP runner has different tools.** The core runner discovers Grail tools + 5 swarm tools. The LSP runner provides `rewrite_self`, `message_node`, `read_node` + agent.extra_tools. These are different tool sets. | **Medium** — different capabilities per execution path. |
| 10 | **No `FileSavedEvent` / `ContentChangedEvent` emission from LSP `did_save`.** The concept (Section 7) says "Did Save → Emit `FileSavedEvent` + `ContentChangedEvent` to EventLog". The `did_save` handler in `documents.py` emits `NodeDiscoveredEvent`/`NodeRemovedEvent` but NOT `FileSavedEvent` or `ContentChangedEvent`. This breaks the "source file changes" default subscription. | **High** — the reactive loop's primary trigger (file save → ContentChangedEvent → subscription → agent trigger) is not wired. |

---

## 5. Section 1.6: Cascade Safety

**Verdict: ALIGNED** — all four mechanisms implemented.

### What the concept says

1. Correlation ID tracking per event chain.
2. Depth limits (`max_trigger_depth`, default 5).
3. Cooldown (`trigger_cooldown_ms`, default 1000ms).
4. Concurrency semaphore (`max_concurrency`, default 4).

### What exists

`src/remora/lsp/runner.py` `AgentRunner`:
- `_check_depth_limit()` — in-memory per `agent_id:correlation_id` (line 243).
- `_check_cooldown()` — in-memory per `agent_id` (line 249).
- `_semaphore = asyncio.Semaphore(max_concurrency)` (line 192).
- DB-backed chain depth check via `server.db.get_activation_chain()` + cycle detection (lines 371-381).
- `_cleanup_stale_depths()` for TTL cleanup (line 258).

`src/remora/core/config.py`:
- `max_trigger_depth: int = 5` — matches concept default.
- `trigger_cooldown_ms: int = 1000` — matches.
- `max_concurrency: int = 4` — matches.

### Gaps

None. All four mechanisms implemented. The LSP runner actually has _two_ depth checks (in-memory + DB-backed), which is more thorough than the concept describes.

---

## 6. Section 1.7: The AgentNode Model

**Verdict: MOSTLY ALIGNED** — minor field differences.

### What the concept says

Single Pydantic `BaseModel` with three roles:
1. Database schema (`model_dump()`, `from_row()`)
2. Agent prompt context (`to_system_prompt()`)
3. LSP protocol data (`.to_hover()`, `.to_code_lens()`, `.to_code_actions()`, `.to_document_symbol()`)

Fields include: identity (node_id, node_type, name, etc.), graph context (parent_id, caller_ids, callee_ids), runtime state (status, last_trigger_event, last_completed_at), specialization (extension_name, custom_system_prompt, mounted_workspaces, extra_tools, extra_subscriptions).

### What exists

`src/remora/core/agent_node.py` — `AgentNode(BaseModel)` with:
- All identity fields present.
- `parent_id`, `caller_ids`, `callee_ids` present.
- `status` present. `last_trigger_event` and `last_completed_at` NOT present.
- `extension_name`, `custom_system_prompt`, `mounted_workspaces` present.
- `extra_tools` present (as list of `ToolSchema`).
- `extra_subscriptions` present.
- All three roles implemented: `to_row()`/`from_row()`, `to_system_prompt()`, `to_code_lens()`/`to_hover()`/`to_code_actions()`/`to_document_symbol()`.

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| 11 | `last_trigger_event: str` and `last_completed_at: float | None` fields from concept doc are missing from `AgentNode`. | **Low** — runtime state fields, easy to add. |

---

## 7. Section 3: Developer Perspective (Config, Bundles, Tools)

**Verdict: ALIGNED** — config matches, bundles work, tools present.

### Config (`remora.yaml`)

Concept specifies:
```yaml
discovery_paths, discovery_languages, discovery_max_workers
bundle_root, bundle_mapping
model_base_url, model_default, model_api_key
swarm_root, max_concurrency, max_turns, max_trigger_depth, trigger_cooldown_ms, timeout_s
```

`src/remora/core/config.py` `Config` class has ALL of these fields plus extras:
- `bundle_mapping_tools` (additional, not in concept)
- `truncation_limit`, `chat_history_limit` (additional)
- `workspace_ignore_patterns`, `workspace_ignore_dotfiles` (additional)
- `nvim_enabled`, `nvim_socket` (additional)

### Bundles

`src/remora/core/manifest.py` — `load_manifest()` loads `bundle.yaml` with: name, system_prompt, agents_dir, model, grammar_config, max_turns, requires_context, limits. Matches concept.

### Built-in Swarm Tools

Concept lists 5: `send_message`, `subscribe`, `unsubscribe`, `broadcast`, `query_agents`.
`src/remora/core/tools/swarm.py` has all 5: `SendMessageTool`, `SubscribeTool`, `UnsubscribeTool`, `BroadcastTool`, `QueryAgentsTool`.

### Grail Tool Discovery

`src/remora/core/tools/grail.py` — `discover_grail_tools()` loads `.pym` scripts + appends swarm tools. Matches concept.

### Spawn/Scaffold Tool

`src/remora/core/tools/spawn_child.py` — `SpawnChildTool` writes stubs, emits `NodeDiscoveredEvent` + `ScaffoldRequestEvent`. Not in concept doc but extends the model correctly.

### Extension Configs

`src/remora/extensions.py` — `AgentExtension` base class, `extension_matches()`, `load_extensions()` from `.remora/models/`. Matches concept.

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| — | No gaps. All described developer-facing features exist. | — |

---

## 8. Section 7: LSP Integration

**Verdict: PARTIALLY ALIGNED** — core LSP features work, some gaps in event emission and SSE.

### What the concept says

| LSP Feature | Mechanism |
|-------------|-----------|
| Code Lens | nodes table → AgentNode → `.to_code_lens()` |
| Hover | nodes table → AgentNode → `.to_hover(recent_events)` |
| Code Actions | nodes table → AgentNode → `.to_code_actions()` |
| Diagnostics | RewriteProposal → LSP diagnostic |
| Did Save | Emit `FileSavedEvent` + `ContentChangedEvent` |
| Did Change | Debounced; incremental tree-sitter re-parsing |
| Custom: Cursor | Debounced (200ms stable) → cursor focus event to EventLog |
| SSE | In-process subscriber → SSE stream via Starlette adapter |

### What exists

| Feature | Status | Notes |
|---------|--------|-------|
| Code Lens | **Working** | `handlers/lens.py` queries EventStore → `agent.to_code_lens()` |
| Hover | **Working** | `handlers/hover.py` queries EventStore → `agent.to_hover(events)` |
| Code Actions | **Working** | `handlers/actions.py` queries EventStore → `agent.to_code_actions()` + proposal actions |
| Diagnostics | **Working** | `documents.py` publishes diagnostics from proposals |
| Did Save events | **Partial** | Emits `NodeDiscoveredEvent`/`NodeRemovedEvent`, but NOT `FileSavedEvent`/`ContentChangedEvent` |
| Did Change | **Not implemented** | No `textDocument/didChange` handler registered. |
| Cursor tracking | **Working** | `notifications.py` `on_cursor_moved` stores to DB. But NOT debounced — handler runs on every call. No cursor focus _event_ appended to EventLog (stored directly in DB table). |
| SSE stream | **Working** | Starlette adapter exists with `/events` SSE stream + Datastar `/subscribe` stream |
| Document Symbol | **Working** | `handlers/lens.py` has `document_symbol` handler (extra, not in concept table) |

### Gaps

| # | Gap | Severity |
|---|-----|----------|
| 10 | **(Duplicate of #10 above)** `did_save` doesn't emit `FileSavedEvent`/`ContentChangedEvent`. Already noted in Section 4. | **High** |
| 12 | **No `textDocument/didChange` handler.** Concept says "Debounced; used for incremental tree-sitter re-parsing." Code has no `did_change` handler at all. Tree-sitter re-parsing only happens on `did_open` and `did_save`. | **Medium** — live editing doesn't update agents until save. |
| 13 | **Cursor tracking not debounced, no EventLog event.** Concept says "Debounced (200ms stable) → cursor focus event to EventLog." Code stores cursor position directly in `cursor_focus` DB table without debouncing and without appending an event to the EventLog. | **Low** — functionally close, but doesn't participate in subscription matching. |

---

## 9. Section 8: Future / Custom CSTNode Types

**Verdict: N/A** — explicitly marked "Future" in concept doc.

This section describes aspirational features:
- Developer-defined node types via custom `.scm` query packs in `.remora/queries/`
- Richer extension configs with structural metadata
- Cross-language semantic links
- Per-type subscription defaults in `remora.yaml`

None of these are implemented, which is expected since the concept marks them as future work.

---

## 10. Two Runner Problem

This is the most significant architectural gap. The codebase has two completely independent agent execution paths:

### Core/CLI path (`SwarmExecutor`)
- `src/remora/core/swarm_executor.py`
- Uses `bundle_mapping` to resolve bundles
- Loads `bundle.yaml` manifests
- Builds workspaces via `CairnWorkspaceService`
- Discovers Grail tools (`.pym`) + swarm tools
- Runs `structured_agents.kernel` with `_EventStoreObserver`
- Kernel events written to EventLog
- Subscription matching triggers further agents

### LSP path (`AgentRunner`)
- `src/remora/lsp/runner.py`
- Does NOT use bundles/manifests
- Does NOT use workspaces
- Has its own `LLMClient` wrapping `structured_agents.client`
- Has its own tool loop (MAX_TOOL_ROUNDS=5)
- Tools: `rewrite_self`, `message_node`, `read_node` (different from core)
- Kernel events NOT written to EventLog
- Emits `LspAgentEvent` for UI display only

### Consequences

1. **Different agent behavior.** The same agent triggered from CLI vs LSP gets different tools, different prompts (no bundle system prompt in LSP path), and different execution semantics.

2. **No audit trail in LSP.** Kernel events from LSP-triggered agents are not in the EventLog, so they can't trigger other agents via subscriptions.

3. **No workspace isolation in LSP.** The core path provides per-agent CoW workspaces via Cairn. The LSP path has no workspace support.

4. **The reactive loop is broken in LSP.** Without `FileSavedEvent`/`ContentChangedEvent` emission and without kernel events in the EventLog, the subscription-matching reactive loop (the core concept of the architecture) only works in CLI mode.

---

## 11. Summary: Gap Priority Matrix

| # | Gap | Section | Severity | Category |
|---|-----|---------|----------|----------|
| 3 | No `.scm` query files (hardcoded AST traversal) | 1.4 | Medium | Architecture |
| 4 | Two separate discovery implementations | 1.4 | Medium | Duplication |
| 5 | Markdown/TOML decomposition incomplete in LSP | 1.4 | Medium | Functionality |
| 6 | **Two runner implementations** | 1.5 | **High** | Architecture |
| 7 | **LSP runner doesn't use bundle_mapping** | 1.5 | **High** | Architecture |
| 8 | **LSP runner doesn't write kernel events to EventLog** | 1.5 | **High** | Architecture |
| 9 | LSP runner has different tools than core runner | 1.5 | Medium | Functionality |
| 10 | **did_save doesn't emit FileSavedEvent/ContentChangedEvent** | 1.5/7 | **High** | Functionality |
| 11 | Missing `last_trigger_event`/`last_completed_at` on AgentNode | 1.7 | Low | Completeness |
| 12 | No `textDocument/didChange` handler | 7 | Medium | Functionality |
| 13 | Cursor tracking not debounced, no EventLog event | 7 | Low | Completeness |

### Priority Grouping

**Critical (blocks the reactive loop):**
- #10: Emit `FileSavedEvent`/`ContentChangedEvent` from `did_save`
- #6, #7, #8: Unify runners or make LSP runner delegate to `SwarmExecutor`

**Important (architectural alignment):**
- #3, #4, #5: Unify discovery + add `.scm` query support
- #9: Unify tool sets between runners
- #12: Add `didChange` handler

**Nice-to-have (completeness):**
- #11: Add missing AgentNode fields
- #13: Debounce cursor tracking + emit as event
