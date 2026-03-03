"""Standardized send-keys helpers for E2E scenarios.

Centralizes all Neovim keystroke patterns so scenarios never have to
hard-code leader keys, timing delays, or tmux send-keys specifics.

Usage::

    from e2e.keys import NvimKeys

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        nv.open_file(target_file)
        nv.goto_line(13)
        nv.leader_chat()          # <Space>rc
        nv.type_in_insert("what do you do?")
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from e2e.harness import TmuxDriver

# ---------------------------------------------------------------------------
# Default timing constants (seconds)
# ---------------------------------------------------------------------------

# Delay between individual keystrokes in a leader sequence (Space, r, c)
LEADER_KEY_DELAY = 0.3

# Delay after a full leader sequence before the next action
LEADER_SETTLE = 1.0

# Delay after entering/exiting insert mode
MODE_SWITCH_DELAY = 0.3

# Delay after an ex-command (:w, :e, etc.)
EX_CMD_DELAY = 0.5

# Delay between repeated navigation keys (j, k, etc.)
NAV_KEY_DELAY = 0.15

# Delay for LSP startup after opening a file
LSP_STARTUP_DELAY = 3.0


# ---------------------------------------------------------------------------
# NvimKeys — the single interface scenarios use for all keystrokes
# ---------------------------------------------------------------------------


class NvimKeys:
    """High-level Neovim keystroke API built on top of TmuxDriver.

    Encapsulates leader key identity, timing, and tmux send-keys
    specifics so scenarios stay readable and maintainable.
    """

    # The tmux key name for Neovim's mapleader.
    # nv2 sets vim.g.mapleader = " " (space) in its init.lua.
    LEADER = "Space"

    def __init__(self, driver: TmuxDriver) -> None:
        self.driver = driver

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def raw(self, key: str, delay: float = 0.0) -> None:
        """Send a single raw key (no Enter appended)."""
        self.driver.send_raw(key)
        if delay > 0:
            time.sleep(delay)

    def keys(self, text: str, *, enter: bool = True, delay: float = 0.0) -> None:
        """Send text with optional Enter."""
        self.driver.send_keys(text, enter=enter)
        if delay > 0:
            time.sleep(delay)

    # ------------------------------------------------------------------
    # Leader sequences (<Space>r + suffix)
    # ------------------------------------------------------------------

    def _leader_seq(self, *suffixes: str, settle: float = LEADER_SETTLE) -> None:
        """Send <leader> followed by one or more suffix keys.

        E.g. ``_leader_seq("r", "c")`` sends ``<Space> r c``.
        """
        self.raw(self.LEADER, delay=LEADER_KEY_DELAY)
        for key in suffixes:
            self.raw(key, delay=LEADER_KEY_DELAY)
        if settle > 0:
            time.sleep(settle)

    def leader_chat(self, settle: float = LEADER_SETTLE) -> None:
        """``<Space>rc`` — open chat input for the agent at cursor."""
        self._leader_seq("r", "c", settle=settle)

    def leader_panel(self, settle: float = 2.0) -> None:
        """``<Space>ra`` — toggle the Remora agent panel."""
        self._leader_seq("r", "a", settle=settle)

    def leader_rewrite(self, settle: float = 5.0) -> None:
        """``<Space>rr`` — request rewrite for the agent at cursor."""
        self._leader_seq("r", "r", settle=settle)

    def leader_accept(self, settle: float = 3.0) -> None:
        """``<Space>ry`` — accept the pending proposal."""
        self._leader_seq("r", "y", settle=settle)

    def leader_reject(self, settle: float = 3.0) -> None:
        """``<Space>rn`` — reject the pending proposal."""
        self._leader_seq("r", "n", settle=settle)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def goto_line(self, line: int, delay: float = EX_CMD_DELAY) -> None:
        """Send ``:N<Enter>`` to jump to a line number."""
        self.raw(":", delay=0.2)
        self.keys(str(line), delay=delay)

    def goto_top(self, delay: float = 0.5) -> None:
        """Send ``gg`` to go to the top of the file."""
        self.raw("g", delay=0.1)
        self.raw("g", delay=delay)

    def move_down(self, count: int = 1, delay: float = NAV_KEY_DELAY) -> None:
        """Send ``j`` *count* times."""
        for _ in range(count):
            self.raw("j", delay=delay)

    def move_up(self, count: int = 1, delay: float = NAV_KEY_DELAY) -> None:
        """Send ``k`` *count* times."""
        for _ in range(count):
            self.raw("k", delay=delay)

    def find_char(self, char: str, delay: float = 0.2) -> None:
        """Send ``f{char}`` to jump to the next occurrence of *char*."""
        self.raw(f"f{char}", delay=delay)

    # ------------------------------------------------------------------
    # Window / pane focus
    # ------------------------------------------------------------------

    def focus_right(self, delay: float = 0.5) -> None:
        """``Ctrl-l`` — move focus to the right split."""
        self.raw("C-l", delay=delay)

    def focus_left(self, delay: float = 0.5) -> None:
        """``Ctrl-h`` — move focus to the left split."""
        self.raw("C-h", delay=delay)

    def focus_window(self, direction: str, delay: float = 0.5) -> None:
        """``Ctrl-w {direction}`` — move focus to a window by direction key."""
        self.raw("C-w", delay=0.1)
        self.raw(direction, delay=delay)

    # ------------------------------------------------------------------
    # Insert mode
    # ------------------------------------------------------------------

    def enter_insert(self, delay: float = MODE_SWITCH_DELAY) -> None:
        """Press ``i`` to enter insert mode."""
        self.raw("i", delay=delay)

    def exit_insert(self, delay: float = MODE_SWITCH_DELAY) -> None:
        """Press ``Escape`` to exit insert mode."""
        self.raw("Escape", delay=delay)

    def type_in_insert(
        self,
        text: str,
        *,
        enter: bool = False,
        exit_after: bool = False,
        delay: float = 0.0,
    ) -> None:
        """Type text while already in insert mode.

        Args:
            text: The literal text to type.
            enter: Whether to press Enter after the text.
            exit_after: Whether to press Escape after typing.
            delay: Extra delay after the text is sent.
        """
        self.keys(text, enter=enter, delay=delay)
        if exit_after:
            self.exit_insert()

    def insert_text(
        self,
        text: str,
        *,
        enter: bool = False,
        delay: float = 0.3,
    ) -> None:
        """Enter insert mode, type text, exit insert mode.

        Convenience wrapper for the full enter -> type -> exit cycle.
        """
        self.enter_insert()
        self.keys(text, enter=enter, delay=delay)
        self.exit_insert()

    # ------------------------------------------------------------------
    # Ex commands (command-line mode)
    # ------------------------------------------------------------------

    def ex(self, command: str, delay: float = EX_CMD_DELAY) -> None:
        """Send an ex command — ``:command<Enter>``."""
        self.raw(":", delay=0.2)
        self.keys(command, delay=delay)

    def save(self, delay: float = EX_CMD_DELAY) -> None:
        """``:w`` — write the current buffer."""
        self.ex("w", delay=delay)

    def edit_file(self, path: str | Path, delay: float = 2.0) -> None:
        """``:e {path}`` — open a file in the current window."""
        self.ex(f"e {path}", delay=delay)

    # ------------------------------------------------------------------
    # Opening nv2 (shell-level, not Neovim-level)
    # ------------------------------------------------------------------

    def open_nvim(
        self,
        file: str | Path,
        *,
        wait_for: str = "def ",
        timeout: float = 15.0,
        lsp_delay: float = LSP_STARTUP_DELAY,
    ) -> None:
        """Launch ``nv2 {file}`` and wait for content + LSP startup.

        Args:
            file: Path to the file to open.
            wait_for: Text to wait for in the pane (confirms file loaded).
            timeout: Max seconds to wait for *wait_for* text.
            lsp_delay: Extra seconds to wait after text appears for LSP init.
        """
        self.driver.send_keys(f"nv2 {file}")
        self.driver.wait_for_text(wait_for, timeout=timeout)
        if lsp_delay > 0:
            time.sleep(lsp_delay)
