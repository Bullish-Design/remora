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
