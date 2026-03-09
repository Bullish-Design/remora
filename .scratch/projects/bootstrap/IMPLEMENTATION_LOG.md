# Bootstrap Implementation Log

## 2026-03-08 — M0 implementation (completed)

### v1 files changed
- `src/remora/core/store/event_store_schema.py`
  - Added `create_graph_tables()` for `graph_nodes` and `graph_edges`.
  - Wired graph table creation into `create_tables()`.
- `src/remora/core/store/node_store.py`
  - Added unified graph API:
    - `read_graph(selector)`
    - `write_graph(op, data)`
  - Added graph read/write helpers for:
    - single-node lookup (`nodes` table fallback to `graph_nodes`)
    - neighbor lookup (code-node `caller_ids`/`callee_ids`, generic `graph_edges`)
    - kind/attribute matching
    - add node / add edge writes into `graph_nodes` / `graph_edges`
  - Added `CODE_NODE_KINDS` and `module -> file` compatibility alias on reads.
  - Enforced bootstrap write protection: code-node kinds are rejected in `write_graph("add_node", ...)`.

### additional v1 changes (beyond original 3-file target)
- `src/remora/core/events/subscriptions.py`
  - Added hybrid event-name resolution:
    - prefers `event.event_type` when present
    - falls back to `type(event).__name__`
  - Applied this to both pattern matching and cache lookup.
  - Reason: enables bootstrap dynamic event envelopes while preserving existing class-name routing.

### new bootstrap files
- `src/remora/bootstrap/__init__.py`
- `src/remora/bootstrap/bedrock.py`
  - `BootstrapEvent` envelope
  - `build_bedrock(...)` with six async bedrock functions
  - `_make_files_provider(...)`
  - `_extract_workspace_tools(...)`

### non-runtime metadata updates
- `tach.toml`
  - Added `remora.bootstrap` module dependency declaration.

### tests added/updated
- Added `tests/unit/test_event_store_schema.py`
  - verifies `graph_nodes` / `graph_edges` creation.
- Added `tests/unit/test_node_store_graph.py`
  - exercises new graph read/write APIs and module alias behavior.
- Added `tests/unit/bootstrap/test_bedrock.py`
  - verifies bedrock delegation and event append behavior.
- Added `tests/unit/bootstrap/__init__.py`
- Updated `tests/unit/test_subscriptions.py`
  - added coverage for dynamic `event_type` matching.

### test commands run
- `devenv shell -- uv sync --extra dev`
- `devenv shell -- pytest tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_subscriptions.py -q`
- `devenv shell -- pytest tests/unit/test_event_store_nodes_query.py tests/unit/test_nodes_table.py -q`

## 2026-03-08 — M1 implementation (completed)

### v1 files changed
- `src/remora/core/tools/grail.py`
  - Extended `discover_grail_tools()` to support:
    - `context: AgentContext | None`
    - `externals: dict[str, Any] | None`
    - `workspace_tools_dir: Path | None`
  - Added `_make_tool_callable()` to expose loaded system Grail tools as async externals.
  - Preserved v1 behavior: Swarm tools only added when `context` is provided.

### bootstrap files changed
- `src/remora/bootstrap/bedrock.py`
  - Added Grail-safe alias keys in the returned externals map:
    - `cairn_read`, `cairn_write`, `graph_read`, `graph_write`, `event_read`, `event_write`
  - Kept canonical underscore keys intact (`_cairn_*`, `_graph_*`, `_event_*`).

### new files
- `bootstrap/tools/read_file.pym`
- `bootstrap/tools/write_file.pym`
- `bootstrap/tools/graph_node.pym`
- `bootstrap/tools/graph_neighbors.pym`
- `bootstrap/tools/graph_find_nodes.pym`
- `bootstrap/tools/graph_add_node.pym`
- `bootstrap/tools/graph_add_edge.pym`
- `bootstrap/tools/read_recent_events.pym`
- `bootstrap/tools/emit_event.pym`
- `tests/unit/test_grail_discovery.py`
- `tests/unit/bootstrap/test_system_tools.py`

### tests updated
- `tests/unit/bootstrap/test_bedrock.py`
  - added coverage that alias keys exist and execute correctly.

### notable implementation notes
- Grail Input declarations in `.pym` files must be top-level assignments
  (`name: type = Input("name")`) for runtime input validation to work.
- Grail/Monty currently fails type-checking for leading-underscore external
  references inside scripts; this drove D15/D16 (underscore-free script
  externals + bedrock alias keys).
- System-tool tests now compile with `grail_dir=tmp_path / ".grail"` to avoid
  mutating repository `.grail/` artifacts during test runs.

