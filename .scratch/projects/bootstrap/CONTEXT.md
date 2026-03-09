# Bootstrap Implementation Project Context

## Status: IN PROGRESS — M3/M4/M5 committed+pushed; M6 implemented locally and validated

## Output
- `.scratch/projects/bootstrap/IMPLEMENTATION_GUIDE.md` — implementation spec
- `.scratch/projects/bootstrap/IMPLEMENTATION_LOG.md` — concrete code/test change log

## What was done in this coding pass
- M0+M1 previously committed/pushed in `f0920ef`.
- M2 previously committed/pushed in `18007eb`.
- M3 self-bootstrap loop scaffolding was committed and pushed:
  - commit `7953623`
- M4 graph seeding support was committed and pushed:
  - commit `20f01a9`
- M5 companion workspace visibility was committed and pushed:
  - commit `2af3e50`
- Implemented M6 tool synthesis hardening:
  - updated `src/remora/bootstrap/activation.py`
    - tracks workspace tool file set before/after each activation turn
    - emits `ToolSynthesizedEvent` for newly created `tools/*.pym` files
      (payload includes `node_id`, `agent_id`, `tool_name`, `file_path`)
  - updated `tests/unit/bootstrap/test_activation.py`
    - added coverage for synthesized-tool event emission path

- Previously implemented M5 artifacts:
  - added `src/remora/companion/sidebar/workspace.py`
    - `WorkspacePanel` dataclass
    - `build_workspace_panels(workspace)` for `role.md`, `schema.yaml`,
      `notes.md`, `todo.md`, `log.jsonl`, and workspace `tools/*.pym`
  - updated `src/remora/companion/sidebar/composer.py`
    - adds `## Workspace` section when workspace identity content exists
    - renders each panel with `### <Title>` and content/empty marker
  - added `tests/unit/companion/test_workspace_panels.py`
    - panel construction and log truncation behavior
    - empty-state behavior
    - compose-sidebar integration assertion

- Previously implemented M4 artifacts:
  - added `src/remora/bootstrap/seed_graph.py`
    - `seed_module_nodes_from_filesystem()`
    - `seed_coordinator_node()`
    - `seed_modules_if_empty()`
    - module entrypoint uses existing DB path: `.remora/events/events.db`
  - updated `src/remora/bootstrap/__init__.py` exports for seeding APIs
  - added `tests/unit/bootstrap/test_seed_graph.py`
    - filesystem seeding creates module nodes via `NodeDiscoveredEvent` projection
    - skip path when module nodes already exist
    - coordinator graph-node creation

- Previously implemented M3 artifacts (now pushed):
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
- `devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/__init__.py src/remora/bootstrap/seed_graph.py tests/unit/bootstrap/test_seed_graph.py`
- `devenv shell -- pytest tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_grail_discovery.py tests/unit/bootstrap/test_system_tools.py tests/unit/bootstrap/test_bedrock.py tests/unit/test_event_store_schema.py tests/unit/test_node_store_graph.py tests/unit/test_subscriptions.py -q`
- `devenv shell -- ruff check src/remora/companion/sidebar/composer.py src/remora/companion/sidebar/workspace.py tests/unit/companion/test_workspace_panels.py`
- `devenv shell -- pytest tests/unit/companion/test_workspace_panels.py tests/unit/companion/test_node_agent.py tests/unit/companion/test_node_workspace.py tests/unit/companion/test_registry.py tests/unit/companion/test_router.py tests/unit/companion/test_startup.py tests/unit/companion/test_swarms.py -q`
- `devenv shell -- ruff check src/remora/bootstrap/activation.py tests/unit/bootstrap/test_activation.py`
- `devenv shell -- pytest tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/test_grail_discovery.py -q`
- `devenv shell -- pytest tests/unit/bootstrap/test_activation.py tests/unit/bootstrap/test_coordinator.py tests/unit/bootstrap/test_agent_schemas.py tests/unit/bootstrap/test_seed_graph.py tests/unit/bootstrap/test_schema_loader.py tests/unit/bootstrap/test_turn_executor.py tests/unit/test_grail_discovery.py tests/unit/companion/test_workspace_panels.py -q`
- All passing.

## Key decisions captured (see DECISIONS.md)
- D19: coordinator assignment source is `agent.attrs.assigned_node_id`
- D20: schema subscription `node_id` is currently informational (ignored in v1 matcher)
- D21: default agent IDs are deterministic and node-derived (`default_agent_id`)
- D22: filesystem fallback seeds modules through `NodeDiscoveredEvent` + `NodeProjection`, not `graph_nodes` writes
- D23: workspace sidebar section renders only when at least one bootstrap panel has content
- D24: tool-synthesis events are emitted by activation-time before/after workspace tool diff

## Next step
- Commit/push current M6 changes.
- Run an optional full test sweep / integration bootstrap loop tests when desired.

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
