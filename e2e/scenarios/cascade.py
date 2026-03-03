"""Cascade scenario — Agent A messages Agent B.

Simulates a code change in loader.py that triggers the load_config agent,
which then messages the test_load_yaml agent via the cascade mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class CascadeScenario:
    """Agent cascade scenario — source agent notifies test agent."""

    name: str = "cascade"
    description: str = "Edit load_config, verify cascade to test agent"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py
        nv.open_nvim(target_file, wait_for="def load_config")

        # Open the panel first to see agent activity
        nv.leader_panel()

        # Move focus into the panel to see it, then back to code
        nv.focus_right()
        nv.focus_left()

        # Position cursor on load_config function signature (line 12)
        nv.goto_line(12)

        # Add a timeout parameter: jump to closing paren, insert before it
        nv.find_char(")")
        nv.enter_insert()
        nv.type_in_insert(", timeout: int = 30", enter=False)
        nv.exit_insert()

        # Save the file to trigger content change detection
        nv.save(delay=5)

        # Wait for pane to stabilize
        driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Capture final state
        _content = driver.capture_pane()
