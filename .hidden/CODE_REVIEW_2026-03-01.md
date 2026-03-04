# Remora — Comprehensive Code Review

> **Date:** 2026-03-01
> **Measured against:** `NEOVIM_DEMO_V21_FINAL_CONCEPT.md` — the LSP-native architecture vision
> **Scope:** Every source file in the repository

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Architecture Alignment with V2.1 Concept](#2-architecture-alignment-with-v21-concept)
3. [Code Quality & Elegance Analysis](#3-code-quality--elegance-analysis)
4. [Layer-by-Layer Findings](#4-layer-by-layer-findings)
   - [4.1 Core Library](#41-core-library-srcremora-core)
   - [4.2 LSP Layer](#42-lsp-layer-srcremora-lsp)
   - [4.3 Service / Adapter / UI Layer](#43-service--adapter--ui-layer)
   - [4.4 Demo Layer](#44-demo-layer-remora_demo)
   - [4.5 Neovim Plugins](#45-neovim-plugins)
   - [4.6 Tests](#46-tests)
5. [Ideas](#5-ideas)
6. [Appendix: Cleanup Candidates](#6-appendix-cleanup-candidates)

---

## 1. Executive Summary

Remora is a reactive agent swarm system where code nodes (functions, classes, methods) become autonomous AI agents. The V2.1 concept envisions **LSP as the spine** — Neovim connects to Remora as a language server, Pydantic models define both agent structure and protocol extensions, and features map cleanly to LSP primitives.

**The good news:** The LSP layer (`src/remora/lsp/`) is the strongest part of the codebase. It implements all 9 V2.1 LSP primitives correctly (CodeLens, Hover, CodeAction, Diagnostics, WorkspaceEdit, custom `$/remora/*` notifications). The Pydantic models are well-crafted with proper `@model_validator` and `@computed_field` usage. The handler split into `handlers/` is clean.

**The bad news:** The core library uses stdlib dataclasses where V2.1 says Pydantic. Three separate SQLite databases where one would do. The service/adapter/UI layer (Starlette + Datastar) is a parallel web system that shares almost no code with the LSP layer. Multiple dead code paths, including `nvim/server.py` (pre-LSP JSON-RPC), `plugin/remora_nvim.lua` (legacy plugin), and the entire `models/__init__.py` stdlib-dataclass model set. There are 5 high-severity bugs.

**Lines of code analyzed:** ~12,000+ across 80+ Python files, 4 Lua files, Nix config, YAML, VimL.

---

## 2. Architecture Alignment with V2.1 Concept

### Scorecard

| V2.1 Requirement | Status | Evidence |
|---|---|---|
| **LSP is the spine** | **ALIGNED** | pygls `LanguageServer`, stdio transport, proper LSP lifecycle |
| **Pydantic models are the bridge** | **PARTIAL** | LSP layer uses Pydantic excellently; core layer uses stdlib `@dataclass` for Config, events, agent state |
| **CodeLens = agent IDs** | **ALIGNED** | `ASTAgentNode.to_code_lens()` — `lsp/models.py:172` |
| **Hover = agent details** | **ALIGNED** | `ASTAgentNode.to_hover()` with events, graph context — `lsp/models.py:191` |
| **CodeAction = tools** | **ALIGNED** | `ASTAgentNode.to_code_actions()` + extension tools — `lsp/models.py:237` |
| **Diagnostics = proposals** | **ALIGNED** | `RewriteProposal.to_diagnostic()` — `lsp/models.py:336` |
| **WorkspaceEdit = apply changes** | **ALIGNED** | `RewriteProposal.to_workspace_edit()` — `lsp/models.py:311` |
| **Custom `$/remora/*` notifications** | **ALIGNED** | event, requestInput, submitInput, cursorMoved, agentsUpdated, agentSelected |
| **Minimal Lua client** | **ALIGNED** | `init.lua` is setup + handlers; `panel.lua` is optional UI |
| **Single SQLite database** | **NOT ALIGNED** | 4 separate databases: EventStore, SubscriptionRegistry, SwarmState, RemoraDB (LSP) |
| **Pydantic Config** | **NOT ALIGNED** | `Config` is `@dataclass(slots=True)` with manual serialization |
| **Pydantic agent state** | **NOT ALIGNED** | `AgentState` is a plain dataclass with JSONL persistence |
| **Clean file structure** | **PARTIAL** | V2.1 proposes `remora/{lsp,core,agent,nvim}`. Actual has `remora/{lsp,core,cli,service,adapters,models,ui,nvim,utils}` — more sprawl |

### Assessment

The LSP integration is the crown jewel and closely matches the V2.1 vision. The divergence is in the core layer, which predates the V2.1 concept and uses a different modeling strategy. The service/adapter/UI layer is an entirely separate system (web-based Datastar UI) that the V2.1 concept doesn't mention — it's orthogonal, not misaligned.

---

## 3. Code Quality & Elegance Analysis

### Strengths

- **LSP models** (`lsp/models.py`): Best file in the codebase. Pydantic models with clean `@model_validator(mode="before")`, `@computed_field` for diffs, and well-typed LSP conversion methods (`to_code_lens`, `to_hover`, `to_code_actions`, `to_diagnostic`, `to_workspace_edit`). This is exactly what V2.1 envisions.

- **Handler split**: The `lsp/handlers/` package cleanly separates concerns: `documents.py` (sync), `hover.py`, `lens.py`, `actions.py`, `commands.py`, `capabilities.py`. Each file is focused and readable.

- **Type annotations throughout**: Consistent use of `from __future__ import annotations`, `TYPE_CHECKING` imports, proper union types. The core library in particular has excellent type coverage.

- **Event hierarchy**: `core/events.py` uses frozen dataclasses with `slots=True` — correct immutability choice. Seven clean error types in `core/errors.py`.

- **`PathResolver`**: Elegant frozen dataclass for path normalization (`utils/path_resolver.py`).

- **Graph Viewer v2** (`remora_demo/graph/`): Clean architecture — d3-force on client, Datastar signals for reactivity, server-rendered sidebar with tabs. Well-tested (32 new tests).

- **Clean `__all__` exports**: Every module defines `__all__`. Barrel files are consistent.

### Weaknesses

- **Three+ SQLite databases**: EventStore, SubscriptionRegistry, SwarmState each open separate DBs. The LSP layer's `RemoraDB` is a fourth. The graph viewer opens a fifth connection. Cross-table queries are impossible. Transaction coordination requires manual orchestration in the reconciler. This is the single biggest architectural flaw.

- **Manual serialization everywhere**: `Config.serialize_config` manually enumerates fields. `AgentState` uses hand-rolled JSONL. `models/__init__.py` has `ConfigSnapshot.from_config()/to_dict()`. With Pydantic, all of this would be `model_dump()`.

- **Stringly-typed dependency injection**: Swarm tools receive `externals: dict[str, Any]` and look up keys at runtime. No type checking, no interface contract. Tool dependencies are invisible at the type level (`tools/swarm.py`).

- **Duplicate kernel setup**: `chat.py` and `SwarmExecutor` both build their own client/adapter/kernel independently. These will drift.

- **Inconsistent defaults**: Three different model configs — `config.py` defaults to `Qwen/Qwen3-4B`, `chat.py` defaults to `Qwen/Qwen3-4B-Instruct-2507-FP8`, `lsp/__main__.py` hardcodes `Qwen/Qwen3-4B-Instruct-2507-FP8`. Three different `model_base_url` defaults.

- **Dead code accumulation**: `nvim/server.py`, `plugin/remora_nvim.lua`, `models/__init__.py`, `vcs.py` (commented out in executor), `TreeSitterDiscoverer` legacy wrapper, `load.vim`.

---

## 4. Layer-by-Layer Findings

### 4.1 Core Library (`src/remora/core/`)

~3,900 lines across 20 modules. This is the framework-agnostic runtime.

#### HIGH SEVERITY

| ID | File:Line | Finding |
|---|---|---|
| **F-12** | `swarm_executor.py:270` | **Parser/model mismatch.** `get_response_parser(manifest.model)` selects parser for the manifest's model, but `_resolve_model_name()` can override to a different model at runtime. Parser may not match actual model response format. |
| **F-17** | `reconciler.py:130-161` | **Stale metadata.** For existing agents, reconciler only emits `ContentChangedEvent` — does NOT update metadata (name, line range, etc.). If a function moves from line 10 to line 50, SwarmState retains old positions. CodeLens will point to wrong lines. |
| **F-21** | `chat.py:209` | **`AttributeError` at runtime.** Calls `self._workspace.cleanup()` which doesn't exist on `CairnWorkspaceService` (should be `close()`). |
| **F-27** | `config.py`, `chat.py`, `lsp/__main__.py` | **Three different default model configs.** Inconsistent defaults will cause silent failures when moving between contexts. |
| **F-32** | `swarm_executor.py:116` | **Latent `NameError`.** `_broadcast` closure references bare `emit_event` variable not in scope — should be `_emit_event`. Will crash the first time broadcast is actually called. |

#### MEDIUM SEVERITY

| ID | File:Line | Finding |
|---|---|---|
| F-01 | `config.py:37` | Config uses `@dataclass(slots=True)`, not Pydantic. No validation, no env var override, no schema generation. |
| F-03 | `config.py:22` / `discovery.py:307` | Duplicate ignore pattern definitions. Discovery has its own hardcoded set, ignores config's `workspace_ignore_patterns`. |
| F-07 | `event_store.py` | Three modules each with own SQLite connection + asyncio.Lock + `to_thread` wrapper. Should share a connection or use aiosqlite. |
| F-08 | Multiple | Three separate SQLite databases for core alone. No cross-table queries, no transaction coordination. |
| F-09 | `agent_state.py:69-80` | JSONL append-only with no compaction. `load()` reads entire file. Unbounded growth. |
| F-10 | `agent_runner.py:80-82` | Cascade prevention uses `"base"` fallback for uncorrelated events — all share same depth counter per agent. |
| F-14 | `swarm_executor.py:344` | Prompt includes last 5 chat history entries AND kernel gets full history as messages. Model sees duplicate context. |
| F-15 | `subscriptions.py:243` | Pattern matching loads ALL subscriptions from SQLite every time. O(n) per event. |
| F-18 | `cairn_bridge.py:138` | Workspace sync reads entire project via `rglob("*")`. No incremental sync, no mtime check. |
| F-19 | `cairn_bridge.py:164-166` | `ensure_file_synced` is a stub — returns `True` without syncing. |
| F-31 | `tools/swarm.py` | Externals dict as stringly-typed DI. No interface contract. |

#### LOW SEVERITY

| ID | File:Line | Finding |
|---|---|---|
| F-02 | `config.py:117-153` | `serialize_config` manually enumerates fields. |
| F-04 | `events.py:103` | `AgentMessageEvent.tags` is mutable `list[str]` on a frozen dataclass. Should be `tuple[str, ...]`. |
| F-05 | `events.py:138-162` | `FileSavedEvent` and `ManualTriggerEvent` not re-exported from `core/__init__.py`. |
| F-06 | `event_bus.py:56-57` | Handler errors logged as warning and swallowed. No dead-letter pattern. |
| F-11 | `swarm_executor.py:273` | New LLM client created per execution. No connection pooling. |
| F-13 | `swarm_executor.py:229` | Chat history hardcoded to last 10 entries. Not configurable. |
| F-22 | `chat.py:212-258` | Two different tool creation patterns: `Tool.from_function` vs `ToolSchema + execute`. |
| F-23 | `vcs.py` | Only supports Jujutsu. Commented out in executor. Dead code. |
| F-24 | `discovery.py:338-362` | `TreeSitterDiscoverer` legacy wrapper with dead `query_pack` parameter. |
| F-26 | `swarm_executor.py:333` | Code fences in prompt lack language tag (`python`). |
| F-28 | `config.py:92-103` | `_find_config_file` returns non-existent sentinel path. Works but not obvious. |
| F-30 | `tools/grail.py:98-105` | `build_virtual_fs` adds both `/path` and `path` entries, doubling memory. |

---

### 4.2 LSP Layer (`src/remora/lsp/`)

~2,200 lines across 15 files + handlers. This is the strongest layer.

#### Issues

| ID | Severity | File:Line | Finding |
|---|---|---|---|
| L-01 | Medium | `__main__.py:15-18` | Hardcoded LLM config (`remora-server:8000`, `Qwen/Qwen3-4B-Instruct-2507-FP8`). Should come from config/env. |
| L-02 | Medium | `__main__.py:26` | `_notify_agents_updated` monkey-patched onto `server` via attribute assignment. Then checked with `hasattr()` in handlers. Should be a proper method on `RemoraLanguageServer`. |
| L-03 | Medium | `server.py:30` | Module-level singleton `server = RemoraLanguageServer()`. Instantiates DB/Graph/Watcher on import. Import has side effects (creates `.remora/indexer.db`). Difficult to test. |
| L-04 | Low | `runner.py:70` | `_load_agent_state` always returns `None`. Dead stub for SwarmExecutor integration. |
| L-05 | Low | `handlers/documents.py:82-87` | `did_save` re-does ID matching that `watcher.parse_and_inject_ids` already does. Redundant. |
| L-06 | Medium | `graph.py:25` | `LazyGraph` opens its own SQLite connection separate from `RemoraDB`. Two connections to same DB. |
| L-07 | Medium | `runner.py:160-180` | `_extract_text_tool_calls` parses `<tool_call>` XML tags. Model-specific workaround for Qwen, not documented or configurable. |
| L-08 | Medium | `handlers/documents.py` | `inject_ids` writes `# rm_xxx` comments into Python files on save. Invasive. V2.1 concept includes this, but it causes re-save loops requiring a `_injecting` guard flag. |
| L-09 | Low | `db.py` | `async_db` decorator wraps every sync SQLite call in `asyncio.to_thread`. Works but adds overhead. Could use aiosqlite. |
| L-10 | Medium | `db.py:_reconstruct_event` | Creates base `AgentEvent` not the original subclass. Round-tripping events through DB loses type information. |
| L-11 | Medium | `db.py` / `runner.py` | `push_command` is sync, `poll_commands` is called from async context via `asyncio.to_thread`. Inconsistent sync/async boundary. |

---

### 4.3 Service / Adapter / UI Layer

This layer (`src/remora/service/`, `src/remora/adapters/`, `src/remora/ui/`, `src/remora/models/`) is a parallel web system using Starlette + Datastar for a browser-based dashboard. It shares the core library but NOT the LSP layer.

#### Issues

| ID | Severity | File:Line | Finding |
|---|---|---|---|
| S-01 | **Bug** | `service/api.py:167,186` | **Method name collision.** `get_subscriptions` appears as both a property (returns `SubscriptionRegistry | None`) and a method (takes `agent_id`, returns `list[dict]`). Linter flags this as an error. |
| S-02 | Medium | `service/chat_service.py` | Module-level `state = ChatServiceState()` singleton. Separate from LSP. Hardcodes model defaults. Uses deprecated `@app.on_event("startup")`. |
| S-03 | Medium | `adapters/starlette.py` | Type errors: `DatastarResponse` content type mismatch (`AsyncIterator[str]` vs `DatastarEvents`). Possible `None` event_type passed to `emit_event`. |
| S-04 | Medium | `models/__init__.py` | Uses stdlib `dataclasses`, not Pydantic. `ConfigSnapshot` has manual `from_config()`/`to_dict()` that Pydantic would auto-generate. Inconsistent with LSP layer. |
| S-05 | **Bug** | `ui/projector.py:132-133` | `total_agents` counter only increments when `total_agents == 0`. Stays at 1 forever after first agent starts. |
| S-06 | Low | `ui/projector.py` | `_to_jsonable` uses `asdict` — linter flags type mismatch with non-dataclass inputs. |
| S-07 | Low | `ui/view.py` | `render_blocked_list` creates `List(items=cards)` with type invariance issue. `render_tag` labeled "Legacy function" but still present. |
| S-08 | Low | `ui/components/dashboard.py` | Inline JavaScript in data attributes for Datastar reactivity. `BlockedAgentCard` XSS concern: uses simple quote replacement for escaping. |

---

### 4.4 Demo Layer (`remora_demo/`)

Two separate viewers + Neovim starter files.

#### `remora_demo/web/` — Hierarchical Tree Layout Viewer

- `layout.py` (625 lines): Deterministic tree layout with cursor-reactive expand/collapse. Directory trie, visibility classification, hybrid-ripple model. Well-structured with clear dataclasses (`NodePosition`, `GroupBox`, `DirGroupBox`, `CollapsedDir`, `FocusBBox`, `LayoutResult`).
- `render.py` (759 lines): Server-side HTML rendering with Catppuccin theme. Inline CSS/JS. Zoom/pan/fit/follow mode.
- `state.py` (179 lines): WAL-based change detection with poll fallback. Clean `GraphSnapshot` dataclass.
- `app.py` (86 lines): Clean Starlette routes.

**Quality:** Good. The layout algorithm is the most complex piece and is well-decomposed. The CSS/JS being inline strings is acceptable for a single-page tool.

#### `remora_demo/graph/` — Force-Directed Graph Viewer (v2)

- `shell.py` (510 lines): d3-force simulation with SVG rendering. Datastar signal integration via `MutationObserver`. Zoom/pan/follow mode.
- `sidebar.py` (154 lines): Server-rendered sidebar with tabs (Log, Source, Connections, Actions). Proposal approve/reject buttons.
- `state.py` (192 lines): Same pattern as web/state.py — poll-based fingerprint change detection. Adds `proposals` table to fingerprint and `push_command` for command queue.
- `app.py` (126 lines): Adds `POST /command` route beyond the web viewer's routes.

**Quality:** Good. The d3-force viewer is the newer, more interactive version. The sidebar is well-structured with proper HTML escaping.

**Issues:**

| ID | Severity | Finding |
|---|---|---|
| D-01 | Low | `web/state.py` and `graph/state.py` duplicate 80% of their code. `GraphSnapshot`, `_get_conn`, `read_snapshot`, `_fingerprint`, `changes`, `close` are nearly identical. Should share a base class. |
| D-02 | Low | `web/layout.py:_watch_wal` is declared as `async def` returning `AsyncIterator` but is called from `changes()` which tries to `await` it — the `return` on line 132 means it never actually yields. Dead code path (falls through to poll). |
| D-03 | Low | Both viewers use the `datastar_py` library with RC7 CDN URL — pinned to a pre-release version. |
| D-04 | Low | `shell.py` reads `document.body.dataset.signals` (line 434-435) which may not reflect Datastar's internal signal state correctly. Works due to MutationObserver but is coupling to implementation details. |

#### `remora_demo/__main__.py`

Imports from `tests.fixtures.mock_llm` — test fixture used in production entry point. Works but odd coupling.

#### `remora_demo/nvim/`

- `remora_starter.lua` (276 lines): Comprehensive but duplicates commands from `lsp/nvim/lua/remora/init.lua`. Uses older `vim.lsp.start` API vs `init.lua`'s `vim.lsp.enable`. They're incompatible approaches.
- `remora.vim` (74 lines): Thin VimL wrapper that calls Lua. No added value.

---

### 4.5 Neovim Plugins

Three separate Neovim plugin systems exist:

| Plugin | Location | API | Status |
|---|---|---|---|
| **LSP-native** | `src/remora/lsp/nvim/lua/remora/` | `vim.lsp.config` + `vim.lsp.enable` (Neovim 0.11+) | **Active, correct** |
| **Demo starter** | `remora_demo/nvim/lua/remora_starter.lua` | `vim.lsp.start` (older API) | Duplicate, conflicts |
| **Legacy JSON-RPC** | `plugin/remora_nvim.lua` | Custom `remora_nvim` module | **Dead code** |

The LSP-native plugin (`init.lua` + `panel.lua`) is the correct path. Issues:

| ID | Severity | Finding |
|---|---|---|
| N-01 | Medium | `panel.lua` line 2: `require("nui.popup")` at module level. Hard crashes if `nui.nvim` not installed. Should wrap in `pcall`. |
| N-02 | Medium | `panel.lua`: `M.is_open` is both a boolean field (`M.state.is_open`) and a function (line 120). `init.lua` checks `M.sidepanel.is_open` which gets the function (always truthy). |
| N-03 | Low | `panel.lua`: `buf_options = { readonly = true }` — `readonly` is a window option in nui.nvim, not a buffer option. |
| N-04 | Low | `init.lua`: `cmd` defaults to `"remora-lsp"` which is correct, but `remora_starter.lua` uses `"python -m remora_demo.lsp.server"`. |

---

### 4.6 Tests

**Test file count:** 27 test files + 7 fixture files + helpers.

**Coverage by layer:**

| Layer | Tests | Notes |
|---|---|---|
| Core: EventStore | `test_event_store.py`, `test_event_store_integration.py` | Good coverage |
| Core: EventBus | `test_event_bus.py` | Basic coverage |
| Core: Subscriptions | `test_subscriptions.py` | Good coverage |
| Core: SwarmState | `test_swarm_state.py` | Good coverage |
| Core: Discovery | `test_discovery.py`, `test_multilanguage_discovery_real.py`, `test_real_code_discovery_real.py` | Good coverage |
| Core: Swarm/chat/reconciler/workspace | **None** | **Gap** — SwarmExecutor, AgentRunner, Reconciler, Workspace have zero tests |
| LSP: Models | `test_lsp_models.py` | Good — tests Pydantic models and LSP conversions |
| LSP: DB | `test_lsp_db.py` | Good |
| LSP: Watcher | `test_lsp_watcher.py` | Good |
| LSP: Server/Handlers | `test_lsp_integration.py` | Integration test exists |
| LSP: Runner | `test_agent_runner.py` | Integration test |
| Demo: Graph viewer v2 | `test_graph_app.py`, `test_graph_state.py`, `test_graph_shell.py`, `test_graph_sidebar.py`, `test_graph_cli.py`, `test_graph_integration.py`, `test_command_queue.py`, `test_command_polling.py` | **Excellent** — 32 tests, comprehensive |
| Demo: Web viewer | `test_web_layout.py` | Layout algorithm tested |
| Service/UI/Adapters | **None** | **Gap** |
| Cairn integration | 8 test files in `tests/integration/cairn/` | Good coverage |

**Test quality observations:**
- Fixtures are well-designed (`conftest.py` provides `DummyKernel`, real component fixtures).
- `MockLLMClient` always returns empty `tool_calls` — useful for testing infrastructure, not agent behavior.
- Graph viewer v2 has the best test coverage in the project — result of the recent implementation effort.
- Major gaps: no tests for SwarmExecutor, Reconciler, chat.py, workspace.py, service layer, or UI components. This is where the high-severity bugs (F-21, F-32) hide untested.

---

## 5. Ideas

### I-01: Unified Pydantic Config

Replace `Config` dataclass with Pydantic `BaseSettings`. Get env var override, validation, `.env` file loading, JSON Schema generation for free. Define model config as a nested `LLMConfig` model. Eliminate all three scattered default model configs.

```python
class LLMConfig(BaseModel):
    base_url: str = "http://localhost:8000/v1"
    model: str = "Qwen/Qwen3-4B"
    api_key: str = "EMPTY"

class RemoraSettings(BaseSettings):
    llm: LLMConfig = LLMConfig()
    # ... all other config
    model_config = SettingsConfigDict(env_prefix="REMORA_")
```

### I-02: Single SQLite Database

Merge EventStore, SubscriptionRegistry, SwarmState, and RemoraDB into one database with separate tables. Share a single connection (with WAL mode). Cross-table queries become possible (e.g., "which agents have unprocessed triggers?"). Remove 3 separate `asyncio.Lock` instances.

### I-03: Typed Externals Protocol

Replace `dict[str, Any]` externals with a typed protocol:

```python
class AgentContext(BaseModel):
    agent_id: str
    config: RemoraSettings
    emit_event: Callable
    workspace: CairnWorkspaceService
    subscriptions: SubscriptionRegistry
    # ...
```

Tools declare dependencies as typed fields. SwarmExecutor constructs the typed context.

### I-04: Kernel Factory

Extract client/adapter/kernel creation from both `SwarmExecutor._run_kernel` and `ChatSession.send` into a shared factory:

```python
def create_kernel(config: LLMConfig, tools: list[ToolSchema]) -> Kernel:
    client = build_client(config.base_url, config.api_key)
    adapter = build_adapter(client, config.model)
    return Kernel(adapter=adapter, tools=tools)
```

### I-05: Incremental Workspace Sync

Replace full-project `rglob("*")` sync with:
1. File mtime comparison on startup
2. `watchfiles` for runtime change detection
3. Content-hash dedup to skip unchanged files

### I-06: Event Bus with Error Escalation

Add configurable error handlers:
```python
bus = EventBus(on_error=ErrorPolicy.LOG)       # current behavior
bus = EventBus(on_error=ErrorPolicy.PROPAGATE)  # for testing
bus = EventBus(on_error=ErrorPolicy.DEAD_LETTER) # for production
```

### I-07: AgentState Compaction

Switch from JSONL append to single-JSON write, or add periodic compaction that rewrites the file with only the latest entry.

### I-08: Subscription Index

Cache subscriptions in memory with invalidation on register/unregister. Index by event_type for O(1) lookup instead of loading all rows on every event.

### I-09: Consolidate Graph State Readers

`web/state.py` and `graph/state.py` share 80% of code. Extract a `BaseGraphState` class:

```python
class BaseGraphState:
    """Shared SQLite reader with WAL change detection."""
    def read_snapshot(self) -> GraphSnapshot: ...
    def read_node(self, node_id: str) -> dict | None: ...
    def _fingerprint(self) -> str: ...
    async def changes(self) -> AsyncIterator[GraphSnapshot]: ...
```

### I-10: Remove ID Injection from Files

The `# rm_xxx` comments written into source files on save are invasive and cause re-save loops. Keep IDs purely in the database and use line-range matching (already done for CodeLens positioning). The V2.1 concept includes ID injection, but in practice the database is the source of truth.

### I-11: Connection Pooling for LLM Client

Create the LLM client once per `SwarmExecutor` lifecycle and reuse across agent turns. The HTTP client can maintain a connection pool to the model server.

### I-12: Replace `_notify_agents_updated` Monkey-Patch

Make `notify_agents_updated` a proper method on `RemoraLanguageServer`:

```python
class RemoraLanguageServer(LanguageServer):
    async def notify_agents_updated(self, uri: str):
        nodes = await self.db.get_nodes_for_file(uri)
        self.send_notification("$/remora/agentsUpdated", ...)
```

### I-13: Web Viewer as Optional Extra

The Starlette/Datastar web viewers (`remora_demo/web/` and `remora_demo/graph/`) could become an optional `remora[web]` extra with their dependencies (`uvicorn`, `starlette`, `datastar-py`) in a separate dependency group.

---

## 6. Appendix: Cleanup Candidates

Everything that should be removed from the repository. No backwards compatibility concerns.

### Dead Code — Remove Entirely

| File/Directory | Reason |
|---|---|
| `plugin/remora_nvim.lua` | Legacy pre-LSP plugin. References `remora_nvim.sidepanel`, `remora_nvim.chat` which don't exist in LSP architecture. |
| `src/remora/nvim/` (`__init__.py`, `server.py`) | Pre-LSP JSON-RPC `NvimServer` via Unix socket. Completely superseded by `lsp/`. |
| `src/remora/core/vcs.py` | Only supports Jujutsu. Commented out in SwarmExecutor. 35 lines of dead code. |
| `src/remora/core/discovery.py:338-362` | `TreeSitterDiscoverer` legacy wrapper. Dead `query_pack` parameter. |
| `load.vim` | References `remora_nvim` (legacy plugin). |
| `remora_demo/nvim/remora.vim` | Thin VimL wrapper adding no value over Lua. |

### Dead/Duplicate Code — Consolidate

| File | Action |
|---|---|
| `remora_demo/nvim/lua/remora_starter.lua` | Merge any unique functionality into `src/remora/lsp/nvim/lua/remora/init.lua`, then delete. Both define conflicting commands. |
| `src/remora/models/__init__.py` | Uses stdlib dataclasses while LSP layer uses Pydantic. Either migrate to Pydantic or delete if service layer is refactored. |
| `remora_demo/web/state.py` + `remora_demo/graph/state.py` | 80% duplicate code. Extract shared base class. |
| `src/remora/core/config.py:85-87` | Local `from remora.core.errors import ConfigError` import is redundant — already imported at module level (line 156). |

### Stale Dependencies

| Item | Issue |
|---|---|
| `nui.nvim` / `nui-components.nvim` | `panel.lua` hard-depends on this. Should be behind `pcall` with graceful degradation. |
| `rustworkx` import in `lsp/graph.py` | Guarded by try/except (good), but linter flags unresolved import. |

### Config Hygiene

| File | Issue |
|---|---|
| `remora.yaml` | Contains `model_base_url: "http://remora-server:8000/v1"` — machine-specific. Should be in `.gitignore` or use env vars. |
| `devenv.nix:5` | Absolute path: `imports = [ /home/andrew/Documents/Projects/nixvim/devenv.nix ]`. Machine-specific. |

### Type Errors (from diagnostics)

| File | Error |
|---|---|
| `service/api.py:167,186` | `get_subscriptions` method name collision |
| `lsp/graph.py` | `rustworkx` import unresolved, `rx` possibly unbound |
| `ui/projector.py` | `asdict` argument type mismatch |
| `ui/view.py` | List type invariance with `BlockedAgentCard` |
| `adapters/starlette.py` | `DatastarResponse` content type mismatch, possible `None` in `emit_event` |

---

*Review complete. All source files in the repository have been read and analyzed.*
