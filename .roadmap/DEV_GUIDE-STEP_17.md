# DEV GUIDE STEP 17: MVP Acceptance Tests

## Goal
Write and execute the full acceptance test suite that validates the MVP success criteria end-to-end using the stock FunctionGemma model via Ollama against a sample Python project.

## Why This Matters
This is the final gate before declaring the MVP complete. Unlike unit tests (which mock the model) and integration tests (which test individual runners), acceptance tests run the full system — CLI, discovery, coordinator, real model calls, Cairn workspaces, accept/reject — exactly as a real user would use it. All six scenarios must pass on a machine with Ollama running and the FunctionGemma model pulled.

## Implementation Checklist
- Create `tests/acceptance/sample_project/` — a small, self-contained Python project with deliberate defects.
- Write acceptance tests for all six scenarios (see below).
- Mark acceptance tests with `@pytest.mark.acceptance`.
- Add `tests/acceptance/conftest.py` with fixtures that skip all acceptance tests if Ollama is not reachable or the model is not available.
- Acceptance tests must be idempotent: each test creates fresh Cairn workspaces and cleans up after itself.
- Document how to run the acceptance suite: `pytest -m acceptance tests/acceptance/`.

## Suggested File Targets
- `tests/acceptance/sample_project/` (Python project fixture)
- `tests/acceptance/conftest.py`
- `tests/acceptance/test_scenario_1_lint.py`
- `tests/acceptance/test_scenario_2_docstring.py`
- `tests/acceptance/test_scenario_3_test_generation.py`
- `tests/acceptance/test_scenario_4_concurrency.py`
- `tests/acceptance/test_scenario_5_error_isolation.py`
- `tests/acceptance/test_scenario_6_watch_mode.py`

## Sample Project Structure

```
tests/acceptance/sample_project/
├── remora.yaml                   # Project-specific config pointing at the Ollama model
├── src/
│   ├── calculator.py             # Functions with lint issues, no docstrings, no tests
│   ├── formatter.py              # Functions with missing type hints and docstrings
│   └── validators.py             # Functions that need fixtures
└── tests/
    └── (empty at start of acceptance run)
```

## Acceptance Test Conftest

```python
# tests/acceptance/conftest.py
import pytest
import llm
import httpx

MODEL_ID = "ollama/functiongemma-4b-it"

def _model_available() -> bool:
    try:
        llm.get_model(MODEL_ID)
        httpx.get("http://localhost:11434/api/tags", timeout=2)
        return True
    except Exception:
        return False

def pytest_collection_modifyitems(items):
    if not _model_available():
        skip = pytest.mark.skip(
            reason=f"Ollama model {MODEL_ID!r} not available — run `ollama pull functiongemma-4b-it`"
        )
        for item in items:
            if "acceptance" in item.keywords:
                item.add_marker(skip)
```

## Acceptance Scenarios

### Scenario 1: Lint and Accept
1. Run `remora analyze src/ --operations lint`
2. Verify results show at least 1 successful lint operation with `issues_fixed > 0`
3. Call `analyzer.accept()` for the lint operation on one node
4. Verify the stable workspace now contains the linted file
5. Verify the file in stable has fewer lint issues than the original

### Scenario 2: Docstring Generation and Accept
1. Run `remora analyze src/ --operations docstring`
2. Verify results show at least 1 successful docstring operation with `action=added`
3. Accept one docstring result
4. Verify the file in stable workspace contains a new docstring for the target function

### Scenario 3: Test Generation and Accept
1. Run `remora analyze src/calculator.py --operations test`
2. Verify a test file was generated in the workspace
3. Accept the test result
4. Verify `tests/test_calculator.py` exists in stable workspace and is valid Python

### Scenario 4: Concurrent Processing
1. Run `remora analyze src/ --operations lint,docstring` (processes all nodes in `src/`)
2. The project has at least 5 function nodes
3. Verify results contain entries for all 5+ nodes
4. Verify `max_concurrent_runners` was respected (check runner logs or timing)
5. All successful results have non-empty `changed_files`

### Scenario 5: Error Isolation
1. Configure one operation to use a non-existent model ID (e.g., `"ollama/nonexistent-model"`)
2. Run `remora analyze src/ --operations lint,docstring`
3. Verify the broken operation shows `status=failed` with `AGENT_002`
4. Verify the working operation completes successfully (failure does not block siblings)
5. Restore the config

### Scenario 6: Watch Mode
1. Start `remora watch src/ --operations lint` in a subprocess
2. Verify the watcher starts without error (check stdout for "Watching" message)
3. Modify `src/calculator.py` (add a trailing space to create a W291 issue)
4. Wait for the debounce period + analysis time
5. Verify the watch process detected the change and ran analysis (check output)
6. Terminate the watcher

## Implementation Notes
- Each acceptance test should use a fresh copy of `tests/acceptance/sample_project/` (copy to a temp directory) to avoid test pollution.
- Scenario 5 (error isolation) modifies config rather than filesystem state — use a config override rather than renaming files.
- Scenario 6 (watch mode) is the most fragile: use a subprocess and poll for output rather than importing the CLI directly. Give generous timeouts.
- Acceptance test failures are bugs. Do not work around them by adjusting expectations — fix the underlying issue.
- The stock model may occasionally produce unexpected output. If scenario failures are intermittent, add a debug flag to capture raw model responses.

## MVP Exit Criteria

The MVP is complete when:
- All 6 acceptance scenarios pass on a machine with Ollama running and FunctionGemma pulled
- Unit tests for steps 1–16 all pass (no model required)
- Integration tests for steps 13–16 pass (Ollama required)
- `remora analyze tests/acceptance/sample_project/src/ --operations lint,docstring,test` exits with code 0
- `remora list-agents` shows all configured agents with their YAML status and model availability
