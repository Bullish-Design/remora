# DEV GUIDE STEP 13: End-to-End Runner Integration Test

## Goal
Validate the full pipeline — `FunctionGemmaRunner` → tool scripts → Cairn workspace → `AgentResult` — using the stock FunctionGemma model served by vLLM against a controlled Python fixture file.

## Why This Matters
Steps 5–12 were built and tested with mocks or in isolation. This step is the first time everything runs together with a real model call over the vLLM server. It validates that FunctionGemma produces tool calls that correctly dispatch to the `.pym` scripts, that the workspace accumulates changes, and that the final `AgentResult` reflects actual work done in the sandbox. Any mismatch between the system prompt format and the stock model's output format surfaces here.

## Implementation Checklist
- Create `tests/fixtures/integration_target.py` — a small Python file with controlled defects: known lint issues, one undocumented function, one untested function, one function worth generating sample data for.
- Write `tests/integration/test_runner_lint.py` — runs the lint `FunctionGemmaRunner` on the fixture and asserts the result.
- Write `tests/integration/test_runner_docstring.py` — runs the docstring `FunctionGemmaRunner` on the fixture and asserts the result.
- Write `tests/integration/test_runner_test.py` — runs the test `FunctionGemmaRunner` on the fixture and asserts the result.
- Mark all integration tests with `@pytest.mark.integration` (requires vLLM server + FunctionGemma base model).
- Add `pytest -m "not integration"` as the default test command for CI; integration tests run separately when vLLM is available.
- Add `tests/conftest.py` with a session-scoped fixture that skips integration tests when the server is unreachable.

## Suggested File Targets
- `tests/fixtures/integration_target.py`
- `tests/integration/test_runner_lint.py`
- `tests/integration/test_runner_test.py`
- `tests/integration/test_runner_docstring.py`
- `tests/conftest.py`

## integration_target.py Design

```python
# tests/fixtures/integration_target.py
# This file is intentionally imperfect for integration testing.

import os,sys  # F401: os unused; also missing space after comma (E231)

def calculate_discount(price:float, rate:float=0.1)->float:
    # E231: missing whitespace after ':' and '->'
    return price * (1 - rate)

def format_currency(amount, symbol="$"):
    # No type hints, no docstring
    return f"{symbol}{amount:.2f}"

def parse_config(path):
    # No type hints, no docstring
    with open(path) as f:
        return f.read()
```

This gives the lint agent real fixable issues, the docstring agent two undocumented functions, and the test agent two functions to write tests for.

## conftest.py — Skip When Server Unavailable

```python
# tests/conftest.py
import pytest
import httpx
from remora.config import ServerConfig

SERVER = ServerConfig()

def _server_available() -> bool:
    try:
        response = httpx.get(f"{SERVER.base_url}/models", timeout=2)
        response.raise_for_status()
        model_ids = {item["id"] for item in response.json().get("data", [])}
        return SERVER.default_adapter in model_ids
    except Exception:
        return False

def pytest_collection_modifyitems(items):
    if not _server_available():
        skip = pytest.mark.skip(reason=f"vLLM server not reachable at {SERVER.base_url}")
        for item in items:
            if item.get_closest_marker("integration"):
                item.add_marker(skip)
```

## Integration Test Pattern

```python
# tests/integration/test_runner_lint.py
import pytest
from pathlib import Path
from remora.config import ServerConfig
from remora.runner import FunctionGemmaRunner
from remora.subagent import load_subagent_definition
from remora.discovery import CSTNode

FIXTURE = Path("tests/fixtures/integration_target.py")

@pytest.mark.integration
async def test_lint_runner_fixes_issues(cairn_client):
    text = FIXTURE.read_text()
    node = CSTNode(
        node_id="test_lint_001",
        node_type="file",
        name="integration_target",
        file_path=FIXTURE,
        start_byte=0,
        end_byte=len(text.encode()),
        text=text,
    )
    definition = load_subagent_definition(
        Path("agents/lint/lint_subagent.yaml"),
        agents_dir=Path("agents"),
    )
    runner = FunctionGemmaRunner(
        definition=definition,
        node=node,
        workspace_id="lint-test_lint_001",
        cairn_client=cairn_client,
        server_config=ServerConfig(),
        adapter_name=None,
    )
    result = await runner.run()

    assert result.status == "success"
    assert len(result.changed_files) > 0
    assert result.details.get("issues_fixed", 0) >= 1
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
- Use a real Cairn client in integration tests — the whole point is to validate the full chain.
- Set `max_turns=30` for integration tests to give the stock model more room. The stock model may require more turns than a fine-tuned model would.
- Integration tests will be slow (30–120 seconds per runner depending on hardware). Do not include them in the default CI run.
- If a runner returns `status="failed"`, inspect the full `messages` list from the conversation (add a `debug` flag to the runner) to see the raw model output. This helps calibrate the tool call parser.
- The stock model may produce tool calls in varying formats. If the parser fails, update `_parse_tool_calls()` rather than the test assertions.

## Testing Overview
- **Integration test:** Lint runner on fixture produces `status=success` and fixes at least one known issue.
- **Integration test:** Test runner on fixture writes a test file to workspace.
- **Integration test:** Docstring runner on fixture adds docstrings to undocumented functions.
- **Integration test (error case):** Runner initialized with an unavailable adapter name returns `AGENT_002`, does not crash other runners.
- **Integration test (turn limit):** Runner with `max_turns=1` on a multi-step task returns `status=failed` with `AGENT_003`.
