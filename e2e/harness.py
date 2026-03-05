"""E2E demo test harness — TmuxDriver, AsciinemaRecorder, Scenario protocol.

Drives the Neovim LSP demo via tmux send-keys, records terminal output
as asciicast v2 files (.cast), and converts recordings to GIF via agg.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Protocol

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_COLS = 120
DEFAULT_ROWS = 35
DEFAULT_TIMEOUT = 30  # seconds
POLL_INTERVAL = 0.3  # seconds between capture-pane polls
SESSION_PREFIX = "remora-e2e"

OUTPUT_DIR = Path(__file__).parent / "output"
LOG_DIR = Path(__file__).parent.parent / ".remora" / "logs"

# The demo project that scenarios open in nv2
DEMO_PROJECT = Path(__file__).parent.parent / "remora_demo" / "project"

# Files in the demo project that scenarios may modify
_DEMO_MUTABLE_FILES = [
    DEMO_PROJECT / "src" / "configlib" / "loader.py",
    DEMO_PROJECT / "src" / "configlib" / "merge.py",
    DEMO_PROJECT / "src" / "configlib" / "schema.py",
    DEMO_PROJECT / "tests" / "test_loader.py",
    DEMO_PROJECT / "tests" / "test_merge.py",
    DEMO_PROJECT / "MONITOR.md",
]

# Remora state directories that should be cleared between runs
_DEMO_STATE_DIR = DEMO_PROJECT / ".remora"


# ---------------------------------------------------------------------------
# Cleanup utilities
# ---------------------------------------------------------------------------


def cleanup_stale_sessions() -> int:
    """Kill any orphaned remora-e2e tmux sessions from previous runs.

    Returns the number of sessions killed.
    """
    result = subprocess.run(
        ["tmux", "list-sessions", "-F", "#{session_name}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # No tmux server running, nothing to clean up
        return 0

    killed = 0
    for line in result.stdout.strip().split("\n"):
        session_name = line.strip()
        if session_name.startswith(SESSION_PREFIX):
            subprocess.run(
                ["tmux", "kill-session", "-t", session_name],
                capture_output=True,
                text=True,
            )
            killed += 1

    return killed


# ---------------------------------------------------------------------------
# DemoProjectGuard — snapshot and restore mutable demo files
# ---------------------------------------------------------------------------


class DemoProjectGuard:
    """Saves and restores demo project files that scenarios may modify.

    Used as a context manager around scenario execution to guarantee the
    demo project is always left in its original state — even if a scenario
    fails or the process is interrupted.

    Also clears Remora event/chat state to ensure test isolation.
    """

    def __init__(
        self,
        files: list[Path] | None = None,
        *,
        clear_state: bool = True,
    ) -> None:
        self._files = files or _DEMO_MUTABLE_FILES
        self._snapshots: dict[Path, bytes] = {}
        self._clear_state = clear_state

    def save(self) -> None:
        """Read and store the current content of each mutable file."""
        for fpath in self._files:
            if fpath.exists():
                self._snapshots[fpath] = fpath.read_bytes()

    def restore(self) -> None:
        """Write back the saved content, restoring files to their original state."""
        for fpath, content in self._snapshots.items():
            fpath.write_bytes(content)

    def clear_remora_state(self) -> None:
        """Clear Remora event/chat databases and logs for test isolation.

        Removes:
        - .remora/events/ (event store files)
        - .remora/indexer.db (node projection database)
        - .remora/subscriptions.db (subscription state)
        - .remora/logs/ (log files)

        Preserves:
        - .remora/models/ (extension definitions — should not change)
        """
        if not _DEMO_STATE_DIR.exists():
            return

        # Clear events directory
        events_dir = _DEMO_STATE_DIR / "events"
        if events_dir.exists():
            shutil.rmtree(events_dir)
            events_dir.mkdir()

        # Clear logs directory
        logs_dir = _DEMO_STATE_DIR / "logs"
        if logs_dir.exists():
            shutil.rmtree(logs_dir)
            logs_dir.mkdir()

        # Remove database files
        for db_file in ["indexer.db", "subscriptions.db"]:
            db_path = _DEMO_STATE_DIR / db_file
            if db_path.exists():
                db_path.unlink()

    def __enter__(self) -> DemoProjectGuard:
        self.save()
        if self._clear_state:
            self.clear_remora_state()
        return self

    def __exit__(self, *exc: object) -> None:
        self.restore()


# ---------------------------------------------------------------------------
# TmuxDriver
# ---------------------------------------------------------------------------


class TmuxError(Exception):
    """Raised when a tmux operation fails."""


@dataclass
class TmuxDriver:
    """Drives a tmux session for E2E demo scenarios.

    Creates a detached tmux session with fixed geometry, sends keystrokes,
    waits for expected text to appear, and captures pane content.
    """

    session_name: str = ""
    cols: int = DEFAULT_COLS
    rows: int = DEFAULT_ROWS
    pipe_log_path: Path | None = None  # Optional path to capture all tmux output
    _started: bool = field(default=False, init=False, repr=False)

    def start(self, working_dir: str | Path | None = None) -> None:
        """Create a new detached tmux session."""
        if not self.session_name:
            self.session_name = f"{SESSION_PREFIX}-{os.getpid()}"

        cmd = [
            "tmux",
            "new-session",
            "-d",  # detached
            "-s",
            self.session_name,
            "-x",
            str(self.cols),
            "-y",
            str(self.rows),
        ]
        if working_dir:
            cmd.extend(["-c", str(working_dir)])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise TmuxError(f"Failed to create tmux session: {result.stderr}")
        self._started = True

        # Enable pipe-pane to capture all output to a log file
        if self.pipe_log_path:
            self.pipe_log_path.parent.mkdir(parents=True, exist_ok=True)
            # Use -o flag to open the pipe, append all output to the log file
            pipe_cmd = [
                "tmux",
                "pipe-pane",
                "-t",
                self.session_name,
                "-o",
                f"cat >> {self.pipe_log_path}",
            ]
            result = subprocess.run(pipe_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise TmuxError(f"Failed to enable pipe-pane: {result.stderr}")

    def send_keys(self, keys: str, *, enter: bool = True) -> None:
        """Send keystrokes to the tmux session.

        Args:
            keys: The key sequence to send. Can be literal text or tmux
                  key names like 'Escape', 'C-c', 'Enter'.
            enter: If True, append Enter after the keys.
        """
        if not self._started:
            raise TmuxError("Session not started")

        cmd = ["tmux", "send-keys", "-t", self.session_name, keys]
        if enter:
            cmd.append("Enter")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise TmuxError(f"send_keys failed: {result.stderr}")

    def send_raw(self, keys: str) -> None:
        """Send keys without appending Enter (alias for send_keys(enter=False))."""
        self.send_keys(keys, enter=False)

    def capture_pane(self) -> str:
        """Return the current visible content of the tmux pane."""
        if not self._started:
            raise TmuxError("Session not started")

        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self.session_name, "-p"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise TmuxError(f"capture_pane failed: {result.stderr}")
        return result.stdout

    def wait_for_text(
        self,
        pattern: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = POLL_INTERVAL,
        regex: bool = False,
    ) -> str:
        """Poll capture_pane until pattern appears or timeout.

        Args:
            pattern: Literal substring or regex to search for.
            timeout: Max seconds to wait.
            poll: Seconds between polls.
            regex: If True, treat pattern as a regex.

        Returns:
            The pane content that matched.

        Raises:
            TimeoutError: If pattern not found within timeout.
        """
        deadline = time.monotonic() + timeout
        compiled = re.compile(pattern) if regex else None

        while time.monotonic() < deadline:
            content = self.capture_pane()
            if regex:
                assert compiled is not None
                if compiled.search(content):
                    return content
            else:
                if pattern in content:
                    return content
            time.sleep(poll)

        # Final capture for error message
        content = self.capture_pane()
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for "
            f"{'regex ' if regex else ''}pattern: {pattern!r}\n"
            f"Last pane content:\n{content}"
        )

    def wait_for_stable(
        self,
        *,
        stable_seconds: float = 2.0,
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = POLL_INTERVAL,
    ) -> str:
        """Wait until pane content stops changing.

        Useful for waiting for Neovim to finish rendering after a command.

        Returns:
            The stable pane content.
        """
        deadline = time.monotonic() + timeout
        last_content = ""
        stable_since = time.monotonic()

        while time.monotonic() < deadline:
            content = self.capture_pane()
            if content != last_content:
                last_content = content
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_seconds:
                return content
            time.sleep(poll)

        return last_content

    def wait_for_absent(
        self,
        pattern: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        poll: float = POLL_INTERVAL,
        regex: bool = False,
    ) -> str:
        """Poll capture_pane until pattern is absent or timeout.

        Useful for verifying that an error message has cleared or that a
        previous state has been replaced.

        Args:
            pattern: Literal substring or regex to check for absence.
            timeout: Max seconds to wait.
            poll: Seconds between polls.
            regex: If True, treat pattern as a regex.

        Returns:
            The pane content where pattern was not found.

        Raises:
            TimeoutError: If pattern still present after timeout.
        """
        deadline = time.monotonic() + timeout
        compiled = re.compile(pattern) if regex else None

        while time.monotonic() < deadline:
            content = self.capture_pane()
            if regex:
                assert compiled is not None
                if not compiled.search(content):
                    return content
            else:
                if pattern not in content:
                    return content
            time.sleep(poll)

        content = self.capture_pane()
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for "
            f"{'regex ' if regex else ''}pattern to disappear: {pattern!r}\n"
            f"Last pane content:\n{content}"
        )

    def kill(self) -> None:
        """Kill the tmux session and all processes within it.

        This ensures no orphaned nvim or remora-lsp processes are left running
        after the test completes or fails.
        """
        if self._started:
            # Disable pipe-pane to flush all output before killing
            if self.pipe_log_path:
                subprocess.run(
                    ["tmux", "pipe-pane", "-t", self.session_name],
                    capture_output=True,
                    text=True,
                )
                time.sleep(0.1)  # Brief pause to ensure flush completes

            # First, send SIGTERM to all processes in the session by killing the pane
            # This is more thorough than just killing the session
            subprocess.run(
                ["tmux", "send-keys", "-t", self.session_name, "C-c"],
                capture_output=True,
                text=True,
            )
            time.sleep(0.1)

            # Kill the session (this sends SIGHUP to all processes)
            subprocess.run(
                ["tmux", "kill-session", "-t", self.session_name],
                capture_output=True,
                text=True,
            )
            self._started = False

            # Verify session is gone
            result = subprocess.run(
                ["tmux", "has-session", "-t", self.session_name],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                # Session still exists, force kill
                subprocess.run(
                    ["tmux", "kill-session", "-t", self.session_name],
                    capture_output=True,
                    text=True,
                )

    def __enter__(self) -> TmuxDriver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.kill()


# ---------------------------------------------------------------------------
# AsciinemaRecorder
# ---------------------------------------------------------------------------


@dataclass
class AsciinemaRecorder:
    """Records a tmux session to asciicast v2 format (.cast).

    Instead of running ``asciinema rec`` (which needs a real PTY), this
    recorder polls ``tmux capture-pane`` in a background thread and writes
    screen snapshots as asciicast v2 JSONL.  The resulting ``.cast`` file
    can be rendered to GIF with ``agg``.

    Each captured frame is written as a full-screen redraw (cursor-home +
    erase-screen + content).  This produces a slightly larger file than a
    true terminal recording but is 100 % reliable in headless / CI
    environments.
    """

    output_path: Path = field(default_factory=lambda: OUTPUT_DIR / "recording.cast")
    cols: int = DEFAULT_COLS
    rows: int = DEFAULT_ROWS
    poll_interval: float = 0.25  # seconds between captures
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _tmux_session: str = field(default="", init=False, repr=False)
    _started: bool = field(default=False, init=False, repr=False)

    def start(self, tmux_session: str) -> None:
        """Begin recording *tmux_session* in a background thread."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        if self.output_path.exists():
            self.output_path.unlink()
        self._tmux_session = tmux_session
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._record_loop, daemon=True)
        self._started = True
        self._thread.start()

    # ---- internal -------------------------------------------------------

    def _capture(self) -> str:
        """Grab the current pane content via tmux (with ANSI escapes)."""
        result = subprocess.run(
            ["tmux", "capture-pane", "-t", self._tmux_session, "-p", "-e"],
            capture_output=True,
            text=True,
        )
        return result.stdout if result.returncode == 0 else ""

    def _record_loop(self) -> None:
        """Background thread: poll capture-pane and write .cast frames."""
        start = time.monotonic()
        last_content = ""

        with open(self.output_path, "w") as fh:
            # asciicast v2 header
            header = {
                "version": 2,
                "width": self.cols,
                "height": self.rows,
                "timestamp": int(time.time()),
                "env": {"TERM": "xterm-256color", "SHELL": "/bin/bash"},
            }
            fh.write(json.dumps(header) + "\n")

            while not self._stop_event.is_set():
                content = self._capture()
                if content and content != last_content:
                    elapsed = time.monotonic() - start
                    # Convert \n to \r\n so each line starts at column 0
                    # in the terminal emulator, then prepend a full-screen
                    # reset (home cursor + erase screen).
                    lines = content.replace("\r\n", "\n").replace("\n", "\r\n")
                    frame = f"\x1b[H\x1b[2J{lines}"
                    fh.write(json.dumps([round(elapsed, 4), "o", frame]) + "\n")
                    fh.flush()
                    last_content = content
                self._stop_event.wait(timeout=self.poll_interval)

    # ---- public API -----------------------------------------------------

    def stop(self) -> Path:
        """Stop recording and return path to the ``.cast`` file."""
        if not self._started:
            raise RuntimeError("Recorder not started")

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._started = False

        if not self.output_path.exists():
            raise RuntimeError(f"Recording file not created: {self.output_path}")
        return self.output_path


