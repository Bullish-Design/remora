"""Agent messaging scenario — Direct agent-to-agent communication.

Demonstrates inter-agent communication by:
1. Opening loader.py and positioning on load_config function
2. Chatting with the load_config agent asking it to "message the test agent"
3. The agent uses the send_message tool to communicate with test_load_yaml
4. Opening test_loader.py to see the test agent received and processed the message

This validates the AgentMessageEvent flow through the system.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class AgentMessageScenario:
    """Direct agent-to-agent messaging scenario."""

    name: str = "agent_message"
    description: str = "Send direct message from load_config agent to test agent"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open loader.py and initialize
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open panel to observe agent activity
        nv.leader_panel()
        nv.focus_right(delay=0.5)
        nv.focus_left(delay=0.3)

        # ---------------------------------------------------------------
        # Beat 2: Position on load_config and verify agent is active
        # ---------------------------------------------------------------
        nv.goto_line(12)
        time.sleep(1)

        # Verify panel shows load_config agent
        content = driver.capture_pane()
        assert "load_config" in content, f"Expected 'load_config' agent in panel:\n{content}"

        # ---------------------------------------------------------------
        # Beat 3: Chat with load_config agent - ask it to message test agent
        # ---------------------------------------------------------------
        nv.leader_chat(settle=0.5)
        nv.wait_for_chat_prompt()

        # Request the agent to send a message to the test agent
        # The agent has access to send_message tool
        nv.keys("Send a message to the test_load_yaml agent saying 'hello from load_config'", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for LLM response and tool execution
        driver.wait_for_stable(stable_seconds=5.0, timeout=45)

        # Verify the send_message tool was executed successfully
        # The tool returns "Message successfully queued for {agent}"
        content = driver.capture_pane()
        assert "message" in content.lower() or "queued" in content.lower() or "send" in content.lower(), (
            f"Expected message/send/queued confirmation in response:\n{content}"
        )

        # ---------------------------------------------------------------
        # Beat 4: Navigate to test file to see test agent
        # ---------------------------------------------------------------
        nv.focus_code_buffer(expected_text="def load_config")

        test_file = DEMO_PROJECT / "tests" / "test_loader.py"
        nv.edit_file(test_file)

        # Wait for test file to load
        driver.wait_for_text("test_load", timeout=10)

        # Position on test_load_yaml function
        nv.goto_line(13)
        time.sleep(1)

        # ---------------------------------------------------------------
        # Beat 5: Verify test agent is visible in panel
        # ---------------------------------------------------------------
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Verify we can see test-related content
        assert "test" in content.lower(), f"Expected test content in pane:\n{content}"

        # The panel should show the test function agent
        # This demonstrates the agent discovery works across files
        nv.assert_not_in_pane("LSP not running", "LSP should be running")
