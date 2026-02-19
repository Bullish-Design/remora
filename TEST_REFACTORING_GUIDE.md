# Test Suite Refactoring Guide

**Target Audience:** Junior developers new to the Remora project
**Estimated Effort:** Medium-term project (multiple phases)
**Prerequisites:** Familiarity with pytest, basic understanding of async Python, access to project documentation

---

## Overview

This guide provides step-by-step instructions for refactoring and improving the Remora test suite based on findings from the code review (see `CODE_REVIEW.md`, Part 5). The goal is to create a more robust, maintainable, and CI-friendly test infrastructure.

### Problems We're Solving

| Issue | Impact |
|-------|--------|
| Tests rely on implementation details | Brittle tests that break when refactoring |
| Missing error path coverage | Bugs slip through in edge cases |
| No property-based testing | Only happy-path scenarios tested |
| Acceptance tests require vLLM server | Tests skip in CI, reducing confidence |
| Test helpers scattered in `tests/` | Can't import helpers in production code |

---

## Phase 1: Restructure Test Helpers

**Goal:** Move reusable test utilities to `remora.testing` so they can be imported anywhere and potentially used by downstream projects.

### Step 1.1: Create the Testing Module

Create a new package at `remora/testing/`:

```bash
mkdir -p remora/testing
touch remora/testing/__init__.py
```

### Step 1.2: Migrate Fake Implementations

Move the fake implementations from `tests/helpers.py` to properly organized modules:

1. **Create `remora/testing/fakes.py`** with the following classes from `tests/helpers.py`:
   - `FakeToolCallFunction`
   - `FakeToolCall`
   - `FakeCompletionMessage`
   - `FakeCompletionChoice`
   - `FakeCompletionResponse`
   - `FakeChatCompletions`
   - `FakeAsyncOpenAI`
   - `FakeGrailExecutor`

2. **Create `remora/testing/factories.py`** for test data builders:
   - `make_ctx()` - Creates `RemoraAgentContext` instances
   - `make_definition()` - Creates `SubagentDefinition` instances
   - `make_node()` - Creates `CSTNode` instances
   - `make_server_config()` - Creates `ServerConfig` instances
   - `make_runner_config()` - Creates `RunnerConfig` instances
   - `tool_schema()` - Creates tool schema dicts
   - `tool_call_message()` - Creates fake tool call messages

3. **Create `remora/testing/patches.py`** for monkeypatch helpers:
   - `patch_openai()` - Patches the AsyncOpenAI client

### Step 1.3: Update the Module's `__init__.py`

```python
# remora/testing/__init__.py
"""Test utilities for Remora.

This module provides fakes, factories, and patches for testing Remora
components. It can be used both internally and by downstream projects.
"""

from remora.testing.fakes import (
    FakeAsyncOpenAI,
    FakeChatCompletions,
    FakeCompletionChoice,
    FakeCompletionMessage,
    FakeCompletionResponse,
    FakeGrailExecutor,
    FakeToolCall,
    FakeToolCallFunction,
)
from remora.testing.factories import (
    make_ctx,
    make_definition,
    make_node,
    make_runner_config,
    make_server_config,
    tool_call_message,
    tool_schema,
)
from remora.testing.patches import patch_openai

__all__ = [
    # Fakes
    "FakeAsyncOpenAI",
    "FakeChatCompletions",
    "FakeCompletionChoice",
    "FakeCompletionMessage",
    "FakeCompletionResponse",
    "FakeGrailExecutor",
    "FakeToolCall",
    "FakeToolCallFunction",
    # Factories
    "make_ctx",
    "make_definition",
    "make_node",
    "make_runner_config",
    "make_server_config",
    "tool_call_message",
    "tool_schema",
    # Patches
    "patch_openai",
]
```

### Step 1.4: Update Test Imports

Update all test files to use the new import path. For example, in `tests/test_runner.py`:

```python
# Before
from tests.helpers import (
    FakeGrailExecutor,
    make_ctx,
    make_definition,
    ...
)

# After
from remora.testing import (
    FakeGrailExecutor,
    make_ctx,
    make_definition,
    ...
)
```

