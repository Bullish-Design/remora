# Architecture Refactoring Implementation Guide

> This guide provides step-by-step instructions for executing the refactoring phases
> outlined in `ARCH_REFACTOR_PLAN.md`. It is designed to be followed linearly.
> **CRITICAL RULE CHECK:** Proceed through these steps using direct tool action (No Subagents).
> After each compact or break, resume exactly where the `PROGRESS.md` leaves off.

---

## Table of Contents

1. **[Phase 1: Sever Core Dependencies](#phase-1-sever-core-dependencies)**
2. **[Phase 2: Break LSP Circular Dependencies](#phase-2-break-lsp-circular-dependencies)**
3. **[Phase 3: Decompose God-Objects & Group Core](#phase-3-decompose-god-objects--group-core)**
4. **[Phase 4: Introduce Server Protocol](#phase-4-introduce-server-protocol)**
5. **[Phase 5: Cleanup & Polish](#phase-5-cleanup--polish)**

---

## Phase 1: Sever Core Dependencies

**Goal:** Ensure `src/remora/core` handles zero imports from `lsp`, `companion`, or `extensions`.

### Step 1.1: Remove AgentRunner from `core/__init__.py`
**File:** `src/remora/core/__init__.py`
1. Locate `from remora.lsp.runner import AgentRunner`.
2. Delete this line.
3. Locate `AgentRunner` in the `__all__` list and remove it.
4. *Verification:* Search the codebase for `from remora.core import AgentRunner` or `from remora.core import .*AgentRunner`.
   - Update any occurrences to `from remora.lsp.runner import AgentRunner`.

### Step 1.2: Decouple RemoraEvent from CompanionEvent
**File:** `src/remora/core/events.py`
1. Locate `from remora.companion.events import CompanionEvent` and delete it.
2. Locate the `RemoraEvent` type union definition.
3. Rename the union definition from `RemoraEvent = (...)` to `CoreEvent = (...)`.
4. Remove `CompanionEvent` from this union.
5. Update `__all__` to export `CoreEvent` instead of `RemoraEvent` and remove `CompanionEvent`.
6. **File:** `src/remora/core/event_store.py` and `src/remora/core/event_bus.py`.
   - Change type hints from `RemoraEvent` to `_FrozenEvent` or `BaseModel` (whichever aligns best with the current base class).
7. *Verification:* Verify that `core.events` no longer depends on `companion.events`.

### Step 1.3: Decouple NodeProjection from extensions
**File:** `src/remora/core/projections.py`
1. Delete `from remora.extensions import extension_matches`.
2. Update `NodeProjection.__init__` signature:
   - Change `extension_configs: list[type] | None = None` to `extension_matcher: Callable | None = None`.
3. In `_project_node_discovered`, replace the iteration over `self._extension_configs` with a direct call to `self._extension_matcher` (if it exists) to get match data.
4. **File:** `src/remora/lsp/__init__.py` (inside `main()`) and `src/remora/service/api.py`.
   - Where `NodeProjection` is instantiated, pre-bind the matcher mechanism.
   - Example: Import `extension_matches` at the call site, wrap it in a lambda/partial bound to the loaded extensions, and pass it as `extension_matcher`.
5. *Verification:* Run `devenv shell -- python -c "import remora.core.projections"`. It should not crash or import `remora.extensions`.

---

## Phase 2: Break LSP Circular Dependencies

**Goal:** Eliminate the `server <-> handlers <-> notifications` import cycle.

### Step 2.1: Remove module-level singleton and side effects
**File:** `src/remora/lsp/server.py`
1. Locate `server = get_server()` (around line 237) and delete it.
2. Locate the `register_handlers()` function call (around line 259) at the module level and delete it.
3. Update `register_handlers()` definition to accept the server instance: `def register_handlers(server: RemoraLanguageServer):`

### Step 2.2: Extract process lock & startup logic
**File:** `src/remora/lsp/__init__.py`
1. Create a new file: `src/remora/lsp/process_lock.py`.
2. Move the `_WorkspaceProcessLock` and `_ParentProcessWatchdog` classes from `__init__.py` to `process_lock.py`.
3. Create a new file: `src/remora/lsp/__main__.py`.
4. Move the `main()` function and `_install_signal_handlers()` from `__init__.py` to `__main__.py`.
5. In `__main__.py`'s `main()` function:
   - Instantiate the server explicitly: `server = get_server()`.
   - Call handler registration explicitly: `register_handlers(server)`.
6. Leave `__init__.py` with only necessary re-exports (e.g., `__all__`).

### Step 2.3: Inject server into handlers
**Files:** All modules in `src/remora/lsp/handlers/` and `src/remora/lsp/notifications.py`
1. Globally search for `from remora.lsp.server import server` and delete it.
2. In each pygls `@server.feature` or `@server.command` handler function, add the `ls: LanguageServer` parameter if it's not already there (pygls injects it as the first argument).
3. Update the function body to use `ls` (or `cast(RemoraLanguageServer, ls)`) instead of the global `server` object.
4. Also update `emit_event` to not rely on the global server state directly; either pass the server to it or move it entirely to the server class (e.g., `server.emit_event()`).

---

## Phase 3: Decompose God-Objects & Group Core

**Goal:** Break apart oversized modules into focused files and reorganize `core/` into subpackages.

### Step 3.1: Create Core Subpackages
1. Create the following directories inside `src/remora/core/`:
   - `store/`
   - `events/`
   - `agents/`
   - `code/`
2. Add empty `__init__.py` files to each new subpackage.

### Step 3.2: Move and Group Existing Core Files
1. Move `event_store.py` to `core/store/`.
2. Move `events.py`, `event_bus.py`, and `subscriptions.py` to `core/events/`.
3. Move `agent_node.py`, `execution.py`, `workspace.py`, `state_manager.py`, `chat.py`, `kernel_factory.py`, and `cairn_bridge.py` to `core/agents/`.
4. Move `discovery.py` and `projections.py` to `core/code/`.
5. After moving, update ALL internal imports across the `src/remora/` codebase to point to the new subpackage paths. Using an IDE mass-rename or sed script is strongly recommended here.

### Step 3.3: Split EventStore
**File:** `src/remora/core/store/event_store.py` (formerly in core)
1. Split the file (~1193 lines) into four files inside `core/store/`:
   - `event_store.py`: The public API (EventStore class), append, replay, trigger queue.
   - `schema.py`: Database DDL, migrations, table creation (create_tables function).
   - `queries.py`: SQLite query strings and fetch logic (e.g., node hydration, chat history).
   - `connection.py`: SQLite connection management, retry/timeout logic, lock diagnostics.
2. Ensure `EventStore.initialize()` delegates to `schema.create_tables(self.db_path)`.

### Step 3.4: Extract AgentRunner Headless Logic
**File:** `src/remora/lsp/runner.py`
1. Create a new file: `src/remora/runner/headless.py` (must create `src/remora/runner/` directory).
2. Move `_HeadlessServer` and `_HeadlessDB` out of `runner.py` into `headless.py`.
3. Create a new file: `src/remora/runner/trigger.py`.
4. Move the `Trigger` pydantic model out of `runner.py` into `trigger.py`.
5. Update `runner.py` imports.

### Step 3.5: Clean up Tools Directory
1. **File:** `src/remora/core/tools/lsp.py`
   - Move to `src/remora/lsp/tools.py` to keep LSP-specific logic out of core.
   - Update imports in `lsp/server.py` to point to the new location.
2. **File:** `src/remora/core/agents/chat.py` (formerly core/chat.py)
   - Re-wire `FunctionTool` and `build_chat_tools()` to either use or be merged directly into the unified tool architecture in `core/tools/__init__.py`.

---

## Phase 4: Introduce Server Protocol

**Goal:** Formalize the duck-typed interface between the Runner and the Server.

### Step 4.1: Define ServerProtocol
1. Create a new file (or use an existing protocols file if one exists for the runner): `src/remora/runner/protocols.py`.
2. Define the `RunnerServer` protocol:
   `python
   from typing import Protocol, runtime_checkable, Any

   @runtime_checkable
   class RunnerServer(Protocol):
       event_store: Any
       db: Any
       subscriptions: Any | None
       proposals: dict[str, Any]

       def generate_correlation_id(self) -> str: ...
   `

### Step 4.2: Type AgentRunner
**File:** `src/remora/runner/agent_runner.py` (moved in Phase 3)
1. In `AgentRunner.__init__`, change the `server` argument type hint from `RemoraLanguageServer` to `RunnerServer`.
2. Ensure both `_HeadlessServer` (in `runner/headless.py`) and `RemoraLanguageServer` (in `lsp/server.py`) comply with this protocol via pyright type checking.

### Step 4.3: Final Top-Level Runner Package
1. If not already completely moved in Phase 3, ensure `AgentRunner` and its dependencies (`headless.py`, `trigger.py`, `protocols.py`) reside in a top-level `src/remora/runner/` package.
2. Update absolute imports globally: `from remora.lsp.runner import AgentRunner` becomes `from remora.runner.agent_runner import AgentRunner`.

---

## Phase 5: Cleanup & Polish

**Goal:** Address naming conflicts, duplicated logic, and dangling dependencies.

### Step 5.1: Consolidate Language Maps
1. Create a new file: `src/remora/utils/languages.py`.
2. Define the single source of truth for file-extension to language mappings:
   `python
   EXTENSION_TO_LANGUAGE: dict[str, tuple[str, str]] = {
       ".py": ("python", "python"),
       ".js": ("javascript", "javascript"),
       # ... combine from core.discovery, core.execution, core.agent_node
   }
   `
3. Update `discovery.py`, `execution.py`, and `agent_node.py` (now in `core/code/` and `core/agents/`) to import this single map.

### Step 5.2: Rename Queries Directory
1. Rename the directory `src/remora/queries/` to `src/remora/ts_queries/` (or similar) since it holds tree-sitter `.scm` files, not SQL.
2. Update the reference in `discovery.py`: find `_get_query_dir()` and update the path string.

### Step 5.3: Clean up `__init__.py` Exports
1. Wait until Phase 1-5 are fully integrated.
2. Open `src/remora/core/__init__.py` and prune the `__all__` list. If an object is better imported directly from its subpackage (e.g., `from remora.core.agents import AgentNode`), remove it from the root `__init__.py` to avoid eager loading of the entire core ecosystem.
3. Open `src/remora/lsp/__init__.py` and ensure it's ~20 lines, only containing necessary re-exports, with all locking/startup logic successfully moved.

---

## Verification Steps Per Phase

After completing **each phase**, follow this verification checklist before proceeding to the next phase.

**1. Test Suite validation:**
```bash
devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q
```
*Expected: No new test failures. Remember: 1 lsp handler test, 2 cairn tests, and 1 benchmark timeout are known failures.*

**2. Type Checking:**
```bash
devenv shell -- pyright src/remora/
```
*Expected: No new type check errors related to the refactored code.*

**3. Dependency Graph Validation (Crucial for Phase 1 & 2):**
```bash
devenv shell -- tach report --dot > tach_module_graph_after.dot
```
*Check the dot file to ensure `"remora.core" -> "remora.lsp"` and `"remora.core.events" -> "remora.companion.events"` edges are gone.*

**4. Core Isolation Validation:**
Create a temporary scratch script and run it:
```python
# tmp_test_core_import.py
import remora.core
import remora.core.events
import remora.core.code.projections
print("Core imported successfully!")
```
Run: `devenv shell -- python tmp_test_core_import.py`
*Expected: It must print without crashing and without Pygls/LanguageServer being instantiated.*
