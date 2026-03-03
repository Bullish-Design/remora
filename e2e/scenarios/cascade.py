"""Cascade scenario — Agent A messages Agent B.

Simulates a code change in loader.py that triggers the load_config agent,
which then messages the test_load_yaml agent via the cascade mechanism.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class CascadeScenario:
    """Agent cascade scenario — source agent notifies test agent."""

    name: str = "cascade"
    description: str = "Edit load_config, verify cascade to test agent"

    def run(self, driver: TmuxDriver) -> None:
        # Launch nv2 on loader.py
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        driver.send_keys(f"nv2 {target_file}")

        # Wait for Neovim + file content
        driver.wait_for_text("def load_config", timeout=15)
        time.sleep(3)  # Let LSP initialize and scan

        # Open the panel first to see agent activity
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("a")
        time.sleep(2)

        # Position cursor on load_config function signature (line 12)
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("12")
        time.sleep(0.5)

        # Enter insert mode and add a timeout parameter
        # Go to end of the signature line: def load_config(path: str | Path) -> dict[str, Any]:
        # We want to add ", timeout: int = 30" before the closing paren
        driver.send_raw("f)")  # Find the closing paren
        time.sleep(0.2)
        driver.send_raw("i")  # Insert mode before the paren
        time.sleep(0.2)
        driver.send_keys(", timeout: int = 30", enter=False)
        time.sleep(0.2)

        # Exit insert mode
        driver.send_raw("Escape")
        time.sleep(0.5)

        # Save the file to trigger content change detection
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("w")
        time.sleep(5)  # Wait for the cascade: load_config agent -> test_load_yaml agent

        # The MockLLM ContentChangedAnalyzeScript should fire, which
        # uses message_node to notify test_load_yaml. Then the
        # TestAgentUpdateScript fires for the test agent.

        # Wait for pane to stabilize
        driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Capture final state
        _content = driver.capture_pane()