### Step 1.5: Deprecate Old Helpers

Keep `tests/helpers.py` temporarily with deprecation warnings:

```python
# tests/helpers.py
"""DEPRECATED: Use remora.testing instead."""
import warnings

warnings.warn(
    "tests.helpers is deprecated. Use remora.testing instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backwards compatibility
from remora.testing import *
```

### Verification Checklist

- [ ] `remora/testing/` package created with `__init__.py`
- [ ] All fake classes moved to `remora/testing/fakes.py`
- [ ] All factory functions moved to `remora/testing/factories.py`
- [ ] Patch helpers moved to `remora/testing/patches.py`
- [ ] All test files updated to import from `remora.testing`
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Old `tests/helpers.py` shows deprecation warning when imported

---

## Phase 2: Add Missing Error Path Tests

**Goal:** Improve test coverage for error handling in `remora/execution.py`.

### Step 2.1: Identify Missing Error Scenarios

Review `remora/execution.py` and identify error paths not covered by `tests/test_execution.py`. Create tests for:

| Error Scenario | Current Coverage | Priority |
|----------------|------------------|----------|
| Script file not found | Missing | High |
| Invalid script syntax (load fails) | Missing | High |
| Empty script result | Missing | Medium |
| Concurrent execution race conditions | Missing | Medium |
| Pool exhaustion under load | Missing | Low |
| Cleanup failures during shutdown | Missing | Low |

### Step 2.2: Add Script Not Found Test

Add to `tests/test_execution.py`:

```python
@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_script_not_found(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Missing script file returns FILE_NOT_FOUND error."""
    mock_exists.return_value = False

    result = _run_in_child("/missing.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "FILE_NOT_FOUND"
    assert "/missing.pym" in result["message"]
```

### Step 2.3: Add Load Failure Test

```python
@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_load_failure(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Script that fails to load returns LOAD_ERROR."""
    mock_exists.return_value = True
    mock_grail.load.side_effect = SyntaxError("invalid syntax at line 5")

    result = _run_in_child("/bad_syntax.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "LOAD_ERROR"
    assert "syntax" in result["message"].lower()
```

### Step 2.4: Add Empty Result Test

```python
@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_empty_result(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Script returning None should return empty result dict."""
    mock_exists.return_value = True
    script = _make_script(run_result=None)
    mock_grail.load.return_value = script

    result = _run_in_child("/empty.pym", "/g", {}, {})

    assert result["error"] is False
    assert result["result"] is None or result["result"] == {}
```

### Step 2.5: Add Concurrent Execution Test

```python
@pytest.mark.asyncio
async def test_executor_concurrent_executions() -> None:
    """Multiple concurrent executions don't interfere with each other."""
    import concurrent.futures

    executor = ProcessIsolatedExecutor(max_workers=4, call_timeout=5.0)
    executor._pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    results_by_id = {}

    def _run_with_id(pym_path: str, *args):
        # Return the path as identifier
        return {"error": False, "result": {"id": pym_path}}

    with patch("remora.execution._run_in_child", side_effect=_run_with_id):
        tasks = [
            executor.execute(
                pym_path=Path(f"/test_{i}.pym"),
                grail_dir=Path("/grail"),
                inputs={"id": i},
            )
            for i in range(10)
        ]
        results = await asyncio.gather(*tasks)

    # Verify all 10 executions completed with correct IDs
    assert len(results) == 10
    paths = {r["result"]["id"] for r in results}
    assert len(paths) == 10  # All unique

    await executor.shutdown()
```

### Verification Checklist

- [ ] Test for script not found error added
- [ ] Test for load failure error added
- [ ] Test for empty result handling added
- [ ] Test for concurrent execution added
- [ ] All new tests pass: `pytest tests/test_execution.py -v`
- [ ] Coverage increased (run `pytest --cov=remora.execution`)

---

## Phase 3: Implement Behavior-Driven Tests

**Goal:** Refactor tests that rely on implementation details to focus on observable behavior instead.

### Step 3.1: Identify Implementation-Coupled Tests

Look for these anti-patterns in existing tests:

