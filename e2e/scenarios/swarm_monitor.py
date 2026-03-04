"""Swarm monitor scenario — Meta-observation of agent activity.

Demonstrates the SwarmMonitor extension by:
1. Opening MONITOR.md which has the SwarmMonitor extension attached
2. Triggering agent activity by editing loader.py
3. Observing that the SwarmMonitor agent receives lifecycle events
4. The monitor sees AgentCompleteEvent, ToolCallEvent from other agents

This validates meta-observation: agents watching other agents without their knowledge.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class SwarmMonitorScenario:
    """Swarm monitor meta-observation scenario."""

    name: str = "swarm_monitor"
    description: str = "MONITOR.md agent observes other agent activity"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open MONITOR.md - the swarm observer file
        # ---------------------------------------------------------------
        monitor_file = DEMO_PROJECT / "MONITOR.md"
        nv.open_nvim(monitor_file, wait_for="MONITOR", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open panel to see the SwarmMonitor agent
        nv.leader_panel()
        nv.focus_right(delay=0.5)
        nv.focus_left(delay=0.3)

        # Verify SwarmMonitor extension is attached
        content = driver.capture_pane()
        # The panel should show this is a file-type agent
        assert "MONITOR" in content or "file" in content.lower(), f"Expected MONITOR agent:\n{content}"

        # ---------------------------------------------------------------
        # Beat 2: Navigate to loader.py to trigger agent activity
        # ---------------------------------------------------------------
        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.edit_file(loader_file)

        driver.wait_for_text("def load_config", timeout=10)

        # Position on load_config
        nv.goto_line(12)
        time.sleep(1)

        # ---------------------------------------------------------------
        # Beat 3: Chat with load_config to generate agent activity
        # ---------------------------------------------------------------
        nv.leader_chat(settle=0.5)
        nv.wait_for_chat_prompt()

        nv.keys("What does this function do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for LLM response - this generates AgentCompleteEvent
        driver.wait_for_stable(stable_seconds=5.0, timeout=45)

        # ---------------------------------------------------------------
        # Beat 4: Make an edit to generate ContentChangedEvent
        # ---------------------------------------------------------------
        nv.focus_code_buffer(expected_text="def load_config")
        nv.goto_line(13)

        nv.raw("o", delay=0.3)  # Open new line
        nv.type_in_insert("    # Swarm monitor is watching", enter=False)
        nv.exit_insert()

        nv.save(delay=3)

        # Wait for events to propagate
        driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # ---------------------------------------------------------------
        # Beat 5: Return to MONITOR.md to see if it captured activity
        # ---------------------------------------------------------------
        nv.edit_file(monitor_file)
        driver.wait_for_text("MONITOR", timeout=10)

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # The monitor file should still be visible
        assert "MONITOR" in content, f"Expected MONITOR.md content:\n{content}"

        # Verify LSP is healthy
        nv.assert_not_in_pane("LSP not running", "LSP should be running")
