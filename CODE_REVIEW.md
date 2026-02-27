# Remora v0.4.0 Refactor Code Review

## Scope
Reviewed the v0.4.0 refactor guides in `.refactor/`, the provided v0.4.0 refactor plan, plus the current Remora library implementation in `src/remora/`, `agents/`, and `tests/`. This report focuses on mismatches against the v0.4.0 concept and areas needing cleanup or refactoring.

## High-Level Summary
The codebase contains partial v0.4.0 modules (events, discovery, graph, executor, workspace, checkpoint, indexer, dashboard), but large portions of the legacy v0.3 architecture remain in place and are still referenced by the public API and CLI. Several critical runtime paths are stubs or inconsistent with the refactor plan, including EventBus integration with structured-agents, bundle metadata wiring, GraphExecutor execution, Cairn workspace creation, and dashboard event handling. The bundle/tool layer and tests still reflect the older “external I/O” patterns and Hub-based services.

## Detailed Findings

### 1) Public API still exposes legacy modules and types
- `src/remora/__init__.py` exports legacy `AgentGraph`, `GraphConfig`, and legacy workspace classes (`GraphWorkspace`, `WorkspaceKV`, `WorkspaceManager`) even though the v0.4 plan replaces them with the flattened graph and Cairn wrappers. This keeps the v0.3 API surface alive and encourages use of removed abstractions. (`src/remora/__init__.py:1`)
- The module also re-exports `Event` from `event_bus.py`, which is explicitly a backwards-compatibility type that the refactor intended to retire. (`src/remora/event_bus.py:276`)

### 2) Event system is not aligned with structured-agents contracts
- `src/remora/events.py` defines stub versions of structured-agents event classes instead of importing the real ones. Step 1 requires direct imports from `structured_agents.events` with no fallback stubs. (`src/remora/events.py:19`)
- The exported kernel event names include `TurnComplete` rather than the expected `TurnCompleteEvent`. This makes the exported event taxonomy inconsistent with structured-agents. (`src/remora/events.py:85`)
- The EventBus is meant to re-emit kernel events from the structured-agents observer stream, but the current event taxonomy cannot safely interoperate with structured-agents because of the stubbed event classes. (`src/remora/event_bus.py:83`)

### 3) Config surface is inconsistent and partially broken
- `serialize_config()` references attributes that do not exist on the new dataclasses (`config.indexer.enabled`, `config.dashboard.enabled`, `config.workspace.path`, `config.model.api_key`). This will raise `AttributeError` at runtime and indicates the config serialization layer is still based on the old schema. (`src/remora/config.py:150`)
- The main CLI passes `overrides` into `load_config()` even though `load_config()` only accepts a path. This will raise `TypeError`. (`src/remora/cli.py:145`, `src/remora/config.py:112`)
- The plan calls for `model_base_url` and `api_key` in `remora.yaml`, plus Remora-owned `BundleMetadata` mappings keyed by bundle name; neither exists in the `RemoraConfig` dataclasses or serialization paths. (`src/remora/config.py:91`)

### 4) Graph topology ignores bundle metadata
- The plan requires Remora-owned `BundleMetadata` (node types, priority, requires_context) keyed by bundle name, but the graph builder only accepts a `node_type -> bundle_path` map and never orders nodes by priority or tracks context requirements. (`src/remora/graph.py:41`)

### 5) Graph executor is a stub and lacks required integrations
- `execute_agent()` returns a hardcoded placeholder and does not use `Agent.from_bundle()`, does not set `STRUCTURED_AGENTS_BASE_URL`/`STRUCTURED_AGENTS_API_KEY`, and does not apply the `CairnResultHandler`. (`src/remora/executor.py:85`)
- `GraphExecutor` never enforces `skip_downstream` behavior or emits `GraphErrorEvent`, and it does not follow the error-handling contract described in Step 7. (`src/remora/executor.py:114`)
- The executor does not pass context into agents or provide a ResultSummary surface for dashboard/context consumers. (`src/remora/executor.py:114`)

### 6) Cairn workspace layer is incomplete and still carries legacy types
- `create_workspace()`, `create_shared_workspace()`, `snapshot_workspace()`, and `restore_workspace()` are all `NotImplementedError` placeholders. This blocks executor, checkpoint, and tool execution from working end-to-end. (`src/remora/workspace.py:148`)
- `CairnResultHandler.handle()` does not return a `ResultSummary` for context/dashboard consumption as required by the plan. (`src/remora/workspace.py:83`)
- Legacy workspace types (`WorkspaceKV`, `GraphWorkspace`, `WorkspaceManager`) are left as empty placeholder classes, contradicting Step 4 cleanup. (`src/remora/workspace.py:209`)