1. **Checking internal state**: Tests that access private attributes (`runner._internal_state`)
2. **Verifying call counts**: Tests that assert exact mock call counts rather than behavior
3. **Matching exact message formats**: Tests that hardcode internal message structures

### Step 3.2: Example Refactoring - Runner Message Tests

**Before (implementation-coupled):**

```python
def test_runner_initializes_model_and_messages(monkeypatch):
    # ... setup ...
    system_message = cast(dict[str, Any], runner.messages[0])
    user_message = cast(dict[str, Any], runner.messages[1])
    assert system_message["role"] == "system"
    assert system_message.get("content") == "You are a lint agent."
```

**After (behavior-focused):**

```python
def test_runner_sends_system_prompt_to_model(monkeypatch):
    """Runner should include the subagent's system prompt when calling the model."""
    # ... setup ...

    result = asyncio.run(runner.run())

    # Verify behavior: the model received a system message
    chat_calls = runner._client.chat.completions.calls
    assert len(chat_calls) >= 1

    first_call_messages = chat_calls[0]["messages"]
    system_messages = [m for m in first_call_messages if m.get("role") == "system"]

    assert len(system_messages) == 1
    assert "lint agent" in system_messages[0]["content"].lower()
```

### Step 3.3: Create Behavior Test Guidelines

Document these principles for the team:

```markdown
## Test Writing Guidelines

### DO: Test Observable Behavior
- Test public method return values
- Test that correct events are emitted
- Test that correct results are produced
- Test error conditions via exceptions or error return values

### DON'T: Test Implementation Details
- Avoid accessing private attributes (prefixed with `_`)
- Avoid asserting exact internal data structures
- Avoid counting exact method calls unless call count IS the behavior
- Avoid testing intermediate states

### Example: Testing Event Emission

# Good: Verify the event was emitted with expected data
events = []
runner.add_event_handler(lambda e: events.append(e))
await runner.run()
assert any(e.type == "tool_call" for e in events)

# Bad: Check internal event queue state
assert len(runner._event_queue) == 3
```

### Verification Checklist

- [ ] Reviewed all tests in `test_runner.py` for implementation coupling
- [ ] Refactored at least 5 tests to be behavior-focused
- [ ] Created `docs/TESTING_GUIDELINES.md` with principles
- [ ] All tests still pass after refactoring

---

## Phase 4: Add Property-Based Testing with Hypothesis

**Goal:** Use property-based testing to find edge cases automatically.

### Step 4.1: Install Hypothesis

Add to your development dependencies:

```bash
pip install hypothesis
# Or add to pyproject.toml/requirements-dev.txt:
# hypothesis>=6.0.0
```

### Step 4.2: Identify Candidates for Property Testing

Good candidates for property-based tests:

| Component | Property to Test |
|-----------|------------------|
| JSON parsing in tool scripts | Any valid JSON should parse without error |
| Node ID generation | Same input always produces same hash |
| Configuration merging | Merging with empty dict is identity |
| Path normalization | Normalized paths are idempotent |

### Step 4.3: Create Property Tests File

Create `tests/test_properties.py`:

