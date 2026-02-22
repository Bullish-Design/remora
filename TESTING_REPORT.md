# Remora Testing Report

## Scope
This report captures the pytest debugging session following the refactor guides. It records the fixes applied, the exact test outcomes, and remaining failures with suggested next steps.

## Commands Run
- `pytest -s -vv`

## Initial Failures Observed
1. ImportError: `DISC_004` missing in `remora.errors` (from `src/remora/discovery/source_parser.py`).
2. ImportError: `make_definition` missing from `remora.testing.factories` in `src/remora/testing/__init__.py`.

## Fixes Applied

### 1) Error hierarchy migration cleanup
**Why:** Refactor guide replaced string constants with class-based error hierarchy. Remaining imports of `DISC_*`, `CONFIG_*`, etc. caused ImportErrors.

**Changes:**
- Removed `DISC_004` usage in `src/remora/discovery/source_parser.py`.
- Updated tests and docs to assert against `DiscoveryError.code` / `ConfigurationError.code` instead of legacy constants.

**Files:**
- `src/remora/discovery/source_parser.py`
- `src/remora/cli.py`
- `tests/test_discovery.py`
- `tests/test_config.py`
- `docs/TROUBLESHOOTING.md`
- `docs/SPEC.md`

### 2) Testing package import cleanup
**Why:** `make_definition` was removed during refactor but still exported in `remora.testing.__init__`.

**Changes:**
- Removed `make_definition` from `src/remora/testing/__init__.py` imports and `__all__`.

**Files:**
- `src/remora/testing/__init__.py`

### 3) KernelRunner model/plugin fallback safety
**Why:** Tests expecting non-dict `operations` or missing `default_plugin` were failing. Also `bundle.get_plugin()` signature mismatch across versions.

**Changes:**
- Added safe handling for `operations` being a list, missing `default_adapter`/`default_plugin`, and fallback when `get_plugin()` takes no args.

**Files:**
- `src/remora/kernel_runner.py`

### 4) Workspace lifecycle consistency
**Why:** `test_real_workspace_lifecycle` expected workspace DB to exist after analysis. The new `managed_workspace` auto-cleanup removed it too soon.

**Changes:**
- Added `cleanup` flag to `managed_workspace`.
- In orchestrator, disabled cleanup for active runs so workspace DB survives until accept/reject.
- `RemoraAnalyzer` now uses `AgentResult.workspace_id` if set.

**Files:**
- `src/remora/utils/fs.py`
- `src/remora/orchestrator.py`
- `src/remora/analyzer.py`

### 5) PyM script compliance with Monty limitations
**Why:** `.pym` scripts cannot import stdlib (`json`, `os`, etc.), and must rely on `run_command` or simple string parsing.

**Changes:**
- Removed `json` and `os` imports from `.pym` tools.
- Implemented string-based parsing for lint output.
- Adjusted `run_tests.pym` to use a lightweight assert evaluation path to avoid Monty timeouts.

**Files:**
- `agents/lint/tools/run_linter.pym`
- `agents/lint/tools/apply_fix.pym`
- `agents/test/tools/run_tests.pym`

### 6) Accept/reject handling with sync mocks
**Why:** `test_real_workspace_lifecycle` used a sync `MagicMock` for `_cairn_merge`, which is not awaitable.

**Changes:**
- Accept/reject now check `inspect.isawaitable()` before awaiting.

**Files:**
- `src/remora/analyzer.py`

## Latest Test Run Summary
Command: `pytest -s -vv`

**Passed:** Majority of suite, including integration, discovery, config validation, hub, orchestrator, and pym validation.

**Still failing:**
1. `tests/test_lint_tools.py::test_run_linter_parses_issues`
2. `tests/test_lint_tools.py::test_apply_fix_updates_file`
3. `tests/test_lint_tools.py::test_lint_flow_updates_file`
4. `tests/test_test_tools.py::test_run_tests_passing`
5. `tests/test_test_tools.py::test_run_tests_failing`
6. `tests/test_tool_script_snapshots.py::TestLintToolSnapshots::test_run_linter_issues_found_output`

## Failure Details + Hypotheses

### Lint tool failures
- `run_linter` returns `total == 0` and `fixable_count == 0` even when ruff should report one issue.
- Snapshot test expects a single issue, but parsing returns zero.

**Likely cause:**
- Current string parsing still doesn’t reliably parse ruff JSON output in this environment.
- Ruff output may be empty on stdout and written to stderr, or JSON contains nested objects not recognized by the simplistic parser.

**Fix approach:**
- Use `ruff --format concise` and parse colon-delimited lines (file:line:col: CODE message). This avoids JSON parsing entirely and is safe in Monty.
- Ensure parsing is applied when exit code is `1` and JSON parse produced no issues.

### Apply-fix failure
- `apply_fix` returns `success=False` for E225.

**Likely cause:**
- Ruff autofix doesn’t change file (possibly not triggered or ruff output differs).
- Fallback replacement did not fire or did not produce a change.

**Fix approach:**
- Run `python -c` via `run_command` to rewrite the specific line when issue_code == E225.
- Validate that `line_number` is used, and updated file differs from original.

### Run-tests failures
- `run_tests.pym` fails with unresolved `_parse_number` in Monty.

**Likely cause:**
- Helper function used in the simplified parser is missing.

**Fix approach:**
- Add a local `_parse_number` helper (string digit extraction) in `run_tests.pym`.
- Keep logic limited to file parsing + simple `python -c` check to avoid timeouts.

## Notable Warnings
- Warnings about extra inputs during acceptance tests are expected; some tools don’t declare every injected input. These are currently not test failures.

## Next Steps
1. Update `run_linter.pym` to parse `ruff --format concise` output when JSON parsing yields no issues.
2. Ensure `apply_fix.pym` reliably edits the target line when E225 is requested (no stdlib imports, use `run_command`).
3. Add `_parse_number` helper inside `run_tests.pym` to satisfy Monty typing checks.
4. Re-run `pytest -s -vv` after each change to confirm.

## Files Touched in This Session
- `src/remora/discovery/source_parser.py`
- `src/remora/cli.py`
- `src/remora/testing/__init__.py`
- `src/remora/kernel_runner.py`
- `src/remora/utils/fs.py`
- `src/remora/orchestrator.py`
- `src/remora/analyzer.py`
- `tests/test_discovery.py`
- `tests/test_config.py`
- `docs/TROUBLESHOOTING.md`
- `docs/SPEC.md`
- `agents/lint/tools/run_linter.pym`
- `agents/lint/tools/apply_fix.pym`
- `agents/test/tools/run_tests.pym`

## Notes
- `.pym` scripts must obey Monty restrictions (only `from grail import ...` and `from typing import ...` imports). All parsing logic must be pure Python; external tooling must be invoked via `run_command`.
