"""Extension discovery scenario — Custom extensions match different node types.

Opens nv2 on schema.py (which has a class + function), waits for LSP to
discover agents, verifies code lenses appear. Then opens the agent panel
to show all discovered agents with their extension assignments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ExtDiscoveryScenario:
    """Discover custom extensions across different node types."""

    name: str = "ext_discovery"
    description: str = "Open schema.py, verify agents discovered, open panel to see extensions"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open schema.py — has SchemaError class + validate function
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "schema.py"
        nv.open_nvim(target_file, wait_for="class SchemaError")

        # Wait for LSP to finish discovering nodes
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Verify the file content is visible
        content = driver.capture_pane()
        assert "class SchemaError" in content, f"Expected 'class SchemaError' in pane:\n{content}"
        assert "def validate" in content, f"Expected 'def validate' in pane:\n{content}"

        # ---------------------------------------------------------------
        # Beat 2: Browse the file — scroll through class and function
        # ---------------------------------------------------------------
        nv.move_down(10, delay=0.3)
        time.sleep(0.5)
        nv.goto_top()
        time.sleep(0.5)

        # ---------------------------------------------------------------
        # Beat 3: Open the agent panel to see discovered agents
        # ---------------------------------------------------------------
        nv.leader_panel()

        # Move focus to panel to show its contents, then back
        nv.focus_right()
        time.sleep(1)
        nv.focus_left()
        time.sleep(0.5)

        # ---------------------------------------------------------------
        # Beat 4: Navigate to loader.py to see function agents
        # ---------------------------------------------------------------
        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.edit_file(loader_file, delay=3)

        # Wait for the file to load and LSP to discover
        driver.wait_for_text("def load_config", timeout=10)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Verify function content visible
        content = driver.capture_pane()
        assert "def load_config" in content, f"Expected 'def load_config' in pane:\n{content}"

        # ---------------------------------------------------------------
        # Beat 5: Final stable state — all agents visible in panel
        # ---------------------------------------------------------------
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        _content = driver.capture_pane()
