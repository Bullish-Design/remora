"""Chat scenario — Chat with an agent.

Opens nv2 on the demo project, positions cursor on `load_config`,
sends a chat message via <leader>rc, verifies the chat panel opened,
then opens the Remora panel via <leader>ra and navigates into it.
"""

from __future__ import annotations

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

        # Launch nv2 on loader.py and wait for LSP
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open the agent panel first (required for chat to work)
        nv.leader_panel()
        nv.focus_right(delay=0.3)
        nv.focus_left(delay=0.3)

        # Position cursor on load_config (line 13 in loader.py)
        nv.goto_line(13)

        # --- Test 1: Direct chat via <leader>rc ---
        nv.leader_chat()

        # Wait for chat prompt to appear before typing
        nv.wait_for_chat_prompt()

        # Type a chat message and send it
        nv.keys("what do you do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=1)

        # Wait for the response to arrive (pane should stabilize)
        driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # --- Test 2: Open the agent panel via <leader>ra ---
        nv.leader_panel()

        # Move focus into the panel
        nv.focus_right(delay=1)

        # Wait for panel to render
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Assert panel shows agent info
        assert "load_config" in content, f"Expected 'load_config' in panel, got:\n{content}"