# ---------------------------------------------------------------------------
# GIF conversion
# ---------------------------------------------------------------------------


def cast_to_gif(
    cast_path: Path,
    gif_path: Path | None = None,
    *,
    speed: float = 1.0,
    font_size: int = 14,
) -> Path:
    """Convert a .cast file to .gif using agg.

    Args:
        cast_path: Path to the .cast file.
        gif_path: Output .gif path. Defaults to same name with .gif extension.
        speed: Playback speed multiplier.
        font_size: Font size for the GIF.

    Returns:
        Path to the generated .gif file.
    """
    if gif_path is None:
        gif_path = cast_path.with_suffix(".gif")

    agg_bin = shutil.which("agg")
    if agg_bin is None:
        raise RuntimeError(
            "agg not found in PATH. Add asciinema-agg to devenv.nix or "
            "install via: nix-build '<nixpkgs>' -A asciinema-agg"
        )

    cmd = [
        agg_bin,
        str(cast_path),
        str(gif_path),
        "--speed",
        str(speed),
        "--font-size",
        str(font_size),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"agg conversion failed: {result.stderr}")

    return gif_path


# ---------------------------------------------------------------------------
# Scenario protocol
# ---------------------------------------------------------------------------


class Scenario(Protocol):
    """Protocol for E2E demo scenarios."""

    @property
    def name(self) -> str:
        """Short identifier for the scenario (used in filenames)."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description."""
        ...

    def run(self, driver: TmuxDriver) -> None:
        """Execute the scenario by sending keys and asserting state."""
        ...


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Result of running a single scenario."""

    scenario_name: str
    success: bool
    cast_path: Path | None = None
    gif_path: Path | None = None
    log_path: Path | None = None  # Path to tmux output log
    error: str | None = None
    duration: float = 0.0


def _copy_recent_lsp_logs(*, start_wallclock: float) -> list[Path]:
    """Copy recent client/server logs from demo workspace into the real log dir."""
    demo_logs_dir = DEMO_PROJECT / ".remora" / "logs"
    if not demo_logs_dir.exists():
        return []

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for log_file in sorted(demo_logs_dir.glob("*.log"), key=lambda p: p.stat().st_mtime):
        name = log_file.name
        if not (name.startswith("server-") or name.startswith("client-")):
            continue
        if log_file.stat().st_mtime < start_wallclock:
            continue
        dest_path = LOG_DIR / name
        try:
            shutil.copy2(log_file, dest_path)
            copied.append(dest_path)
        except Exception:
            # Don't fail scenario execution if debug-log copy fails.
            continue
    return copied


def _select_primary_lsp_log(copied_logs: list[Path]) -> Path | None:
    """Choose the most useful copied LSP log to display in result output."""
    if not copied_logs:
        return None
    server_logs = [path for path in copied_logs if path.name.startswith("server-")]
    if server_logs:
        return server_logs[-1]
    return copied_logs[-1]


def run_scenario(
    scenario: Scenario,
    *,
    record: bool = True,
    gif: bool = False,
    working_dir: str | Path | None = None,
) -> ScenarioResult:
    """Run a single scenario with optional recording and GIF conversion.

    Args:
        scenario: The scenario to run.
        record: Whether to record with asciinema.
        gif: Whether to convert recording to GIF.
        working_dir: Working directory for the tmux session.
    """
    start_time = time.monotonic()
    start_wallclock = time.time()  # For comparing with file mtimes
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cast_path = OUTPUT_DIR / f"{scenario.name}_{stamp}.cast"
    tmux_log_path = LOG_DIR / f"e2e-{scenario.name}_{stamp}-tmux.log"
    driver = TmuxDriver(pipe_log_path=tmux_log_path)
    recorder = AsciinemaRecorder(output_path=cast_path) if record else None
    guard = DemoProjectGuard()
    guard.save()
    lsp_log_path = None

    try:
        driver.start(working_dir=working_dir)

        if recorder:
            recorder.start(driver.session_name)

        scenario.run(driver)

        if recorder:
            result_path = recorder.stop()
        else:
            result_path = None

        gif_path = None
        if gif and result_path:
            gif_path = cast_to_gif(result_path)

        # Copy recent LSP client/server logs from demo workspace to real log dir.
        copied_lsp_logs = _copy_recent_lsp_logs(start_wallclock=start_wallclock)
        lsp_log_path = _select_primary_lsp_log(copied_lsp_logs)

        return ScenarioResult(
            scenario_name=scenario.name,
            success=True,
            cast_path=result_path,
            gif_path=gif_path,
            log_path=lsp_log_path or tmux_log_path,  # Prefer LSP log, fall back to tmux
            duration=time.monotonic() - start_time,
        )

    except Exception as e:
        # Try to stop recorder if running
        if recorder and recorder._started:
            try:
                recorder.stop()
            except Exception:
                pass

        # Copy recent LSP client/server logs even on failure.
        copied_lsp_logs = _copy_recent_lsp_logs(start_wallclock=start_wallclock)
        lsp_log_path = _select_primary_lsp_log(copied_lsp_logs)

        return ScenarioResult(
            scenario_name=scenario.name,
            success=False,
            log_path=lsp_log_path or tmux_log_path,  # Prefer LSP log, fall back to tmux
            error=str(e),
            duration=time.monotonic() - start_time,
        )

    finally:
        driver.kill()
        # Always restore demo project files to their original state
        guard.restore()
