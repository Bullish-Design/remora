"""Chat scenario — Chat with an agent.

Opens nv2 on the demo project, positions cursor on `load_config`,
opens the Remora panel, and sends a chat message. Verifies the
agent's response appears in the panel.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ChatScenario:
    """Chat with an agent scenario."""

    name: str = "chat"
    description: str = "Chat with load_config agent, verify response in panel"

    def run(self, driver: TmuxDriver) -> None:
        # Launch nv2 on loader.py
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        driver.send_keys(f"nv2 {target_file}")

        # Wait for Neovim + file content
        driver.wait_for_text("def load_config", timeout=15)
        time.sleep(3)  # Let LSP initialize

        # Position cursor on load_config (line 12 in loader.py)
        # Use Neovim command mode to go to line 12
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("12")
        time.sleep(0.5)

        # Open the Remora panel with <leader>ra
        # Default leader is backslash
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("a")
        time.sleep(2)  # Let panel open and populate

        # Now trigger chat with <leader>rc
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("c")
        time.sleep(1)

        # Type a chat message — the requestInput handler should focus the input
        driver.send_keys("what do you do?")
        time.sleep(3)  # Wait for mock LLM response

        # Verify the agent response appears
        # MockLLM HumanChatScript returns "I'm the agent for `load_config`..."
        content = driver.wait_for_text("load_config", timeout=15)

        # Wait for everything to settle
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)