### test/lint commands run
- `devenv shell -- pytest tests/unit/test_grail_discovery.py -q` (fail first, then pass after implementation)
- `devenv shell -- pytest tests/unit/bootstrap/test_system_tools.py -q` (fail first, then pass after tool runtime fixes)
- `devenv shell -- ruff check src/remora/core/tools/grail.py src/remora/bootstrap/bedrock.py tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/bootstrap/test_bedrock.py`
- `devenv shell -- pytest tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/test_execution.py tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_subscriptions.py -q`

## 2026-03-08 — M2 implementation (completed)

### bootstrap files added
- `src/remora/bootstrap/schema_loader.py`
  - Added `TurnSchema`, `ContextStep`, `SubscriptionSpec`
  - Added embedded `DEFAULT_SCHEMA_YAML` fallback
  - Added `load_schema(cairn_externals, system_agents_dir=...)`
  - Added one-level `extends` support with list-append merge for
    `context` / `tools` / `subscriptions`
  - Added `resolve_context_vars()` for `{{name}}` substitutions
- `src/remora/bootstrap/turn_executor.py`
  - Added `TurnResult` dataclass
  - Added `TurnExecutor` with:
    - schema load from Cairn workspace
    - sequential context pipeline
    - `{node.*}` + `{{name}}` prompt resolution
    - schema-based tool activation and kernel dispatch
    - response extraction + kernel close safety

### bootstrap package exports updated
- `src/remora/bootstrap/__init__.py`
  - Exported schema loader models/functions and turn executor types.

### tests added
- `tests/unit/bootstrap/test_schema_loader.py`
  - default schema fallback
  - workspace schema load
  - `extends` merge behavior
  - context variable substitution
- `tests/unit/bootstrap/test_turn_executor.py`
  - context pipeline + prompt resolution + kernel dispatch
  - client reuse path + optional missing context step behavior

### validation commands run
- `devenv shell -- pytest tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/schema_loader.py src/remora/bootstrap/turn_executor.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py`
- `devenv shell -- pytest tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_execution.py tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_subscriptions.py -q`

## 2026-03-08 — M3 implementation (completed)

### bootstrap files added
- `src/remora/bootstrap/activation.py`
  - Added `ActivationResult`
  - Added deterministic `default_agent_id(node_id)`
  - Added `handle_agent_needed(...)` orchestration:
    - workspace initialization (`SyncMode.NONE`)
    - `CairnExternals` creation
    - bedrock + tool discovery (system + extracted workspace tools)
    - node attribute load from graph
    - `TurnExecutor` execution
    - schema reload and subscription registration
    - graph writes for `kind=agent` node + `assigned_to` edge
  - Added helpers for direct subscription and schema subscription registration.
- `src/remora/bootstrap/coordinator.py`
  - Added `AgentNeededPlan`
  - Added `find_unassigned_modules(event_store)`
  - Added `emit_agent_needed_events(event_store, swarm_id, coordinator_id=...)`
- `src/remora/bootstrap/__init__.py`
  - Exported activation/coordinator symbols.

### bootstrap schema assets added
- `bootstrap/agents/DEFAULT_SCHEMA.yaml`
- `bootstrap/agents/base_code_agent.yaml`
- `bootstrap/agents/coordinator.yaml`

### tests added
- `tests/unit/bootstrap/test_agent_schemas.py`
  - schema file existence + `TurnSchema` validation + coordinator subscriptions
- `tests/unit/bootstrap/test_coordinator.py`
  - unassigned-module detection + `AgentNeededEvent` emission verification
- `tests/unit/bootstrap/test_activation.py`
  - activation orchestration, subscription behavior, graph writes, deterministic id fallback

### notable implementation notes
- `subscriptions[].node_id` in schema is currently informational only; v1
  `SubscriptionPattern` has no node-id filter support.
- Coordinator assignment detection currently uses `agent.attrs.assigned_node_id`
  as the source of truth.

### validation commands run
- `devenv shell -- uv sync --extra dev`
- `devenv shell -- pytest tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/activation.py src/remora/bootstrap/coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py`

## 2026-03-08 — M4 implementation (completed)

### bootstrap files added
- `src/remora/bootstrap/seed_graph.py`
  - Added `seed_module_nodes_from_filesystem(event_store, project_root, swarm_id=...)`
  - Added `seed_coordinator_node(event_store, coordinator_id=...)`
  - Added `seed_modules_if_empty(event_store, project_root, swarm_id=...)`
  - Added module entrypoint (`python -m remora.bootstrap.seed_graph`) that:
    - uses existing DB path `.remora/events/events.db`
    - initializes `EventStore(..., projection=NodeProjection())`
    - seeds coordinator node + conditional module fallback seed

### bootstrap package exports updated
- `src/remora/bootstrap/__init__.py`
  - exported `seed_module_nodes_from_filesystem`
  - exported `seed_coordinator_node`
  - exported `seed_modules_if_empty`

