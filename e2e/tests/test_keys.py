"""Unit tests for e2e/keys.py — NvimKeys helper methods."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# Add parent to path for imports
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from e2e.keys import NvimKeys


class TestNvimKeysLspReady:
    """Tests for NvimKeys.wait_for_lsp_ready method."""

    def test_waits_for_indicator_and_settles(self) -> None:
        """Should wait for indicator text then settle."""
        driver = MagicMock()
        driver.wait_for_text.return_value = "[Remora] initialized"

        nv = NvimKeys(driver)

        with patch("e2e.keys.time.sleep") as mock_sleep:
            result = nv.wait_for_lsp_ready(
                indicator="[Remora]",
                timeout=10.0,
                extra_settle=2.0,
            )

        driver.wait_for_text.assert_called_once_with("[Remora]", timeout=10.0)
        mock_sleep.assert_called_once_with(2.0)
        assert result == "[Remora] initialized"

    def test_no_settle_when_zero(self) -> None:
        """Should skip settle sleep when extra_settle=0."""
        driver = MagicMock()
        driver.wait_for_text.return_value = "content"

        nv = NvimKeys(driver)

        with patch("e2e.keys.time.sleep") as mock_sleep:
            nv.wait_for_lsp_ready(extra_settle=0)

        mock_sleep.assert_not_called()


class TestNvimKeysChatPrompt:
    """Tests for NvimKeys.wait_for_chat_prompt method."""

    def test_waits_for_prompt_text(self) -> None:
        """Should wait for chat prompt text."""
        driver = MagicMock()
        driver.wait_for_text.return_value = "Message to agent: |"

        nv = NvimKeys(driver)
        result = nv.wait_for_chat_prompt(prompt_text="Message to agent:", timeout=5.0)

        driver.wait_for_text.assert_called_once_with("Message to agent:", timeout=5.0)
        assert "Message to agent" in result

    def test_propagates_timeout_error(self) -> None:
        """Should propagate TimeoutError if prompt doesn't appear."""
        driver = MagicMock()
        driver.wait_for_text.side_effect = TimeoutError("prompt not found")

        nv = NvimKeys(driver)

        with pytest.raises(TimeoutError):
            nv.wait_for_chat_prompt()


class TestNvimKeysFocusCodeBuffer:
    """Tests for NvimKeys.focus_code_buffer method."""

    def test_finds_code_on_first_try(self) -> None:
        """Should return immediately if left window has code."""
        driver = MagicMock()
        driver.capture_pane.return_value = "def load_config():\n    pass"

        nv = NvimKeys(driver)

        with patch.object(nv, "raw") as mock_raw:
            result = nv.focus_code_buffer(expected_text="def ")

        # Should have tried C-h first
        mock_raw.assert_called_once_with("C-h", delay=0.3)
        assert "def load_config" in result

    def test_tries_previous_window(self) -> None:
        """Should try C-w p if left window doesn't have code."""
        driver = MagicMock()
        # First capture (after C-h): chat buffer, second (after C-w p): code
        driver.capture_pane.side_effect = [
            "remora://input\nMessage to agent:",
            "def load_config():\n    pass",
        ]

        nv = NvimKeys(driver)

        with patch.object(nv, "raw") as mock_raw:
            result = nv.focus_code_buffer(expected_text="def ")

        # Should have tried C-h, then C-w p
        calls = mock_raw.call_args_list
        assert calls[0] == call("C-h", delay=0.3)
        assert calls[1] == call("C-w", delay=0.1)
        assert calls[2] == call("p", delay=0.3)
        assert "def load_config" in result

    def test_cycles_through_windows(self) -> None:
        """Should cycle through windows if previous strategies fail."""
        driver = MagicMock()
        # First three captures fail, fourth succeeds
        driver.capture_pane.side_effect = [
            "chat buffer",
            "help buffer",
            "panel buffer",
            "def load_config():\n    pass",
        ]

        nv = NvimKeys(driver)

        with patch.object(nv, "raw") as mock_raw:
            result = nv.focus_code_buffer(expected_text="def ")

        assert "def load_config" in result

    def test_timeout_when_not_found(self) -> None:
        """Should raise TimeoutError if code buffer not found."""
        driver = MagicMock()
        driver.capture_pane.return_value = "no code here"

        nv = NvimKeys(driver)

        with patch.object(nv, "raw"):
            with pytest.raises(TimeoutError) as exc_info:
                nv.focus_code_buffer(expected_text="def ", timeout=0.5)

        assert "def " in str(exc_info.value)


class TestNvimKeysAssertions:
    """Tests for NvimKeys assertion helpers."""

    def test_assert_in_pane_passes(self) -> None:
        """Should pass when text is in pane."""
        driver = MagicMock()
        driver.capture_pane.return_value = "def load_config():\n    pass"

        nv = NvimKeys(driver)
        result = nv.assert_in_pane("load_config")

        assert "load_config" in result

    def test_assert_in_pane_fails(self) -> None:
        """Should raise AssertionError when text not in pane."""
        driver = MagicMock()
        driver.capture_pane.return_value = "something else"

        nv = NvimKeys(driver)

        with pytest.raises(AssertionError) as exc_info:
            nv.assert_in_pane("load_config")

        assert "load_config" in str(exc_info.value)

    def test_assert_in_pane_custom_message(self) -> None:
        """Should use custom message when provided."""
        driver = MagicMock()
        driver.capture_pane.return_value = "nope"

        nv = NvimKeys(driver)

        with pytest.raises(AssertionError) as exc_info:
            nv.assert_in_pane("foo", msg="Custom error message")

        assert "Custom error message" in str(exc_info.value)

    def test_assert_not_in_pane_passes(self) -> None:
        """Should pass when text is NOT in pane."""
        driver = MagicMock()
        driver.capture_pane.return_value = "def load_config():\n    pass"

        nv = NvimKeys(driver)
        result = nv.assert_not_in_pane("LSP not running")

        assert "load_config" in result

    def test_assert_not_in_pane_fails(self) -> None:
        """Should raise AssertionError when text IS in pane."""
        driver = MagicMock()
        driver.capture_pane.return_value = "error: LSP not running"

        nv = NvimKeys(driver)

        with pytest.raises(AssertionError) as exc_info:
            nv.assert_not_in_pane("LSP not running")

        assert "LSP not running" in str(exc_info.value)


class TestNvimKeysOpenWithPanel:
    """Tests for NvimKeys.open_nvim_with_panel convenience method."""

    def test_combines_all_steps(self) -> None:
        """Should call open_nvim, wait_for_lsp_ready, leader_panel, focus cycle."""
        driver = MagicMock()
        driver.wait_for_text.return_value = "content"

        nv = NvimKeys(driver)

        with (
            patch.object(nv, "open_nvim") as mock_open,
            patch.object(nv, "wait_for_lsp_ready") as mock_lsp,
            patch.object(nv, "leader_panel") as mock_panel,
            patch.object(nv, "focus_right") as mock_right,
            patch.object(nv, "focus_left") as mock_left,
        ):
            nv.open_nvim_with_panel("/path/to/file.py", wait_for="def ", timeout=20.0)

        mock_open.assert_called_once_with(
            "/path/to/file.py",
            wait_for="def ",
            timeout=20.0,
            lsp_delay=0,
        )
        mock_lsp.assert_called_once()
        mock_panel.assert_called_once()
        mock_right.assert_called_once_with(delay=0.3)
        mock_left.assert_called_once_with(delay=0.3)
