"""Tests for HubWatcher file filtering."""

from pathlib import Path

from remora.hub.watcher import HubWatcher


async def _noop_callback(_change: str, _path: Path) -> None:
    return None


def test_should_process_python_file(tmp_path: Path) -> None:
    watcher = HubWatcher(tmp_path, _noop_callback)

    assert watcher._should_process(tmp_path / "example.py") is True


def test_should_filter_non_python_file(tmp_path: Path) -> None:
    watcher = HubWatcher(tmp_path, _noop_callback)

    assert watcher._should_process(tmp_path / "example.txt") is False


def test_should_filter_ignored_paths(tmp_path: Path) -> None:
    watcher = HubWatcher(tmp_path, _noop_callback)

    assert watcher._should_process(tmp_path / "node_modules" / "lib.py") is False
    assert watcher._should_process(tmp_path / ".remora" / "hub.py") is False


def test_should_filter_hidden_paths(tmp_path: Path) -> None:
    watcher = HubWatcher(tmp_path, _noop_callback)

    assert watcher._should_process(tmp_path / ".hidden" / "file.py") is False
    assert watcher._should_process(tmp_path / ".hidden.py") is False