### tests added
- `tests/unit/bootstrap/test_seed_graph.py`
  - verifies filesystem fallback creates module nodes and skips ignored dirs
  - verifies conditional skip when module nodes already exist
  - verifies coordinator graph node creation

### notable implementation notes
- Module fallback seeding is implemented via `NodeDiscoveredEvent` projection
  writes into the `nodes` table, not direct `graph_nodes` inserts for `module`.
  This keeps code-node seeding aligned with existing `NodeStore` write guards.

### validation commands run
- `devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/seed_graph.py tests/unit/bootstrap/test_seed_graph.py`
- `devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/test_subscriptions.py -q`

## 2026-03-08 — M5 implementation (completed)

### companion files added
- `src/remora/companion/sidebar/workspace.py`
  - Added `WorkspacePanel` dataclass
  - Added `build_workspace_panels(workspace)`:
    - reads `role.md`, `schema.yaml`, `notes.md`, `todo.md`, `log.jsonl`
    - truncates log panel to last 20 non-empty lines
    - lists synthesized tools from `tools/*.pym`
    - marks each panel with `is_empty`

### companion files changed
- `src/remora/companion/sidebar/composer.py`
  - Integrated workspace panel rendering into markdown sidebar
  - Added `## Workspace` section with per-panel `###` headers
  - Section renders only when at least one panel is non-empty

### tests added
- `tests/unit/companion/test_workspace_panels.py`
  - verifies panel loading and log truncation behavior
  - verifies missing-file empty-state behavior
  - verifies `compose_sidebar()` renders workspace section when populated

### validation commands run
- `devenv shell -- ruff check src/remora/companion/sidebar/composer.py src/remora/companion/sidebar/workspace.py tests/unit/companion/test_workspace_panels.py`
- `devenv shell -- pytest tests/unit/companion/test_workspace_panels.py tests/unit/companion/test_node_agent.py tests/unit/companion/test_node_workspace.py tests/unit/companion/test_registry.py tests/unit/companion/test_router.py tests/unit/companion/test_startup.py tests/unit/companion/test_swarms.py -q`

## 2026-03-08 — M6 implementation (completed)

### bootstrap files changed
- `src/remora/bootstrap/activation.py`
  - Added workspace tool snapshot helper (`_list_workspace_tool_files`)
  - Added synthesized-tool event helper (`_emit_tool_synthesized_events`)
  - `handle_agent_needed()` now:
    - snapshots workspace `tools/*.pym` before turn
    - snapshots again after turn
    - emits `ToolSynthesizedEvent` for each new tool file

### tests changed
- `tests/unit/bootstrap/test_activation.py`
  - Added `test_handle_agent_needed_emits_tool_synthesized_event`
    - verifies new tool diff results in `BootstrapEvent(event_type="ToolSynthesizedEvent")`

### notable implementation notes
- Tool synthesis events are produced by activation-level diffing, not by adding
  side effects to `write_file.pym`. This keeps behavior independent of how a
  tool file was created during the turn.

### validation commands run
- `devenv shell -- ruff check src/remora/bootstrap/activation.py tests/unit/bootstrap/test_activation.py`
- `devenv shell -- pytest tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/test_grail_discovery.py -q`
- `devenv shell -- pytest tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_grail_discovery.py tests/unit/companion/test_workspace_panels.py -q`

## 2026-03-08 — M7 implementation (completed)

### tests added
- `tests/integration/test_bootstrap_loop.py`
  - Added `test_bootstrap_loop_emits_and_handles_agent_needed`
    - seeds module discovery through `NodeDiscoveredEvent`
    - verifies coordinator emits one `AgentNeededEvent`
    - verifies activation persists agent assignment to graph
    - verifies direct + `ContentChangedEvent` subscriptions are registered
    - verifies activation emits one `ToolSynthesizedEvent` for new workspace tool

### non-runtime metadata updates
- `.grail/add_tool/check.json`
  - Updated by local Grail metadata churn during test execution.
  - User explicitly approved including this change in commit.

### notable implementation notes
- Integration test uses `await agentfs_available()` (async-safe) instead of
  sync helper to avoid nested event-loop runtime errors.

### validation commands run
- `devenv shell -- ruff check tests/integration/test_bootstrap_loop.py`
- `devenv shell -- pytest tests/integration/test_bootstrap_loop.py -q`
- `devenv shell -- pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q`

## 2026-03-08 — M8 implementation (completed)

### bootstrap files added
- `src/remora/bootstrap/runner.py`
  - Added `BootstrapRunner` lifecycle:
    - path setup for existing EventStore layout (`.remora/events/events.db`)
    - resource initialization (`SubscriptionRegistry`, `EventStore`, `CairnWorkspaceService`)
    - coordinator/module fallback seeding
    - one-pass orchestration (`run_once`) for:
      `find_unassigned_modules` -> `emit_agent_needed_events` -> `handle_agent_needed`
    - long-running polling loop (`run_forever`) plus `stop()` and `close()`
  - Added `run_bootstrap(config, ...)` convenience entrypoint.

