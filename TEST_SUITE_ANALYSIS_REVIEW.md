# Test Suite Analysis & Refactoring Review

This document analyzes the current condition of the Remora test suite, evaluating failing test cases against the reactive architecture outlined in `REMORA_SIMPLIFICATION_IDEAS.md`, and provides recommendations to repair and align the test suite.

## 1. High-Level Overview

**Test Metrics:**
- **Total Tests:** 100
- **Passed:** 86
- **Failed:** 14

The majority of failures originate from recent structural changes to the library's core models (`AgentMetadata`, `Config`), the removal or shifting of legacy batch-mode concepts (`remora run`, `bundles`), and the introduction of asynchronous, event-driven reactive components (`AgentRunner`).

---

## 2. Failure Categorization & Analysis

### A. Core Model Changes & Schema Upgrades (Unit Tests)
**Affected Tests:**
- `test_upsert_agent`
- `test_list_agents`
- `test_mark_orphaned`
- `test_update_agent`

**Underlying Issue:**
`AgentMetadata` was updated to include two new fields: `name` and `full_name`. The SQLite underlying persistence layer requires `full_name` to be `NOT NULL`. The existing unit tests are instantiating `AgentMetadata` with missing positional arguments.
**Recommendation:**
Update all test setup fixtures and test calls in `tests/unit/test_swarm_state.py` to instantiate `AgentMetadata` with valid dummy strings for `name` and `full_name`.

### B. CLI and Core Config Evolution (Integration Tests)
**Affected Tests:**
- `test_cli_run_real`
- `test_cli_run_invalid_config_fails`
- `test_cli_run_missing_bundle_mapping_fails`
- `test_service_cli_run_serves_http`

**Underlying Issue:**
The library CLI completely removed the `run` command as the codebase transitioned away from imperative graph batch execution towards long-running reactive swarm state. Additionally, `bundles` was stripped from the baseline `Config` parameters as execution now resolves natively against CST node agents.
**Recommendation:**
1. Drop the legacy `remora run` CLI tests if the command is deprecated, or replace them with tests for the new reactive engine kickoff commands (e.g., `remora serve` or swarm initializing commands).
2. Remove any `"bundles"` entries from configurations generated within tests, replacing them with valid configuration setups appropriate for the new configuration dataclass.

### C. Asynchronous Reactivity and Run Loops (Integration Tests)
**Affected Tests:**
- `test_cooldown_prevents_duplicate_triggers`
- `test_concurrent_trigger_handling`

**Underlying Issue:**
In the new `AgentRunner`, trigger handling uses an event loop queue (`_trigger_queue`). In these tests, `mock_executor` is verified for a call count, but the result is `0`. This is because merely appending to the `event_store` does not automatically synchronously iterate the mocked agent, or the runner process (`runner.run_loop()`) was never spawned in a background task within the test execution scope.
**Recommendation:**
Wrap the `runner` in an `asyncio.create_task(runner.run_loop())` within the setup phase of the test to allow it to actively drain the trigger queue, and then reliably `await asyncio.sleep(...)` or yield control to the loop so that the mocked executor runs.

### D. Glob Matching Nuances
**Affected Tests:**
- `test_subscription_pattern_path_glob`

**Underlying Issue:**
The assertion `assert pattern.matches(event2) is False` fails (evaluates to true) for a pattern `src/*.py` matching a path `src/utils/helper.py`. This indicates that the path matching implementation (likely using `pathlib.Path.match` or `fnmatch`) does not treat the `/` directory separator strictly for the `*` wildcard.
**Recommendation:**
Refine the matching logic within `SubscriptionPattern.matches()` to respect directory boundaries. Consider using `wcmatch.glob` using the `GLOBSTAR` flag if you want strict directory separators, or swap your usage of `pathlib.Path.match` which checks against suffix matching.

### E. VLLM Integrations and Third-Party Dependencies
**Affected Tests:**
- `test_real_vllm_tool_calling`
- `test_real_vllm_grail_tool_execution`

**Underlying Issue:**
The tests rely on `structured_agents`, which exhibits an incompatible API:
1. `AgentKernel`'s init fails mapping tools because tool instances are expected to expose `.schema.name` differently, or the model exposes a raw dict rather than an object.
2. `GrailTool` lacks a `from_script` factory method.
**Recommendation:**
Ensure `structured_agents` is updated to a compatible version within the environment, or rewrite the tool wrappers inside the integration test file to accurately reflect the interface expected by the currently pinned version of `structured_agents`.

### F. Cairn Workspace Lifecycle
**Affected Tests:**
- `test_agent_workspace_creates_database`

**Underlying Issue:**
The test verifies the literal `.db` existence locally when executing `get_agent_workspace()`. With recent storage consolidations, either workspaces have become deferred/lazy-initialized upon their first transaction or the persistence file naming (`agent_id.db` vs `workspace.db` inside an `agent_id` folder) was altered.
**Recommendation:**
Identify whether lazy initialization is the new standard. If so, execute a dummy read/write operation via `workspace_service` before analyzing the file system, or update the test path targeting to the correct `workspace.db` location.

---

## 3. Step-by-Step Refactoring Mission

To cleanly resolve the test suite and enforce the new reactive model, perform the following ordered steps:

1. **Unit Tests (Quick Wins):** Fix `AgentMetadata` instantiations in `tests/unit/test_swarm_state.py` by adding `name` and `full_name` strings.
2. **Glob Fixing:** Fix `SubscriptionPattern` matching in `src/remora/core/subscriptions.py` to ensure `*` does not cross directory boundaries.
3. **Runner Lifecycle & Events:** Refactor `tests/integration/test_agent_runner.py` to correctly orchestrate background asyncio loops using `asyncio.create_task(runner.run_loop())` so triggers adequately traverse the queue.
4. **CLI & Config Realignment:** Port CLI tests in `tests/integration/test_cli_real.py` off the defunct `run` command to the new `serve` or equivalents, and purge `bundles` from explicitly mocked YAML payloads.
5. **Cairn Adjustments:** Ensure the state/database checks precisely match the new `.db`/`.jsonl` locations in `tests/integration/cairn/test_lifecycle.py`.
6. **VLLM Adapters:** Fix the dict dictionary attribute fetches in external plugins or local testing adapters (`tests/integration/test_vllm_real.py`).
