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

# Delay after pressing Enter to submit chat input
CHAT_SUBMIT_DELAY = 1.0

# Poll interval while waiting for chat history updates
CHAT_HISTORY_POLL = 0.2


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

    # ------------------------------------------------------------------
    # LSP and chat readiness helpers
    # ------------------------------------------------------------------

    def wait_for_lsp_ready(
        self,
        *,
        indicator: str = "[Remora]",
        timeout: float = 15.0,
        extra_settle: float = 2.0,
    ) -> str:
        """Wait for the Remora LSP to show its initialization notification.

        After the indicator appears, waits an additional settle period for
        the LSP to fully attach to all buffers.

        Args:
            indicator: Text that confirms LSP initialization.
            timeout: Max seconds to wait for the indicator.
            extra_settle: Additional seconds after indicator appears.

        Returns:
            The pane content where the indicator was found.
        """
        content = self.driver.wait_for_text(indicator, timeout=timeout)
        if extra_settle > 0:
            time.sleep(extra_settle)
        return content

    def wait_for_chat_prompt(
        self,
        *,
        prompt_text: str = "Message to agent:",
        timeout: float = 10.0,
    ) -> str:
        """Wait for the chat input prompt to appear after leader_chat().

        Returns the pane content where the prompt was found.
        Raises TimeoutError if the prompt doesn't appear (e.g., LSP not running).
        """
        return self.driver.wait_for_text(prompt_text, timeout=timeout)

    def wait_for_chat_history_message(
        self,
        text: str,
        *,
        timeout: float = 10.0,
        poll: float = CHAT_HISTORY_POLL,
        empty_marker: str = "No messages yet.",
    ) -> str:
        """Wait until a sent message is visible in history (not just input).

        This prevents false-passes where text appears only in the input box
        without a real submit.
        """
        deadline = time.monotonic() + timeout
        last_content = ""

        while time.monotonic() < deadline:
            content = self.driver.capture_pane()
            last_content = content
            if text in content and empty_marker not in content:
                return content
            time.sleep(poll)

        raise AssertionError(
            f"Timed out waiting for submitted chat history message {text!r}; "
            f"'{empty_marker}' never cleared.\nLast pane content:\n{last_content}"
        )

    def submit_chat_message(
        self,
        text: str,
        *,
        prompt_text: str = "Message to agent:",
        prompt_timeout: float = 10.0,
        type_delay: float = 0.3,
        submit_delay: float = CHAT_SUBMIT_DELAY,
        exit_insert: bool = True,
        message_timeout: float = 10.0,
    ) -> str:
        """Submit a chat message via the active request-input prompt.

        Sequence:
        1. Wait for prompt (`$/remora/requestInput` path active)
        2. Type text
        3. Press Enter to submit
        4. Optionally press Escape for normal-mode leader mappings
        5. Verify history updated and empty-state marker cleared
        """
        self.wait_for_chat_prompt(prompt_text=prompt_text, timeout=prompt_timeout)
        self.keys(text, enter=False, delay=type_delay)
        self.raw("Enter", delay=submit_delay)
        if exit_insert:
            self.raw("Escape", delay=MODE_SWITCH_DELAY)
        return self.wait_for_chat_history_message(
            text,
            timeout=message_timeout,
            empty_marker="No messages yet.",
        )

    # ------------------------------------------------------------------
    # Focus helpers
    # ------------------------------------------------------------------

    def focus_code_buffer(
        self,
        expected_text: str = "def ",
        timeout: float = 5.0,
    ) -> str:
        """Navigate to the window containing source code.

        Tries multiple strategies to find the code buffer:
        1. Ctrl-h (left window, most common layout)
        2. Ctrl-w p (previous window)
        3. Window cycling with Ctrl-w w

        Args:
            expected_text: Text that identifies the code buffer.
            timeout: Max seconds to find the code buffer.

        Returns:
            The pane content of the code buffer.

        Raises:
            TimeoutError: If code buffer not found within timeout.
        """
        start = time.monotonic()

        # Try left window first (most common layout)
        self.raw("C-h", delay=0.3)
        content = self.driver.capture_pane()
        if expected_text in content:
            return content

        # Try Ctrl-w p (previous window)
        self.raw("C-w", delay=0.1)
        self.raw("p", delay=0.3)
        content = self.driver.capture_pane()
        if expected_text in content:
            return content

        # Fallback: cycle through windows
        for _ in range(4):
            if time.monotonic() - start > timeout:
                break
            self.raw("C-w", delay=0.1)
            self.raw("w", delay=0.3)
            content = self.driver.capture_pane()
            if expected_text in content:
                return content

        raise TimeoutError(f"Could not find window containing '{expected_text}'")

    # ------------------------------------------------------------------
    # Assertion helpers
    # ------------------------------------------------------------------

    def assert_in_pane(self, text: str, msg: str = "") -> str:
        """Assert that text is in the current pane content.

        Args:
            text: The text to find.
            msg: Optional failure message.

        Returns:
            The pane content.

        Raises:
            AssertionError: If text is not found.
        """
        content = self.driver.capture_pane()
        assert text in content, msg or f"Expected {text!r} in pane, got:\n{content}"
        return content

    def assert_not_in_pane(self, text: str, msg: str = "") -> str:
        """Assert that text is NOT in the current pane content.

        Args:
            text: The text that should be absent.
            msg: Optional failure message.

        Returns:
            The pane content.

        Raises:
            AssertionError: If text is found.
        """
        content = self.driver.capture_pane()
        assert text not in content, msg or f"Did not expect {text!r} in pane, got:\n{content}"
        return content

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def open_nvim_with_panel(
        self,
        file: str | Path,
        *,
        wait_for: str = "def ",
        timeout: float = 15.0,
    ) -> None:
        """Open nv2, wait for content and LSP, then open the agent panel.

        Combines open_nvim + wait_for_lsp_ready + leader_panel + focus cycle.
        This is a common pattern for scenarios that need both the code buffer
        and the agent panel visible.
        """
        self.open_nvim(file, wait_for=wait_for, timeout=timeout, lsp_delay=0)
        self.wait_for_lsp_ready()
        self.leader_panel()
        self.focus_right(delay=0.3)
        self.focus_left(delay=0.3)
