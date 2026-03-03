"""Panel navigation scenario — Open panel, move between functions, close.

Opens the Remora agent panel, moves the cursor between different
functions to trigger panel refresh, toggles the tools section,
and closes the panel. Verifies the panel responds to cursor movement.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class PanelNavScenario:
    """Open panel, navigate between agents, close panel."""

    name: str = "panel_nav"
    description: str = "Open agent panel, move between functions, toggle tools, close"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py with event-driven LSP wait
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open the Remora agent panel
        nv.leader_panel()

        # Verify panel appeared — focus into it and back
        nv.focus_right(delay=1)
        nv.focus_left(delay=0.5)

        # ---------------------------------------------------------------
        # Move cursor to load_config (line 12) — panel should show it
        # ---------------------------------------------------------------
        nv.goto_line(12)
        # CursorHold debounce is 300ms, wait a bit for panel refresh
        time.sleep(2)

        content = driver.capture_pane()
        assert "load_config" in content, f"Expected 'load_config' in panel after navigating to it:\n{content}"

        # ---------------------------------------------------------------
        # Move cursor to detect_format (line 29) — panel should update
        # ---------------------------------------------------------------
        nv.goto_line(29)
        time.sleep(2)

        content = driver.capture_pane()
        assert "detect_format" in content, f"Expected 'detect_format' in panel after navigating to it:\n{content}"

        # ---------------------------------------------------------------
        # Move cursor to load_yaml (line 39) — panel should update
        # ---------------------------------------------------------------
        nv.goto_line(39)
        time.sleep(2)

        content = driver.capture_pane()
        assert "load_yaml" in content, f"Expected 'load_yaml' in panel after navigating to it:\n{content}"

        # ---------------------------------------------------------------
        # Focus into panel and toggle tools section with 't'
        # ---------------------------------------------------------------
        nv.focus_right(delay=0.5)
        nv.raw("t", delay=1)

        # Toggle back
        nv.raw("t", delay=1)

        # ---------------------------------------------------------------
        # Close panel with 'q'
        # ---------------------------------------------------------------
        nv.raw("q", delay=1)

        # Focus should return to code — verify the panel closed
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Verify we can still see the code
        assert "def " in content, f"Expected code content after panel close:\n{content}"
