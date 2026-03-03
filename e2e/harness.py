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
import tempfile
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


# ---------------------------------------------------------------------------
# DemoProjectGuard — snapshot and restore mutable demo files
# ---------------------------------------------------------------------------


class DemoProjectGuard:
    """Saves and restores demo project files that scenarios may modify.

    Used as a context manager around scenario execution to guarantee the
    demo project is always left in its original state — even if a scenario
    fails or the process is interrupted.
    """

    def __init__(self, files: list[Path] | None = None) -> None:
        self._files = files or _DEMO_MUTABLE_FILES
        self._snapshots: dict[Path, bytes] = {}

    def save(self) -> None:
        """Read and store the current content of each mutable file."""
        for fpath in self._files:
            if fpath.exists():
                self._snapshots[fpath] = fpath.read_bytes()

    def restore(self) -> None:
        """Write back the saved content, restoring files to their original state."""
        for fpath, content in self._snapshots.items():
            fpath.write_bytes(content)

    def __enter__(self) -> DemoProjectGuard:
        self.save()
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

    def kill(self) -> None:
        """Kill the tmux session."""
        if self._started:
            subprocess.run(
                ["tmux", "kill-session", "-t", self.session_name],
                capture_output=True,
                text=True,
            )
            self._started = False

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
    error: str | None = None
    duration: float = 0.0


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
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    cast_path = OUTPUT_DIR / f"{scenario.name}_{stamp}.cast"
    driver = TmuxDriver()
    recorder = AsciinemaRecorder(output_path=cast_path) if record else None
    guard = DemoProjectGuard()
    guard.save()

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

        return ScenarioResult(
            scenario_name=scenario.name,
            success=True,
            cast_path=result_path,
            gif_path=gif_path,
            duration=time.monotonic() - start_time,
        )

    except Exception as e:
        # Try to stop recorder if running
        if recorder and recorder._started:
            try:
                recorder.stop()
            except Exception:
                pass

        return ScenarioResult(
            scenario_name=scenario.name,
            success=False,
            error=str(e),
            duration=time.monotonic() - start_time,
        )

    finally:
        driver.kill()
        # Always restore demo project files to their original state
        guard.restore()