```python
"""Property-based tests using Hypothesis."""

from __future__ import annotations

import json
from pathlib import Path

from hypothesis import given, strategies as st, assume, settings

from remora.discovery import CSTNode, NodeType


# Strategy for generating valid node data
node_names = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N"), whitelist_characters="_"),
    min_size=1,
    max_size=50,
).filter(lambda s: s[0].isalpha() or s[0] == "_")


@given(
    name=node_names,
    file_path=st.text(min_size=1, max_size=100).map(lambda s: s.replace("\x00", "")),
    start_byte=st.integers(min_value=0, max_value=10000),
    length=st.integers(min_value=1, max_value=1000),
)
def test_node_id_deterministic(name: str, file_path: str, start_byte: int, length: int) -> None:
    """Node ID generation is deterministic - same input = same output."""
    assume(len(file_path) > 0)

    node1 = CSTNode(
        node_id="",  # Will be computed
        node_type=NodeType.FUNCTION,
        name=name,
        file_path=Path(file_path),
        start_byte=start_byte,
        end_byte=start_byte + length,
        text=f"def {name}(): pass",
        start_line=1,
        end_line=1,
    )

    node2 = CSTNode(
        node_id="",
        node_type=NodeType.FUNCTION,
        name=name,
        file_path=Path(file_path),
        start_byte=start_byte,
        end_byte=start_byte + length,
        text=f"def {name}(): pass",
        start_line=1,
        end_line=1,
    )

    # If node_id is computed from content, these should match
    # Adjust based on actual implementation
    assert node1.node_id == node2.node_id


@given(data=st.dictionaries(st.text(), st.text() | st.integers() | st.floats(allow_nan=False)))
def test_json_roundtrip(data: dict) -> None:
    """Any JSON-serializable dict should survive encode/decode."""
    encoded = json.dumps(data)
    decoded = json.loads(encoded)
    assert decoded == data


@given(
    base=st.dictionaries(st.text(min_size=1), st.text()),
    override=st.dictionaries(st.text(min_size=1), st.text()),
)
def test_config_merge_empty_identity(base: dict, override: dict) -> None:
    """Merging with empty dict should return equivalent config."""
    from remora.config import _deep_merge  # If this function exists

    result = _deep_merge(base, {})
    assert result == base


@given(path=st.text(min_size=1, max_size=200))
@settings(max_examples=200)
def test_path_normalization_idempotent(path: str) -> None:
    """Normalizing a path twice should give the same result."""
    assume("\x00" not in path)  # Null bytes aren't valid in paths

    try:
        p = Path(path)
        normalized_once = p.resolve()
        normalized_twice = normalized_once.resolve()
        assert normalized_once == normalized_twice
    except (OSError, ValueError):
        pass  # Invalid paths are expected to fail
```

### Step 4.4: Add Fuzz Testing for Tool Script JSON

Create `tests/test_tool_script_fuzzing.py`:

```python
"""Fuzz testing for tool script JSON handling."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from hypothesis import given, strategies as st, settings, HealthCheck

# Strategy for potentially malicious/malformed JSON strings
json_like_strings = st.one_of(
    st.just(""),
    st.just("null"),
    st.just("{}"),
    st.just("[]"),
    st.just('{"key": "value"}'),
    st.text(),  # Random text
    st.binary().map(lambda b: b.decode("utf-8", errors="replace")),
)


@given(input_data=json_like_strings)
@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_tool_script_handles_malformed_json(input_data: str, tmp_path: Path) -> None:
    """Tool scripts should not crash on malformed JSON input."""
    # Create a minimal test script
    script_content = '''
import json
import os
import sys

try:
    input_str = os.environ.get("REMORA_INPUT", "{}")
    data = json.loads(input_str)
    print(json.dumps({"result": "ok", "parsed": True}))
except json.JSONDecodeError as e:
    print(json.dumps({"error": str(e), "parsed": False}))
except Exception as e:
    print(json.dumps({"error": str(e), "parsed": False}))
'''

    script_path = tmp_path / "test_script.py"
    script_path.write_text(script_content)

    env = {"REMORA_INPUT": input_data}

    result = subprocess.run(
        [sys.executable, str(script_path)],
        capture_output=True,
        text=True,
        env=env,
        timeout=5,
    )

    # Script should never crash (return code should be 0)
    assert result.returncode == 0, f"Script crashed with: {result.stderr}"

    # Output should be valid JSON
    try:
        output = json.loads(result.stdout.strip())
        assert "result" in output or "error" in output
    except json.JSONDecodeError:
        pytest.fail(f"Script produced invalid JSON: {result.stdout}")
```

### Verification Checklist

- [ ] Hypothesis installed and added to dev dependencies
- [ ] `tests/test_properties.py` created with property tests
- [ ] `tests/test_tool_script_fuzzing.py` created with fuzz tests
- [ ] All property tests pass: `pytest tests/test_properties.py -v`
- [ ] Fuzz tests pass: `pytest tests/test_tool_script_fuzzing.py -v`

---

## Phase 5: Add Snapshot/Golden Tests

**Goal:** Capture expected tool script outputs as snapshots for regression testing.

