"""Unit tests for e2e/harness.py — TmuxDriver and DemoProjectGuard."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from e2e.harness import (
    DemoProjectGuard,
    TmuxDriver,
    _copy_recent_lsp_logs,
)


class TestTmuxDriverWaitForAbsent:
    """Tests for TmuxDriver.wait_for_absent method."""

    def test_returns_immediately_when_pattern_not_present(self) -> None:
        """Should return content immediately if pattern is not in pane."""
        driver = TmuxDriver()
        driver._started = True

        with patch.object(driver, "capture_pane", return_value="hello world"):
            result = driver.wait_for_absent("foo", timeout=1.0)
            assert result == "hello world"

    def test_waits_until_pattern_disappears(self) -> None:
        """Should poll until pattern is no longer present."""
        driver = TmuxDriver()
        driver._started = True

        # First two calls have pattern, third doesn't
        call_count = 0

        def mock_capture() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return "error: LSP not running"
            return "success: LSP ready"

        with patch.object(driver, "capture_pane", side_effect=mock_capture):
            result = driver.wait_for_absent("LSP not running", timeout=5.0, poll=0.01)
            assert "LSP ready" in result
            assert call_count == 3

    def test_timeout_raises_error(self) -> None:
        """Should raise TimeoutError if pattern never disappears."""
        driver = TmuxDriver()
        driver._started = True

        with patch.object(driver, "capture_pane", return_value="error: still here"):
            with pytest.raises(TimeoutError) as exc_info:
                driver.wait_for_absent("error", timeout=0.1, poll=0.02)
            assert "still here" in str(exc_info.value)

    def test_regex_mode_works(self) -> None:
        """Should support regex patterns."""
        driver = TmuxDriver()
        driver._started = True

        with patch.object(driver, "capture_pane", return_value="success 123"):
            # Pattern not present (no "error" anywhere)
            result = driver.wait_for_absent(r"error.*\d+", timeout=1.0, regex=True)
            assert result == "success 123"

    def test_regex_timeout_when_pattern_matches(self) -> None:
        """Should timeout if regex pattern keeps matching."""
        driver = TmuxDriver()
        driver._started = True

        with patch.object(driver, "capture_pane", return_value="error 999"):
            with pytest.raises(TimeoutError):
                driver.wait_for_absent(r"error.*\d+", timeout=0.1, poll=0.02, regex=True)


class TestDemoProjectGuard:
    """Tests for DemoProjectGuard snapshot/restore and state clearing."""

    def test_save_and_restore_files(self, tmp_path: Path) -> None:
        """Should snapshot files and restore them after modification."""
        # Create test files
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("original content 1")
        file2.write_text("original content 2")

        guard = DemoProjectGuard(files=[file1, file2], clear_state=False)
        guard.save()

        # Modify files
        file1.write_text("modified content 1")
        file2.write_text("modified content 2")

        # Restore
        guard.restore()

        assert file1.read_text() == "original content 1"
        assert file2.read_text() == "original content 2"

    def test_context_manager_restores_on_exit(self, tmp_path: Path) -> None:
        """Should restore files when exiting context manager."""
        file1 = tmp_path / "test.py"
        file1.write_text("original")

        with DemoProjectGuard(files=[file1], clear_state=False):
            file1.write_text("modified")

        assert file1.read_text() == "original"

    def test_clear_remora_state_removes_databases(self, tmp_path: Path) -> None:
        """Should remove indexer.db and subscriptions.db."""
        # Create mock .remora directory structure
        remora_dir = tmp_path / ".remora"
        remora_dir.mkdir()
        (remora_dir / "indexer.db").write_text("db content")
        (remora_dir / "subscriptions.db").write_text("sub content")
        (remora_dir / "events").mkdir()
        (remora_dir / "events" / "event1.json").write_text("{}")
        (remora_dir / "logs").mkdir()
        (remora_dir / "logs" / "log1.txt").write_text("log")
        (remora_dir / "models").mkdir()
        (remora_dir / "models" / "model.yaml").write_text("keep this")

        guard = DemoProjectGuard(files=[], clear_state=True)

        # Patch the state dir to point to our tmp_path
        with patch("e2e.harness._DEMO_STATE_DIR", remora_dir):
            guard.clear_remora_state()

        # DBs should be removed
        assert not (remora_dir / "indexer.db").exists()
        assert not (remora_dir / "subscriptions.db").exists()

        # Events and logs dirs should be cleared but exist
        assert (remora_dir / "events").exists()
        assert not (remora_dir / "events" / "event1.json").exists()
        assert (remora_dir / "logs").exists()
        assert not (remora_dir / "logs" / "log1.txt").exists()

        # Models should be preserved
        assert (remora_dir / "models" / "model.yaml").exists()
        assert (remora_dir / "models" / "model.yaml").read_text() == "keep this"

    def test_clear_state_on_context_entry(self, tmp_path: Path) -> None:
        """Should clear state when entering context if clear_state=True."""
        remora_dir = tmp_path / ".remora"
        remora_dir.mkdir()
        (remora_dir / "indexer.db").write_text("db")
        (remora_dir / "events").mkdir()
        (remora_dir / "logs").mkdir()

        with patch("e2e.harness._DEMO_STATE_DIR", remora_dir):
            with DemoProjectGuard(files=[], clear_state=True):
                # State should be cleared on entry
                assert not (remora_dir / "indexer.db").exists()


class TestLogCopying:
    """Tests for copying demo LSP logs into the real log directory."""

    def test_copy_recent_logs_copies_client_and_server(self, tmp_path: Path) -> None:
        demo_project = tmp_path / "demo"
        demo_logs = demo_project / ".remora" / "logs"
        real_logs = tmp_path / "real-logs"
        demo_logs.mkdir(parents=True)
        real_logs.mkdir(parents=True)

        old_server = demo_logs / "server-2026-03-05_100000.log"
        new_server = demo_logs / "server-2026-03-05_120000.log"
        new_client = demo_logs / "client-2026-03-05_120000.log"
        ignored_misc = demo_logs / "random.log"
        old_server.write_text("old")
        new_server.write_text("new-server")
        new_client.write_text("new-client")
        ignored_misc.write_text("misc")

        now = time.time()
        start_wallclock = now - 5
        old_mtime = now - 20
        new_mtime = now - 1
        for path, mtime in (
            (old_server, old_mtime),
            (new_server, new_mtime),
            (new_client, new_mtime),
            (ignored_misc, new_mtime),
        ):
            path.touch()
            os.utime(path, (mtime, mtime))

        with patch("e2e.harness.DEMO_PROJECT", demo_project), patch("e2e.harness.LOG_DIR", real_logs):
            copied = _copy_recent_lsp_logs(
                start_wallclock=start_wallclock,
            )

        copied_names = sorted(path.name for path in copied)
        assert copied_names == ["client-2026-03-05_120000.log", "server-2026-03-05_120000.log"]
        assert (real_logs / "client-2026-03-05_120000.log").read_text() == "new-client"
        assert (real_logs / "server-2026-03-05_120000.log").read_text() == "new-server"
        assert not (real_logs / "server-2026-03-05_100000.log").exists()
        assert not (real_logs / "random.log").exists()
