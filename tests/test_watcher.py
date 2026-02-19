"""Tests for remora.watcher — RemoraFileWatcher."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.watcher import (
    DEFAULT_IGNORE_PATTERNS,
    FileChange,
    RemoraFileWatcher,
)


# ---------------------------------------------------------------------------
# FileChange dataclass
# ---------------------------------------------------------------------------


class TestFileChange:
    def test_fields(self) -> None:
        change = FileChange(path=Path("/foo/bar.py"), change_type="modified")
        assert change.path == Path("/foo/bar.py")
        assert change.change_type == "modified"

    def test_frozen(self) -> None:
        change = FileChange(path=Path("/x.py"), change_type="added")
        with pytest.raises(AttributeError):
            change.path = Path("/y.py")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RemoraFileWatcher — construction & properties
# ---------------------------------------------------------------------------


class TestRemoraFileWatcherInit:
    def test_default_extensions(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
        )
        assert watcher._extensions == {".py"}

    def test_custom_extensions(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
            extensions={".py", ".pyi"},
        )
        assert watcher._extensions == {".py", ".pyi"}

    def test_default_ignore_patterns(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
        )
        assert watcher._ignore_patterns == list(DEFAULT_IGNORE_PATTERNS)

    def test_custom_ignore_patterns(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
            ignore_patterns=["vendor", ".mypy_cache"],
        )
        assert watcher._ignore_patterns == ["vendor", ".mypy_cache"]

    def test_debounce_conversion(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
            debounce_ms=1000,
        )
        assert watcher._debounce_s == 1.0

    def test_running_property_initially_false(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
        )
        assert watcher.running is False


# ---------------------------------------------------------------------------
# _should_ignore
# ---------------------------------------------------------------------------


class TestShouldIgnore:
    def _make_watcher(
        self,
        watch_root: Path,
        ignore_patterns: list[str] | None = None,
    ) -> RemoraFileWatcher:
        return RemoraFileWatcher(
            watch_paths=[watch_root],
            on_changes=AsyncMock(),
            ignore_patterns=ignore_patterns or ["__pycache__", ".git"],
        )

    def test_ignored_directory(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path)
        assert watcher._should_ignore(tmp_path / "__pycache__" / "foo.pyc") is True

    def test_not_ignored(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path)
        assert watcher._should_ignore(tmp_path / "src" / "main.py") is False

    def test_git_ignored(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path)
        assert watcher._should_ignore(tmp_path / ".git" / "objects" / "abc") is True

    def test_path_outside_watch_root(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path / "subdir")
        assert watcher._should_ignore(Path("/completely/different/path.py")) is True


# ---------------------------------------------------------------------------
# Extension filtering
# ---------------------------------------------------------------------------


class TestExtensionFiltering:
    def _make_watcher(
        self,
        watch_root: Path,
        extensions: set[str] | None = None,
    ) -> RemoraFileWatcher:
        return RemoraFileWatcher(
            watch_paths=[watch_root],
            on_changes=AsyncMock(),
            extensions=extensions,
            ignore_patterns=[],
        )

    def test_py_extension_accepted_by_default(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path)
        # The extension check is made in start() on the suffix, so we just
        # verify the extensions set
        assert ".py" in watcher._extensions

    def test_txt_extension_rejected_by_default(self, tmp_path: Path) -> None:
        watcher = self._make_watcher(tmp_path)
        assert ".txt" not in watcher._extensions


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    def test_stop_sets_event_and_flag(self) -> None:
        watcher = RemoraFileWatcher(
            watch_paths=[Path(".")],
            on_changes=AsyncMock(),
        )
        watcher._running = True
        watcher.stop()
        assert watcher._running is False
        assert watcher._stop_event.is_set()


# ---------------------------------------------------------------------------
# start() — integration-style with mocked awatch
# ---------------------------------------------------------------------------


class TestStartWithMockedWatch:
    """Test the start/stop lifecycle by mocking ``watchfiles.awatch``."""

    @pytest.mark.asyncio
    async def test_triggers_callback_on_py_change(self, tmp_path: Path) -> None:
        """A .py change should reach the callback after debounce."""
        callback = AsyncMock()
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=50,  # short debounce for test speed
            ignore_patterns=[],
        )

        py_file = tmp_path / "example.py"

        # Simulate watchfiles yielding one batch of changes, then stopping
        from watchfiles import Change

        async def fake_awatch(*args, **kwargs):
            yield {(Change.modified, str(py_file))}
            # Give debounce time to fire
            await asyncio.sleep(0.1)
            watcher.stop()

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            await watcher.start()

        assert callback.call_count >= 1
        changes = callback.call_args[0][0]
        assert len(changes) >= 1
        assert changes[0].path == py_file
        assert changes[0].change_type == "modified"

    @pytest.mark.asyncio
    async def test_filters_non_py_extension(self, tmp_path: Path) -> None:
        """A .txt change should NOT reach the callback."""
        callback = AsyncMock()
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=50,
            ignore_patterns=[],
        )

        txt_file = tmp_path / "readme.txt"

        from watchfiles import Change

        async def fake_awatch(*args, **kwargs):
            yield {(Change.modified, str(txt_file))}
            await asyncio.sleep(0.1)
            watcher.stop()

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            await watcher.start()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_filters_ignored_directory(self, tmp_path: Path) -> None:
        """Changes in __pycache__ should NOT reach the callback."""
        callback = AsyncMock()
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=50,
            ignore_patterns=["__pycache__"],
        )

        pycache_file = tmp_path / "__pycache__" / "module.cpython-313.pyc"

        from watchfiles import Change

        async def fake_awatch(*args, **kwargs):
            yield {(Change.modified, str(pycache_file))}
            await asyncio.sleep(0.1)
            watcher.stop()

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            await watcher.start()

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_callback_error_does_not_crash_watcher(self, tmp_path: Path) -> None:
        """An exception in the callback should be logged, not re-raised."""
        callback = AsyncMock(side_effect=RuntimeError("analysis failed"))
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=50,
            ignore_patterns=[],
        )

        py_file = tmp_path / "crash.py"

        from watchfiles import Change

        async def fake_awatch(*args, **kwargs):
            yield {(Change.modified, str(py_file))}
            await asyncio.sleep(0.15)
            # Watcher should still be running despite callback error
            watcher.stop()

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            # Should NOT raise RuntimeError — it should be caught and logged
            await watcher.start()

        # Callback was called despite raising
        assert callback.call_count >= 1

    @pytest.mark.asyncio
    async def test_stop_terminates_watch_loop(self, tmp_path: Path) -> None:
        """Calling stop() should exit the watch loop cleanly."""
        callback = AsyncMock()
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=50,
        )

        async def fake_awatch(*args, **kwargs):
            # Will keep yielding, but stop should break the loop
            while True:
                yield set()
                await asyncio.sleep(0.05)

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            # Start in a task and stop after a short delay
            task = asyncio.create_task(watcher.start())
            await asyncio.sleep(0.1)
            assert watcher.running is True
            watcher.stop()
            await asyncio.wait_for(task, timeout=2.0)

        assert watcher.running is False

    @pytest.mark.asyncio
    async def test_debounce_batches_rapid_changes(self, tmp_path: Path) -> None:
        """Multiple rapid changes should be batched into one callback."""
        callback = AsyncMock()
        watcher = RemoraFileWatcher(
            watch_paths=[tmp_path],
            on_changes=callback,
            debounce_ms=100,
            ignore_patterns=[],
        )

        file_a = tmp_path / "a.py"
        file_b = tmp_path / "b.py"

        from watchfiles import Change

        async def fake_awatch(*args, **kwargs):
            # Emit two batches in rapid succession (within debounce window)
            yield {(Change.modified, str(file_a))}
            await asyncio.sleep(0.01)  # way shorter than debounce
            yield {(Change.modified, str(file_b))}
            # Wait for debounce to fire
            await asyncio.sleep(0.2)
            watcher.stop()

        with patch("remora.watcher.awatch", side_effect=fake_awatch):
            await watcher.start()

        # Should have been called once (batched), with both files
        assert callback.call_count == 1
        changes = callback.call_args[0][0]
        paths = {c.path for c in changes}
        assert file_a in paths
        assert file_b in paths


# ---------------------------------------------------------------------------
# WatchConfig integration
# ---------------------------------------------------------------------------


class TestWatchConfig:
    def test_default_config(self) -> None:
        from remora.config import WatchConfig

        cfg = WatchConfig()
        assert cfg.extensions == {".py"}
        assert "__pycache__" in cfg.ignore_patterns
        assert cfg.debounce_ms == 500

    def test_custom_config(self) -> None:
        from remora.config import WatchConfig

        cfg = WatchConfig(
            extensions={".py", ".pyi"},
            ignore_patterns=["vendor"],
            debounce_ms=1000,
        )
        assert cfg.extensions == {".py", ".pyi"}
        assert cfg.ignore_patterns == ["vendor"]
        assert cfg.debounce_ms == 1000

    def test_remora_config_includes_watch(self) -> None:
        from remora.config import RemoraConfig, WatchConfig

        config = RemoraConfig()
        assert isinstance(config.watch, WatchConfig)
