"""Tests for remora.execution — ProcessIsolatedExecutor and _run_in_child."""

from __future__ import annotations

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
    if run_side_effect is not None:
        script.run_sync.side_effect = run_side_effect
    else:
        script.run_sync.return_value = run_result
    return script


# ---------------------------------------------------------------------------
# _run_in_child tests
# ---------------------------------------------------------------------------


@patch("remora.execution.grail")
def test_run_in_child_success(mock_grail: MagicMock) -> None:
    """Valid script returns result dict."""
    script = _make_script(run_result={"answer": 42})
    mock_grail.load.return_value = script

    result = _run_in_child("/fake.pym", "/fake_grail", {"x": 1}, {})

    assert result == {"error": False, "result": {"answer": 42}}
    mock_grail.load.assert_called_once_with("/fake.pym", grail_dir="/fake_grail")
    script.check.assert_called_once()
    script.run_sync.assert_called_once_with(inputs={"x": 1}, limits={})


@patch("remora.execution.grail")
def test_run_in_child_check_failure(mock_grail: MagicMock) -> None:
    """Invalid script returns GRAIL_CHECK error."""
    err = MagicMock()
    err.__str__ = lambda self: "bad declaration"
    script = _make_script(check_valid=False, check_errors=[err])
    mock_grail.load.return_value = script

    result = _run_in_child("/bad.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "GRAIL_CHECK"
    assert "bad declaration" in result["message"]
    script.run_sync.assert_not_called()


@patch("remora.execution.grail")
def test_run_in_child_limit_error(mock_grail: MagicMock) -> None:
    """LimitError maps to structured dict with limit_type."""
    limit_exc = MagicMock(spec=Exception)
    limit_exc.limit_type = "max_duration"
    limit_exc.__str__ = lambda self: "duration exceeded"
    limit_exc.__class__ = type("LimitError", (Exception,), {})
    mock_grail.LimitError = type(limit_exc)

    # Rebuild with the real exception class
    real_exc = mock_grail.LimitError()
    real_exc.limit_type = "max_duration"
    real_exc.__str__ = lambda: "duration exceeded"

    script = _make_script(run_side_effect=real_exc)
    mock_grail.load.return_value = script

    result = _run_in_child("/slow.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "LIMIT"
    assert result["limit_type"] == "max_duration"


@patch("remora.execution.grail")
def test_run_in_child_execution_error(mock_grail: MagicMock) -> None:
    """ExecutionError maps to structured dict with lineno."""

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
def test_run_in_child_grail_error(mock_grail: MagicMock) -> None:
    """GrailError maps to code GRAIL."""

    class FakeGrailError(Exception):
        pass

    mock_grail.LimitError = type("LimitError", (Exception,), {})
    mock_grail.ExecutionError = type("ExecutionError", (Exception,), {})
    mock_grail.GrailError = FakeGrailError

    exc = FakeGrailError("something went wrong")

    script = _make_script(run_side_effect=exc)
    mock_grail.load.return_value = script

    result = _run_in_child("/fail.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "GRAIL"
    assert "something went wrong" in result["message"]


@patch("remora.execution.grail")
def test_run_in_child_unexpected_error(mock_grail: MagicMock) -> None:
    """Generic Exception maps to code INTERNAL."""
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
async def test_executor_shutdown_idempotent() -> None:
    """Calling shutdown twice doesn't raise."""
    executor = ProcessIsolatedExecutor(max_workers=1)
    await executor.shutdown()
    await executor.shutdown()  # Should not raise
