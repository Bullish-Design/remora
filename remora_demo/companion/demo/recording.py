"""Asciicast v2 writer and GIF converter for Companion demo recordings.

Writes asciicast v2 format (https://docs.asciinema.org/manual/asciicast/v2/)
directly from renderer frames, then converts to GIF using `agg`.

Asciicast v2 format:
  - Line 1: JSON header (version, width, height, timestamp, ...)
  - Lines 2+: JSON arrays [time, event_type, data]
    - time: float seconds since recording start
    - event_type: "o" for stdout output
    - data: string written to terminal

Usage:
    writer = AsciicastWriter(cols=100, rows=56)
    writer.write_frame(ansi_frame_string, duration=3.0)
    writer.write_frame(next_frame_string, duration=2.5)
    writer.save("recording.cast")
    writer.to_gif("recording.cast", "output.gif")
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class AsciicastFrame:
    """A single frame in an asciicast recording."""

    timestamp: float  # Seconds since recording start
    data: str  # ANSI content written to terminal


@dataclass
class AsciicastRecording:
    """An in-memory asciicast v2 recording."""

    cols: int = 100
    rows: int = 56
    title: str = "Companion Demo"
    frames: list[AsciicastFrame] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=lambda: {"SHELL": "/bin/bash", "TERM": "xterm-256color"})

    @property
    def duration(self) -> float:
        """Total duration of the recording in seconds."""
        if not self.frames:
            return 0.0
        return self.frames[-1].timestamp


class AsciicastWriter:
    """Builds an asciicast v2 recording from renderer frames.

    Each call to write_frame() appends output events that:
    1. Clear the screen
    2. Move cursor to home
    3. Write the full ANSI frame
    4. Advance the clock by the given duration

    This produces a recording where each "frame" is a full repaint,
    just like a real terminal session running the demo.
    """

    # Terminal control sequences for frame transitions
    CLEAR = "\033[2J"
    HOME = "\033[H"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"

    def __init__(
        self,
        cols: int = 100,
        rows: int = 56,
        title: str = "Companion Demo",
    ) -> None:
        self._recording = AsciicastRecording(
            cols=cols,
            rows=rows,
            title=title,
        )
        self._clock: float = 0.0

    @property
    def recording(self) -> AsciicastRecording:
        return self._recording

    @property
    def frame_count(self) -> int:
        return len(self._recording.frames)

    def write_header_frame(self, text: str, duration: float = 2.0) -> None:
        """Write a title/header frame (centered text on blank screen)."""
        data = self.HIDE_CURSOR + self.CLEAR + self.HOME + text
        self._recording.frames.append(AsciicastFrame(timestamp=self._clock, data=data))
        self._clock += duration

    def write_frame(self, ansi_content: str, duration: float = 3.0) -> None:
        """Write a full-screen frame from the renderer.

        Args:
            ansi_content: Full ANSI frame string (from TerminalRenderer.render())
            duration: How long to display this frame, in seconds.
        """
        # Build the terminal output: hide cursor, clear, home, draw frame
        data = self.HIDE_CURSOR + self.HOME + ansi_content
        self._recording.frames.append(AsciicastFrame(timestamp=self._clock, data=data))
        self._clock += duration

    def write_transition(
        self,
        from_frame: str,
        to_frame: str,
        steps: int = 3,
        step_duration: float = 0.08,
    ) -> None:
        """Write a brief transition between two frames.

        Currently just does a quick flash — the 'from' frame stays briefly,
        then the 'to' frame appears. Can be extended with fancier transitions.
        """
        # Brief pause on the departing frame
        self._recording.frames.append(
            AsciicastFrame(
                timestamp=self._clock,
                data=self.HOME + from_frame,
            )
        )
        self._clock += step_duration * steps

    def write_finale(self, duration: float = 3.0) -> None:
        """Write a final frame showing the cursor again."""
        self._recording.frames.append(
            AsciicastFrame(
                timestamp=self._clock,
                data=self.SHOW_CURSOR,
            )
        )
        self._clock += duration

    def save(self, path: str | Path) -> Path:
        """Save the recording as an asciicast v2 file (.cast).

        Returns the path written to.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with path.open("w", encoding="utf-8") as f:
            # Header line
            header = {
                "version": 2,
                "width": self._recording.cols,
                "height": self._recording.rows,
                "timestamp": int(time.time()),
                "title": self._recording.title,
                "env": self._recording.env,
            }
            f.write(json.dumps(header) + "\n")

            # Event lines
            for frame in self._recording.frames:
                event = [frame.timestamp, "o", frame.data]
                f.write(json.dumps(event) + "\n")

        logger.info(
            "Saved asciicast: %s (%d frames, %.1fs)",
            path,
            len(self._recording.frames),
            self._recording.duration,
        )
        return path

    @staticmethod
    def to_gif(
        cast_path: str | Path,
        gif_path: str | Path,
        *,
        theme: str = "dracula",
        font_size: int = 14,
        fps_cap: int = 30,
        idle_time_limit: float = 3.0,
        speed: float = 1.0,
        last_frame_duration: float = 5.0,
    ) -> Path:
        """Convert an asciicast file to GIF using agg.

        Requires `agg` to be installed (available in devenv).

        Args:
            cast_path: Path to the .cast file.
            gif_path: Output .gif path.
            theme: Color theme (dracula, monokai, nord, etc.)
            font_size: Font size in pixels.
            fps_cap: Maximum FPS.
            idle_time_limit: Max seconds of idle to keep.
            speed: Playback speed multiplier.
            last_frame_duration: How long to hold the last frame.

        Returns:
            Path to the generated GIF.

        Raises:
            FileNotFoundError: If agg is not installed.
            subprocess.CalledProcessError: If agg fails.
        """
        cast_path = Path(cast_path)
        gif_path = Path(gif_path)
        gif_path.parent.mkdir(parents=True, exist_ok=True)

        agg_bin = shutil.which("agg")
        if agg_bin is None:
            raise FileNotFoundError("agg not found. Install it via your package manager or nix.")

        cmd = [
            agg_bin,
            "--theme",
            theme,
            "--font-size",
            str(font_size),
            "--fps-cap",
            str(fps_cap),
            "--idle-time-limit",
            str(idle_time_limit),
            "--speed",
            str(speed),
            "--last-frame-duration",
            str(last_frame_duration),
            str(cast_path),
            str(gif_path),
        ]

        logger.info("Running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        if result.stderr:
            logger.debug("agg stderr: %s", result.stderr)

        logger.info("Generated GIF: %s", gif_path)
        return gif_path

    @staticmethod
    def cast_to_gif(
        cast_path: str | Path,
        gif_path: str | Path | None = None,
        **kwargs,
    ) -> Path:
        """Convenience: convert .cast to .gif, auto-naming if needed."""
        cast_path = Path(cast_path)
        if gif_path is None:
            gif_path = cast_path.with_suffix(".gif")
        return AsciicastWriter.to_gif(cast_path, gif_path, **kwargs)
