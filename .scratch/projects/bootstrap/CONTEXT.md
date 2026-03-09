# Bootstrap Implementation Project Context

## Status: IN PROGRESS — M3 implemented locally; ready to commit/push, then start M4

## Output
- `.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — implementation spec
- `.scratch/projects/bootstrap/IMPLEMENTATION_LOG.md` — concrete code/test change log

## What was done in this coding pass
- M0+M1 previously committed/pushed in `f0920ef`.
- M2 previously committed/pushed in `18007eb`.
- Implemented M3 self-bootstrap loop scaffolding:
  - added `src/remora/bootstrap/activation.py`
    - `ActivationResult`, `default_agent_id()`, `handle_agent_needed()`
    - direct-subscription ensure + schema-subscription registration
    - bedrock/tool discovery + turn execution orchestration
    - agent node/edge persistence in graph store (`assigned_to`)
  - added `src/remora/bootstrap/coordinator.py`
    - `find_unassigned_modules()`
    - `emit_agent_needed_events()`
  - added bootstrap schemas:
    - `bootstrap/agents/DEFAULT_SCHEMA.yaml`
    - `bootstrap/agents/base_code_agent.yaml`
    - `bootstrap/agents/coordinator.yaml`
  - updated `src/remora/bootstrap/__init__.py` exports
  - added M3 tests:
    - `tests/unit/bootstrap/test_agent_schemas.py`
    - `tests/unit/bootstrap/test_coordinator.py`
    - `tests/unit/bootstrap/test_activation.py`

## Validation completed
- `devenv shell -- uv sync --extra dev`
- `devenv shell -- pytest tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/activation.py src/remora/bootstrap/coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py`
- All passing.

## Key decisions captured (see DECISIONS.md)
- D19: coordinator assignment source is `agent.attrs.assigned_node_id`
- D20: schema subscription `node_id` is currently informational (ignored in v1 matcher)
- D21: default agent IDs are deterministic and node-derived (`default_agent_id`)

## Next step
- Commit/push current M3 changes.
- Implement M4 graph seeding module (`src/remora/bootstrap/seed_graph.py`) + tests.

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
