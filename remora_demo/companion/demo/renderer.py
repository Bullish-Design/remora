"""Terminal renderer for A4-sized demo display.

Renders a split-pane view in the terminal:
- Left pane: simulated editor with file content and cursor highlight
- Right pane: companion sidebar markdown
- Bottom bar: status and agent activation info

A4-sized: 80 columns x 60 rows (portrait aspect ratio), suitable for
documents, screenshots, and screen recordings.
"""

import os
import shutil
import sys
import textwrap
from dataclasses import dataclass, field


# ANSI escape codes
class Ansi:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    ITALIC = "\033[3m"
    UNDERLINE = "\033[4m"

    # Foreground colors (catppuccin-ish)
    FG_TEXT = "\033[38;5;253m"
    FG_SUBTEXT = "\033[38;5;249m"
    FG_DIM = "\033[38;5;243m"
    FG_GREEN = "\033[38;5;114m"
    FG_BLUE = "\033[38;5;111m"
    FG_YELLOW = "\033[38;5;222m"
    FG_RED = "\033[38;5;210m"
    FG_MAUVE = "\033[38;5;183m"
    FG_TEAL = "\033[38;5;116m"
    FG_PEACH = "\033[38;5;216m"
    FG_WHITE = "\033[38;5;255m"
    FG_LINE_NR = "\033[38;5;240m"

    # Background colors
    BG_SURFACE = "\033[48;5;236m"
    BG_EDITOR = "\033[48;5;235m"
    BG_SIDEBAR = "\033[48;5;234m"
    BG_CURSOR_LINE = "\033[48;5;238m"
    BG_STATUS = "\033[48;5;237m"
    BG_BORDER = "\033[48;5;239m"
    BG_HEADER = "\033[48;5;237m"

    # Cursor control
    CLEAR_SCREEN = "\033[2J"
    HOME = "\033[H"
    HIDE_CURSOR = "\033[?25l"
    SHOW_CURSOR = "\033[?25h"

    @staticmethod
    def move_to(row: int, col: int) -> str:
        return f"\033[{row};{col}H"


@dataclass
class RenderConfig:
    """Configuration for terminal rendering.

    Default is A4-ish portrait: 100 columns x 56 rows.
    Editor gets 55% width, sidebar gets 45%.
    """

    total_width: int = 100
    total_height: int = 56
    editor_width_pct: float = 0.55
    header_height: int = 1
    status_height: int = 2
    border_width: int = 1
    line_number_width: int = 4
    show_agent_bar: bool = True

    @property
    def editor_width(self) -> int:
        return int(self.total_width * self.editor_width_pct) - self.border_width

    @property
    def sidebar_width(self) -> int:
        return self.total_width - self.editor_width - self.border_width

    @property
    def content_height(self) -> int:
        return self.total_height - self.header_height - self.status_height

    @property
    def editor_text_width(self) -> int:
        return self.editor_width - self.line_number_width - 1  # 1 for padding


@dataclass
class EditorState:
    """State for the editor pane."""

    file_path: str = ""
    lines: list[str] = field(default_factory=list)
    cursor_line: int = 1
    cursor_col: int = 0
    scroll_offset: int = 0
    language: str = "python"


@dataclass
class SidebarState:
    """State for the sidebar pane."""

    markdown: str = ""


@dataclass
class StatusState:
    """State for the status bar."""

    message: str = ""
    agents_active: list[str] = field(default_factory=list)
    chunks_indexed: int = 0
    phase: str = ""


