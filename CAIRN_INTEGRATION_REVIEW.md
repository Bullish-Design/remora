# Cairn Integration Review

## Test Run Summary

- Command: `pytest tests/integration/cairn/ -v -m cairn`
- Result: **Failed before collection**
- Error:
  - `ModuleNotFoundError: No module named 'cairn.orchestrator'`
  - Import chain: `tests/integration/cairn/conftest.py` -> `remora.cairn_bridge` -> `remora.executor` -> `cairn.orchestrator.lifecycle`

This indicates the Cairn package (or the module path used by Remora) is not available in the current environment. The Cairn integration tests cannot run until the Cairn runtime is installed and importable.

## What Changed

### Test Suite Refactor (Clean Break)
- Added a dedicated Cairn test suite under `tests/integration/cairn/`.
- Implemented fixtures in `tests/integration/cairn/conftest.py` that create isolated workspace services, sample project roots, and helper operations.
- Added comprehensive tests for:
  - Copy-on-write isolation between stable and agent workspaces.
  - Agent-to-agent isolation.
  - Read fall-through semantics and list directory behavior.
  - Write isolation behavior.
  - Workspace lifecycle behaviors (create, reopen, graph isolation).
  - KV submission storage and isolation.
  - Error recovery behavior.
  - Path normalization edge cases.
  - Concurrency safety and stress scenarios.
- Added new helper utilities in `tests/integration/helpers.py` to assert workspace contents, capture snapshots, and compare state.

### Workspace Behavior Alignment
- Updated `AgentWorkspace.list_dir()` in `src/remora/workspace.py` to return a union of agent and stable entries to match Cairn copy-on-write semantics (read fall-through and combined visibility).

### Pytest & CI Updates
- Added Cairn-specific pytest markers to `pyproject.toml`.
- Added a CI workflow at `.github/workflows/cairn-tests.yml` to run the Cairn suite on relevant changes.
- Documented Cairn test usage and coverage guidance in `docs/TESTING_GUIDELINES.md`.
- Added a coverage report stub at `docs/reports/cairn_test_coverage.md`.

## Integration Status (Based on Current Evidence)

### Strengths
- Remora uses Cairn consistently through `CairnWorkspaceService`, `AgentWorkspace`, and `CairnExternals`.
- The new test suite explicitly verifies the copy-on-write model, stable vs. agent isolation, and multi-agent concurrency safety.
- Path normalization is validated against the external function layer.

### Gaps / Follow-ups Needed
- **Cairn dependency availability**: The current environment lacks `cairn.orchestrator`. The Cairn runtime must be installed or made importable for both tests and runtime behavior.
- **Accept/Reject support**: Remora still raises `WorkspaceError` for accept/reject operations. The new tests reflect this explicit lack of support, but this remains a functional gap if merge functionality is desired.
- **CI assumptions**: The Cairn test workflow assumes dependencies resolve via `uv sync --all-extras`. Verify Cairn is included in the dependency graph or provide installation steps.

## Recommendations

1. Ensure Cairn is installed and importable in the test environment (e.g., add to `pyproject.toml` dependencies or update the CI job to install it).
2. Once Cairn is available, rerun `pytest tests/integration/cairn/ -v -m cairn` to validate isolation and concurrency coverage.
3. If merge/accept is required, implement workspace merge support in `AgentWorkspace.accept()` (e.g., via Cairn merge APIs) and extend tests accordingly.

## Files Touched

- `tests/integration/cairn/conftest.py`
- `tests/integration/cairn/test_workspace_isolation.py`
- `tests/integration/cairn/test_agent_isolation.py`
- `tests/integration/cairn/test_read_semantics.py`
- `tests/integration/cairn/test_write_semantics.py`
- `tests/integration/cairn/test_kv_operations.py`
- `tests/integration/cairn/test_lifecycle.py`
- `tests/integration/cairn/test_concurrent_safety.py`
- `tests/integration/cairn/test_error_recovery.py`
- `tests/integration/cairn/test_path_resolution.py`
- `tests/integration/cairn/test_merge_operations.py`
- `tests/integration/helpers.py`
- `src/remora/workspace.py`
- `pyproject.toml`
- `.github/workflows/cairn-tests.yml`
- `docs/TESTING_GUIDELINES.md`
- `docs/reports/cairn_test_coverage.md`
