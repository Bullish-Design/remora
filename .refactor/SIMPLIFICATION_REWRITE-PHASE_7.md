# Phase 7 - Polish and End-to-End

## Goal
Finish the migration by polishing CLI/API surfaces and validating the unified reactive swarm end-to-end.

## Guiding principles
- All external interfaces should reflect the new mental model: agents, subscriptions, events.
- Avoid adding back graph-only concepts that conflict with reactive execution.
- Provide a minimal, clear user workflow for running the swarm.

## Definition of done
- CLI exposes swarm-oriented commands.
- HTTP API includes swarm routes.
- Integration tests confirm reactive execution and Neovim notifications.

## Step-by-step implementation

### 1) Update CLI to expose swarm commands
Implementation:
- In `src/remora/cli/main.py`, add a `swarm` command group with subcommands:
  - `swarm start` (starts reconciler + runner + optional nvim server)
  - `swarm reconcile` (runs reconciliation only)
  - `swarm emit` (emit a manual event)
  - `swarm list` (list known agents)
- Use the new flat `Config` and load it once at startup.
- Ensure CLI help text uses swarm terminology (agents, subscriptions, triggers).

Testing:
- Add CLI tests in `tests/integration/test_cli_real.py` to cover `swarm start` and `swarm list`.

### 2) Update HTTP API routes
Implementation:
- In `src/remora/service/api.py` and `src/remora/service/handlers.py`, add routes:
  - `GET /swarm/agents` -> list agents from SwarmState
  - `GET /swarm/agents/{id}` -> get agent state
  - `POST /swarm/events` -> append event
  - `GET /swarm/subscriptions/{id}` -> list subscriptions
- Keep responses JSON-serializable and stable for UI/Neovim use.

Testing:
- Add unit tests in `tests/unit/test_service_handlers.py` for the new routes.

### 3) Update UI projector (if still used)
Implementation:
- If the UI still depends on `EventBus`, ensure it can display the new event types.
- Map new events to UI-friendly payloads (agent id, path, status).
- Keep the UI as a subscriber; do not add direct DB reads in UI.

Testing:
- Run `python -m pytest tests/unit/test_ui_projector.py` and update snapshots as needed.

### 4) Add end-to-end swarm test
Implementation:
- Create a new integration test (e.g., `tests/integration/test_swarm_reactive_real.py`):
  - Create a small fixture project.
  - Run reconciliation to spawn agents.
  - Emit a `ContentChangedEvent` or `AgentMessageEvent`.
  - Assert that the target agent runs and emits completion events.
- Use a temporary directory and avoid external network calls.

Testing:
- Run the new integration test in isolation to confirm reactive flow works.

### 5) Update documentation and examples
Implementation:
- Update `README.md` and `HOW_TO_USE_REMORA.md` with the new workflow:
  - How to start the swarm
  - How to emit events
  - How to attach Neovim
- Update `remora.yaml.example` to include the swarm and nvim fields from the flat config.

Testing:
- `rg -n "swarm" README.md HOW_TO_USE_REMORA.md` to verify references.

### 6) Final test sweep
Implementation:
- Run a focused set of unit and integration tests to validate the migration.
- Fix any failures before considering the phase complete.

Testing:
- Suggested set:
  - `python -m pytest tests/test_config.py tests/unit/test_event_store.py tests/unit/test_subscriptions.py`
  - `python -m pytest tests/integration/test_swarm_reactive_real.py tests/integration/test_cli_real.py`

## Testing additions (unit/smoke/examples)
Unit tests to add/update:
- `tests/unit/test_service_handlers.py::test_swarm_list_agents` (new).
- `tests/unit/test_service_handlers.py::test_swarm_emit_event` (new).
- `tests/unit/test_cli_swarm.py::test_swarm_list_command` (new).
- `tests/unit/test_cli_swarm.py::test_swarm_emit_command` (new).

Smoke tests to add/update:
- `tests/integration/test_cli_real.py::test_swarm_list_smoke` (new).
- `tests/integration/test_dashboard_api_real.py::test_swarm_agents_endpoint` (new).

Example tests to add:
- `tests/integration/test_swarm_reactive_real.py::test_content_changed_triggers_agent` (new).
- `tests/integration/test_cli_real.py::test_swarm_emit_smoke` (new).

## Notes
- Keep commands minimal and composable; avoid nested config objects in CLI flags.
- Make sure new endpoints and CLI commands describe the reactive mental model, not batch graphs.