### Step 5.1: Install Snapshot Testing Library

```bash
pip install pytest-snapshot
# Or syrupy for inline snapshots:
pip install syrupy
```

### Step 5.2: Create Snapshot Test Infrastructure

Create `tests/snapshots/__init__.py` and the snapshot directory structure:

```bash
mkdir -p tests/snapshots
touch tests/snapshots/__init__.py
```

### Step 5.3: Create Snapshot Tests for Tool Scripts

Create `tests/test_tool_script_snapshots.py`:

```python
"""Snapshot tests for tool script outputs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def tool_scripts_dir() -> Path:
    """Get the directory containing tool scripts."""
    return Path(__file__).parent.parent / "remora" / "tools"


class TestLintToolSnapshots:
    """Snapshot tests for the lint tool scripts."""

    def test_run_linter_clean_file_output(
        self,
        snapshot,
        grail_executor_factory,
        integration_workspace,
    ):
        """Lint tool output for a clean file should match snapshot."""
        base_dir, target_relpath = integration_workspace
        executor = grail_executor_factory()

        # Setup clean workspace
        workspace_dir = base_dir / "test_workspace"
        executor.setup_workspace(workspace_dir)

        # Write a clean Python file
        clean_code = '''"""A clean module."""

def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b
'''
        (workspace_dir / target_relpath).write_text(clean_code)

        # Run the linter
        import asyncio
        result = asyncio.run(
            executor.execute(
                pym_path=Path("tools/lint/run_linter.pym"),
                grail_dir=workspace_dir,
                inputs={},
            )
        )

        # Normalize dynamic fields before snapshot comparison
        normalized = _normalize_lint_output(result)
        assert normalized == snapshot

    def test_run_linter_issues_found_output(
        self,
        snapshot,
        grail_executor_factory,
        integration_workspace,
    ):
        """Lint tool output with issues should match snapshot."""
        base_dir, target_relpath = integration_workspace
        executor = grail_executor_factory()

        workspace_dir = base_dir / "test_workspace"
        executor.setup_workspace(workspace_dir)

        # Write code with lint issues
        messy_code = '''import os
import sys
import json  # unused
def foo(x,y):
  return x+y
'''
        (workspace_dir / target_relpath).write_text(messy_code)

        import asyncio
        result = asyncio.run(
            executor.execute(
                pym_path=Path("tools/lint/run_linter.pym"),
                grail_dir=workspace_dir,
                inputs={},
            )
        )

        normalized = _normalize_lint_output(result)
        assert normalized == snapshot


def _normalize_lint_output(result: dict) -> dict:
    """Normalize lint output for snapshot comparison.

    Removes or normalizes fields that vary between runs:
    - Timestamps
    - Absolute file paths
    - Process IDs
    """
    if "error" in result:
        return {"error": True, "type": type(result.get("error")).__name__}

    normalized = dict(result)

    # Normalize file paths to relative
    if "files" in normalized:
        normalized["files"] = [
            str(Path(f).name) for f in normalized["files"]
        ]

    # Remove timing information
    normalized.pop("duration_ms", None)
    normalized.pop("timestamp", None)

    return normalized
```

### Step 5.4: Generate Initial Snapshots

Run the snapshot tests to generate initial snapshots:

```bash
pytest tests/test_tool_script_snapshots.py --snapshot-update
```

This creates snapshot files in `tests/snapshots/` that capture the expected output.

### Step 5.5: Add Snapshot Tests to CI

Update your CI configuration to run snapshot tests:

```yaml
# .github/workflows/test.yml
- name: Run snapshot tests
  run: pytest tests/test_tool_script_snapshots.py -v
```

### Verification Checklist

- [ ] Snapshot testing library installed
- [ ] `tests/snapshots/` directory created
- [ ] `tests/test_tool_script_snapshots.py` created
- [ ] Initial snapshots generated
- [ ] Snapshot tests pass: `pytest tests/test_tool_script_snapshots.py -v`

---

## Phase 6: Mock vLLM Server for CI

**Goal:** Enable acceptance tests to run in CI without a real vLLM server.