### bootstrap files changed
- `src/remora/bootstrap/__init__.py`
  - Exported `BootstrapRunner` and `run_bootstrap`.

### tests added
- `tests/unit/bootstrap/test_runner.py`
  - verifies default DB path layout
  - verifies run-once orchestration emits + handles unassigned modules
  - verifies run-forever exits when stopped

### notable implementation notes
- Runner reuses existing DB path conventions from prior decisions:
  - event store: `.remora/events/events.db`
  - subscription store: `.remora/events/subscriptions.db`
- Activation is executed from deterministic plans found before emission to keep
  one-pass behavior stable in v1 bootstrap runtime.

### validation commands run
- `devenv shell -- uv sync --extra dev`
- `devenv shell -- pytest tests/unit/bootstrap/test_runner.py -q` (fail first, then pass after implementation)
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py --fix`
- `devenv shell -- ruff check src/remora/bootstrap/runner.py src/remora/bootstrap/__init__.py tests/unit/bootstrap/test_runner.py`
- `devenv shell -- pytest tests/unit/bootstrap/test_runner.py tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_coordinator.py -q`
- `devenv shell -- pytest tests/unit/bootstrap/ -q`
- `devenv shell -- pytest tests/integration/test_bootstrap_loop.py -q`

### commit
- `c8814e5` — Add bootstrap runner runtime loop and tests

## 2026-03-08 — M9 implementation (completed; commit pending)

### core files added
- `src/remora/core/runtime_paths.py`
  - Added `RuntimePaths` dataclass with `from_config(...)` resolver for:
    - project root
    - swarm root
    - EventStore path
    - subscriptions path
    - bootstrap root
    - models root

### core files changed
- `src/remora/core/config.py`
  - Added `bootstrap_enabled` and `bootstrap_poll_interval_s` config fields.
- `src/remora/core/__init__.py`
  - Exported `RuntimePaths`.

### bootstrap files changed
- `src/remora/bootstrap/runner.py`
  - Switched path resolution to `RuntimePaths`.
  - Added support for shared runtime primitives (`event_store`,
    `subscriptions`, `workspace_service`) for LSP integration.
  - Added ownership-aware close behavior (do not close shared resources).

### lsp files changed
- `src/remora/lsp/__main__.py`
  - `_prepare()` now derives paths via `RuntimePaths`.
  - `_run_server()` accepts shared `config` + `runtime_paths`.
  - Configures and starts `BootstrapRunner` loop on LSP initialized event.
  - Adds bootstrap task cancellation/cleanup on shutdown.

### companion files changed
- `src/remora/companion/startup.py`
  - Added assignment-aware workspace owner resolver using graph lookup:
    `kind=agent` + `assigned_node_id=<node_id>`.
- `src/remora/companion/registry.py`
  - Added injectable `workspace_owner_resolver`.
  - Added workspace-owner tracking and re-creation when ownership changes.

### tests added/changed
- `tests/unit/test_runtime_paths.py` (new)
  - default and override path resolution coverage.
- `tests/unit/bootstrap/test_runner.py`
  - updated expected subscriptions path.
- `tests/unit/companion/test_registry.py`
  - added resolver usage and owner-change rebind tests.
- Existing LSP startup tests exercised updated `_run_server` flow.

### validation commands run
- `devenv shell -- ruff check src/remora/core/runtime_paths.py src/remora/core/config.py src/remora/bootstrap/runner.py src/remora/lsp/__main__.py src/remora/companion/registry.py src/remora/companion/startup.py tests/unit/bootstrap/test_runner.py tests/unit/test_runtime_paths.py tests/unit/companion/test_registry.py`
- `devenv shell -- pytest tests/unit/test_runtime_paths.py tests/unit/bootstrap/test_runner.py tests/unit/companion/test_registry.py tests/unit/companion/test_startup.py -q`
- `devenv shell -- pytest tests/unit/bootstrap/ tests/unit/companion/ -q`
- `devenv shell -- pytest tests/unit/test_lsp_startup_sequence.py tests/unit/test_lsp_background_scan_manifest.py -q`
- `devenv shell -- pytest tests/integration/test_bootstrap_loop.py -q`
- `devenv shell -- pytest tests/unit/test_runtime_paths.py tests/unit/bootstrap/test_runner.py tests/unit/companion/test_registry.py tests/unit/test_lsp_startup_sequence.py tests/unit/test_lsp_background_scan_manifest.py tests/integration/test_bootstrap_loop.py -q`
