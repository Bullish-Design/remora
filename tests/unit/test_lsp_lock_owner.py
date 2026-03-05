from __future__ import annotations

import time
from pathlib import Path

import pytest

from remora.lsp import _LockOwnerMetadata, _WorkspaceProcessLock


def _read_heartbeat_ms(pid_path: Path) -> int:
    lines = pid_path.read_text(encoding="utf-8").splitlines()
    return int(lines[1])


def test_workspace_lock_heartbeat_updates_and_release_cleans_pid(tmp_path: Path) -> None:
    lock = _WorkspaceProcessLock(
        lock_path=tmp_path / "lsp.lock",
        pid_path=tmp_path / "lsp.pid",
        heartbeat_interval_ms=40,
    )
    try:
        lock.acquire()
        first = _read_heartbeat_ms(lock.pid_path)
        time.sleep(0.12)
        second = _read_heartbeat_ms(lock.pid_path)
        assert second > first
    finally:
        lock.release()
    assert not lock.pid_path.exists()


def test_workspace_lock_reclaims_stale_owner_and_retries(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock = _WorkspaceProcessLock(
        lock_path=tmp_path / "lsp.lock",
        pid_path=tmp_path / "lsp.pid",
        stale_owner_ms=10,
    )

    calls = {"attempts": 0, "terminated": 0}

    def fake_try_flock(_handle) -> bool:
        calls["attempts"] += 1
        return calls["attempts"] > 1

    def fake_read_owner() -> _LockOwnerMetadata:
        return _LockOwnerMetadata(pid=424242, heartbeat_ms=1)

    def fake_now_ms() -> int:
        return 10_000

    def fake_is_alive(_pid: int) -> bool:
        return True

    def fake_matches_workspace(_pid: int) -> bool:
        return True

    def fake_terminate(_pid: int) -> bool:
        calls["terminated"] += 1
        return True

    monkeypatch.setattr(lock, "_try_flock", fake_try_flock)
    monkeypatch.setattr(lock, "_read_owner_metadata", fake_read_owner)
    monkeypatch.setattr(lock, "_now_ms", fake_now_ms)
    monkeypatch.setattr(lock, "_is_process_alive", fake_is_alive)
    monkeypatch.setattr(lock, "_process_matches_workspace", fake_matches_workspace)
    monkeypatch.setattr(lock, "_terminate_stale_owner", fake_terminate)

    try:
        lock.acquire()
    finally:
        lock.release()

    assert calls["terminated"] == 1
    assert calls["attempts"] == 2


def test_workspace_lock_does_not_reclaim_fresh_owner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    lock = _WorkspaceProcessLock(
        lock_path=tmp_path / "lsp.lock",
        pid_path=tmp_path / "lsp.pid",
        stale_owner_ms=5_000,
    )

    def fake_try_flock(_handle) -> bool:
        return False

    def fake_read_owner() -> _LockOwnerMetadata:
        return _LockOwnerMetadata(pid=777, heartbeat_ms=9_900)

    def fake_now_ms() -> int:
        return 10_000

    def fake_is_alive(_pid: int) -> bool:
        return True

    terminated = {"count": 0}

    def fake_terminate(_pid: int) -> bool:
        terminated["count"] += 1
        return True

    monkeypatch.setattr(lock, "_try_flock", fake_try_flock)
    monkeypatch.setattr(lock, "_read_owner_metadata", fake_read_owner)
    monkeypatch.setattr(lock, "_now_ms", fake_now_ms)
    monkeypatch.setattr(lock, "_is_process_alive", fake_is_alive)
    monkeypatch.setattr(lock, "_terminate_stale_owner", fake_terminate)

    with pytest.raises(RuntimeError, match="already active"):
        lock.acquire()

    assert terminated["count"] == 0