### Step 6.1: Create Mock vLLM Server

Create `remora/testing/mock_vllm_server.py`:

```python
"""Mock vLLM server for testing without real inference."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from aiohttp import web


@dataclass
class MockResponse:
    """Represents a canned response for the mock server."""

    pattern: str  # Regex pattern to match against prompt
    response: dict[str, Any]  # Response to return


@dataclass
class MockVLLMServer:
    """A mock vLLM server that returns canned responses."""

    host: str = "127.0.0.1"
    port: int = 8765
    responses: list[MockResponse] = field(default_factory=list)
    default_model: str = "google/functiongemma-270m-it"
    _app: web.Application | None = None
    _runner: web.AppRunner | None = None

    def add_response(self, pattern: str, response: dict[str, Any]) -> None:
        """Add a canned response for prompts matching the pattern."""
        self.responses.append(MockResponse(pattern=pattern, response=response))

    def add_tool_call_response(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        pattern: str = ".*",
    ) -> None:
        """Add a response that calls a specific tool."""
        response = {
            "id": "chatcmpl-mock",
            "object": "chat.completion",
            "created": 1234567890,
            "model": self.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_mock",
                        "type": "function",
                        "function": {
                            "name": tool_name,
                            "arguments": json.dumps(arguments),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        self.add_response(pattern, response)

    async def _handle_models(self, request: web.Request) -> web.Response:
        """Handle GET /v1/models."""
        return web.json_response({
            "object": "list",
            "data": [{"id": self.default_model, "object": "model"}],
        })

    async def _handle_completions(self, request: web.Request) -> web.Response:
        """Handle POST /v1/chat/completions."""
        import re

        body = await request.json()
        messages = body.get("messages", [])

        # Find last user message for pattern matching
        user_content = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        # Find matching response
        for mock_response in self.responses:
            if re.search(mock_response.pattern, user_content, re.IGNORECASE):
                return web.json_response(mock_response.response)

        # Default: return submit_result
        return web.json_response({
            "id": "chatcmpl-default",
            "object": "chat.completion",
            "created": 1234567890,
            "model": self.default_model,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "call_default",
                        "type": "function",
                        "function": {
                            "name": "submit_result",
                            "arguments": json.dumps({
                                "summary": "Mock completion",
                                "changed_files": [],
                                "details": {},
                            }),
                        },
                    }],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        })

    async def start(self) -> str:
        """Start the mock server and return its URL."""
        self._app = web.Application()
        self._app.router.add_get("/v1/models", self._handle_models)
        self._app.router.add_post("/v1/chat/completions", self._handle_completions)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()

        return f"http://{self.host}:{self.port}/v1"

    async def stop(self) -> None:
        """Stop the mock server."""
        if self._runner:
            await self._runner.cleanup()
```

### Step 6.2: Create Mock Server Fixture

Add to `tests/conftest.py`:

```python
import pytest
from remora.testing.mock_vllm_server import MockVLLMServer


@pytest.fixture
async def mock_vllm_server():
    """Fixture that provides a running mock vLLM server."""
    server = MockVLLMServer()
    url = await server.start()

    yield server, url

    await server.stop()


@pytest.fixture
def mock_server_config(mock_vllm_server):
    """Fixture that provides a ServerConfig pointing to the mock server."""
    server, url = mock_vllm_server
    from remora.config import ServerConfig

    return ServerConfig(
        base_url=url,
        api_key="mock-key",
        timeout=30,
        default_adapter=server.default_model,
    )
```

### Step 6.3: Create CI-Friendly Acceptance Tests

Create `tests/acceptance/test_mock_scenarios.py`:

