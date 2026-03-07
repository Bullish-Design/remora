# Architecture Refactoring Guide V2

> Validated, corrected, and expanded implementation guide for the Remora architecture refactor.
> Based on direct source-code audit of `src/remora/` on 2026-03-06.
>
> **CRITICAL RULE CHECK:** No subagents. Do all work directly.
> After each compaction, resume exactly where `PROGRESS.md` leaves off.

---

## Table of Contents

1. **[Pre-Refactor Snapshot](#1-pre-refactor-snapshot)** — Current state of violations, with exact file/line references.
2. **[Phase 1: Sever Core → Outer Layer Dependencies](#2-phase-1-sever-core--outer-layer-dependencies)** — Remove all upward imports from `core/`. Three sub-steps. *Critical priority.*
3. **[Phase 2: Break LSP Circular Dependencies](#3-phase-2-break-lsp-circular-dependencies)** — Eliminate the server singleton, extract process lock, inject server via pygls. *High priority.*
4. **[Phase 3: Decompose God-Objects](#4-phase-3-decompose-god-objects)** — Split EventStore (1192 lines), extract AgentRunner helpers, move `core/tools/lsp.py`. *Medium priority, largest amount of work.*
5. **[Phase 4: Reorganize Core into Subpackages](#5-phase-4-reorganize-core-into-subpackages)** — Group flat `core/` into `store/`, `events/`, `agents/`, `code/` subpackages. *Medium priority.*
6. **[Phase 5: Introduce Runner Package & Server Protocol](#6-phase-5-introduce-runner-package--server-protocol)** — Move AgentRunner to top-level `remora.runner`, formalize the duck-typed server interface. *Lower priority.*
7. **[Phase 6: Cleanup & Polish](#7-phase-6-cleanup--polish)** — Consolidate language maps, rename `queries/` dir, prune `__init__.py` exports. *Lowest priority.*
8. **[Verification Procedure (Per Phase)](#8-verification-procedure-per-phase)** — Test commands, type checking, import validation, dependency graph checks.
9. **[Risk Assessment & Execution Order](#9-risk-assessment--execution-order)** — What could go wrong and the recommended sequence.

---


## 1. Pre-Refactor Snapshot

This section documents the exact violations and issues as they exist in the codebase **right now**, validated by direct source inspection. Every file path and line number has been verified.

### 1.1 Layer Violations (Core → Outer)

These are the **blocking** violations where `core/` imports from packages that should depend on it:

| Violation | File | Line | Import |
|-----------|------|------|--------|
| Core → LSP | `core/__init__.py` | 65 | `from remora.lsp.runner import AgentRunner` |
| Core → Companion | `core/events.py` | 227 | `from remora.companion.events import CompanionEvent` |
| Core → Extensions | `core/projections.py` | 23 | `from remora.extensions import extension_matches` |

### 1.2 LSP Circular Dependencies

The `lsp/server.py` module creates a singleton and registers handlers at **module level** (not during startup):

- **Line 237:** `server = get_server()` — eagerly creates the LanguageServer singleton on import.
- **Line 259:** `register_handlers()` — force-imports all handler modules on import.

All 6 handler modules and `notifications.py` import the singleton back:

| File | Import |
|------|--------|
| `handlers/documents.py:9` | `from remora.lsp.server import logger, publish_diagnostics, refresh_code_lenses, server, uri_to_path` |
| `handlers/commands.py:9` | `from remora.lsp.server import emit_event, logger, server` |
| `handlers/lens.py:5` | `from remora.lsp.server import logger, server` |
| `handlers/actions.py:6` | `from remora.lsp.server import logger, server` |
| `handlers/capabilities.py:5` | `from remora.lsp.server import logger, server` |
| `handlers/hover.py:5` | `from remora.lsp.server import logger, server` |
| `notifications.py:9` | `from remora.lsp.server import emit_event, logger, server` |

### 1.3 Bloated Modules

| File | Lines | Problem |
|------|-------|---------|
| `core/event_store.py` | 1192 | God object: SQLite connections, schema DDL, write retries, event append/replay, node hydration, chat history, trigger queue — all in one file. |
| `lsp/runner.py` | 743 | `AgentRunner` (~650 lines) + `_HeadlessServer` + `_HeadlessDB` + `Trigger` model mixed together. |
| `lsp/__init__.py` | 452 | `_WorkspaceProcessLock` (230 lines), `_ParentProcessWatchdog`, signal handlers, and `main()` startup — all in the package init. |
| `lsp/__main__.py` | 372 | A **second** `main()` with startup logic, background scan, logging setup. Duplicates/overlaps the `main()` in `__init__.py`. |

### 1.4 Other Issues

- **Duplicated language maps:** `LANGUAGE_EXTENSIONS` in `core/discovery.py:27` and `_LANG_TAGS` in `core/execution.py:56` — same data, different names. (Note: `_EXT_TO_LANG` in `agent_node.py` referenced by the original plan **no longer exists** — it was already removed.)
- **`core/tools/lsp.py` (10.5KB):** LSP-specific tool implementations living inside `core/tools/`, blurring the layer boundary.
- **No formal server protocol:** `AgentRunner` accepts `server: RemoraLanguageServer` but `create_headless()` passes a `_HeadlessServer` that duck-types the interface. No `Protocol` class defines the contract.
- **`queries/` naming collision:** `src/remora/queries/` contains tree-sitter `.scm` files, not SQL queries. Confusing name.
- **`EventBus` type hint:** `event_bus.py:18` imports `RemoraEvent` (the union that includes `CompanionEvent`). After Phase 1 decoupling, this needs updating.

---


## 2. Phase 1: Sever Core → Outer Layer Dependencies

**Goal:** After this phase, `import remora.core` must succeed without loading `pygls`, `lsprotocol`, or `remora.companion`. Core becomes independently importable and testable.

**Priority:** CRITICAL — foundation for everything else.

### Step 1.1: Remove AgentRunner re-export from `core/__init__.py`

**File:** `src/remora/core/__init__.py`

1. **Delete** line 65: `from remora.lsp.runner import AgentRunner`
2. **Delete** `"AgentRunner"` from the `__all__` list (around line 78).
3. **Find all callers** that do `from remora.core import AgentRunner`:
   ```bash
   devenv shell -- grep -rn "from remora.core import.*AgentRunner" src/ tests/
   ```
4. **Update each caller** to import directly:
   ```python
   # Before:
   from remora.core import AgentRunner
   # After:
   from remora.lsp.runner import AgentRunner
   ```
5. **Verify:** `devenv shell -- python -c "import remora.core"` should not import `pygls`.

### Step 1.2: Decouple `RemoraEvent` from `CompanionEvent`

**File:** `src/remora/core/events.py`

1. **Delete** line 227: `from remora.companion.events import CompanionEvent`
2. **Rename** the type alias from `RemoraEvent` to `CoreEvent`:
   ```python
   # Before (line 229):
   RemoraEvent = (
       AgentStartEvent | AgentCompleteEvent | ...
       | CompanionEvent  # DELETE this line
   )
   # After:
   CoreEvent = (
       AgentStartEvent | AgentCompleteEvent | AgentErrorEvent
       | HumanInputRequestEvent | HumanInputResponseEvent
       | AgentMessageEvent | FileSavedEvent | ContentChangedEvent
       | CursorFocusEvent | ManualTriggerEvent
       | NodeDiscoveredEvent | ScaffoldRequestEvent | NodeRemovedEvent
       | KernelStartEvent | KernelEndEvent
       | ToolCallEvent | ToolResultEvent
       | ModelRequestEvent | ModelResponseEvent
       | TurnCompleteEvent
   )
   ```
3. **Update `__all__`:** Replace `"RemoraEvent"` with `"CoreEvent"`, remove `"CompanionEvent"`.
4. **Update `EventBus` type hint** in `core/event_bus.py`:
   - Line 18: change `from remora.core.events import RemoraEvent` to `from remora.core.events import CoreEvent`
   - Update type hints throughout from `RemoraEvent` to `CoreEvent` (or use the broader `StructuredEvent | CoreEvent` union that's already there for the method signatures).
5. **Update `EventStore` type hints** in `core/event_store.py`:
   - The `EventStore.append()` and `EventStore.batch_append()` signatures use `StructuredEvent | RemoraEvent`. Change to `StructuredEvent | CoreEvent`.
   - Runtime behavior is unchanged: both methods use `type(event).__name__` and `.model_dump()`, not the union type directly.
6. **Update `NodeProjection.apply()` type hint** in `core/projections.py`:
   - Line 88: `def apply(self, conn, event: RemoraEvent)` → `def apply(self, conn, event: CoreEvent)`
   - Line 21: change `RemoraEvent` import to `CoreEvent`.
7. **Update all other internal references** to `RemoraEvent`:
   ```bash
   devenv shell -- grep -rn "RemoraEvent" src/remora/core/
   ```
   Every hit in `core/` should be changed to `CoreEvent`.
8. **External callers** (in `lsp/`, `companion/`, `service/`):
   ```bash
   devenv shell -- grep -rn "RemoraEvent" src/remora/ --include="*.py" | grep -v core/
   ```
   If any external code needs the combined union, it can define its own alias:
   ```python
   from remora.core.events import CoreEvent
   from remora.companion.events import CompanionEvent
   AnyRemoraEvent = CoreEvent | CompanionEvent
   ```
   Or simply accept `_FrozenEvent` (the base class) — which is what `EventStore` should do anyway.

### Step 1.3: Decouple `NodeProjection` from `remora.extensions`

**File:** `src/remora/core/projections.py`

1. **Delete** line 23: `from remora.extensions import extension_matches`
2. **Change the `__init__` signature** (line 85):
   ```python
   # Before:
   def __init__(self, extension_configs: list[type] | None = None):
       self._extension_configs = extension_configs or []

   # After:
   def __init__(
       self,
       extension_matcher: Callable[[type, str, str, str, str], bool] | None = None,
       extension_configs: list[type] | None = None,
   ):
       self._extension_matcher = extension_matcher
       self._extension_configs = extension_configs or []
   ```
   > **Note:** `extension_matches()` returns `bool`, not `dict`. Its signature is:
   > `extension_matches(ext: Type[AgentExtension], node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool`
3. **Update `_project_node_discovered()`** (lines 164-180):
   ```python
   # Before:
   for ext in self._extension_configs:
       if extension_matches(ext, row["node_type"], row["name"],
                            file_path=row["file_path"], source_code=row["source_code"]):
           ...

   # After:
   if self._extension_matcher is not None:
       for ext in self._extension_configs:
           if self._extension_matcher(ext, row["node_type"], row["name"],
                                       file_path=row["file_path"],
                                       source_code=row["source_code"]):
               ext_data = ext.get_extension_data()
               for key, value in ext_data.items():
                   if key in row:
                       if isinstance(value, (list, dict)):
                           row[key] = json.dumps(value, default=_dataclass_default)
                       else:
                           row[key] = value
               break
   ```
4. **Update callers** that instantiate `NodeProjection`:
   - **`lsp/__main__.py` or `lsp/__init__.py` `main()`:** Where `NodeProjection` is created, pass the matcher:
     ```python
     from remora.extensions import extension_matches, load_extensions
     extensions = load_extensions(models_dir)
     projection = NodeProjection(
         extension_matcher=extension_matches,
         extension_configs=extensions,
     )
     ```
   - **`service/api.py`:** Same pattern if it creates a `NodeProjection`.
   - Search for all instantiations:
     ```bash
     devenv shell -- grep -rn "NodeProjection(" src/remora/
     ```
5. **Add import** at top of `projections.py`:
   ```python
   from collections.abc import Callable
   ```
6. **Verify:** `devenv shell -- python -c "import remora.core.projections"` should not import `remora.extensions`.

### Phase 1 Verification

```bash
# 1. Tests
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# 2. Core isolation
devenv shell -- python -c "
import sys
import remora.core
import remora.core.events
import remora.core.projections
# Verify no outer packages leaked in
for mod in sorted(sys.modules):
    if any(mod.startswith(p) for p in ('remora.lsp', 'remora.companion', 'remora.extensions', 'pygls', 'lsprotocol')):
        print(f'VIOLATION: {mod} was imported')
        exit(1)
print('Core isolation: PASS')
"

# 3. Dependency graph
devenv shell -- tach report --dot > .scratch/projects/architecture_refactor/tach_after_phase1.dot
# Verify edges "remora.core" -> "remora.lsp", "remora.core.events" -> "remora.companion.events",
# and "remora.core.projections" -> "remora.extensions" are all GONE.
```

---


## 3. Phase 2: Break LSP Circular Dependencies

**Goal:** Eliminate the `server ↔ handlers ↔ notifications` import cycle. After this phase, `lsp/server.py` has no module-level side effects, handlers receive the server via pygls injection, and `lsp/__init__.py` is a thin re-export file.

**Priority:** HIGH — required before Phase 3 can safely restructure the runner.

### Step 2.1: Remove module-level singleton and side effects from `server.py`

**File:** `src/remora/lsp/server.py`

1. **Delete** line 237: `server = get_server()` (the eager singleton).
2. **Delete** line 259: `register_handlers()` (the eager handler import).
3. **Delete** the module-level convenience functions that delegate to the singleton (lines 240-256):
   - `uri_to_path()`, `refresh_code_lenses()`, `publish_diagnostics()`, `emit_event()` — these are thin wrappers around `server.xxx()`. They exist solely so handler modules can `from remora.lsp.server import emit_event` instead of accessing the server instance directly.
   - After handler injection (Step 2.3), these wrappers become unnecessary.
4. **Keep** `get_server()` and `register_handlers()` as functions — they will be called explicitly from the startup path.
5. **Update `register_handlers()`** to accept a server parameter:
   ```python
   # Before:
   def register_handlers():
       import remora.lsp.handlers.commands
       import remora.lsp.handlers.documents
       # ...

   # After:
   def register_handlers(server: RemoraLanguageServer):
       """Register LSP handlers on the given server instance.

       Must be called AFTER server creation, BEFORE server.start_io().
       Handlers use pygls's built-in LanguageServer parameter injection.
       """
       # Force-import handler modules so their @server.feature decorators execute.
       # The decorators need the server instance, which they get via closure
       # from the module-level registration call.
       import remora.lsp.handlers.commands
       import remora.lsp.handlers.documents
       import remora.lsp.handlers.actions
       import remora.lsp.handlers.capabilities
       import remora.lsp.handlers.hover
       import remora.lsp.handlers.lens
       import remora.lsp.notifications
   ```

> **Important design consideration:** pygls `@server.feature` decorators need the `server` object at decoration time. The cleanest approach is to change from module-level decorators to explicit registration. See Step 2.3 for the handler side.

### Step 2.2: Consolidate and extract `lsp/__init__.py`

**Current state:** There are **two** startup paths:
- `lsp/__init__.py` line 340: `main()` — creates EventStore, SubscriptionRegistry, then calls `server.start_io()`.
- `lsp/__main__.py` line 61: `main()` — sets up logging, loads config, creates runner, registers `@server.feature(INITIALIZED)` handler, runs background scan.

These need to be **unified into `lsp/__main__.py`** (which is already the actual entrypoint called by `remora-lsp`).

1. **Create** `src/remora/lsp/process_lock.py`:
   - Move `_LockOwnerMetadata`, `_WorkspaceProcessLock`, `_ParentProcessWatchdog` from `__init__.py` into this new file.
   - These classes are self-contained (they only use stdlib imports).

2. **Move signal handler** to `__main__.py`:
   - Move `_install_signal_handlers()` from `__init__.py` to `__main__.py` (or `process_lock.py` if it's tightly coupled to the lock).

3. **Merge the two `main()` functions** into `lsp/__main__.py`:
   - The `__main__.py` version is already the more complete one (it has logging setup, config loading, runner creation, background scan).
   - From `__init__.py`'s `main()`, extract only the parts that `__main__.py` doesn't already have:
     - EventStore creation and initialization
     - SubscriptionRegistry creation
     - Process lock acquisition
   - Integrate these into `__main__.py`'s `main()`.

4. **Gut `__init__.py`** to be a thin re-export file (~20-30 lines):
   ```python
   """Remora LSP server package."""
   from remora.lsp.db import RemoraDB
   from remora.lsp.graph import LazyGraph
   from remora.lsp.models import (
       LspAgentEvent,
       LspAgentMessageEvent,
       LspHumanChatEvent,
       LspRewriteAppliedEvent,
       LspRewriteProposalEvent,
       LspRewriteRejectedEvent,
       RewriteProposal,
       generate_id,
   )
   from remora.lsp.server import RemoraLanguageServer

   __all__ = [
       "LspAgentEvent", "LspAgentMessageEvent", "LspHumanChatEvent",
       "LspRewriteAppliedEvent", "LspRewriteProposalEvent",
       "LspRewriteRejectedEvent", "RewriteProposal", "generate_id",
       "RemoraDB", "LazyGraph", "RemoraLanguageServer",
   ]
   ```

5. **Update `__main__.py`'s startup sequence** to explicitly wire everything:
   ```python
   from remora.lsp.server import get_server, register_handlers
   from remora.lsp.process_lock import _WorkspaceProcessLock, _ParentProcessWatchdog

   server = get_server()
   register_handlers(server)
   # ... rest of startup
   ```

### Step 2.3: Inject server into handlers via pygls parameter

**Key insight:** pygls handler functions decorated with `@server.feature(...)` automatically receive the `LanguageServer` instance as their first argument (`ls`). Most handlers already have access to it but ignore it in favor of the global `server` import. This is the root of the circular dependency.

**Files:** All modules in `src/remora/lsp/handlers/` and `src/remora/lsp/notifications.py`

**For each handler file:**

1. **Delete** the `from remora.lsp.server import ...` line.
2. **Add the `ls` parameter** to each handler function (if not already present):
   ```python
   # Before (e.g. in handlers/commands.py):
   from remora.lsp.server import emit_event, logger, server

   @server.feature("$/remora/runAgent")
   async def run_agent(params: dict) -> None:
       ...server.runner.trigger(...)

   # After:
   import logging
   from typing import cast
   from remora.lsp.server import RemoraLanguageServer

   logger = logging.getLogger("remora.lsp")

   def register_command_handlers(server: RemoraLanguageServer):
       @server.feature("$/remora/runAgent")
       async def run_agent(ls: RemoraLanguageServer, params: dict) -> None:
           ...ls.runner.trigger(...)
   ```
3. **Replace all uses of the global `server`** with `ls` (cast to `RemoraLanguageServer` if needed for type checking).
4. **Replace `emit_event(event)`** calls with `await ls.emit_event(event)` (it's already a method on `RemoraLanguageServer`).
5. **Replace `logger`** from `server.py` with a local `logger = logging.getLogger("remora.lsp")`.
6. **Replace `publish_diagnostics()`** and `refresh_code_lenses()`** calls with `ls.publish_diagnostics()` and `ls.refresh_code_lenses()`.

**For `notifications.py`:**
- Same pattern. The two handler functions (`on_cursor_moved`, `on_input_submitted`) currently use `server` and `emit_event` globals extensively.
- Wrap them in a `register_notification_handlers(server)` function.

**Update `register_handlers()` in `server.py`:**
```python
def register_handlers(server: RemoraLanguageServer):
    from remora.lsp.handlers.commands import register_command_handlers
    from remora.lsp.handlers.documents import register_document_handlers
    from remora.lsp.handlers.actions import register_action_handlers
    from remora.lsp.handlers.capabilities import register_capability_handlers
    from remora.lsp.handlers.hover import register_hover_handlers
    from remora.lsp.handlers.lens import register_lens_handlers
    from remora.lsp.notifications import register_notification_handlers

    register_command_handlers(server)
    register_document_handlers(server)
    register_action_handlers(server)
    register_capability_handlers(server)
    register_hover_handlers(server)
    register_lens_handlers(server)
    register_notification_handlers(server)
```

### Phase 2 Verification

```bash
# 1. Tests
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# 2. Import side-effect check
devenv shell -- python -c "
import remora.lsp.server
import sys
# server.py should NOT have created a LanguageServer instance
from remora.lsp.server import _server
assert _server is None, 'Module-level singleton still exists!'
print('No side effects: PASS')
"

# 3. Verify handlers don't import server singleton
devenv shell -- grep -rn "from remora.lsp.server import.*server" src/remora/lsp/handlers/ src/remora/lsp/notifications.py
# Expected: NO results
```

---


## 4. Phase 3: Decompose God-Objects

**Goal:** Break apart oversized modules into focused, single-responsibility files. This phase is pure extraction — no logic changes, only file moves and import updates.

**Priority:** MEDIUM — largest amount of work but low architectural risk since it's mechanical.

### Step 3.1: Split EventStore (1192 lines → ~4 files)

**File:** `src/remora/core/event_store.py`

Create four files by extracting logical concerns:

| New File | Responsibility | What to Move |
|----------|---------------|-------------|
| `core/event_store.py` | Public API: `EventStore` class, `append()`, `batch_append()`, `replay()`, `get_triggers()` | Keep the class definition and core append/replay methods. |
| `core/event_store_schema.py` | Database DDL and migrations | Extract `EventStore.initialize()` internal DDL (the `CREATE TABLE` statements from lines ~77-205) and `_migrate_routing_fields()` into a standalone `create_tables(conn)` and `migrate(conn)` function. |
| `core/event_store_queries.py` | Read queries: node hydration, chat history, event replay | Extract `get_node()`, `list_nodes()`, `get_recent_events()`, `get_events_for_correlation()`, `_row_to_dict()` into standalone functions that accept a connection. |
| `core/event_store_connection.py` | Connection management, retry logic, lock diagnostics | Extract `_begin_immediate_with_recovery()`, `_run_locked_write_with_retries()`, `_lock_diagnostics()`, `_is_locked_error()`, `_retry_delay_seconds()` into a `ConnectionManager` class or module-level functions. |

**Extraction strategy:**

1. Start with `event_store_schema.py` — extract the DDL strings and `create_tables()` function. Update `EventStore.initialize()` to call `event_store_schema.create_tables(self._write_conn)`.
2. Next, `event_store_connection.py` — extract the retry/recovery methods. The `EventStore` class can hold a `ConnectionManager` instance.
3. Finally, `event_store_queries.py` — extract the read-side query methods. These should be pure functions that accept a `sqlite3.Connection`.
4. Keep `EventStore` as the public facade in `event_store.py`, delegating to the extracted modules.

**Key principle:** The `EventStore` class remains the single public API. External code still does `from remora.core.event_store import EventStore`. The split is internal.

### Step 3.2: Extract AgentRunner helpers from `runner.py`

**File:** `src/remora/lsp/runner.py` (743 lines)

Extract supporting types into sibling files (they stay in `lsp/` for now — Phase 5 moves them to `remora.runner`):

1. **Create** `src/remora/lsp/runner_headless.py`:
   - Move `_HeadlessDB` (lines 52-68) and `_HeadlessServer` (lines 71-85).
   - These are self-contained — they only use stdlib + `uuid`.
   - Update `runner.py` to import them: `from remora.lsp.runner_headless import _HeadlessServer, _HeadlessDB`

2. **Create** `src/remora/lsp/runner_trigger.py`:
   - Move the `Trigger` Pydantic model (lines 43-49).
   - Update `runner.py` to import it: `from remora.lsp.runner_trigger import Trigger`

3. **Update `AgentRunner.create_headless()`** to use the imported `_HeadlessServer`.

### Step 3.3: Move `core/tools/lsp.py` to `lsp/tools.py`

**File:** `src/remora/core/tools/lsp.py` (10.5KB)

1. **Move** the file to `src/remora/lsp/tools.py`.
2. **Update imports** in any file that references `remora.core.tools.lsp`:
   ```bash
   devenv shell -- grep -rn "from remora.core.tools.lsp import\|from remora.core.tools import.*lsp" src/
   ```
   Change to `from remora.lsp.tools import ...`.
3. **Update `core/tools/__init__.py`** to remove any re-export of `lsp` tools.

### Phase 3 Verification

```bash
# Tests (the most important check — pure extraction should not break anything)
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Verify EventStore still works end-to-end
devenv shell -- python -c "
from remora.core.event_store import EventStore
print('EventStore import: OK')
"
```

---


## 5. Phase 4: Reorganize Core into Subpackages

**Goal:** Replace the flat `core/` directory (22 Python files) with logical subpackages for improved navigation and conceptual grouping. This is purely organizational — moving files and updating imports.

**Priority:** MEDIUM — depends on Phase 3 completing the EventStore split.

### Step 4.1: Create subpackage directories

```bash
mkdir -p src/remora/core/{store,events,agents,code}
touch src/remora/core/{store,events,agents,code}/__init__.py
```

### Step 4.2: Move files into subpackages

| Subpackage | Files to Move | Responsibility |
|-----------|--------------|----------------|
| `core/store/` | `event_store.py`, `event_store_schema.py`, `event_store_queries.py`, `event_store_connection.py` | SQLite persistence layer |
| `core/events/` | `events.py`, `event_bus.py`, `subscriptions.py` | Event types, dispatch, and subscription matching |
| `core/agents/` | `agent_node.py`, `agent_context.py`, `execution.py`, `workspace.py`, `state_manager.py`, `chat.py`, `kernel_factory.py`, `cairn_bridge.py`, `cairn_externals.py`, `swarm_executor.py` | Agent definition, execution, and workspace |
| `core/code/` | `discovery.py`, `projections.py`, `reconciler.py` | Tree-sitter parsing and read-model projection |

Files that stay at `core/` root:
- `config.py` — cross-cutting configuration
- `errors.py` — exception hierarchy
- `manifest.py` — bundle manifest loading
- `protocols.py` — protocol definitions
- `tools/` — tool definitions (already a subpackage)
- `__init__.py` — re-exports

### Step 4.3: Update all internal imports

This is the most tedious part. Use a systematic search-and-replace:

```bash
# Find every import that references the old paths
devenv shell -- grep -rn "from remora.core.event_store import\|from remora.core.event_bus import\|from remora.core.events import\|from remora.core.subscriptions import" src/ tests/

devenv shell -- grep -rn "from remora.core.agent_node import\|from remora.core.agent_context import\|from remora.core.execution import\|from remora.core.workspace import\|from remora.core.state_manager import\|from remora.core.chat import\|from remora.core.kernel_factory import\|from remora.core.cairn_bridge import\|from remora.core.cairn_externals import\|from remora.core.swarm_executor import" src/ tests/

devenv shell -- grep -rn "from remora.core.discovery import\|from remora.core.projections import\|from remora.core.reconciler import" src/ tests/
```

**Mapping:**
```
from remora.core.event_store  →  from remora.core.store.event_store
from remora.core.event_bus    →  from remora.core.events.event_bus
from remora.core.events       →  from remora.core.events.events
from remora.core.subscriptions →  from remora.core.events.subscriptions
from remora.core.agent_node   →  from remora.core.agents.agent_node
from remora.core.execution    →  from remora.core.agents.execution
from remora.core.discovery    →  from remora.core.code.discovery
from remora.core.projections  →  from remora.core.code.projections
... etc.
```

### Step 4.4: Update subpackage `__init__.py` re-exports

Each subpackage `__init__.py` should re-export its public API so consumers can do:
```python
from remora.core.store import EventStore
from remora.core.events import CoreEvent, EventBus
from remora.core.agents import AgentNode, execute_agent_turn
from remora.core.code import CSTNode, discover, NodeProjection
```

### Step 4.5: Update `core/__init__.py`

After moving everything, `core/__init__.py` should import from the new subpackage locations. The `__all__` list stays the same — the public API doesn't change, only the internal organization.

### Phase 4 Verification

```bash
# Full test suite
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Verify old import paths still work via re-exports
devenv shell -- python -c "
from remora.core import EventStore, AgentNode, CoreEvent, discover, NodeProjection
print('Re-exports: OK')
"
```

---

## 6. Phase 5: Introduce Runner Package & Server Protocol

**Goal:** Move `AgentRunner` out of `lsp/` into a top-level `remora.runner` package and formalize the duck-typed server interface with a Protocol class.

**Priority:** LOWER — depends on Phases 1-3 being complete.

### Step 5.1: Create the `runner/` package

```bash
mkdir -p src/remora/runner
touch src/remora/runner/__init__.py
```

### Step 5.2: Define `RunnerServer` protocol

**Create** `src/remora/runner/protocols.py`:

```python
"""Protocol defining the server interface required by AgentRunner.

Both RemoraLanguageServer (LSP mode) and _HeadlessServer (CLI mode)
must satisfy this protocol.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class RunnerServer(Protocol):
    """Minimal server interface needed by AgentRunner."""

    event_store: Any
    db: Any
    subscriptions: Any | None
    proposals: dict[str, Any]

    def generate_correlation_id(self) -> str: ...
```

### Step 5.3: Move runner files

1. **Move** `lsp/runner.py` → `runner/agent_runner.py`
2. **Move** `lsp/runner_headless.py` → `runner/headless.py` (created in Phase 3)
3. **Move** `lsp/runner_trigger.py` → `runner/trigger.py` (created in Phase 3)

### Step 5.4: Type AgentRunner against the protocol

**File:** `src/remora/runner/agent_runner.py`

```python
# Before:
from remora.lsp.server import RemoraLanguageServer
class AgentRunner:
    def __init__(self, server: RemoraLanguageServer, ...):

# After:
from remora.runner.protocols import RunnerServer
class AgentRunner:
    def __init__(self, server: RunnerServer, ...):
```

### Step 5.5: Update all imports globally

```bash
# Find all references to the old path
devenv shell -- grep -rn "from remora.lsp.runner import\|from remora.lsp import.*AgentRunner" src/ tests/
```

Change every occurrence to:
```python
from remora.runner.agent_runner import AgentRunner
```

Or, set up `runner/__init__.py` to re-export:
```python
from remora.runner.agent_runner import AgentRunner
from remora.runner.protocols import RunnerServer
from remora.runner.trigger import Trigger

__all__ = ["AgentRunner", "RunnerServer", "Trigger"]
```

So consumers can do `from remora.runner import AgentRunner`.

### Step 5.6: Verify protocol conformance

```bash
# Type-check that both server implementations satisfy the protocol
devenv shell -- pyright src/remora/runner/ src/remora/lsp/server.py
```

Both `RemoraLanguageServer` and `_HeadlessServer` should pass without errors.

### Phase 5 Verification

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
devenv shell -- pyright src/remora/runner/
```

---

## 7. Phase 6: Cleanup & Polish

**Goal:** Eliminate remaining DRY violations, naming confusion, and dead weight.

**Priority:** LOWEST — polish work after the structural refactor is stable.

### Step 6.1: Consolidate language extension maps

Currently two near-identical maps exist:
- `core/discovery.py:27` — `LANGUAGE_EXTENSIONS: dict[str, str]`
- `core/execution.py:56` — `_LANG_TAGS: dict[str, str]`

Both map file extensions (`.py`, `.js`, etc.) to language names. They have the *same entries*.

1. **Create** `src/remora/utils/languages.py`:
   ```python
   """Single source of truth for file-extension → language mapping."""

   EXTENSION_TO_LANGUAGE: dict[str, str] = {
       ".py": "python",
       ".js": "javascript",
       ".ts": "typescript",
       ".md": "markdown",
       ".toml": "toml",
       ".yaml": "yaml",
       ".yml": "yaml",
       ".json": "json",
       ".sh": "bash",
       ".rs": "rust",
       ".go": "go",
   }
   ```
2. **Update `discovery.py`:** Replace `LANGUAGE_EXTENSIONS` data with an import from `utils/languages.py`. Keep the name `LANGUAGE_EXTENSIONS` as an alias for backward compatibility:
   ```python
   from remora.utils.languages import EXTENSION_TO_LANGUAGE as LANGUAGE_EXTENSIONS
   ```
3. **Update `execution.py`:** Replace `_LANG_TAGS` with:
   ```python
   from remora.utils.languages import EXTENSION_TO_LANGUAGE as _LANG_TAGS
   ```

### Step 6.2: Rename `queries/` directory

**Current:** `src/remora/queries/` contains tree-sitter `.scm` files (not SQL).

1. **Rename** the directory to `src/remora/ts_queries/`.
2. **Update the reference** in `core/discovery.py` line 103:
   ```python
   # Before:
   return Path(importlib.resources.files("remora")) / "queries"
   # After:
   return Path(importlib.resources.files("remora")) / "ts_queries"
   ```
3. **Update `pyproject.toml`** if there are any package data references to `queries/`.

### Step 6.3: Prune `core/__init__.py` exports

After all phases are done:

1. Review the `__all__` list. If a symbol is better imported from its subpackage directly, remove it from the root `__init__.py`.
2. Consider keeping only the most commonly-used symbols in the root re-export:
   - `AgentNode`, `CSTNode`, `EventStore`, `EventBus`, `CoreEvent`, `NodeProjection`, `Config`
   - Remove rarely-used items that can be imported from their subpackage.

### Step 6.4: Consolidate tool infrastructure (optional)

`core/chat.py` defines `FunctionTool` and `build_chat_tools()` — a parallel tool-wrapping mechanism alongside `core/tools/`. If these are still separate after refactoring:

1. Move `FunctionTool` to `core/tools/function_tool.py`.
2. Update `chat.py` to import from it.
3. Or, if `FunctionTool` is no longer used, delete it.

### Phase 6 Verification

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q

# Verify language map consolidation
devenv shell -- python -c "
from remora.utils.languages import EXTENSION_TO_LANGUAGE
from remora.core.discovery import LANGUAGE_EXTENSIONS
assert EXTENSION_TO_LANGUAGE is LANGUAGE_EXTENSIONS or EXTENSION_TO_LANGUAGE == LANGUAGE_EXTENSIONS
print('Language maps consolidated: OK')
"
```

---

## 8. Verification Procedure (Per Phase)

After completing **each phase**, run this full checklist before proceeding:

### 8.1 Test Suite

```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```

**Known pre-existing failures** (do NOT count these as regressions):
- `test_lsp_handlers_register_and_advertise_capabilities` — missing `workspace/executeCommand`
- 2 cairn merge-ops tests (skipped via `--ignore`)
- 1 benchmark timeout (skipped via `--ignore`)

### 8.2 Type Checking

```bash
devenv shell -- pyright src/remora/
```

No new type errors related to the refactored code.

### 8.3 Dependency Graph Validation

```bash
devenv shell -- tach report --dot > .scratch/projects/architecture_refactor/tach_after_phaseN.dot
```

Check the dot file to confirm unwanted edges are removed:
- After Phase 1: `"remora.core" -> "remora.lsp"`, `"remora.core.events" -> "remora.companion.events"`, `"remora.core.projections" -> "remora.extensions"` should be **GONE**.
- After Phase 2: `"remora.lsp.handlers" -> "remora.lsp.server"` cycle should be **GONE**.

### 8.4 Core Isolation Check (After Phase 1)

```python
import sys, remora.core, remora.core.events, remora.core.projections
violations = [m for m in sys.modules if any(
    m.startswith(p) for p in ('remora.lsp', 'remora.companion', 'remora.extensions', 'pygls', 'lsprotocol')
)]
assert not violations, f"Core isolation violated: {violations}"
print("Core isolation: PASS")
```

---

## 9. Risk Assessment & Execution Order

### Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Phase 2 breaks LSP handler registration | **High** | High | Test LSP startup (via integration test or manual `remora-lsp` launch) after every handler modification |
| Phase 3 EventStore split introduces DB bugs | Medium | High | Pure extraction — no logic changes. Run full test suite after each file created. |
| Phase 1 `CoreEvent` rename breaks serialization | Low | Medium | `EventStore` uses `type(event).__name__` for dispatch, not the union type. Runtime is unaffected. |
| Phase 4 mass import renaming misses a reference | Medium | Low | Use `grep -rn` to find ALL references before moving. Run tests after every batch of moves. |
| Phase 5 `_HeadlessServer` protocol mismatch | Low | Medium | `@runtime_checkable` protocol + pyright catches mismatches at type-check time. |

### Recommended Execution Order

1. **Phase 1** — Smallest blast radius, biggest architectural win. Do first.
2. **Phase 6.1** (language maps) — Quick win, no dependencies on other phases.
3. **Phase 2** — Required before Phase 3/5 can move the runner.
4. **Phase 3** — Largest amount of work, but low risk (mechanical extraction).
5. **Phase 4** — Depends on Phase 3 (EventStore split must finish first).
6. **Phase 5** — Depends on Phases 1-3 (runner must be decoupled from LSP).
7. **Phase 6** remainder — Polish, lowest priority.

### Commit Strategy

Each step (e.g., 1.1, 1.2, 1.3) should be a **separate commit** with a descriptive message. This makes bisecting easy if something breaks. Example:

```
arch: remove AgentRunner re-export from core/__init__.py
arch: rename RemoraEvent to CoreEvent, decouple from CompanionEvent
arch: inject extension_matcher into NodeProjection
arch: remove module-level server singleton from lsp/server.py
...
```

---

*Generated from direct source audit of `src/remora/` on 2026-03-06. All line numbers verified against current codebase.*

