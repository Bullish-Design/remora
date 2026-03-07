# Plan: Architecture Refactor

## Objective
Implement the 5-phase refactoring plan outlined in `ARCH_REFACTOR_PLAN.md` to establish a clean downward-facing dependency graph and eliminate architectural violations.

## Execution Plan & Dependencies

### Phase 1: Sever Core -> LSP/Companion/Extensions (CRITICAL)
**Goal:** Remove all upward dependencies from `core/` so it can be imported and tested in isolation. Must be completed first, as it's the foundation.
1. Remove `AgentRunner` from `core/__init__.py`.
2. Define `CoreEvent` as union of only core events in `core/events.py` and decouple from `CompanionEvent`.
3. Modify `NodeProjection.__init__` to accept a callable `extension_matcher` instead of importing `remora.extensions`.

### Phase 2: Break LSP Circular Dependencies
**Goal:** Eliminate the `server <-> handlers <-> notifications` import cycle. Required before Phase 3.
1. Make `lsp/server.py` initialization explicit; remove module-level `server = get_server()` and `register_handlers()`.
2. Handlers receive the server instance via parameter injection.
3. Move `_WorkspaceProcessLock` and `_ParentProcessWatchdog` to `lsp/process_lock.py` and move `main()` to `__main__.py`.

### Phase 3: Decompose God-Objects & Group Core
**Goal:** Break apart oversized modules into focused, single-responsibility files and group the flat `core/` directory.
1. Break `EventStore` into 4 focused modules (`event_store.py`, `_schema.py`, `_queries.py`, `_connection.py`).
2. Split `AgentRunner` logic into `agent_runner.py`, `headless.py`, `trigger.py`.
3. Restructure `core/` into domain subdirectories (`store/`, `events/`, `agents/`, `code/`, `tools/`).

### Phase 4: Introduce Server Protocol
**Goal:** Formalize duck-typed server interface.
1. Add `RunnerServer` Protocol to explicitly formalize contracts used by `AgentRunner`.

### Phase 5: Cleanup and Polish
**Goal:** Eliminate remaining DRY violations and naming confusion.
1. Create `utils/languages.py` source of truth.
2. Rename `queries/` to `tree_sitter_queries/`.
3. Consolidate tool wrapping (`FunctionTool`).

### Verification Criteria
- `devenv shell -- python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` runs successfully.
- Dependency graph generation using `tach` shows no edges violating the layer architecture.
- Core packages can be imported without pulling in `lsp`, `companion`, or `extensions`.
