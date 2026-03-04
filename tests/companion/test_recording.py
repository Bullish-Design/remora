"""Unit tests for AsciicastWriter and AsciicastRecording.

Tests the asciicast v2 format correctness, frame management,
file output, and GIF conversion (with mocked agg binary).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from remora_demo.companion.demo.recording import (
    AsciicastFrame,
    AsciicastRecording,
    AsciicastWriter,
)


# ---------------------------------------------------------------------------
# AsciicastRecording dataclass tests
# ---------------------------------------------------------------------------


class TestAsciicastRecording:
    def test_default_dimensions(self):
        rec = AsciicastRecording()
        assert rec.cols == 100
        assert rec.rows == 56

    def test_default_title(self):
        rec = AsciicastRecording()
        assert rec.title == "Companion Demo"

    def test_empty_duration(self):
        rec = AsciicastRecording()
        assert rec.duration == 0.0

    def test_duration_from_frames(self):
        rec = AsciicastRecording(
            frames=[
                AsciicastFrame(timestamp=0.0, data="first"),
                AsciicastFrame(timestamp=2.5, data="second"),
                AsciicastFrame(timestamp=5.0, data="third"),
            ]
        )
        assert rec.duration == 5.0

    def test_custom_env(self):
        rec = AsciicastRecording()
        assert "TERM" in rec.env
        assert rec.env["TERM"] == "xterm-256color"


# ---------------------------------------------------------------------------
# AsciicastWriter — frame management
# ---------------------------------------------------------------------------


class TestAsciicastWriterFrames:
    def test_initial_frame_count(self):
        writer = AsciicastWriter()
        assert writer.frame_count == 0

    def test_write_frame_increments_count(self):
        writer = AsciicastWriter()
        writer.write_frame("content", duration=1.0)
        assert writer.frame_count == 1

    def test_write_multiple_frames(self):
        writer = AsciicastWriter()
        writer.write_frame("frame1", duration=1.0)
        writer.write_frame("frame2", duration=2.0)
        writer.write_frame("frame3", duration=1.5)
        assert writer.frame_count == 3

    def test_frame_timestamps_advance(self):
        writer = AsciicastWriter()
        writer.write_frame("frame1", duration=1.0)
        writer.write_frame("frame2", duration=2.0)
        writer.write_frame("frame3", duration=1.5)

        frames = writer.recording.frames
        assert frames[0].timestamp == 0.0
        assert frames[1].timestamp == pytest.approx(1.0)
        assert frames[2].timestamp == pytest.approx(3.0)

    def test_recording_duration(self):
        writer = AsciicastWriter()
        writer.write_frame("frame1", duration=1.0)
        writer.write_frame("frame2", duration=2.0)
        # Duration is last frame's timestamp (when it starts), not total
        assert writer.recording.duration == pytest.approx(1.0)

    def test_frame_data_includes_control_sequences(self):
        writer = AsciicastWriter()
        writer.write_frame("hello world", duration=1.0)
        frame = writer.recording.frames[0]
        # Should include hide-cursor and home-cursor sequences
        assert AsciicastWriter.HIDE_CURSOR in frame.data
        assert AsciicastWriter.HOME in frame.data
        assert "hello world" in frame.data

    def test_write_header_frame(self):
        writer = AsciicastWriter()
        writer.write_header_frame("Welcome to Companion", duration=2.0)
        assert writer.frame_count == 1
        frame = writer.recording.frames[0]
        assert "Welcome to Companion" in frame.data
        assert AsciicastWriter.CLEAR in frame.data

    def test_write_header_frame_advances_clock(self):
        writer = AsciicastWriter()
        writer.write_header_frame("Title", duration=2.0)
        writer.write_frame("content", duration=1.0)
        assert writer.recording.frames[1].timestamp == pytest.approx(2.0)

    def test_write_transition(self):
        writer = AsciicastWriter()
        writer.write_transition("from_frame", "to_frame", steps=3, step_duration=0.08)
        assert writer.frame_count == 1
        # Clock should advance by steps * step_duration
        writer.write_frame("after", duration=1.0)
        assert writer.recording.frames[1].timestamp == pytest.approx(0.24)

    def test_write_finale(self):
        writer = AsciicastWriter()
        writer.write_frame("last_content", duration=1.0)
        writer.write_finale(duration=3.0)
        assert writer.frame_count == 2
        finale = writer.recording.frames[1]
        assert AsciicastWriter.SHOW_CURSOR in finale.data

    def test_write_finale_advances_clock(self):
        writer = AsciicastWriter()
        writer.write_frame("content", duration=1.0)
        writer.write_finale(duration=3.0)
        # Finale starts at 1.0, duration 3.0 → clock at 4.0
        assert writer.recording.duration == pytest.approx(1.0)

    def test_custom_dimensions(self):
        writer = AsciicastWriter(cols=120, rows=40, title="Custom")
        assert writer.recording.cols == 120
        assert writer.recording.rows == 40
        assert writer.recording.title == "Custom"


# ---------------------------------------------------------------------------
# AsciicastWriter — save (file output)
# ---------------------------------------------------------------------------


class TestAsciicastWriterSave:
    def test_save_creates_file(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("test content", duration=1.0)
        path = writer.save(tmp_path / "test.cast")
        assert path.exists()

    def test_save_returns_path(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("test", duration=1.0)
        result = writer.save(tmp_path / "test.cast")
        assert isinstance(result, Path)
        assert result == tmp_path / "test.cast"

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("test", duration=1.0)
        nested = tmp_path / "a" / "b" / "c" / "test.cast"
        result = writer.save(nested)
        assert result.exists()

    def test_saved_file_has_header_line(self, tmp_path: Path):
        writer = AsciicastWriter(cols=100, rows=56, title="Test Recording")
        writer.write_frame("test", duration=1.0)
        path = writer.save(tmp_path / "test.cast")

        lines = path.read_text().splitlines()
        header = json.loads(lines[0])
        assert header["version"] == 2
        assert header["width"] == 100
        assert header["height"] == 56
        assert header["title"] == "Test Recording"
        assert "timestamp" in header
        assert isinstance(header["timestamp"], int)
        assert "env" in header

    def test_saved_file_has_event_lines(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("frame1", duration=1.0)
        writer.write_frame("frame2", duration=2.0)
        path = writer.save(tmp_path / "test.cast")

        lines = path.read_text().splitlines()
        # Line 0 is header, lines 1+ are events
        assert len(lines) == 3  # 1 header + 2 events

    def test_event_lines_are_json_arrays(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("content", duration=1.0)
        path = writer.save(tmp_path / "test.cast")

        lines = path.read_text().splitlines()
        event = json.loads(lines[1])
        assert isinstance(event, list)
        assert len(event) == 3

    def test_event_format_time_type_data(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("hello", duration=1.0)
        path = writer.save(tmp_path / "test.cast")

        lines = path.read_text().splitlines()
        event = json.loads(lines[1])
        time_val, event_type, data = event
        assert isinstance(time_val, (int, float))
        assert time_val == 0.0
        assert event_type == "o"
        assert isinstance(data, str)
        assert "hello" in data

    def test_event_timestamps_are_sequential(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("a", duration=1.0)
        writer.write_frame("b", duration=2.0)
        writer.write_frame("c", duration=0.5)
        path = writer.save(tmp_path / "test.cast")

        lines = path.read_text().splitlines()
        timestamps = [json.loads(line)[0] for line in lines[1:]]
        assert timestamps == [pytest.approx(0.0), pytest.approx(1.0), pytest.approx(3.0)]

    def test_save_with_string_path(self, tmp_path: Path):
        writer = AsciicastWriter()
        writer.write_frame("test", duration=1.0)
        path = writer.save(str(tmp_path / "string_path.cast"))
        assert Path(path).exists()


# ---------------------------------------------------------------------------
# AsciicastWriter — GIF conversion
# ---------------------------------------------------------------------------


class TestAsciicastWriterGif:
    def test_to_gif_raises_when_agg_not_found(self, tmp_path: Path):
        cast_file = tmp_path / "test.cast"
        cast_file.write_text("{}\n")  # minimal content
        gif_file = tmp_path / "test.gif"

        with patch("shutil.which", return_value=None):
            with pytest.raises(FileNotFoundError, match="agg not found"):
                AsciicastWriter.to_gif(cast_file, gif_file)

    def test_to_gif_calls_agg_with_correct_args(self, tmp_path: Path):
        cast_file = tmp_path / "test.cast"
        cast_file.write_text("{}\n")
        gif_file = tmp_path / "test.gif"

        with (
            patch("shutil.which", return_value="/usr/bin/agg"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stderr = ""
            AsciicastWriter.to_gif(
                cast_file,
                gif_file,
                theme="dracula",
                font_size=14,
                fps_cap=30,
            )

            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "/usr/bin/agg"
            assert "--theme" in cmd
            assert "dracula" in cmd
            assert "--font-size" in cmd
            assert "14" in cmd
            assert str(cast_file) in cmd
            assert str(gif_file) in cmd

    def test_to_gif_creates_parent_dirs(self, tmp_path: Path):
        cast_file = tmp_path / "test.cast"
        cast_file.write_text("{}\n")
        gif_file = tmp_path / "nested" / "dir" / "test.gif"

        with (
            patch("shutil.which", return_value="/usr/bin/agg"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stderr = ""
            AsciicastWriter.to_gif(cast_file, gif_file)
            # Parent dirs should have been created
            assert gif_file.parent.exists()

    def test_to_gif_returns_path(self, tmp_path: Path):
        cast_file = tmp_path / "test.cast"
        cast_file.write_text("{}\n")
        gif_file = tmp_path / "test.gif"

        with (
            patch("shutil.which", return_value="/usr/bin/agg"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stderr = ""
            result = AsciicastWriter.to_gif(cast_file, gif_file)
            assert result == gif_file

    def test_cast_to_gif_auto_names_output(self, tmp_path: Path):
        cast_file = tmp_path / "recording.cast"
        cast_file.write_text("{}\n")

        with (
            patch("shutil.which", return_value="/usr/bin/agg"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stderr = ""
            result = AsciicastWriter.cast_to_gif(cast_file)
            assert result == tmp_path / "recording.gif"

    def test_cast_to_gif_with_explicit_output(self, tmp_path: Path):
        cast_file = tmp_path / "input.cast"
        cast_file.write_text("{}\n")
        gif_file = tmp_path / "custom_name.gif"

        with (
            patch("shutil.which", return_value="/usr/bin/agg"),
            patch("subprocess.run") as mock_run,
        ):
            mock_run.return_value.stderr = ""
            result = AsciicastWriter.cast_to_gif(cast_file, gif_file)
            assert result == gif_file


# ---------------------------------------------------------------------------
# Integration: write → save → parse back
# ---------------------------------------------------------------------------


class TestAsciicastRoundTrip:
    def test_full_recording_round_trip(self, tmp_path: Path):
        """Write a multi-frame recording, save it, parse it back."""
        writer = AsciicastWriter(cols=80, rows=24, title="Round Trip Test")
        writer.write_header_frame("Welcome", duration=2.0)
        writer.write_frame("Frame 1 content", duration=3.0)
        writer.write_frame("Frame 2 content", duration=2.0)
        writer.write_transition("from", "to", steps=2, step_duration=0.1)
        writer.write_finale(duration=1.0)

        path = writer.save(tmp_path / "roundtrip.cast")
        content = path.read_text()
        lines = content.splitlines()

        # Header
        header = json.loads(lines[0])
        assert header["version"] == 2
        assert header["width"] == 80
        assert header["height"] == 24

        # Events: header_frame + frame1 + frame2 + transition + finale = 5
        assert len(lines) == 6  # 1 header + 5 events

        # All event lines must be valid JSON arrays
        for line in lines[1:]:
            event = json.loads(line)
            assert isinstance(event, list)
            assert len(event) == 3
            assert isinstance(event[0], (int, float))
            assert event[1] == "o"
            assert isinstance(event[2], str)

        # Timestamps should be monotonically non-decreasing
        timestamps = [json.loads(line)[0] for line in lines[1:]]
        for i in range(1, len(timestamps)):
            assert timestamps[i] >= timestamps[i - 1]
