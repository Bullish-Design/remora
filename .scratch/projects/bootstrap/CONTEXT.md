# Bootstrap Implementation Project Context

## Status: IN PROGRESS — M0, M1, and M2 implemented; ready for M3

## Output
- `.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — implementation spec
- `.scratch/projects/bootstrap/IMPLEMENTATION_LOG.md` — concrete code/test change log

## What was done in this coding pass
- Committed and pushed M0+M1 work to `main`:
  - commit `f0920ef`
  - pushed to `origin/main`
- Implemented M2 schema loading layer:
  - added `src/remora/bootstrap/schema_loader.py`
  - `TurnSchema`, `ContextStep`, `SubscriptionSpec`
  - embedded `DEFAULT_SCHEMA_YAML` fallback
  - one-level `extends` merge from `system_agents_dir`
  - `resolve_context_vars()` for `{{name}}` placeholders
- Implemented M2 turn executor:
  - added `src/remora/bootstrap/turn_executor.py`
  - `TurnExecutor.run()` flow: load schema → context pipeline → prompt render → kernel run
  - `{node.*}` substitution in args/system prompt
  - active-tool filtering from schema tool list
  - client reuse support + safe response extraction
- Updated package exports in `src/remora/bootstrap/__init__.py`
- Added M2 tests:
  - `tests/unit/bootstrap/test_schema_loader.py`
  - `tests/unit/bootstrap/test_turn_executor.py`

## Validation completed
- `devenv shell -- pytest tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/schema_loader.py src/remora/bootstrap/turn_executor.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py`
- `devenv shell -- pytest tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_execution.py tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_subscriptions.py -q`
- All passing.

## Key decisions captured (see DECISIONS.md)
- D15/D16: Grail-safe external names + bedrock alias keys
- D17: schema.yaml loaded from Cairn workspace with one-level extends
- D18: context pipeline stays sequential and fail-soft

## Next step
- Start M3: self-bootstrap loop scaffolding (`bootstrap/agents/*.yaml` + coordinator wiring).

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
