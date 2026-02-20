"""Tests for remora.execution — ProcessIsolatedExecutor and _run_in_child."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from remora.execution import ProcessIsolatedExecutor, _run_in_child


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_check(*, valid: bool = True, errors: list | None = None, warnings: list | None = None) -> MagicMock:
    check = MagicMock()
    check.valid = valid
    check.errors = errors or []
    check.warnings = warnings or []
    return check


def _make_script(
    *,
    check_valid: bool = True,
    check_errors: list | None = None,
    run_result: Any = None,
    run_side_effect: Exception | None = None,
) -> MagicMock:
    script = MagicMock()
    script.check.return_value = _make_check(valid=check_valid, errors=check_errors)

    # Create async mock for script.run
    async def _async_run(*args, **kwargs):
        if run_side_effect is not None:
            raise run_side_effect
        return run_result

    script.run = _async_run
    return script


# ---------------------------------------------------------------------------
# _run_in_child tests
# ---------------------------------------------------------------------------


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_success(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Valid script returns result dict."""
    mock_exists.return_value = True
    script = _make_script(run_result={"answer": 42})
    mock_grail.load.return_value = script

    result = _run_in_child("/fake.pym", "/fake_grail", {"x": 1}, {})

    assert result == {"error": False, "result": {"answer": 42}}
    mock_grail.load.assert_called_once_with("/fake.pym", grail_dir="/fake_grail")
    script.check.assert_called_once()


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_script_not_found(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Missing script file returns FILE_NOT_FOUND error."""
    mock_exists.return_value = False

    result = _run_in_child("/missing.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "FILE_NOT_FOUND"
    assert "/missing.pym" in result["message"]
    mock_grail.load.assert_not_called()


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


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_check_failure(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Invalid script returns GRAIL_CHECK error."""
    mock_exists.return_value = True
    err = MagicMock()
    err.__str__ = lambda self: "bad declaration"
    script = _make_script(check_valid=False, check_errors=[err])
    mock_grail.load.return_value = script

    result = _run_in_child("/bad.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "GRAIL_CHECK"
    assert "bad declaration" in result["message"]


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_limit_error(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """LimitError maps to structured dict with limit_type."""
    mock_exists.return_value = True

    # Create a proper exception class
    class LimitError(Exception):
        pass

    mock_grail.LimitError = LimitError

    # Create exception instance with limit_type
    real_exc = LimitError("duration exceeded")
    real_exc.limit_type = "max_duration"

    script = _make_script(run_side_effect=real_exc)
    mock_grail.load.return_value = script

    result = _run_in_child("/slow.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "LIMIT"
    assert result["limit_type"] == "max_duration"


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_execution_error(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """ExecutionError maps to structured dict with lineno."""
    mock_exists.return_value = True

    class FakeExecError(Exception):
        pass

    mock_grail.LimitError = type("LimitError", (Exception,), {})
    mock_grail.ExecutionError = FakeExecError
    mock_grail.GrailError = type("GrailError", (Exception,), {})

    exc = FakeExecError("name 'x' is not defined")
    exc.lineno = 10

    script = _make_script(run_side_effect=exc)
    mock_grail.load.return_value = script

    result = _run_in_child("/err.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "EXECUTION"
    assert result["lineno"] == 10


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_grail_error(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """GrailError maps to code GRAIL."""
    mock_exists.return_value = True

    class LimitError(Exception):
        pass

    class ExecutionError(Exception):
        pass

    class GrailError(Exception):
        pass

    mock_grail.LimitError = LimitError
    mock_grail.ExecutionError = ExecutionError
    mock_grail.GrailError = GrailError

    exc = GrailError("something went wrong")

    script = _make_script(run_side_effect=exc)
    mock_grail.load.return_value = script

    result = _run_in_child("/fail.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "GRAIL"
    assert "something went wrong" in result["message"]


@patch("remora.execution.grail")
@patch("remora.execution.Path.exists")
def test_run_in_child_unexpected_error(mock_exists: MagicMock, mock_grail: MagicMock) -> None:
    """Generic Exception maps to code INTERNAL."""
    mock_exists.return_value = True
    mock_grail.LimitError = type("LimitError", (Exception,), {})
    mock_grail.ExecutionError = type("ExecutionError", (Exception,), {})
    mock_grail.GrailError = type("GrailError", (Exception,), {})

    script = _make_script(run_side_effect=ValueError("surprise"))
    mock_grail.load.return_value = script

    result = _run_in_child("/oops.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "INTERNAL"
    assert "ValueError" in result["message"]


# ---------------------------------------------------------------------------
# ProcessIsolatedExecutor tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_success() -> None:
    """Happy path: execute returns result from _run_in_child."""
    executor = ProcessIsolatedExecutor(max_workers=1, call_timeout=5.0)
    expected = {"error": False, "result": {"ok": True}}

    # Use ThreadPoolExecutor to avoid pickling issues with MagicMock
    import concurrent.futures

    executor._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    with patch("remora.execution._run_in_child", return_value=expected) as mock_run:
        result = await executor.execute(
            pym_path=Path("/test.pym"),
            grail_dir=Path("/grail"),
            inputs={"x": 1},
            limits={"max_duration": "2s"},
        )

    assert result == expected
    await executor.shutdown()


@pytest.mark.asyncio
async def test_executor_timeout() -> None:
    """Timeout returns a structured TIMEOUT error dict."""
    executor = ProcessIsolatedExecutor(max_workers=1, call_timeout=0.01)

    # Use ThreadPoolExecutor to avoid pickling issues
    import concurrent.futures

    executor._pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    import time

    def _slow(*args: Any, **kwargs: Any) -> dict:
        time.sleep(1)
        return {"error": False, "result": {}}

    with patch("remora.execution._run_in_child", side_effect=_slow):
        result = await executor.execute(
            pym_path=Path("/slow.pym"),
            grail_dir=Path("/grail"),
            inputs={},
        )

    assert result["error"] is True
    assert result["code"] == "TIMEOUT"
    await executor.shutdown()


@pytest.mark.asyncio
async def test_executor_concurrent_executions() -> None:
    """Multiple concurrent executions don't interfere with each other."""
    import concurrent.futures

    executor = ProcessIsolatedExecutor(max_workers=4, call_timeout=5.0)
    executor._pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def _run_with_id(pym_path: str, *args: Any) -> dict[str, Any]:
        return {"error": False, "result": {"id": pym_path}}

    with patch("remora.execution._run_in_child", side_effect=_run_with_id):
        tasks = [
            executor.execute(
                pym_path=Path(f"/test_{index}.pym"),
                grail_dir=Path("/grail"),
                inputs={"id": index},
            )
            for index in range(10)
        ]
        results = await asyncio.gather(*tasks)

    assert len(results) == 10
    paths = {result["result"]["id"] for result in results}
    assert len(paths) == 10

    await executor.shutdown()


@pytest.mark.asyncio
async def test_executor_shutdown_idempotent() -> None:
    """Calling shutdown twice doesn't raise."""
    executor = ProcessIsolatedExecutor(max_workers=1)
    await executor.shutdown()
    await executor.shutdown()  # Should not raise
