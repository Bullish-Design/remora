"""Standardized send-keys helpers for Companion E2E scenarios.

Extends NvimKeys with Companion-specific operations like sidebar toggle,
timeline view, and connection verification.

Usage::

    from e2e.companion_keys import CompanionKeys

    def run(self, driver: TmuxDriver) -> None:
        ck = CompanionKeys(driver)
        ck.open_companion(target_file)
        ck.toggle_sidebar()
        ck.wait_for_sidebar_content("Similar")
        ck.navigate_to_class("DataProcessor")
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from e2e.keys import NvimKeys

if TYPE_CHECKING:
    from e2e.harness import TmuxDriver

# ---------------------------------------------------------------------------
# Timing constants (seconds)
# ---------------------------------------------------------------------------

# Delay after toggling sidebar
SIDEBAR_TOGGLE_DELAY = 1.5

# Delay for LSP to initialize (embedding model is slow)
COMPANION_LSP_DELAY = 5.0

# Delay after cursor move for agents to process
AGENT_SETTLE_DELAY = 2.0

# Path to Companion examples
COMPANION_EXAMPLES = Path(__file__).parent.parent / "remora_demo" / "companion" / "examples"

# Path to Companion Neovim plugin
COMPANION_NVIM_PLUGIN = Path(__file__).parent.parent / "remora_demo" / "companion" / "nvim"


# ---------------------------------------------------------------------------
# CompanionKeys
# ---------------------------------------------------------------------------


class CompanionKeys(NvimKeys):
    """Companion-specific keystroke API extending NvimKeys.

    Adds methods for interacting with the Companion sidebar,
    verifying connection detection, and timeline visualization.
    """

    # Companion keymaps use <leader>k prefix (k for knowledge)
    COMPANION_PREFIX = "k"

    def __init__(self, driver: TmuxDriver) -> None:
        super().__init__(driver)

    # ------------------------------------------------------------------
    # Companion leader sequences (<Space>k + suffix)
    # ------------------------------------------------------------------

    def toggle_sidebar(self, settle: float = SIDEBAR_TOGGLE_DELAY) -> None:
        """``<Space>ks`` -- toggle the Companion sidebar panel."""
        self._leader_seq(self.COMPANION_PREFIX, "s", settle=settle)

    def refresh_sidebar(self, settle: float = 1.0) -> None:
        """``<Space>kr`` -- refresh the Companion sidebar content."""
        self._leader_seq(self.COMPANION_PREFIX, "r", settle=settle)

    # ------------------------------------------------------------------
    # Opening nv2 with Companion
    # ------------------------------------------------------------------

    def open_companion(
        self,
        file: str | Path,
        *,
        wait_for: str = "def ",
        timeout: float = 20.0,
        lsp_delay: float = COMPANION_LSP_DELAY,
        with_sidebar: bool = True,
    ) -> None:
        """Launch ``nv2 {file}`` and wait for Companion LSP + optionally open sidebar.

        This method:
        1. Opens nv2 on the file
        2. Dynamically loads the Companion plugin (not in default runtimepath)
        3. Waits for the Companion LSP to initialize
        4. Optionally opens the sidebar

        Args:
            file: Path to the file to open.
            wait_for: Text to wait for in the pane (confirms file loaded).
            timeout: Max seconds to wait for content.
            lsp_delay: Seconds to wait for Companion LSP initialization.
            with_sidebar: Whether to open the sidebar after launch.
        """
        # Launch nv2 on the file
        self.driver.send_keys(f"nv2 {file}")
        self.driver.wait_for_text(wait_for, timeout=timeout)

        # Add Companion plugin to runtimepath and set it up
        # This is needed because the Companion plugin is not in nv2's default rtp
        self._setup_companion_plugin()

        # Wait for Companion LSP to initialize (embedding model loads)
        if lsp_delay > 0:
            time.sleep(lsp_delay)

        # Optionally open sidebar
        if with_sidebar:
            self.toggle_sidebar()

    def _setup_companion_plugin(self, delay: float = 2.0) -> None:
        """Dynamically load the Companion plugin into the running Neovim.

        Adds the Companion plugin directory to runtimepath and calls setup().
        Uses :silent lua to avoid polluting the command line output.
        """
        plugin_path = str(COMPANION_NVIM_PLUGIN.resolve())

        # Use :silent lua with a single-line command to avoid output
        # The setup is broken into separate commands to keep each one simple
        self.ex(f"silent lua vim.opt.rtp:prepend('{plugin_path}')", delay=0.3)

        # Now require and setup the companion module
        setup_cmd = (
            "silent lua local ok, c = pcall(require, 'companion'); "
            "if ok then c.setup({cmd={'companion-lsp'}, "
            "filetypes={'python','markdown','lua'}, "
            "root_markers={'.companion','.git'}}) end"
        )
        self.ex(setup_cmd, delay=delay)

    def wait_for_companion_ready(
        self,
        *,
        indicator: str = "[Companion]",
        timeout: float = 30.0,
        extra_settle: float = 2.0,
    ) -> str:
        """Wait for the Companion LSP to show its initialization notification.

        Note: Companion may not show a notification like Remora does.
        This method waits for the sidebar content or a status indicator.

        Args:
            indicator: Text that confirms LSP initialization.
            timeout: Max seconds to wait for the indicator.
            extra_settle: Additional seconds after indicator appears.

        Returns:
            The pane content where the indicator was found.
        """
        try:
            content = self.driver.wait_for_text(indicator, timeout=timeout)
            if extra_settle > 0:
                time.sleep(extra_settle)
            return content
        except TimeoutError:
            # Companion LSP may not show a notification; just wait and proceed
            time.sleep(extra_settle)
            return self.driver.capture_pane()

    # ------------------------------------------------------------------
    # Sidebar content verification
    # ------------------------------------------------------------------

    def wait_for_sidebar_content(
        self,
        text: str,
        *,
        timeout: float = 15.0,
        poll: float = 0.5,
    ) -> str:
        """Wait for specific text to appear in the sidebar.

        Args:
            text: Text to wait for in the pane (sidebar content).
            timeout: Max seconds to wait.
            poll: Seconds between polls.

        Returns:
            The pane content where text was found.
        """
        return self.driver.wait_for_text(text, timeout=timeout, poll=poll)

    def wait_for_sidebar_section(
        self,
        section: str,
        *,
        timeout: float = 15.0,
    ) -> str:
        """Wait for a sidebar section header to appear.

        Common sections:
        - "## Context" or "# Context"
        - "## Similar" or "Similar Results"
        - "## Connections" or "Related"

        Args:
            section: Section name/header to look for.
            timeout: Max seconds to wait.

        Returns:
            The pane content where section was found.
        """
        return self.driver.wait_for_text(section, timeout=timeout)

    def assert_sidebar_contains(self, *texts: str, msg: str = "") -> str:
        """Assert that the sidebar contains all specified texts.

        Args:
            texts: Texts that should all be present in the pane.
            msg: Optional failure message prefix.

        Returns:
            The pane content.

        Raises:
            AssertionError: If any text is missing.
        """
        content = self.driver.capture_pane()
        for text in texts:
            assert text in content, f"{msg}Expected '{text}' in sidebar:\n{content}"
        return content

    def assert_sidebar_connection(
        self,
        source: str,
        target: str,
        msg: str = "",
    ) -> str:
        """Assert that a connection between source and target is shown.

        The sidebar should show connections like:
        - "test_processor.py" (test file for processor.py)
        - "architecture.md" (docs reference)

        Args:
            source: Source file or identifier (e.g., "processor.py")
            target: Target file or identifier (e.g., "test_processor.py")
            msg: Optional failure message prefix.

        Returns:
            The pane content.
        """
        content = self.driver.capture_pane()
        # Check for either source or target in the content
        # The sidebar may show connections in various formats
        found = target in content or (source in content and target in content)
        assert found, f"{msg}Expected connection to '{target}' in sidebar:\n{content}"
        return content

    # ------------------------------------------------------------------
    # Navigation helpers for Companion examples
    # ------------------------------------------------------------------

    def navigate_to_class(
        self,
        class_name: str,
        *,
        timeout: float = 5.0,
    ) -> str:
        """Navigate to a class definition using search.

        Uses ``/{class_name}`` to find the class.

        Args:
            class_name: Name of the class to find.
            timeout: Max seconds to wait for navigation.

        Returns:
            The pane content after navigation.
        """
        self.raw("/", delay=0.2)
        self.keys(f"class {class_name}", delay=0.5)
        time.sleep(0.5)  # Let the cursor settle
        return self.driver.capture_pane()

    def navigate_to_function(
        self,
        func_name: str,
        *,
        timeout: float = 5.0,
    ) -> str:
        """Navigate to a function definition using search.

        Uses ``/def {func_name}`` to find the function.

        Args:
            func_name: Name of the function to find.
            timeout: Max seconds to wait for navigation.

        Returns:
            The pane content after navigation.
        """
        self.raw("/", delay=0.2)
        self.keys(f"def {func_name}", delay=0.5)
        time.sleep(0.5)
        return self.driver.capture_pane()

    def wait_for_agents_to_settle(
        self,
        stable_seconds: float = AGENT_SETTLE_DELAY,
        timeout: float = 15.0,
    ) -> str:
        """Wait for all agents to finish processing after a cursor move.

        This gives time for:
        - cursor_tracker to sense the move
        - context_extractor to extract context
        - embedding_searcher to find similar
        - connection_finder to find connections
        - sidebar_composer to update output

        Returns:
            The stable pane content.
        """
        return self.driver.wait_for_stable(
            stable_seconds=stable_seconds,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Ex commands for Companion
    # ------------------------------------------------------------------

    def companion_status(self, delay: float = 1.0) -> None:
        """:CompanionStatus -- show Companion LSP status."""
        self.ex("CompanionStatus", delay=delay)

    def companion_refresh(self, delay: float = 1.0) -> None:
        """:CompanionRefresh -- refresh sidebar content."""
        self.ex("CompanionRefresh", delay=delay)

    def companion_sidebar(self, delay: float = 1.0) -> None:
        """:CompanionSidebar -- toggle sidebar."""
        self.ex("CompanionSidebar", delay=delay)
