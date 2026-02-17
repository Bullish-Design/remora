# DEV GUIDE STEP 14: End-to-End Runner Integration Test

## Goal
Validate the full pipeline — `FunctionGemmaRunner` → tool scripts → Cairn workspace → `AgentResult` — using real GGUF models against a controlled Python fixture file.

## Why This Matters
Steps 5–13 were built and tested with mocks or in isolation. This step is the first time everything runs together with real models. It validates that the GGUF model produces tool calls that correctly dispatch to the `.pym` scripts, that the workspace accumulates changes, and that the final `AgentResult` reflects actual work done in the sandbox. Any mismatch between training data assumptions and runtime behavior surfaces here.

## Implementation Checklist
- Create `tests/fixtures/integration_target.py` — a small Python file with controlled defects: known lint issues, one undocumented function, one untested function, one function worth generating sample data for.
- Write `tests/integration/test_runner_lint.py` — runs the lint `FunctionGemmaRunner` on the fixture and asserts the result.
- Write `tests/integration/test_runner_test.py` — runs the test `FunctionGemmaRunner` on the fixture and asserts the result.
- Write `tests/integration/test_runner_docstring.py` — runs the docstring `FunctionGemmaRunner` on the fixture and asserts the result.
- Mark all integration tests with `@pytest.mark.integration` (requires real GGUF files).
- Add `pytest -m "not integration"` as the default test command for CI; integration tests run separately.

## Suggested File Targets
- `tests/fixtures/integration_target.py`
- `tests/integration/test_runner_lint.py`
- `tests/integration/test_runner_test.py`
- `tests/integration/test_runner_docstring.py`
- `tests/conftest.py` (skip integration tests if GGUF files are absent)

## integration_target.py Design

```python
# tests/fixtures/integration_target.py
# This file is intentionally imperfect for integration testing.

import os,sys  # F401: os unused; also missing space after comma (E231)

def calculate_discount(price:float, rate:float=0.1)->float:
    # E231: missing whitespace after ':' and '->'
    return price * (1 - rate)

def format_currency(amount,symbol="$"):
    # No type hints, no docstring
    return f"{symbol}{amount:.2f}"

def parse_config(path):
    # No type hints, no docstring
    with open(path) as f:
        return f.read()
```

This gives the lint agent real fixable issues, the docstring agent two undocumented functions, and the test agent two functions to write tests for.

## Integration Test Pattern

```python
# tests/integration/test_runner_lint.py
import pytest
from pathlib import Path
from remora.runner import FunctionGemmaRunner
from remora.subagent import load_subagent_definition
from remora.discovery import CSTNode

GGUF_PATH = Path("agents/lint/models/lint_functiongemma_q8.gguf")

@pytest.mark.integration
@pytest.mark.skipif(not GGUF_PATH.exists(), reason="GGUF not found")
async def test_lint_runner_fixes_issues():
    node = CSTNode(
        node_id="test_lint_001",
        node_type="file",
        name="integration_target",
        file_path=Path("tests/fixtures/integration_target.py"),
        start_byte=0,
        end_byte=...,  # fill from file
        text=GGUF_PATH.read_text(),  # fill from file
    )
    definition = load_subagent_definition(
        Path("agents/lint/lint_subagent.yaml"),
        agents_dir=Path("agents"),
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="lint-test_lint_001",
        cairn_client=...,  # real Cairn client
    )
    result = await runner.run()

    assert result.status == "success"
    assert len(result.changed_files) > 0
    assert result.issues_fixed > 0  # in details
```

## Assertions per Runner

**Lint runner:**
- `result.status == "success"`
- `result.changed_files` is non-empty
- `result.details["issues_fixed"] >= 1`
- Workspace diff shows actual file changes

**Test runner:**
- `result.status == "success"`
- `result.changed_files` contains a test file path
- Workspace contains a valid Python test file
- Test file imports the target module

**Docstring runner:**
- `result.status == "success"`
- `result.changed_files` contains the source file
- Workspace diff shows inserted docstrings for both undocumented functions
- Docstrings follow the configured style

## Implementation Notes
- Use a real Cairn client in integration tests, not a mock. The whole point of this step is to validate the full chain.
- Set `max_turns=30` for integration tests — give the model more room to reason in a real (slower) inference environment.
- Integration tests are expected to be slow (~30–120 seconds per runner on CPU). Do not include them in the default CI run.
- If a runner returns `status="failed"` due to a model issue, inspect the full `messages` list from the runner (add a `debug` flag) to understand what the model produced.

## Testing Overview
- **Integration test:** Lint runner on fixture produces `status=success` and fixes at least one known issue.
- **Integration test:** Test runner on fixture writes a test file to workspace.
- **Integration test:** Docstring runner on fixture adds docstrings to undocumented functions.
- **Integration test (error case):** Runner initialized with invalid GGUF path returns failed result, does not crash.
- **Integration test (turn limit):** Runner with `max_turns=1` on a multi-step task returns `status=failed` with `AGENT_003`.