### 7) Dashboard does not consume the EventBus stream
- The dashboard UI never updates state because `DashboardState.record()` is never called when events arrive. The `subscribe()` loop emits views without recording events. (`src/remora/dashboard/app.py:49`, `src/remora/dashboard/state.py:23`)
- `_execute_graph()` calls `executor.run(agent_nodes)` without the required `workspace_config` argument, so execution will fail. (`src/remora/dashboard/app.py:128`, `src/remora/executor.py:122`)
- `_trigger_graph()` builds the bundle map with `{bundle_name: Path(...)}` but `build_graph()` expects a map keyed by `node_type`. This yields no agent nodes when node types are `function`, `class`, or `file`. (`src/remora/dashboard/app.py:107`, `src/remora/graph.py:41`)

### 8) CLI still targets legacy Hub and config structure
- The main CLI references hub metrics and legacy config fields (`config.server`, `config.operations`, `config.agents_dir`). This is incompatible with the v0.4 `RemoraConfig` schema. (`src/remora/cli.py:183`)
- The legacy hub CLI still exists (`src/remora/hub/cli.py`) and pulls constants and hub DB names that Step 15 cleanup calls for removing. (`src/remora/hub/cli.py:1`)

### 9) Legacy packages remain alongside new v0.4 modules
The cleanup guide (Step 15) calls for removing these packages, but they still exist:
- `src/remora/hub/` (legacy services)
- `src/remora/frontend/` (absorbed by dashboard)
- `src/remora/interactive/` (replaced by event-based IPC)
- `src/remora/discovery/` and `src/remora/context/` (should be consolidated)
- `src/remora/agent_graph.py`, `src/remora/agent_state.py`, `src/remora/backend.py`, `src/remora/constants.py` (deprecated core)

### 10) Bundle/tool layer still uses legacy or disallowed patterns
- Bundle files still reference tools that should be removed in Step 9 (e.g., `tools/read_file.pym`, `tools/run_tests.pym`). (`agents/lint/bundle.yaml:1`, `agents/test/bundle.yaml:1`)
- Several `.pym` tools still declare `@external` for local file or lint operations (e.g., `run_ruff_check`, `apply_ruff_fix`), which violates the “Input-only, external-only-for-ask_user” contract. (`agents/lint/tools/run_linter.pym:1`, `agents/lint/tools/apply_fix.pym:1`)
- Legacy context scripts (`agents/*/context/*.pym`) remain, despite the new contract that DataProviders supply files instead of running context tools. (`agents/docstring/context/docstring_style.pym:1`, `agents/test/context/pytest_config.pym:1`)
- There is no Remora-specific Grail tool loader that instantiates scripts once per bundle with the `files` dict and `ask_user` external adapter; the current executor does not integrate this flow at all. (`src/remora/executor.py:85`)

### 11) Tests still target legacy Hub-centric behavior
- The test suite contains extensive `tests/hub/*` coverage and `agent_graph`/`agent_state` tests, which indicate refactor tests have not replaced legacy coverage. This will prevent clean removal of the Hub and workspace abstractions and masks v0.4 regressions.

## Recommendations (Priority Order)

1) **Replace stubs with working integrations**
   - Implement `execute_agent()` with `Agent.from_bundle()`, set `STRUCTURED_AGENTS_BASE_URL`/`STRUCTURED_AGENTS_API_KEY`, pass `CairnDataProvider`, and persist results with `CairnResultHandler` + `ResultSummary`.
   - Implement Cairn workspace creation + snapshot/restore to enable executor and checkpoint flows.

2) **Align config + CLI to the new schema**
   - Add `model_base_url`/`api_key` and Remora `BundleMetadata` mappings to `RemoraConfig` and `remora.yaml`.
   - Remove legacy CLI options, wire `RemoraConfig` to discovery/graph/executor exactly as the plan describes.
   - Fix `serialize_config()` to reference only the new dataclass fields.

3) **Clean the public API and delete legacy modules**
   - Remove exports of `AgentGraph`, `GraphWorkspace`, `WorkspaceKV`, and legacy Event types.
   - Delete the legacy packages and files listed in Step 15.

4) **Make dashboard functional**
   - Subscribe to EventBus and call `DashboardState.record()` as events arrive.
   - Fix `_execute_graph()` and bundle mapping in `_trigger_graph()` so execution can start.

5) **Complete agent/tool refactor**
   - Remove `read_file.pym`, `ruff_config.pym`, and `pytest_config.pym` scripts.
   - Replace remaining `@external` usage with `Input()`-driven data flows (only keep `ask_user`).
   - Update bundle.yaml files accordingly.

6) **Replace or update tests**
   - Add v0.4 tests for events, executor, workspace, and context per the step guides.
   - Remove or quarantine legacy Hub tests once the new architecture is verified.

---

## Notable Strengths
- `src/remora/discovery.py` is a clean consolidation of discovery logic and largely matches Step 2.
- `src/remora/graph.py` implements the expected pure topology layer with dependency helpers.
- `src/remora/checkpoint.py` is aligned with the Cairn snapshot-based approach (pending workspace integration).
- `src/remora/indexer/` package largely matches the step guide structure.
