"""Chat scenario — Chat with an agent.

Opens nv2 on the demo project, positions cursor on `load_config`,
sends a chat message via <leader>rc, verifies the response, then
opens the Remora panel via <leader>ra and navigates into it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ChatScenario:
    """Chat with an agent scenario."""

    name: str = "chat"
    description: str = "Chat with load_config agent, verify response in panel"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py
        nv.open_nvim(target_file, wait_for="def load_config")

        # Position cursor on load_config (line 13 in loader.py)
        nv.goto_line(13)

        # --- Test 1: Direct chat via <leader>rc ---
        nv.leader_chat()

        # Type a chat message and send it
        time.sleep(0.5)
        nv.keys("what do you do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=5)

        # Verify the agent response appears
        driver.wait_for_text("load_config", timeout=15)

        # --- Test 2: Open the agent panel via <leader>ra ---
        nv.leader_panel()

        # Move focus into the panel
        nv.focus_right(delay=1)

        # Wait for everything to settle
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)