```python
"""Acceptance tests that use mock vLLM server (CI-friendly)."""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.analyzer import RemoraAnalyzer
from remora.config import load_config

pytestmark = [pytest.mark.asyncio, pytest.mark.acceptance_mock]


async def test_lint_scenario_with_mock(
    sample_project: Path,
    remora_config: Path,
    mock_vllm_server,
):
    """Test lint workflow with mock vLLM server."""
    server, url = mock_vllm_server

    # Configure mock to return lint-specific tool calls
    server.add_tool_call_response(
        "run_linter",
        {"fix": True},
        pattern="lint",
    )
    server.add_tool_call_response(
        "submit_result",
        {"summary": "Linting complete", "changed_files": ["calculator.py"], "details": {}},
        pattern=".*",  # Default fallback
    )

    # Load config and override server URL
    config = load_config(remora_config)
    config.server.base_url = url

    analyzer = RemoraAnalyzer(config)
    results = await analyzer.analyze(
        [sample_project / "src"],
        operations=["lint"],
    )

    assert results.total_nodes > 0
    assert results.successful_operations > 0


async def test_docstring_scenario_with_mock(
    sample_project: Path,
    remora_config: Path,
    mock_vllm_server,
):
    """Test docstring generation with mock vLLM server."""
    server, url = mock_vllm_server

    server.add_tool_call_response(
        "read_docstring",
        {},
        pattern="docstring",
    )
    server.add_tool_call_response(
        "write_docstring",
        {"docstring": "A sample function."},
        pattern=".*",
    )
    server.add_tool_call_response(
        "submit_result",
        {"summary": "Docstring written", "changed_files": [], "details": {}},
    )

    config = load_config(remora_config)
    config.server.base_url = url

    analyzer = RemoraAnalyzer(config)
    results = await analyzer.analyze(
        [sample_project / "src"],
        operations=["docstring"],
    )

    assert results.total_nodes > 0
```

### Step 6.4: Update CI Configuration

```yaml
# .github/workflows/test.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run unit tests
        run: pytest tests/ -v --ignore=tests/acceptance --ignore=tests/integration

      - name: Run mock acceptance tests
        run: pytest tests/acceptance/test_mock_scenarios.py -v -m acceptance_mock
```

### Verification Checklist

- [ ] `remora/testing/mock_vllm_server.py` created
- [ ] Mock server fixture added to `tests/conftest.py`
- [ ] `tests/acceptance/test_mock_scenarios.py` created
- [ ] Mock acceptance tests pass locally
- [ ] CI configuration updated
- [ ] CI pipeline passes with mock tests

---

## Phase 7: Add Performance Benchmarks

**Goal:** Establish performance baselines and catch regressions.

### Step 7.1: Install Benchmarking Tools

```bash
pip install pytest-benchmark
```

### Step 7.2: Create Benchmark Tests

Create `tests/benchmarks/test_discovery_performance.py`:

```python
"""Performance benchmarks for discovery module."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


def _create_test_files(directory: Path, count: int, lines_per_file: int) -> None:
    """Create test Python files for benchmarking."""
    for i in range(count):
        content = "\n".join([
            f"def function_{j}():",
            f"    '''Function {j} in file {i}.'''",
            f"    return {j}",
            "",
        ] for j in range(lines_per_file // 4))

        (directory / f"module_{i}.py").write_text(content)


@pytest.fixture
def small_codebase(tmp_path: Path) -> Path:
    """Create a small test codebase (10 files, ~100 lines each)."""
    _create_test_files(tmp_path, count=10, lines_per_file=100)
    return tmp_path


@pytest.fixture
def medium_codebase(tmp_path: Path) -> Path:
    """Create a medium test codebase (50 files, ~200 lines each)."""
    _create_test_files(tmp_path, count=50, lines_per_file=200)
    return tmp_path


@pytest.fixture
def large_codebase(tmp_path: Path) -> Path:
    """Create a large test codebase (200 files, ~500 lines each)."""
    _create_test_files(tmp_path, count=200, lines_per_file=500)
    return tmp_path


class TestDiscoveryPerformance:
    """Benchmark tests for the discovery module."""

    def test_discover_small_codebase(self, benchmark, small_codebase: Path):
        """Benchmark discovery on small codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer()

        result = benchmark(discoverer.discover, small_codebase)

        assert len(result) > 0

    def test_discover_medium_codebase(self, benchmark, medium_codebase: Path):
        """Benchmark discovery on medium codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer()

        result = benchmark(discoverer.discover, medium_codebase)

        assert len(result) > 0

    @pytest.mark.slow
    def test_discover_large_codebase(self, benchmark, large_codebase: Path):
        """Benchmark discovery on large codebase."""
        from remora.discovery import TreeSitterDiscoverer

        discoverer = TreeSitterDiscoverer()

        result = benchmark(discoverer.discover, large_codebase)

        assert len(result) > 0


class TestExecutionPerformance:
    """Benchmark tests for script execution."""

    def test_executor_startup_time(self, benchmark):
        """Benchmark executor initialization."""
        from remora.execution import ProcessIsolatedExecutor

        def create_executor():
            executor = ProcessIsolatedExecutor(max_workers=4)
            return executor

        executor = benchmark(create_executor)

        # Cleanup
        import asyncio
        asyncio.run(executor.shutdown())
```

