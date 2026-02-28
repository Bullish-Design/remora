# Phase 8 - Integration Test Suite (Reactive Swarm)

## Goal
Build a comprehensive integration test suite that exercises the reactive swarm end-to-end, with a mix of **REAL** tests (AgentFS + vLLM where available), lightweight smoke tests, and deterministically reproducible integration checks that do not rely on network access.

## Guiding principles
- Follow existing test conventions: `pytest.mark.integration`, helper functions in `tests/integration/helpers.py`, and skip logic for unavailable dependencies.
- Prefer real system wiring (EventStore + SubscriptionRegistry + AgentRunner + SwarmState) even when using stubbed models.
- Keep tests small, fast, and focused on a single behavior.

## Definition of done
- A full set of integration tests exists for reconciliation, subscriptions, runner, CLI, HTTP API, and Neovim server.
- Smoke tests verify the critical startup path and basic event flow.
- "REAL" tests run against vLLM and AgentFS when available and skip gracefully otherwise.

## Test suite structure

### 1) Core reactive flow
Files to add:
- `tests/integration/test_swarm_reconcile_real.py`
- `tests/integration/test_swarm_runner_real.py`

Tests to include:
- `test_reconcile_creates_agents_from_discovery`
  - Setup: temp project with 1-2 python files.
  - Run: discovery + reconciler.
  - Assert: `swarm_state.db` entries created and `state.jsonl` files exist.
- `test_reconcile_marks_orphaned_on_delete`
  - Setup: reconcile, delete a source file, reconcile again.
  - Assert: agent marked orphaned, subscriptions removed.
- `test_runner_processes_trigger_and_emits_events`
  - Setup: real EventStore + SubscriptionRegistry + SwarmState.
  - Emit: `AgentMessageEvent` to a known agent.
  - Assert: `AgentStartEvent` and `AgentCompleteEvent` recorded.

Smoke variants (fast):
- `test_swarm_boot_smoke` - reconciliation + single event trigger with no LLM calls.

### 2) Event routing and subscriptions
Files to add:
- `tests/integration/test_swarm_event_routing_real.py`

Tests to include:
- `test_direct_message_triggers_only_target_agent`
- `test_path_glob_subscription_triggers_on_file_change`
- `test_tags_filtering_limits_triggers`

These should use real sqlite files for EventStore and SubscriptionRegistry; no network required.

### 3) CLI integration
Files to add:
- `tests/integration/test_swarm_cli_real.py`

Tests to include:
- `test_swarm_list_smoke` - run `remora swarm list` and assert output includes known agents.
- `test_swarm_emit_smoke` - emit a manual event and assert it appears in EventStore.
- `test_swarm_reconcile_smoke` - run reconcile command and verify agents exist.

Note: use `subprocess` or CLI runner (matching existing CLI tests) and a temp project.

### 4) HTTP API integration
Files to add:
- `tests/integration/test_swarm_api_real.py`

Tests to include:
- `test_get_agents_returns_registry_entries`
- `test_post_event_appends_to_event_store`
- `test_get_agent_subscriptions`

Note: use the same Starlette test client patterns already present in `tests/unit/test_service_handlers.py`.

### 5) Neovim server integration
Files to add:
- `tests/integration/test_nvim_server_real.py`

Tests to include:
- `test_nvim_emit_event_roundtrip`
  - Connect over socket, send `swarm.emit`, assert event stored.
- `test_nvim_receives_event_notifications`
  - Subscribe to EventBus, emit event, assert client receives notification.
- `test_nvim_agent_chat_triggers_turn`
  - Send `agent.chat`, assert AgentRunner completes a turn.

### 6) REAL (vLLM + AgentFS) end-to-end tests
Files to add:
- `tests/integration/test_swarm_e2e_real.py`

Tests to include:
- `test_swarm_e2e_real_agent_turn`
  - Skip unless `agentfs_available()` and `vllm_available()`.
  - Setup: small project + bundle with minimal system prompt.
  - Run: reconcile + emit message to a function agent.
  - Assert: ModelResponseEvent exists and workspace content updated if a tool call occurs.

Optional additional REAL tests:
- `test_swarm_tool_call_real` - uses a tool bundle and verifies a file is written in the agent workspace.

### 7) Smoke test matrix
File to add:
- `tests/integration/test_swarm_smoke_real.py`

Smoke tests to include:
- `test_swarm_start_smoke` - starts reconciler + runner (no LLM), emits a dummy event, verifies completion events.
- `test_swarm_event_store_smoke` - append + replay with routing fields.
- `test_nvim_server_smoke` - server starts and accepts a client connection.

## Shared fixtures and helpers
- Reuse `tests/integration/helpers.py` for `agentfs_available()` and `vllm_available()`.
- Add a `swarm_project` fixture that builds a temp project with 1-2 files and returns paths.
- Add a `swarm_runtime` fixture that initializes EventStore, SubscriptionRegistry, SwarmState, and AgentRunner.

## Expected pytest markers
- All new tests should be tagged `pytest.mark.integration`.
- REAL tests should include skip checks at the top of the test using the existing helpers.

## Suggested execution commands
- Fast local smoke: `python -m pytest tests/integration/test_swarm_smoke_real.py`
- Full integration (no network): `python -m pytest tests/integration/test_swarm_*_real.py -k "not e2e"`
- Full REAL suite: `python -m pytest tests/integration/test_swarm_*_real.py`

## Notes
- Keep REAL tests optional and skip gracefully without failing the suite.
- Favor deterministic assertions: event types recorded, DB rows inserted, and files created in temp directories.
