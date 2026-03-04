"""Unit tests for TerminalRenderer.

Tests the plain-text output mode (no ANSI), editor line preparation,
sidebar markdown styling, layout dimensions, and helper functions.
"""

from __future__ import annotations

import re

import pytest

from remora_demo.companion.demo.renderer import (
    RenderConfig,
    TerminalRenderer,
    _find_comment,
    _has_ansi,
    _visible_len,
)


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestFindComment:
    def test_simple_comment(self):
        assert _find_comment("x = 1  # comment") == 7

    def test_no_comment(self):
        assert _find_comment("x = 1") is None

    def test_hash_inside_string(self):
        assert _find_comment('x = "# not a comment"') is None

    def test_hash_after_string(self):
        assert _find_comment('x = "val"  # comment') is 11

    def test_empty_line(self):
        assert _find_comment("") is None

    def test_line_starting_with_comment(self):
        assert _find_comment("# whole line comment") == 0


class TestHasAnsi:
    def test_plain_text(self):
        assert _has_ansi("hello world") is False

    def test_ansi_text(self):
        assert _has_ansi("\033[1mhello\033[0m") is True

    def test_empty(self):
        assert _has_ansi("") is False


class TestVisibleLen:
    def test_plain_text(self):
        assert _visible_len("hello") == 5

    def test_ansi_text(self):
        assert _visible_len("\033[1mhello\033[0m") == 5

    def test_empty(self):
        assert _visible_len("") == 0

    def test_multiple_ansi_codes(self):
        assert _visible_len("\033[38;5;111m\033[1mhi\033[0m") == 2


# ---------------------------------------------------------------------------
# RenderConfig tests
# ---------------------------------------------------------------------------


class TestRenderConfig:
    def test_default_dimensions(self):
        cfg = RenderConfig()
        assert cfg.total_width == 100
        assert cfg.total_height == 56

    def test_editor_sidebar_widths_sum_to_total(self):
        cfg = RenderConfig()
        assert cfg.editor_width + cfg.sidebar_width + cfg.border_width == cfg.total_width

    def test_content_height(self):
        cfg = RenderConfig()
        assert cfg.content_height == cfg.total_height - cfg.header_height - cfg.status_height

    def test_editor_text_width(self):
        cfg = RenderConfig()
        # editor_text_width = editor_width - line_number_width - 1 (padding)
        assert cfg.editor_text_width == cfg.editor_width - cfg.line_number_width - 1

    def test_custom_dimensions(self):
        cfg = RenderConfig(total_width=120, total_height=40)
        assert cfg.total_width == 120
        assert cfg.total_height == 40
        assert cfg.editor_width + cfg.sidebar_width + cfg.border_width == 120


# ---------------------------------------------------------------------------
# Plain-text rendering tests
# ---------------------------------------------------------------------------


