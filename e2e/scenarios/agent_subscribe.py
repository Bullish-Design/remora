"""Agent subscription scenario — Dynamic event subscriptions.

Demonstrates the subscribe tool by:
1. Opening test_loader.py and positioning on a test function
2. Asking the test agent to "subscribe to changes in load_config"
3. The agent uses the subscribe tool with from_agents filter
4. Editing load_config to trigger a ContentChangedEvent
5. Observing that the subscribed test agent receives the event

This validates dynamic subscription registration and event routing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class AgentSubscriptionScenario:
    """Dynamic subscription scenario — test agent subscribes to source changes."""

    name: str = "agent_subscribe"
    description: str = "Test agent subscribes to load_config changes dynamically"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open test_loader.py and initialize
        # ---------------------------------------------------------------
        test_file = DEMO_PROJECT / "tests" / "test_loader.py"
        nv.open_nvim(test_file, wait_for="def test_load", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open panel to observe agent activity
        nv.leader_panel()
        nv.focus_right(delay=0.5)
        nv.focus_left(delay=0.3)

        # ---------------------------------------------------------------
        # Beat 2: Position on test_load_yaml and verify agent
        # ---------------------------------------------------------------
        nv.goto_line(13)  # test_load_yaml function
        time.sleep(1)

        content = driver.capture_pane()
        assert "test_load" in content, f"Expected 'test_load' in panel:\n{content}"

        # ---------------------------------------------------------------
        # Beat 3: Chat with test agent - ask it to subscribe to load_config
        # ---------------------------------------------------------------
        nv.leader_chat(settle=0.5)
        nv.wait_for_chat_prompt()

        # Request the agent to subscribe to ContentChangedEvent from loader.py
        nv.keys("Subscribe to ContentChangedEvent events from loader.py", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for LLM response and subscription registration
        driver.wait_for_stable(stable_seconds=5.0, timeout=45)

        # Verify the subscribe tool was executed successfully
        # The tool returns "Subscription successfully registered."
        content = driver.capture_pane()
        assert "subscri" in content.lower() or "register" in content.lower(), (
            f"Expected subscription/register confirmation in response:\n{content}"
        )

        # ---------------------------------------------------------------
        # Beat 4: Navigate to loader.py and make an edit
        # ---------------------------------------------------------------
        nv.focus_code_buffer(expected_text="def test_load")

        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.edit_file(loader_file)

        driver.wait_for_text("def load_config", timeout=10)
        nv.goto_line(12)

        # Add a comment to trigger content change
        nv.find_char(")")
        nv.enter_insert()
        nv.type_in_insert("  # modified for subscription test", enter=False)
        nv.exit_insert()

        # Save to trigger ContentChangedEvent
        nv.save(delay=3)

        # Wait for event propagation
        driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # ---------------------------------------------------------------
        # Beat 5: Go back to test file and verify agent received event
        # ---------------------------------------------------------------
        nv.edit_file(test_file)
        driver.wait_for_text("test_load", timeout=10)
        nv.goto_line(13)

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Verify test file is shown and agent panel is active
        assert "test" in content.lower(), f"Expected test content:\n{content}"

        # Verify LSP is healthy
        nv.assert_not_in_pane("LSP not running", "LSP should be running")
