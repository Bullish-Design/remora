# Bootstrap Implementation Project Context

## Status: IN PROGRESS — M0 and M1 implemented; ready for M2

## Output
- `.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — implementation spec
- `.scratch/projects/bootstrap/IMPLEMENTATION_LOG.md` — concrete code/test change log

## What was done in this coding pass
- Completed M1 Grail discovery extension in `src/remora/core/tools/grail.py`:
  - `discover_grail_tools()` now supports either `context` or explicit `externals`
  - optional workspace tool loading via `workspace_tools_dir`
  - `_make_tool_callable()` added for workspace-tool externals
  - swarm tools still attached only in context/v1 mode
- Added bootstrap system tools under `bootstrap/tools/`:
  - `read_file.pym`, `write_file.pym`
  - `graph_node.pym`, `graph_neighbors.pym`, `graph_find_nodes.pym`
  - `graph_add_node.pym`, `graph_add_edge.pym`
  - `read_recent_events.pym`, `emit_event.pym`
- Updated bedrock externals in `src/remora/bootstrap/bedrock.py`:
  - kept underscore APIs (`_cairn_*`, `_graph_*`, `_event_*`)
  - added Grail-safe aliases (`cairn_*`, `graph_*`, `event_*`)
- Added M1 tests:
  - `tests/unit/test_grail_discovery.py`
  - `tests/unit/bootstrap/test_system_tools.py`
  - updated `tests/unit/bootstrap/test_bedrock.py` with alias coverage
- Ensured system-tool tests compile to isolated temp Grail artifact dirs to avoid mutating repo `.grail/`
- Ran targeted test suites and ruff checks (all passing)

## Key decisions captured (see DECISIONS.md)
- NodeStore remains the unified graph API (M0)
- EventStore DB/path remains `.remora/events/events.db` (M0)
- `_event_read` remains agent-centric in v1 bootstrap (M0)
- For Grail compatibility, system tools use underscore-free external names and bedrock exposes alias keys (M1)

## V1 files modified so far
- `src/remora/core/store/event_store_schema.py`
- `src/remora/core/store/node_store.py`
- `src/remora/core/events/subscriptions.py`
- `src/remora/core/tools/grail.py`

## New files/directories so far
- `src/remora/bootstrap/__init__.py`
- `src/remora/bootstrap/bedrock.py`
- `bootstrap/tools/*.pym` (9 files)
- `tests/unit/test_event_store_schema.py`
- `tests/unit/test_node_store_graph.py`
- `tests/unit/test_grail_discovery.py`
- `tests/unit/bootstrap/__init__.py`
- `tests/unit/bootstrap/test_bedrock.py`
- `tests/unit/bootstrap/test_system_tools.py`
- `.scratch/projects/bootstrap/IMPLEMENTATION_LOG.md`

## Next step
- Start M2: implement `src/remora/bootstrap/schema_loader.py` and `src/remora/bootstrap/turn_executor.py` with stage-gated tests.

## 2026-03-08 decision lock (implementation kickoff)
The following decisions were reconfirmed with the user before coding:
- Reuse EventStore DB/path: `.remora/events/events.db`
- Subscription matching: hybrid event name (`event.event_type` fallback to class)
- Keep `_event_read` agent-centric in v1 bootstrap
- Code-neighbor topology is best-effort; do not rely on complete call graph
- Keep bootstrap graph in EventStore (not LSP indexer DB)
- Use `file` as canonical code unit kind (`module` optional alias)
- Implement in stage-gated milestones with tests between stages
- Minimal additional v1 changes allowed if required, with careful notes
