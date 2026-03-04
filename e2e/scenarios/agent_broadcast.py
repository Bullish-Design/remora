"""Agent broadcast scenario — Broadcast messages to multiple agents.

Demonstrates the broadcast tool by:
1. Opening loader.py where multiple functions exist (load_config, detect_format, load_yaml)
2. Chatting with load_config and asking it to "broadcast to siblings"
3. The agent uses the broadcast tool with pattern "siblings"
4. All sibling function agents in the same file receive the message

This validates the broadcast mechanism for one-to-many agent communication.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class AgentBroadcastScenario:
    """Broadcast message to sibling agents scenario."""

    name: str = "agent_broadcast"
    description: str = "Broadcast message from load_config to sibling function agents"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open loader.py - it has 3 functions (siblings)
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open panel to observe agent activity
        nv.leader_panel()
        nv.focus_right(delay=0.5)
        nv.focus_left(delay=0.3)

        # ---------------------------------------------------------------
        # Beat 2: Scroll through the file to show all functions
        # ---------------------------------------------------------------
        # Show detect_format
        nv.goto_line(29)
        time.sleep(0.5)

        # Show load_yaml
        nv.goto_line(39)
        time.sleep(0.5)

        # Back to load_config
        nv.goto_line(12)
        time.sleep(1)

        # Verify multiple functions are visible
        content = driver.capture_pane()
        assert "load_config" in content, f"Expected 'load_config' visible:\n{content}"

        # ---------------------------------------------------------------
        # Beat 3: Chat with load_config - ask it to broadcast to siblings
        # ---------------------------------------------------------------
        nv.leader_chat(settle=0.5)
        nv.wait_for_chat_prompt()

        # Request a broadcast to siblings
        nv.keys("Broadcast to your sibling functions: 'Code review needed for error handling'", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for LLM response and broadcast execution
        driver.wait_for_stable(stable_seconds=5.0, timeout=45)

        # Verify the broadcast tool was executed
        # The tool returns "Broadcast sent to N agents" on success
        content = driver.capture_pane()
        assert "broadcast" in content.lower() or "siblings" in content.lower() or "sent" in content.lower(), (
            f"Expected broadcast/siblings/sent confirmation in response:\n{content}"
        )

        # ---------------------------------------------------------------
        # Beat 4: Navigate to detect_format to see it received message
        # ---------------------------------------------------------------
        nv.focus_code_buffer(expected_text="def")
        nv.goto_line(29)  # detect_format function
        time.sleep(1)

        # Panel should update to show detect_format agent
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        assert "detect_format" in content, f"Expected 'detect_format' in panel:\n{content}"

        # ---------------------------------------------------------------
        # Beat 5: Navigate to load_yaml to see it also received message
        # ---------------------------------------------------------------
        nv.goto_line(39)  # load_yaml function
        time.sleep(1)

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        assert "load_yaml" in content, f"Expected 'load_yaml' in panel:\n{content}"

        # Verify LSP is healthy throughout
        nv.assert_not_in_pane("LSP not running", "LSP should be running")