class TerminalRenderer:
    """Renders the A4-sized demo display to the terminal.

    Layout:
    ┌─── editor.py ──────────────────────┬─── Companion ────────────┐
    │  1 │ import asyncio                │ # Companion Context      │
    │  2 │ from pathlib import Path      │                          │
    │  3 │ ...                           │ > Tracking: editor.py:10 │
    │ >10│ def process_data(self):  ◀────│                          │
    │ 11 │     ...                       │ ## Related Content        │
    │    │                               │ - validators.py (85%)     │
    │    │                               │ ...                       │
    ├────────────────────────────────────┴──────────────────────────┤
    │ ● context_extractor → embedding_searcher → sidebar_composer  │
    │ Indexed 42 chunks | Phase: exploring                         │
    └──────────────────────────────────────────────────────────────┘
    """

    def __init__(self, config: RenderConfig | None = None) -> None:
        self.config = config or RenderConfig()
        self.editor = EditorState()
        self.sidebar = SidebarState()
        self.status = StatusState()
        self._buffer: list[str] = []

    def setup(self) -> None:
        """Set up the terminal for rendering."""
        # Try to resize terminal
        sys.stdout.write(Ansi.HIDE_CURSOR)
        sys.stdout.write(Ansi.CLEAR_SCREEN)
        sys.stdout.write(Ansi.HOME)
        sys.stdout.flush()

    def teardown(self) -> None:
        """Restore terminal state."""
        sys.stdout.write(Ansi.SHOW_CURSOR)
        sys.stdout.write(Ansi.RESET)
        sys.stdout.write(Ansi.CLEAR_SCREEN)
        sys.stdout.write(Ansi.HOME)
        sys.stdout.flush()

    def render(self) -> str:
        """Render the full frame and return as string."""
        self._buffer = []
        cfg = self.config

        # Header
        self._render_header()

        # Content rows: editor + sidebar
        editor_lines = self._prepare_editor_lines()
        sidebar_lines = self._prepare_sidebar_lines()

        for row in range(cfg.content_height):
            editor_line = editor_lines[row] if row < len(editor_lines) else ""
            sidebar_line = sidebar_lines[row] if row < len(sidebar_lines) else ""
            self._render_content_row(editor_line, sidebar_line, row)

        # Status bar
        self._render_status()

        return "\n".join(self._buffer)

    def render_to_terminal(self) -> None:
        """Render and display on terminal."""
        frame = self.render()
        sys.stdout.write(Ansi.HOME)
        sys.stdout.write(frame)
        sys.stdout.flush()

    def render_to_file(self, path: str) -> None:
        """Render to a file (without ANSI codes, for plain text capture)."""
        frame = self._render_plain()
        with open(path, "w") as f:
            f.write(frame)

    # ---- Header ----

    def _render_header(self) -> None:
        cfg = self.config

        # Editor header
        filename = self.editor.file_path.split("/")[-1] if self.editor.file_path else "untitled"
        editor_title = f" {filename} "
        editor_pad = cfg.editor_width - len(editor_title) - 2  # 2 for corner chars
        editor_header = (
            f"{Ansi.BG_HEADER}{Ansi.FG_MAUVE}{Ansi.BOLD}"
            f"\u250c\u2500{editor_title}\u2500{'─' * max(0, editor_pad)}"
            f"{Ansi.RESET}"
        )

        # Sidebar header
        sidebar_title = " Companion "
        sidebar_pad = cfg.sidebar_width - len(sidebar_title) - 2
        sidebar_header = (
            f"{Ansi.BG_HEADER}{Ansi.FG_TEAL}{Ansi.BOLD}"
            f"\u252c\u2500{sidebar_title}\u2500{'─' * max(0, sidebar_pad)}\u2510"
            f"{Ansi.RESET}"
        )

        self._buffer.append(editor_header + sidebar_header)

    # ---- Content ----

    def _prepare_editor_lines(self) -> list[str]:
        """Prepare editor lines with line numbers and syntax hints."""
        cfg = self.config
        lines = []
        visible_lines = cfg.content_height
        start = self.editor.scroll_offset
        end = start + visible_lines

        for i in range(start, min(end, len(self.editor.lines))):
            line_num = i + 1
            line_text = self.editor.lines[i]

            # Truncate to fit
            max_text_width = cfg.editor_text_width
            if len(line_text) > max_text_width:
                line_text = line_text[: max_text_width - 1] + "…"

            # Pad to width
            line_text = line_text.ljust(max_text_width)

            is_cursor_line = line_num == self.editor.cursor_line
            bg = Ansi.BG_CURSOR_LINE if is_cursor_line else Ansi.BG_EDITOR
            arrow = "▸" if is_cursor_line else " "
            nr_color = Ansi.FG_YELLOW if is_cursor_line else Ansi.FG_LINE_NR

            formatted = (
                f"{bg}{Ansi.FG_DIM}│{Ansi.RESET}"
                f"{bg}{nr_color}{arrow}{line_num:>3}{Ansi.RESET}"
                f"{bg}{Ansi.FG_DIM}│{Ansi.RESET}"
                f"{bg}{self._syntax_highlight(line_text, self.editor.language)}{Ansi.RESET}"
            )
            lines.append(formatted)

        # Fill remaining with empty lines
        while len(lines) < cfg.content_height:
            empty_text = " " * cfg.editor_text_width
            lines.append(
                f"{Ansi.BG_EDITOR}{Ansi.FG_DIM}│{Ansi.RESET}"
                f"{Ansi.BG_EDITOR}{Ansi.FG_LINE_NR} {'~':>3}{Ansi.RESET}"
                f"{Ansi.BG_EDITOR}{Ansi.FG_DIM}│{Ansi.RESET}"
                f"{Ansi.BG_EDITOR}{empty_text}{Ansi.RESET}"
            )

        return lines

    def _prepare_sidebar_lines(self) -> list[str]:
        """Prepare sidebar lines from markdown."""
        cfg = self.config
        max_width = cfg.sidebar_width - 2  # 2 for border chars
        lines = []

        if not self.sidebar.markdown:
            # Empty state
            lines.append(self._sidebar_line("", max_width))
            lines.append(self._sidebar_line("  Waiting for cursor...", max_width, Ansi.FG_DIM))
            return lines

        for raw_line in self.sidebar.markdown.split("\n"):
            styled = self._style_markdown_line(raw_line, max_width)
            lines.append(styled)

        # Fill remaining
        while len(lines) < cfg.content_height:
            lines.append(self._sidebar_line("", max_width))

        return lines[: cfg.content_height]

    def _sidebar_line(self, text: str, width: int, color: str = Ansi.FG_TEXT) -> str:
        """Create a single sidebar line."""
        # Strip ANSI for length calculation, then pad
        display_text = text[:width].ljust(width) if not _has_ansi(text) else text
        return (
            f"{Ansi.BG_SIDEBAR}{Ansi.FG_DIM}│{Ansi.RESET}"
            f"{Ansi.BG_SIDEBAR}{color}{display_text}{Ansi.RESET}"
            f"{Ansi.BG_SIDEBAR}{Ansi.FG_DIM}│{Ansi.RESET}"
        )

    def _style_markdown_line(self, line: str, width: int) -> str:
        """Style a markdown line for the sidebar."""
        stripped = line.rstrip()

        # Heading
        if stripped.startswith("# "):
            text = stripped[2:].strip()
            return self._sidebar_line_styled(text[:width], width, Ansi.FG_MAUVE, Ansi.BOLD)
        if stripped.startswith("## "):
            text = stripped[3:].strip()
            return self._sidebar_line_styled(text[:width], width, Ansi.FG_BLUE, Ansi.BOLD)
        if stripped.startswith("### "):
            text = stripped[4:].strip()
            return self._sidebar_line_styled(text[:width], width, Ansi.FG_TEAL, Ansi.BOLD)

        # Blockquote
        if stripped.startswith("> "):
            text = stripped[2:][: width - 2]
            return self._sidebar_line_styled(f"  {text}", width, Ansi.FG_DIM, "")

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            rule = "─" * (width - 2)
            return self._sidebar_line_styled(f" {rule}", width, Ansi.FG_DIM, "")

        # List item
        if stripped.startswith("- **"):
            # Bold item
            text = stripped[2:][: width - 4]
            return self._sidebar_line_styled(f"  {text}", width, Ansi.FG_GREEN, "")

        if stripped.startswith("- "):
            text = stripped[2:][: width - 4]
            return self._sidebar_line_styled(f"  • {text}", width, Ansi.FG_TEXT, "")

        # Small tag
        if "<small>" in stripped:
            text = stripped.replace("<small>", "").replace("</small>", "")[: width - 2]
            return self._sidebar_line_styled(f" {text}", width, Ansi.FG_DIM, "")

        # Code inline
        if "`" in stripped:
            # Simple inline code highlighting
            text = stripped[:width]
            return self._sidebar_line_styled(f" {text}", width, Ansi.FG_TEXT, "")

        # Regular text
        text = stripped[:width]
        return self._sidebar_line_styled(f" {text}", width, Ansi.FG_TEXT, "")

    def _sidebar_line_styled(self, text: str, width: int, color: str, style: str) -> str:
        """Create a styled sidebar line."""
        padded = text.ljust(width)[:width]
        return (
            f"{Ansi.BG_SIDEBAR}{Ansi.FG_DIM}│{Ansi.RESET}"
            f"{Ansi.BG_SIDEBAR}{style}{color}{padded}{Ansi.RESET}"
            f"{Ansi.BG_SIDEBAR}{Ansi.FG_DIM}│{Ansi.RESET}"
        )

    def _render_content_row(self, editor_line: str, sidebar_line: str, row: int) -> None:
        """Render a single content row with editor + sidebar."""
        self._buffer.append(editor_line + sidebar_line)

    # ---- Status Bar ----

    def _render_status(self) -> None:
        cfg = self.config

        # Separator line
        sep = (
            f"{Ansi.BG_HEADER}{Ansi.FG_DIM}├{'─' * (cfg.editor_width - 1)}┴{'─' * (cfg.sidebar_width - 1)}┤{Ansi.RESET}"
        )
        self._buffer.append(sep)

        # Agent activation line
        if self.status.agents_active:
            agents_str = " → ".join(f"{Ansi.FG_GREEN}●{Ansi.FG_TEAL} {a}" for a in self.status.agents_active)
            agent_line = f" {agents_str}"
        else:
            agent_line = f" {Ansi.FG_DIM}No agents active"

        agent_padded = agent_line  # Will be padded by total_width
        self._buffer.append(
            f"{Ansi.BG_STATUS}{Ansi.FG_DIM}│{Ansi.RESET}"
            f"{Ansi.BG_STATUS}{agent_padded}{Ansi.RESET}"
            f"{' ' * max(0, cfg.total_width - _visible_len(agent_line) - 2)}"
            f"{Ansi.BG_STATUS}{Ansi.FG_DIM}│{Ansi.RESET}"
        )

        # Info line + bottom border
        info_parts = []
        if self.status.chunks_indexed > 0:
            info_parts.append(f"Indexed {self.status.chunks_indexed} chunks")
        if self.status.phase:
            info_parts.append(f"Phase: {self.status.phase}")
        if self.status.message:
            info_parts.append(self.status.message)
        info_str = " │ ".join(info_parts) if info_parts else "Ready"

        bottom = f"{Ansi.BG_STATUS}{Ansi.FG_DIM}│{Ansi.RESET}{Ansi.BG_STATUS}{Ansi.FG_SUBTEXT} {info_str}{Ansi.RESET}"
        pad_needed = cfg.total_width - _visible_len(f"│ {info_str}") - 1
        bottom += f"{Ansi.BG_STATUS}{' ' * max(0, pad_needed)}{Ansi.FG_DIM}│{Ansi.RESET}"
        self._buffer.append(bottom)

        # Bottom border
        self._buffer.append(f"{Ansi.BG_HEADER}{Ansi.FG_DIM}└{'─' * (cfg.total_width - 2)}┘{Ansi.RESET}")

    # ---- Syntax highlighting (basic) ----

    def _syntax_highlight(self, line: str, language: str) -> str:
        """Very basic syntax highlighting for demo purposes."""
        if language == "python":
            return self._highlight_python(line)
        elif language == "markdown":
            return self._highlight_markdown(line)
        return f"{Ansi.FG_TEXT}{line}"

    def _highlight_python(self, line: str) -> str:
        """Basic Python syntax highlighting."""
        stripped = line.lstrip()

        # Keywords
        keywords = {
            "def ",
            "class ",
            "import ",
            "from ",
            "return ",
            "if ",
            "else:",
            "elif ",
            "for ",
            "while ",
            "with ",
            "as ",
            "try:",
            "except ",
            "finally:",
            "raise ",
            "yield ",
            "async ",
            "await ",
            "pass",
            "None",
            "True",
            "False",
            "self",
            "self.",
            "super()",
        }

        # Comments
        comment_pos = _find_comment(line)
        if comment_pos is not None:
            code_part = line[:comment_pos]
            comment_part = line[comment_pos:]
            return f"{self._color_python_code(code_part)}{Ansi.FG_DIM}{Ansi.ITALIC}{comment_part}{Ansi.RESET}"

        # Decorators
        if stripped.startswith("@"):
            return f"{Ansi.FG_YELLOW}{line}{Ansi.RESET}"

        # String (triple-quoted)
        if stripped.startswith('"""') or stripped.startswith("'''"):
            return f"{Ansi.FG_GREEN}{line}{Ansi.RESET}"

        return self._color_python_code(line)

    def _color_python_code(self, line: str) -> str:
        """Color Python code tokens."""
        result = f"{Ansi.FG_TEXT}{line}"

        # Simple keyword coloring via prefix detection
        stripped = line.lstrip()
        indent = line[: len(line) - len(stripped)]

        for kw in ["def ", "async def ", "class "]:
            if stripped.startswith(kw):
                return f"{Ansi.FG_TEXT}{indent}{Ansi.FG_BLUE}{Ansi.BOLD}{kw}{Ansi.RESET}{Ansi.FG_YELLOW}{stripped[len(kw) :]}"

        for kw in ["import ", "from "]:
            if stripped.startswith(kw):
                return f"{Ansi.FG_TEXT}{indent}{Ansi.FG_MAUVE}{stripped}"

        for kw in ["return ", "yield ", "raise "]:
            if stripped.startswith(kw):
                return f"{Ansi.FG_TEXT}{indent}{Ansi.FG_RED}{kw}{Ansi.RESET}{Ansi.FG_TEXT}{stripped[len(kw) :]}"

        for kw in ["if ", "elif ", "else:", "for ", "while ", "with ", "try:", "except ", "finally:"]:
            if stripped.startswith(kw):
                return f"{Ansi.FG_TEXT}{indent}{Ansi.FG_MAUVE}{kw}{Ansi.RESET}{Ansi.FG_TEXT}{stripped[len(kw) :]}"

        return result

    def _highlight_markdown(self, line: str) -> str:
        """Basic markdown highlighting."""
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return f"{Ansi.FG_MAUVE}{Ansi.BOLD}{line}"
        if stripped.startswith("- "):
            return f"{Ansi.FG_TEAL}{line}"
        if stripped.startswith("> "):
            return f"{Ansi.FG_DIM}{Ansi.ITALIC}{line}"
        if stripped.startswith("```"):
            return f"{Ansi.FG_DIM}{line}"
        return f"{Ansi.FG_TEXT}{line}"

    # ---- Plain text render (no ANSI) ----

    def _render_plain(self) -> str:
        """Render without ANSI codes for file output."""
        cfg = self.config
        lines = []

        # Header
        # editor_header is editor_width chars; sidebar_header includes the
        # middle border (border_width) so spans border_width + sidebar_width chars.
        filename = self.editor.file_path.split("/")[-1] if self.editor.file_path else "untitled"
        editor_header = f"┌─ {filename} " + "─" * (cfg.editor_width - len(filename) - 4)
        sb_hdr_prefix = "┬─ Companion "
        sb_hdr_dashes = cfg.sidebar_width + cfg.border_width - len(sb_hdr_prefix) - 1  # -1 for ┐
        sidebar_header = sb_hdr_prefix + "─" * sb_hdr_dashes + "┐"
        lines.append(editor_header + sidebar_header)

        # Content — editor(editor_width) + "│"(border_width) + sidebar(sidebar_width)
        # sidebar lines do NOT include the left │ border; it's added here.
        editor_lines = self._prepare_editor_lines_plain()
        sidebar_lines = self._prepare_sidebar_lines_plain()

        empty_ed = "│" + " " * (cfg.editor_width - 1)
        empty_sb = " " * (cfg.sidebar_width - 1) + "│"
        for row in range(cfg.content_height):
            ed = editor_lines[row] if row < len(editor_lines) else empty_ed
            sb = sidebar_lines[row] if row < len(sidebar_lines) else empty_sb
            lines.append(ed + "│" + sb)

        # Status
        lines.append("├" + "─" * (cfg.editor_width - 1) + "┴" + "─" * (cfg.sidebar_width - 1) + "┤")
        agents_str = " → ".join(self.status.agents_active) if self.status.agents_active else "No agents active"
        lines.append(f"│ ● {agents_str}".ljust(cfg.total_width - 1) + "│")
        info = f"Indexed {self.status.chunks_indexed} chunks" if self.status.chunks_indexed else "Ready"
        lines.append(f"│ {info}".ljust(cfg.total_width - 1) + "│")
        lines.append("└" + "─" * (cfg.total_width - 2) + "┘")

        return "\n".join(lines)

    def _prepare_editor_lines_plain(self) -> list[str]:
        """Plain text editor lines."""
        cfg = self.config
        lines = []
        start = self.editor.scroll_offset
        end = start + cfg.content_height

        for i in range(start, min(end, len(self.editor.lines))):
            line_num = i + 1
            text = self.editor.lines[i][: cfg.editor_text_width]
            arrow = "▸" if line_num == self.editor.cursor_line else " "
            formatted = f"│{arrow}{line_num:>3}│{text}".ljust(cfg.editor_width)
            lines.append(formatted)

        while len(lines) < cfg.content_height:
            lines.append(f"│ {'~':>3}│".ljust(cfg.editor_width))

        return lines

    def _prepare_sidebar_lines_plain(self) -> list[str]:
        """Plain text sidebar lines (without left │ border).

        The left │ border is the pane divider and is added by the caller
        during row assembly. Each line here is sidebar_width chars:
        content(sidebar_width - 1) + right │.
        """
        cfg = self.config
        max_width = cfg.sidebar_width - 1  # content area (right │ takes the last char)
        lines = []

        if not self.sidebar.markdown:
            lines.append(" " * max_width + "│")
            lines.append("  Waiting for cursor...".ljust(max_width) + "│")
        else:
            for raw_line in self.sidebar.markdown.split("\n"):
                text = raw_line[:max_width].ljust(max_width)
                lines.append(f"{text}│")

        while len(lines) < cfg.content_height:
            lines.append(" " * max_width + "│")

        return lines[: cfg.content_height]


def _find_comment(line: str) -> int | None:
    """Find the position of a Python comment (not inside a string)."""
    in_string = False
    string_char = None
    for i, ch in enumerate(line):
        if in_string:
            if ch == string_char and (i == 0 or line[i - 1] != "\\"):
                in_string = False
        elif ch in ('"', "'"):
            in_string = True
            string_char = ch
        elif ch == "#":
            return i
    return None


def _has_ansi(text: str) -> bool:
    """Check if text contains ANSI escape codes."""
    return "\033[" in text


def _visible_len(text: str) -> int:
    """Calculate visible length of text (excluding ANSI codes)."""
    import re

    return len(re.sub(r"\033\[[^m]*m", "", text))