class TestRendererPlainOutput:
    """Tests for _render_plain — the ANSI-free output mode."""

    def test_empty_state_produces_correct_dimensions(self, renderer: TerminalRenderer):
        output = renderer._render_plain()
        lines = output.split("\n")
        # header + content_height + separator + 2 status lines + bottom border
        expected_lines = 1 + renderer.config.content_height + 1 + 2 + 1
        assert len(lines) == expected_lines

    def test_all_lines_same_width(self, renderer: TerminalRenderer):
        """Every line should be exactly total_width characters."""
        output = renderer._render_plain()
        for i, line in enumerate(output.split("\n")):
            assert len(line) == renderer.config.total_width, (
                f"Line {i} has width {len(line)}, expected {renderer.config.total_width}: {line!r}"
            )

    def test_header_contains_filename(self, renderer: TerminalRenderer):
        renderer.editor.file_path = "src/processor.py"
        output = renderer._render_plain()
        header = output.split("\n")[0]
        assert "processor.py" in header

    def test_header_contains_companion(self, renderer: TerminalRenderer):
        output = renderer._render_plain()
        header = output.split("\n")[0]
        assert "Companion" in header

    def test_editor_lines_show_content(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.file_path = "processor.py"
        renderer.editor.cursor_line = 5
        output = renderer._render_plain()
        lines = output.split("\n")

        # Content lines start at index 1 (after header)
        # Line 5 should show the cursor arrow
        found_arrow = False
        for line in lines[1:]:
            if "\u25b8" in line and "5" in line:
                found_arrow = True
                break
        assert found_arrow, "Cursor arrow not found on line 5"

    def test_sidebar_shows_markdown_when_set(
        self,
        renderer: TerminalRenderer,
        sample_sidebar_markdown: str,
    ):
        renderer.sidebar.markdown = sample_sidebar_markdown
        output = renderer._render_plain()
        # The sidebar should contain some of the markdown text
        assert "Companion Context" in output
        assert "Related Content" in output

    def test_sidebar_shows_waiting_when_empty(self, renderer: TerminalRenderer):
        renderer.sidebar.markdown = ""
        output = renderer._render_plain()
        assert "Waiting for cursor" in output

    def test_status_shows_agents(self, renderer: TerminalRenderer):
        renderer.status.agents_active = ["context_extractor", "sidebar_composer"]
        output = renderer._render_plain()
        assert "context_extractor" in output
        assert "sidebar_composer" in output

    def test_status_shows_chunk_count(self, renderer: TerminalRenderer):
        renderer.status.chunks_indexed = 42
        output = renderer._render_plain()
        assert "42 chunks" in output

    def test_status_no_agents(self, renderer: TerminalRenderer):
        renderer.status.agents_active = []
        output = renderer._render_plain()
        assert "No agents active" in output

    def test_box_drawing_chars_present(self, renderer: TerminalRenderer):
        output = renderer._render_plain()
        # Should have box-drawing corners and edges
        assert "\u250c" in output  # top-left
        assert "\u2510" in output  # top-right
        assert "\u2514" in output  # bottom-left
        assert "\u2518" in output  # bottom-right
        assert "\u2502" in output  # vertical
        assert "\u252c" in output  # T-junction top


# ---------------------------------------------------------------------------
# Editor line preparation tests
# ---------------------------------------------------------------------------


class TestEditorLinePreparation:
    def test_plain_editor_lines_count(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
    ):
        renderer.editor.lines = sample_editor_content
        lines = renderer._prepare_editor_lines_plain()
        assert len(lines) == renderer.config.content_height

    def test_empty_editor_fills_with_tildes(self, renderer: TerminalRenderer):
        renderer.editor.lines = []
        lines = renderer._prepare_editor_lines_plain()
        assert len(lines) == renderer.config.content_height
        # Every line should have a tilde
        for line in lines:
            assert "~" in line

    def test_scroll_offset_skips_lines(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.scroll_offset = 5
        lines = renderer._prepare_editor_lines_plain()
        # First visible line should be line 6 (0-indexed 5)
        assert "6" in lines[0]

    def test_cursor_line_has_arrow(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.cursor_line = 8
        lines = renderer._prepare_editor_lines_plain()
        # Line 8 should have the arrow
        line_8 = lines[7]  # 0-indexed
        assert "\u25b8" in line_8

    def test_non_cursor_lines_have_space(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.cursor_line = 8
        lines = renderer._prepare_editor_lines_plain()
        # Line 1 should NOT have the arrow
        assert "\u25b8" not in lines[0]


# ---------------------------------------------------------------------------
# Sidebar line preparation tests
# ---------------------------------------------------------------------------


class TestSidebarLinePreparation:
    def test_plain_sidebar_lines_count(
        self,
        renderer: TerminalRenderer,
        sample_sidebar_markdown: str,
    ):
        renderer.sidebar.markdown = sample_sidebar_markdown
        lines = renderer._prepare_sidebar_lines_plain()
        assert len(lines) == renderer.config.content_height

    def test_sidebar_lines_end_with_pipe(
        self,
        renderer: TerminalRenderer,
        sample_sidebar_markdown: str,
    ):
        """Sidebar lines end with │ (left │ is the pane divider, added by caller)."""
        renderer.sidebar.markdown = sample_sidebar_markdown
        lines = renderer._prepare_sidebar_lines_plain()
        for line in lines:
            assert line.endswith("\u2502")
            # Left │ is NOT included — the caller adds it as the pane divider
            assert len(line) == renderer.config.sidebar_width

    def test_empty_sidebar(self, renderer: TerminalRenderer):
        renderer.sidebar.markdown = ""
        lines = renderer._prepare_sidebar_lines_plain()
        assert len(lines) == renderer.config.content_height
        # Should show waiting message
        found_waiting = any("Waiting" in line for line in lines)
        assert found_waiting


# ---------------------------------------------------------------------------
# ANSI render smoke test
# ---------------------------------------------------------------------------


class TestRendererAnsiOutput:
    """Smoke tests for the ANSI render path."""

    def test_render_returns_string(self, renderer: TerminalRenderer):
        result = renderer.render()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_render_contains_ansi_codes(self, renderer: TerminalRenderer):
        result = renderer.render()
        assert "\033[" in result

    def test_render_with_content(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
        sample_sidebar_markdown: str,
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.file_path = "processor.py"
        renderer.editor.cursor_line = 10
        renderer.sidebar.markdown = sample_sidebar_markdown
        renderer.status.agents_active = ["context_extractor"]
        renderer.status.chunks_indexed = 47
        result = renderer.render()
        # Should produce output without crashing
        assert len(result) > 100


# ---------------------------------------------------------------------------
# render_to_file test
# ---------------------------------------------------------------------------


class TestRenderToFile:
    def test_render_to_file(
        self,
        renderer: TerminalRenderer,
        sample_editor_content: list[str],
        tmp_path,
    ):
        renderer.editor.lines = sample_editor_content
        renderer.editor.file_path = "test.py"
        renderer.editor.cursor_line = 3
        out_file = tmp_path / "frame.txt"
        renderer.render_to_file(str(out_file))
        assert out_file.exists()
        content = out_file.read_text()
        assert "test.py" in content
        assert len(content.split("\n")) > 10