### Step 7.3: Run Benchmarks

```bash
# Run all benchmarks
pytest tests/benchmarks/ -v --benchmark-only

# Save benchmark results
pytest tests/benchmarks/ --benchmark-json=benchmark_results.json

# Compare against previous results
pytest tests/benchmarks/ --benchmark-compare=benchmark_results.json
```

### Step 7.4: Add Benchmark to CI (Optional)

```yaml
# .github/workflows/benchmark.yml
name: Performance Benchmarks

on:
  pull_request:
    branches: [main]

jobs:
  benchmark:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Run benchmarks
        run: |
          pytest tests/benchmarks/ \
            --benchmark-json=benchmark.json \
            --benchmark-compare-fail=mean:10%  # Fail if 10% slower

      - name: Upload benchmark results
        uses: actions/upload-artifact@v4
        with:
          name: benchmark-results
          path: benchmark.json
```

### Verification Checklist

- [ ] pytest-benchmark installed
- [ ] `tests/benchmarks/` directory created
- [ ] Discovery benchmarks created
- [ ] Execution benchmarks created
- [ ] Benchmarks run successfully: `pytest tests/benchmarks/ -v`
- [ ] Baseline benchmark results saved

---

## Final Verification

After completing all phases, verify the entire test suite:

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=remora --cov-report=html

# Run only unit tests (fast)
pytest tests/ -v --ignore=tests/acceptance --ignore=tests/integration -m "not slow"

# Run mock acceptance tests
pytest tests/acceptance/test_mock_scenarios.py -v

# Run benchmarks
pytest tests/benchmarks/ -v --benchmark-only
```

### Overall Checklist

- [ ] Phase 1: Test helpers moved to `remora.testing`
- [ ] Phase 2: Error path tests added
- [ ] Phase 3: Behavior-driven tests implemented
- [ ] Phase 4: Property-based tests added
- [ ] Phase 5: Snapshot tests created
- [ ] Phase 6: Mock vLLM server enables CI
- [ ] Phase 7: Performance benchmarks established
- [ ] All tests pass
- [ ] CI pipeline green
- [ ] Coverage improved

---

## Appendix: Quick Reference

### Running Specific Test Categories

```bash
# Unit tests only
pytest tests/test_*.py -v

# Integration tests (requires vLLM)
pytest tests/integration/ -v -m integration

# Acceptance tests (requires vLLM)
pytest tests/acceptance/ -v -m acceptance

# Mock acceptance tests (CI-safe)
pytest tests/acceptance/ -v -m acceptance_mock

# Property tests
pytest tests/test_properties.py -v

# Benchmarks
pytest tests/benchmarks/ --benchmark-only
```

### Common pytest Markers

```python
@pytest.mark.integration     # Requires vLLM server
@pytest.mark.acceptance      # End-to-end, requires vLLM
@pytest.mark.acceptance_mock # End-to-end with mock server
@pytest.mark.slow            # Long-running tests
@pytest.mark.asyncio         # Async test functions
```

### Useful pytest Plugins

| Plugin | Purpose |
|--------|---------|
| pytest-asyncio | Async test support |
| pytest-cov | Coverage reporting |
| pytest-benchmark | Performance benchmarks |
| pytest-snapshot / syrupy | Snapshot testing |
| hypothesis | Property-based testing |
| pytest-xdist | Parallel test execution |
