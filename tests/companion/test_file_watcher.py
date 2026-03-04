"""Tests for the file_watcher sensor agent.

The file watcher monitors a workspace directory for external file changes
(created, modified, deleted) and emits FileChanged events. It uses asyncio
polling rather than an external dependency like watchdog.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

from remora_demo.companion.agents.sensors.file_watcher import (
    FileWatcher,
    FileWatcherConfig,
)
from remora_demo.companion.models.events import FileChanged


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace directory with some initial files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "README.md").write_text("# Project")
    return tmp_path


@pytest.fixture
def config(tmp_workspace: Path) -> FileWatcherConfig:
    return FileWatcherConfig(
        watch_path=tmp_workspace,
        poll_interval_ms=50,  # Fast polling for tests
    )


@pytest.fixture
def watcher(config: FileWatcherConfig) -> FileWatcher:
    return FileWatcher(config)


# -- Construction --


class TestFileWatcherInit:
    def test_creates_with_defaults(self, tmp_workspace: Path) -> None:
        cfg = FileWatcherConfig(watch_path=tmp_workspace)
        w = FileWatcher(cfg)
        assert w.config.watch_path == tmp_workspace
        assert w.config.poll_interval_ms == 1000  # default

    def test_creates_with_custom_config(self, tmp_workspace: Path) -> None:
        cfg = FileWatcherConfig(
            watch_path=tmp_workspace,
            poll_interval_ms=500,
            ignore_patterns=[".git", "__pycache__", "node_modules", ".venv"],
        )
        w = FileWatcher(cfg)
        assert w.config.poll_interval_ms == 500
        assert ".venv" in w.config.ignore_patterns

    def test_event_handlers_initially_empty(self, watcher: FileWatcher) -> None:
        assert watcher._event_handlers == []


# -- Event registration --


class TestEventRegistration:
    def test_on_event_registers_handler(self, watcher: FileWatcher) -> None:
        handler = lambda e: None
        watcher.on_event(handler)
        assert len(watcher._event_handlers) == 1

    def test_multiple_handlers(self, watcher: FileWatcher) -> None:
        watcher.on_event(lambda e: None)
        watcher.on_event(lambda e: None)
        assert len(watcher._event_handlers) == 2


# -- Ignore patterns --


class TestIgnorePatterns:
    def test_ignores_git_directory(self, watcher: FileWatcher) -> None:
        assert watcher._should_ignore(Path("/project/.git/objects/abc123"))

    def test_ignores_node_modules(self, watcher: FileWatcher) -> None:
        assert watcher._should_ignore(Path("/project/node_modules/lodash/index.js"))

    def test_ignores_pycache(self, watcher: FileWatcher) -> None:
        assert watcher._should_ignore(Path("/project/src/__pycache__/main.cpython-311.pyc"))

    def test_does_not_ignore_normal_files(self, watcher: FileWatcher) -> None:
        assert not watcher._should_ignore(Path("/project/src/main.py"))

    def test_does_not_ignore_readme(self, watcher: FileWatcher) -> None:
        assert not watcher._should_ignore(Path("/project/README.md"))


# -- File change detection --


class TestFileCreated:
    async def test_detects_new_file(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        events: list[FileChanged] = []
        watcher.on_event(lambda e: events.append(e))

        # Take initial snapshot
        watcher._snapshot = watcher._take_snapshot()

        # Create a new file
        (tmp_workspace / "src" / "new_module.py").write_text("# new")

        # Detect changes
        changes = watcher._detect_changes()

        assert len(changes) == 1
        assert changes[0].kind == "created"
        assert "new_module.py" in changes[0].path


class TestFileModified:
    async def test_detects_modified_file(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        # Take initial snapshot
        watcher._snapshot = watcher._take_snapshot()

        # Modify a file — ensure mtime changes
        import time

        time.sleep(0.05)
        (tmp_workspace / "src" / "main.py").write_text("print('modified')")

        # Detect changes
        changes = watcher._detect_changes()

        assert len(changes) == 1
        assert changes[0].kind == "modified"
        assert "main.py" in changes[0].path


class TestFileDeleted:
    async def test_detects_deleted_file(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        # Take initial snapshot
        watcher._snapshot = watcher._take_snapshot()

        # Delete a file
        (tmp_workspace / "README.md").unlink()

        # Detect changes
        changes = watcher._detect_changes()

        assert len(changes) == 1
        assert changes[0].kind == "deleted"
        assert "README.md" in changes[0].path


# -- Snapshot --


class TestSnapshot:
    def test_snapshot_includes_existing_files(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        snapshot = watcher._take_snapshot()
        paths = {str(p) for p in snapshot.keys()}
        assert any("main.py" in p for p in paths)
        assert any("README.md" in p for p in paths)

    def test_snapshot_excludes_ignored(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        # Create an ignored directory
        git_dir = tmp_workspace / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "abc123").write_text("blob")

        snapshot = watcher._take_snapshot()
        paths = {str(p) for p in snapshot.keys()}
        assert not any(".git" in p for p in paths)


# -- Start / Stop lifecycle --


class TestLifecycle:
    async def test_start_and_stop(self, watcher: FileWatcher) -> None:
        await watcher.start()
        assert watcher._running is True
        assert watcher._poll_task is not None

        await watcher.stop()
        assert watcher._running is False

    async def test_start_takes_initial_snapshot(self, watcher: FileWatcher) -> None:
        await watcher.start()
        assert watcher._snapshot is not None
        assert len(watcher._snapshot) > 0
        await watcher.stop()


# -- Emit integration --


class TestEmitIntegration:
    async def test_emits_events_to_handlers(self, tmp_workspace: Path, watcher: FileWatcher) -> None:
        events: list[FileChanged] = []

        async def handler(e: FileChanged) -> None:
            events.append(e)

        watcher.on_event(handler)

        # Start watcher (takes snapshot)
        await watcher.start()

        # Create a new file
        (tmp_workspace / "new_file.txt").write_text("hello")

        # Wait for at least one poll cycle
        await asyncio.sleep(0.15)

        await watcher.stop()

        assert len(events) >= 1
        assert events[0].kind == "created"
        assert "new_file.txt" in events[0].path
