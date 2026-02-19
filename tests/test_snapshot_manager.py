"""Tests for remora.execution — SnapshotManager pause/resume lifecycle."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from remora.execution import SnapshotManager, SnapshotRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_snapshot(*, is_complete: bool = False, value: Any = None) -> MagicMock:
    """Build a mock grail Snapshot."""
    snap = MagicMock()
    snap.is_complete = is_complete
    snap.value = value
    snap.function_name = "some_external"
    snap.args = ("arg1",)
    snap.kwargs = {"key": "val"}
    return snap


def _make_script(*, start_snapshot: MagicMock | None = None) -> MagicMock:
    """Build a mock GrailScript."""
    script = MagicMock()
    if start_snapshot is not None:
        script.start.return_value = start_snapshot
    return script


# ---------------------------------------------------------------------------
# start_script tests
# ---------------------------------------------------------------------------


@patch("remora.execution.grail")
def test_start_completes_immediately(mock_grail: MagicMock) -> None:
    """Script that finishes without suspending returns result directly."""
    snap = _make_snapshot(is_complete=True, value={"answer": 42})
    script = _make_script(start_snapshot=snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=3)
    result = mgr.start_script(
        pym_path="/test.pym",
        grail_dir="/grail",
        inputs={"x": 1},
        externals={"fn": lambda: None},
        agent_id="agent-1",
        tool_name="my_tool",
    )

    assert result == {"error": False, "result": {"answer": 42}}
    assert mgr.active_count == 0  # No snapshot stored


@patch("remora.execution.grail")
def test_start_suspends(mock_grail: MagicMock) -> None:
    """Script that pauses at an external call returns snapshot info."""
    snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=3)
    result = mgr.start_script(
        pym_path="/test.pym",
        grail_dir="/grail",
        inputs={},
        externals={},
        agent_id="agent-1",
        tool_name="my_tool",
    )

    assert result["error"] is False
    assert result["suspended"] is True
    assert "snapshot_id" in result
    assert result["function_name"] == "some_external"
    assert mgr.active_count == 1


@patch("remora.execution.grail")
def test_start_grail_load_error(mock_grail: MagicMock) -> None:
    """GrailError during load returns structured error."""
    mock_grail.GrailError = type("GrailError", (Exception,), {})
    mock_grail.load.side_effect = mock_grail.GrailError("bad script")

    mgr = SnapshotManager()
    result = mgr.start_script("/bad.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "GRAIL"
    assert "bad script" in result["message"]


@patch("remora.execution.grail")
def test_start_unexpected_error(mock_grail: MagicMock) -> None:
    """Generic exception during start returns INTERNAL error."""
    mock_grail.GrailError = type("GrailError", (Exception,), {})
    script = MagicMock()
    script.start.side_effect = RuntimeError("boom")
    mock_grail.load.return_value = script

    mgr = SnapshotManager()
    result = mgr.start_script("/test.pym", "/g", {}, {})

    assert result["error"] is True
    assert result["code"] == "INTERNAL"
    assert "RuntimeError" in result["message"]


# ---------------------------------------------------------------------------
# resume_script tests
# ---------------------------------------------------------------------------


@patch("remora.execution.grail")
def test_resume_completes(mock_grail: MagicMock) -> None:
    """Resuming a suspended snapshot that finishes returns the result."""
    initial_snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=initial_snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=5)
    start_result = mgr.start_script("/test.pym", "/g", {}, {}, agent_id="a1")
    sid = start_result["snapshot_id"]

    # Prepare the resumed snapshot to be complete
    resumed_snap = _make_snapshot(is_complete=True, value={"done": True})
    initial_snap.resume.return_value = resumed_snap

    result = mgr.resume_script(sid, return_value="extra data")

    assert result == {"error": False, "result": {"done": True}}
    assert mgr.active_count == 0  # Cleaned up after completion


@patch("remora.execution.grail")
def test_resume_resuspends(mock_grail: MagicMock) -> None:
    """Script suspends again after resume — snapshot updated in place."""
    initial_snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=initial_snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=5)
    start_result = mgr.start_script("/test.pym", "/g", {}, {}, agent_id="a1")
    sid = start_result["snapshot_id"]

    # Prepare the resumed snapshot to suspend again
    second_snap = _make_snapshot(is_complete=False)
    second_snap.function_name = "another_external"
    initial_snap.resume.return_value = second_snap

    result = mgr.resume_script(sid)

    assert result["error"] is False
    assert result["suspended"] is True
    assert result["snapshot_id"] == sid
    assert result["function_name"] == "another_external"
    assert result["resume_count"] == 1
    assert mgr.active_count == 1


@patch("remora.execution.grail")
def test_resume_max_exceeded(mock_grail: MagicMock) -> None:
    """Exceeding max_resumes returns error and cleans up the snapshot."""
    initial_snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=initial_snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=1)
    start_result = mgr.start_script("/test.pym", "/g", {}, {}, agent_id="a1")
    sid = start_result["snapshot_id"]

    # First resume: still suspended
    next_snap = _make_snapshot(is_complete=False)
    initial_snap.resume.return_value = next_snap

    mgr.resume_script(sid)
    assert mgr.active_count == 1

    # Second resume: exceeds max_resumes=1
    result = mgr.resume_script(sid)

    assert result["error"] is True
    assert result["code"] == "MAX_RESUMES"
    assert mgr.active_count == 0  # Cleaned up


def test_resume_not_found() -> None:
    """Resuming an unknown snapshot_id returns SNAPSHOT_NOT_FOUND."""
    mgr = SnapshotManager()
    result = mgr.resume_script("nonexistent-id")

    assert result["error"] is True
    assert result["code"] == "SNAPSHOT_NOT_FOUND"


@patch("remora.execution.grail")
def test_resume_exception_cleans_up(mock_grail: MagicMock) -> None:
    """If resume() raises, the snapshot is cleaned up."""
    initial_snap = _make_snapshot(is_complete=False)
    initial_snap.resume.side_effect = RuntimeError("corrupt state")
    script = _make_script(start_snapshot=initial_snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=5)
    start_result = mgr.start_script("/test.pym", "/g", {}, {}, agent_id="a1")
    sid = start_result["snapshot_id"]

    result = mgr.resume_script(sid)

    assert result["error"] is True
    assert result["code"] == "RESUME_FAILED"
    assert mgr.active_count == 0


# ---------------------------------------------------------------------------
# cleanup_agent + eviction tests
# ---------------------------------------------------------------------------


@patch("remora.execution.grail")
def test_cleanup_agent(mock_grail: MagicMock) -> None:
    """cleanup_agent removes all snapshots for the given agent."""
    snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=10, max_resumes=5)

    mgr.start_script("/a.pym", "/g", {}, {}, agent_id="agent-A")
    mgr.start_script("/b.pym", "/g", {}, {}, agent_id="agent-A")
    mgr.start_script("/c.pym", "/g", {}, {}, agent_id="agent-B")

    assert mgr.active_count == 3

    removed = mgr.cleanup_agent("agent-A")

    assert removed == 2
    assert mgr.active_count == 1


@patch("remora.execution.grail")
def test_eviction(mock_grail: MagicMock) -> None:
    """Exceeding max_snapshots evicts the oldest entry."""
    snap = _make_snapshot(is_complete=False)
    script = _make_script(start_snapshot=snap)
    mock_grail.load.return_value = script

    mgr = SnapshotManager(max_snapshots=2, max_resumes=5)

    r1 = mgr.start_script("/a.pym", "/g", {}, {}, agent_id="a1", tool_name="t1")
    r2 = mgr.start_script("/b.pym", "/g", {}, {}, agent_id="a1", tool_name="t2")
    r3 = mgr.start_script("/c.pym", "/g", {}, {}, agent_id="a1", tool_name="t3")

    assert mgr.active_count == 2  # Oldest evicted

    # The first snapshot should have been evicted
    first_id = r1["snapshot_id"]
    result = mgr.resume_script(first_id)
    assert result["error"] is True
    assert result["code"] == "SNAPSHOT_NOT_FOUND"


def test_clear() -> None:
    """clear() removes all snapshots."""
    mgr = SnapshotManager()
    # Manually insert a record to test clear
    from remora.execution import SnapshotRecord
    record = SnapshotRecord(
        snapshot_id="test-id",
        pym_path="/test.pym",
        agent_id="a1",
        tool_name="t1",
        created_at=0.0,
        snapshot=MagicMock(),
    )
    mgr._snapshots["test-id"] = record
    assert mgr.active_count == 1

    mgr.clear()
    assert mgr.active_count == 0
