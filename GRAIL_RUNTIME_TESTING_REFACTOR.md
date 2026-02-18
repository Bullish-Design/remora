# Grail Runtime Testing Refactor

## Purpose

Fully validate Remora agent tools and contexts through Grail’s runtime pipeline instead of importing `.pym` files as Python modules. The new test architecture must execute **every tool script** with Grail, validate Grail artifacts, and ensure parity with Cairn’s execution model.

## Non‑Negotiables

- Every `.pym` tool/context executes via `grail.load(...).run_sync(...)` in tests.
- `grail check` (strict) is enforced for every `.pym` file.
- Test harness validates `.grail/<script_name>/` artifacts for every run.
- No test should import `.pym` via `SourceFileLoader`.
- All external functions are injected through Grail externals (not direct Python imports).

## Current Issues

- Tests import `.pym` files directly, which bypasses Grail validation entirely.
- Top‑level `await` in `.pym` files fails CPython imports and hides Grail compliance issues.
- Submit tools rely on module‑level `result` but tests expect a callable entrypoint.

## Target Architecture

### New Grail Runtime Test Harness

Create a shared harness that:

- Loads scripts via `grail.load(path, grail_dir=...)`.
- Runs via `script.run_sync(inputs=..., externals=..., files=...)`.
- Captures output + artifact paths for assertions.
- Emits Grail validation failures with readable diagnostics.

### Test Layers

- **Validation tests**: call `script.check()` on every `.pym` file.
- **Runtime tests**: execute each tool with stub externals + inputs.
- **Integration tests**: execute with Cairn workspace contexts and real filesystem state.

## Detailed Implementation Plan

### 1) Add test harness module

**New file**: `tests/utils/grail_runtime.py`

Responsibilities:

- `load_script(path: Path, grail_dir: Path | None = None) -> GrailScript`
- `run_script(path: Path, inputs: dict, externals: dict, files: dict | None = None) -> dict`
- `assert_artifacts(grail_dir: Path)` to validate `check.json`, `stubs.pyi`, `monty_code.py`.
- Accept a `workspace_root` so tests can inject `.remora/` files, inputs, and fixtures.

### 2) Replace direct `.pym` imports

Remove `SourceFileLoader` usage in:

- `tests/test_lint_tools.py`
- `tests/test_docstring_tools.py`
- `tests/test_test_tools.py`
- `tests/test_sample_data_tools.py`

Each test should call the Grail harness and provide:

- `inputs` (Input declarations)
- `externals` (tool API stubs)
- optional `files` (Monty FS override)

### 3) Add strict Grail validation tests

**New file**: `tests/test_pym_validation.py`

- Iterate `agents/**/*.pym`.
- For each file, call `script.check()` and assert `valid == True`.
- Ensure failures display diagnostic lines in assertions.

### 4) Update test markers

Add pytest markers in `pyproject.toml`:

- `grail_runtime`: tests that run Grail runtime execution.
- `integration`: existing Cairn/vLLM integration tests.

### 5) CI expectations

- `pytest -m "not integration"` must include Grail runtime tests.
- `pytest -m "grail_runtime"` is required in CI.

## External Function Injection Strategy

Standardize the interface between Grail externals and tests:

- Each test defines Python callables matching the `@external` signatures.
- For IO helpers, provide minimal stub behavior (read/write file, run command, list directory).
- Ensure async externals are supported (wrap sync functions with `async def` as needed).

## Artifact Assertions

Every runtime test must assert:

- `.grail/<script_name>/check.json` exists and `valid: true`.
- `.grail/<script_name>/stubs.pyi` exists and lists externals/inputs.
- `.grail/<script_name>/monty_code.py` exists.
- `run.log` exists when runtime execution completes.

## Required Validation

- All `.pym` files must pass `grail check --strict`.
- Every tool script runs at least one test case through Grail runtime.
- No remaining references to `SourceFileLoader` for `.pym` scripts.

## Migration Notes

- Update tests before touching `.pym` syntax, so failures are isolated.
- Expect new failures once Grail runtime is fully enforced.
- Iterate per tool family: `lint`, `docstring`, `test`, `sample_data`.

## Success Criteria

- 100% of `.pym` tool scripts validated and executed via Grail.
- Grail artifacts generated and verified in tests.
- Tests align with Cairn execution model (externals injected; no direct Python imports).
