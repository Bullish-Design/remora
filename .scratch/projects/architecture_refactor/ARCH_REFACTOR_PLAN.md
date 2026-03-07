# Remora Architecture Refactor Plan

> Independent analysis and validated refactoring plan based on the
> `ARCH_REFACTOR_REPORT.md` findings, the `tach_module_graph.dot` dependency
> graph, and a direct source-code audit of every package in `src/remora/`.

---

## Table of Contents

1. **[Validation of Original Report](#1-validation-of-original-report)** — Which claims hold, which need nuance.
2. **[Additional Issues Discovered](#2-additional-issues-discovered)** — Problems the original report missed.
3. **[Proposed Layer Architecture](#3-proposed-layer-architecture)** — Target dependency graph.
4. **[Refactor Phase 1 — Sever Core → LSP/Companion/Extensions](#4-refactor-phase-1)** — Eliminate layer violations.
5. **[Refactor Phase 2 — Break LSP Circular Dependencies](#5-refactor-phase-2)** — Untangle the server singleton.
6. **[Refactor Phase 3 — Decompose God-Objects & Group Core](#6-refactor-phase-3)** — Split oversized modules & create subpackages.
7. **[Refactor Phase 4 — Introduce Server Protocol](#7-refactor-phase-4)** — Formalize the duck-typing.
8. **[Refactor Phase 5 — Cleanup & Polish](#8-refactor-phase-5)** — Entrypoints, deduplication, naming.
9. **[Verification Plan](#9-verification-plan)** — How to confirm correctness.
10. **[Risk Assessment](#10-risk-assessment)** — What could go wrong.

---

## 1. Validation of Original Report

The original `ARCH_REFACTOR_REPORT.md` identified five issues. All five are **confirmed** by direct
source inspection, with some needing additional nuance.

### 1.1 Core -> LSP Layer Violation — Confirmed (Critical)

**Claim:** `remora.core` imports `remora.lsp.runner`.

**Evidence:** `core/__init__.py` line 65: `from remora.lsp.runner import AgentRunner`. This is
the most severe layer violation — it forces the entire LSP stack (pygls, lsprotocol) to load whenever
`import remora.core` is evaluated. `AgentRunner` itself is ~743 lines and drags in `lsp.server`,
`lsp.handlers`, `lsp.models`, and `lsp.db`.

**Graph edge:** `"remora.core" -> "remora.lsp.runner"` (line 223 of dot file).

### 1.2 Core -> Companion Layer Violation — Confirmed (Critical)

**Claim:** `remora.core.events` imports from `remora.companion.events`.

**Evidence:** `core/events.py` line 227: `from remora.companion.events import CompanionEvent`.
The companion events are then folded into the `RemoraEvent` union type at the bottom of the file.
This means core cannot be imported/tested without the companion package. The dependency direction
is backwards — companion should depend on core, not vice-versa.

**Graph edge:** `"remora.core.events" -> "remora.companion.events"` (line 80).

**Nuance:** The companion events already inherit from `core.events._FrozenEvent`, so the dependency
*from* companion -> core is correct. The *reverse* dependency (importing `CompanionEvent` back into
the `RemoraEvent` union type) is the violation. The union type needs a different composition strategy.

### 1.3 Core -> Extensions Layer Violation — Confirmed (Moderate)

**Claim:** `remora.core.projections` depends on `remora.extensions`.

**Evidence:** `core/projections.py` line 23: `from remora.extensions import extension_matches`.
`NodeProjection._project_node_discovered()` calls `extension_matches()` to apply extension
configs during node upsert. This means projections cannot operate without the extension loading
machinery (which does dynamic `importlib` loading of user `.py` files).

**Graph edge:** `"remora.core.projections" -> "remora.extensions"` (line 205).

**Better approach:** `NodeProjection.__init__` already accepts `extension_configs: list[type]`.
The projection should receive a pre-built matcher callable instead of importing the extension
module directly.

### 1.4 LSP Circular Dependencies — Confirmed (High)

**Claim:** `remora.lsp.server` <-> `remora.lsp.handlers` and `remora.lsp.server` <-> `remora.lsp.notifications`.

**Evidence:**
- `server.py` line 259: `register_handlers()` is called at **module level** (not deferred), which
  force-imports all handler modules. Handlers import `server` for the global singleton.
- `server.py` line 237: `server = get_server()` — a **module-level** singleton created eagerly.
- `notifications.py` line 9: `from remora.lsp.server import emit_event, logger, server`.
- `lsp/handlers/commands.py`, `documents.py`, etc. all do `from remora.lsp.server import server`.

The cycle works today only because Python caches partially-initialized modules, but it is fragile
and creates tight coupling. Every handler/notification module statically binds to the singleton.

### 1.5 LSP Entrypoint Leakage — Confirmed (Low)

**Claim:** `remora.lsp.__init__` imports `remora.lsp.__main__`.

**Evidence:** Graph edge `"remora.lsp" -> "remora.lsp.__main__"` (line 217). The `lsp/__init__.py`
defines a `main()` function (line 340-432) that embeds what should be in `__main__.py`. The
`__init__.py` is 452 lines — a process lock manager, a parent-process watchdog, signal handlers,
and the full startup sequence are all in the library surface.

### 1.6 Service -> UI Coupling — Confirmed (Acceptable for now)

**Claim:** `remora.service.api` imports UI rendering components.

**Evidence:** `service/api.py` lines 27-29 import `UiStateProjector`, `render_dashboard`. This is
a Datastar BFF pattern — the service layer renders HTML fragments. Architecturally impure but
operationally correct for the current use case. **Lowest priority.**

---

## 2. Additional Issues Discovered

The original report missed several significant problems found during direct source inspection.

### 2.1 God Object: EventStore (1193 lines)

`core/event_store.py` is **1193 lines** — the largest file in the codebase by far. It handles:
- SQLite connection management (write connection, read connection, thread-local cursors)
- Schema creation and migration (10+ tables)
- Write operations with retry logic, lock diagnostics, and recovery
- Event append with routing, subscription matching, and trigger queueing
- Event replay and query APIs
- Node hydration (`get_node`, `get_node_at_position`, `list_all_nodes`)
- Graph management (`delete_graph`)
- Chat history management
- Projection application within transactions

This violates SRP and makes the module extremely hard to reason about and test. It should be
decomposed into at least 3-4 focused modules.

### 2.2 God Object: AgentRunner (743 lines in runner.py)

`lsp/runner.py` is **743 lines** containing:
- The `AgentRunner` class (~650 lines) — trigger queueing, execution coordination, cascade depth
  tracking, cooldown management, tool loop, command polling
- `_HeadlessServer` / `_HeadlessDB` — duck-typed stubs for CLI mode
- `Trigger` model

`AgentRunner` mixes LSP-specific concerns (command queue polling, `_HeadlessServer`) with
transport-agnostic execution coordination. The `_HeadlessServer` duck-type is an informal protocol
that should be formalized (see Phase 4).

### 2.3 Bloated lsp/__init__.py (452 lines)

The LSP package's `__init__.py` contains:
- `_WorkspaceProcessLock` class (230 lines) — file-locking, heartbeat, stale-owner reclamation
- `_ParentProcessWatchdog` class (50 lines)
- `_install_signal_handlers()` function
- `main()` function (90 lines) — full server startup sequence

This should be split into at least `lsp/process_lock.py` and the startup moved to `__main__.py`.
The `__init__.py` should only contain re-exports.

### 2.4 No Formal Server Protocol

`AgentRunner.__init__` accepts `server: RemoraLanguageServer`, but
`AgentRunner.create_headless()` passes a `_HeadlessServer` instance that merely duck-types the
same interface. There is no `Protocol` or `ABC` defining the contract. This makes the boundary
invisible and fragile — any new attribute added to `RemoraLanguageServer` that `AgentRunner`
calls will silently break headless mode.

### 2.5 Duplicated Language Extension Maps

`_LANG_TAGS` / `LANGUAGE_EXTENSIONS` / `_EXT_TO_LANG` appear in:
- `core/discovery.py` (lines 28-37, `LANGUAGE_EXTENSIONS`)
- `core/execution.py` (lines 56-68, `_LANG_TAGS`)
- `core/agent_node.py` (lines 21-33, `_EXT_TO_LANG`)

Three separate dicts mapping file extensions to language names, each covering a slightly different
set. Should be consolidated into a single source of truth in `utils/`.

### 2.6 core.events RemoraEvent Union — Fragile Composition

The `RemoraEvent` type alias is built by importing `CompanionEvent` at the bottom of
`core/events.py` (line 227) and including it in the union. This hard-codes every event subsystem
into core. A plugin/feature that wants to add events must modify `core/events.py`.

**Better approach:** Define `CoreEvent` as the union of only core events in `core/events.py`.
Let `companion.events` define `CompanionEvent` separately. Consumers that need the combined type
can import both. The `EventStore` and `EventBus` should accept `BaseModel` (or `_FrozenEvent`)
rather than the specific union type.

### 2.7 Module-Level Side Effects in lsp/server.py

`lsp/server.py` lines 237 and 259:

    server = get_server()    # creates singleton at import time
    register_handlers()      # force-imports all handler modules at import time

This means importing `remora.lsp.server` has side effects: it creates a LanguageServer instance
and registers all LSP handlers. This breaks testability (every test that imports the module gets
a real server) and creates the circular import cycles noted in 1.4.

### 2.8 SQL Fragmentation (Expanded)

The original report noted scattered SQL. The actual scope is wider than reported:

| Module | SQL Concern |
|--------|------------|
| `core/event_store.py` | Schema DDL (10+ tables), all event CRUD, node queries, chat history |
| `core/subscriptions.py` | Subscription CRUD |
| `core/projections.py` | Node upsert/delete/status updates |
| `lsp/db.py` | Edge management, proposals, commands, cursor tracking |
| `lsp/graph.py` | Node relationship queries |

A `queries/` directory already exists in `src/remora/queries/`, but it contains **tree-sitter
.scm query files** for code discovery — not SQL. The name collision is confusing. SQL should
be centralized into a new module (e.g., `core/sql.py` or `core/schema.py`), or at minimum the
constants should be extracted from inline strings to named variables.

### 2.9 core/tools/ Sub-Modules Blur LSP Boundary

`core/tools/lsp.py` (10795 bytes) contains LSP-specific tool implementations inside `core/tools/`.
File name suggests it belongs in `lsp/` or at least behind an interface boundary. This blurs the
line between transport-agnostic tools and LSP-specific tools.

### 2.10 core/chat.py Reinvents Tool Wrapping

`core/chat.py` defines `FunctionTool` and `build_chat_tools()` — a separate tool-wrapping
mechanism parallel to the `core/tools/` module and the `structured_agents.Tool` protocol. This is
a DRY violation and should be consolidated with the existing tool infrastructure.

---

## 3. Proposed Layer Architecture

```
+----------------------------------------------------------+
|                    Entrypoints                           |
|  remora.__main__  .  remora.cli  .  remora.lsp.__main__ |
+----------+--------------+---------------+----------------+
           |              |               |
           v              v               v
+--------------+  +--------------+  +------------------+
|   Service    |  |     LSP      |  |    Companion     |
|  (Datastar)  |  |  (pygls)     |  |  (event-driven)  |
+------+-------+  +------+-------+  +------+-----------+
       |                 |                 |
       v                 v                 v
+----------------------------------------------------------+
|                      Runner                              |
|  AgentRunner  .  ServerProtocol  .  Trigger pipeline     |
+--------------------------+-------------------------------+
                           |
                           v
+----------------------------------------------------------+
|                       Core                               |
|  ├── store/ (db schema, connections, event_store api)    |
|  ├── events/ (bus, event types, subscriptions)           |
|  ├── agents/ (node, execution, workspace, state, chat)   |
|  ├── code/ (tree-sitter discovery, projections)          |
|  └── tools/ (core capabilities and swarm commands)       |
+--------------------------+-------------------------------+
                           |
                           v
+----------------------------------------------------------+
|                      Utils                               |
|  PathResolver . Types . FS . Text . LanguageMap          |
+----------------------------------------------------------+
```

**Key invariant:** Arrows only point downward. Core NEVER imports from LSP, Service, Companion,
or Runner. Runner NEVER imports from LSP or Service directly (only through the `ServerProtocol`).

---

## 4. Refactor Phase 1 — Sever Core -> LSP/Companion/Extensions

**Goal:** Remove all upward dependencies from `core/` so it can be imported and tested in isolation.

**Priority:** CRITICAL — this is the foundation for all subsequent phases.

### 4.1 Move AgentRunner out of core re-exports

- **File:** `core/__init__.py`
- **Change:** Remove `from remora.lsp.runner import AgentRunner` (line 65) and remove
  `AgentRunner` from `__all__`.
- **Migration:** Any code doing `from remora.core import AgentRunner` switches to
  `from remora.lsp.runner import AgentRunner`. Longer term, `AgentRunner` moves to a new
  top-level `remora.runner` module (see Phase 4).

### 4.2 Decouple RemoraEvent from CompanionEvent

- **File:** `core/events.py`
- **Change:** Remove line 227 (`from remora.companion.events import CompanionEvent`) and remove
  `CompanionEvent` from the `RemoraEvent` union.
- **Define `CoreEvent`** as the union of only core events in `core/events.py`.
- **Rename existing** `RemoraEvent` to `CoreEvent`.
- **Create `remora/event_types.py`** that imports from both and defines the combined alias if needed,
  OR just let each subsystem use its own event types.
- **EventStore / EventBus impact:** Both should accept `_FrozenEvent` (the base class) rather
  than the specific union type. Runtime behavior unchanged since they use `model_dump()` and
  `type(event).__name__`.

### 4.3 Decouple NodeProjection from extensions

- **File:** `core/projections.py`
- **Change:** Replace `from remora.extensions import extension_matches` with accepting a callable
  parameter. `NodeProjection.__init__` already takes `extension_configs: list[type]`; change to:
  `extension_matcher: Callable[[str, str, str, str], dict] | None = None`
- **Callers** (`lsp/__init__.py` `main()`, `service/api.py`): Build the matcher at the call site
  using `remora.extensions.load_extensions()` and pass it in.

---

## 5. Refactor Phase 2 — Break LSP Circular Dependencies

**Goal:** Eliminate the `server <-> handlers <-> notifications` import cycle.

### 5.1 Remove module-level singleton and side effects from server.py

- **File:** `lsp/server.py`
- **Change:** Remove lines 237 (`server = get_server()`) and 259 (`register_handlers()`).
  The singleton should be created explicitly in the startup path (`lsp/__init__.py:main()` or
  `lsp/__main__.py`), not at import time.
- **Handler registration:** Pass the server instance to a `register_handlers(server)` function
  that is called during startup, not at import time.

### 5.2 Inject server into handlers via parameter

- **Files:** All modules in `lsp/handlers/` and `lsp/notifications.py`
- **Change:** Instead of `from remora.lsp.server import server`, handlers receive the server
  instance via pygls's built-in `LanguageServer` parameter injection. pygls handler functions
  already receive `ls: LanguageServer` as their first argument — use it instead of the global.
- **Benefit:** Breaks the circular import entirely. Handlers no longer import `server.py`.

### 5.3 Extract process lock from lsp/__init__.py

- **File:** `lsp/__init__.py` (452 lines)
- **Change:** Move `_WorkspaceProcessLock` and `_ParentProcessWatchdog` to `lsp/process_lock.py`.
  Move `main()` and `_install_signal_handlers()` to `lsp/__main__.py`. The `__init__.py`
  should only contain re-exports and `__all__`.

---

## 6. Refactor Phase 3 — Decompose God-Objects & Group Core

**Goal:** Break apart oversized modules into focused, single-responsibility files, and organize the flat `core/` directory into conceptual subpackages for easier navigation.

### 6.1 Split EventStore (1193 lines -> ~4 modules)

| New Module | Responsibility | Approx Lines |
|-----------|---------------|-------------|
| `core/event_store.py` | Core append/replay API, trigger queue | ~300 |
| `core/event_store_schema.py` | Schema DDL, migrations, table creation | ~200 |
| `core/event_store_queries.py` | Node queries, chat history, replay queries | ~300 |
| `core/event_store_connection.py` | Connection management, retry logic, lock diagnostics | ~250 |

The public `EventStore` class stays in `core/event_store.py` but delegates to the extracted
modules. The `initialize()` method calls `event_store_schema.create_tables(conn)`. Query methods
delegate to `event_store_queries`.

### 6.2 Split AgentRunner (743 lines -> ~3 modules)

| New Module | Responsibility | Approx Lines |
|-----------|---------------|-------------|
| `runner/agent_runner.py` | Core runner loop, trigger queue, cascade depth | ~400 |
| `runner/headless.py` | `_HeadlessServer`, `_HeadlessDB` | ~80 |
| `runner/trigger.py` | `Trigger` model, cooldown logic | ~100 |

Or, if `AgentRunner` stays in `lsp/`, at least extract the headless stubs and triggers.

### 6.3 Clean up core/tools/

- Move `core/tools/lsp.py` to `lsp/tools.py` — these are LSP-specific tools.
- Consolidate `core/chat.py`'s `FunctionTool` with the existing tool infrastructure in
  `core/tools/__init__.py`.

### 6.4 Restructure Core into Conceptual Subpackages

To dramatically improve directory tree comprehension at a glance, the flat `src/remora/core/` package will be grouped into distinct domain subdirectories:

| Subpackage | Responsibility | Contents |
|-----------|---------------|----------|
| `core/store/` | SQLite persistence layer | `event_store.py` (and the splits from 6.1) |
| `core/events/` | Event-driven reactive system | `events.py` (types), `event_bus.py`, `subscriptions.py` |
| `core/agents/` | Agent definition and execution | `agent_node.py`, `execution.py`, `workspace.py`, `state_manager.py`, `chat.py`, `kernel_factory.py`, `cairn_bridge.py` |
| `core/code/` | Static analysis & read models | `discovery.py`, `projections.py` |
| `core/tools/` | Tool definitions and registry | `grail.py`, `spawn_child.py`, `swarm.py` |

*Note: `config.py`, `exceptions.py` (if any), and `__init__.py` remain at the `core/` root.*

---

## 7. Refactor Phase 4 — Introduce Server Protocol

**Goal:** Formalize the duck-typed server interface so LSP and headless modes share an explicit contract.

### 7.1 Define ServerProtocol

- **New file:** `core/protocols.py` (already exists at 3578 bytes — extend it, or create
  `runner/protocols.py`)
- **Content:**

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class RunnerServer(Protocol):
    event_store: Any
    db: Any
    subscriptions: Any | None
    proposals: dict[str, Any]

    def generate_correlation_id(self) -> str: ...
```

### 7.2 Type AgentRunner against the protocol

- `AgentRunner.__init__(self, server: RunnerServer, ...)`
- `_HeadlessServer` naturally satisfies the protocol — verify with `isinstance` in tests.
- `RemoraLanguageServer` satisfies the protocol — no changes needed to it.

### 7.3 Consider top-level `remora.runner` package

If `AgentRunner` is truly transport-agnostic (it should be after Phase 1-3), move it out of
`lsp/` entirely:

```
src/remora/runner/
    __init__.py
    agent_runner.py
    headless.py
    trigger.py
    protocols.py
```

This makes the architecture's layer diagram a reality in the file system.

---

## 8. Refactor Phase 5 — Cleanup and Polish

**Goal:** Eliminate remaining DRY violations and naming confusion.

### 8.1 Consolidate language extension maps

- **New file:** `utils/languages.py`
- **Content:** Single `EXTENSION_TO_LANGUAGE: dict[str, tuple[str, str]]` mapping.
- **Migrate:** `core/discovery.py`, `core/execution.py`, `core/agent_node.py` all import
  from `utils/languages.py`.

### 8.2 Rename queries/ directory

- **Current:** `src/remora/queries/` contains tree-sitter `.scm` files.
- **Rename to:** `src/remora/tree_sitter_queries/` or `src/remora/ts_queries/` to avoid
  confusion with SQL queries.
- **Update:** `core/discovery.py` `_get_query_dir()` path reference.

### 8.3 Clean up __init__.py re-exports

- `core/__init__.py`: After Phase 1, audit the remaining re-exports. The 129-line `__all__`
  list is a code smell — consider whether consumers should import from submodules directly.
- `lsp/__init__.py`: After Phase 2.3, should be ~20 lines max.

### 8.4 Consolidate tool infrastructure

- `core/chat.py`'s `FunctionTool` and `build_chat_tools()` should use the same base as
  `core/tools/` module's tool classes.
- If `FunctionTool` wrapping is useful, promote it to `core/tools/function_tool.py`.

---

## 9. Verification Plan

### 9.1 Automated Tests

After each phase, run the full test suite:
```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

Known pre-existing failures (per REPO_RULES.md):
- `test_lsp_handlers_register_and_advertise_capabilities`
- 2 cairn merge-ops tests (skipped)
- 1 benchmark timeout (skipped)

No new failures should appear.

### 9.2 Import Validation

After Phase 1, verify core isolation:
```python
# This should succeed without importing pygls, lsprotocol, or companion:
import remora.core
import remora.core.events
import remora.core.projections
```

### 9.3 Dependency Graph Verification

Re-run tach after each phase to regenerate the dot file and confirm edges are removed:
```bash
devenv shell -- tach report --dot > tach_module_graph_after.dot
```

### 9.4 Type Checking

After Phase 4 (ServerProtocol), run type checking to verify protocol conformance:
```bash
devenv shell -- pyright src/remora/runner/ src/remora/lsp/server.py
```

---

## 10. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Breaking LSP handler registration | High | High | Phase 2 must be atomic — test LSP startup after every change |
| EventStore split introduces DB bugs | Medium | High | Phase 3.1 is pure extraction — no logic changes, only file moves |
| `RemoraEvent` union removal breaks serialization | Medium | Medium | EventStore uses `type(event).__name__` for dispatch, not the union type |
| `_HeadlessServer` protocol mismatch | Low | Medium | Phase 4 adds explicit `Protocol` — catches issues at type-check time |
| Circular import regression | Medium | Low | tach check in CI after each phase |

### Recommended Execution Order

1. **Phase 1** first — smallest blast radius, biggest architectural win
2. **Phase 2** second — required before Phase 3 can safely split runner
3. **Phase 5.1** (language maps) — quick win, can be done any time
4. **Phase 3** — largest amount of work, do after 1 and 2 are stable
5. **Phase 4** — can be done after Phase 3 moves runner out of lsp/
6. **Phase 5** remainder — polish, lowest priority

---

*Generated from direct source audit of `src/remora/` on 2026-03-06.*
