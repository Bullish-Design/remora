"""Golden path scenario — Full demo flow.

Combines all scenario beats into one continuous recording:
1. Open nv2 on demo project
2. Explore the file (cursor movement, scroll)
3. Open agent panel
4. Chat with load_config agent ("what do you do?")
5. Edit load_config to add timeout parameter
6. Watch cascade: load_config agent -> test_load_yaml agent
7. See test agent propose a rewrite
8. Accept the proposal
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class GoldenPathScenario:
    """Full golden path demo scenario."""

    name: str = "golden_path"
    description: str = "Complete demo: startup -> chat -> edit -> cascade -> accept"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open nv2 on loader.py with event-driven LSP wait
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # ---------------------------------------------------------------
        # Beat 2: Explore the file — scroll through functions
        # ---------------------------------------------------------------
        nv.move_down(15, delay=0.3)
        time.sleep(1)
        nv.goto_top()

        # ---------------------------------------------------------------
        # Beat 3: Open the Remora agent panel
        # ---------------------------------------------------------------
        nv.leader_panel()

        # Move focus into the panel to show it, then back to code
        nv.focus_right()
        nv.focus_left()

        # ---------------------------------------------------------------
        # Beat 4: Position on load_config and chat
        # ---------------------------------------------------------------
        nv.goto_line(13, delay=1)

        # Chat with the agent
        nv.leader_chat(settle=0.5)

        # Wait for chat prompt to appear before typing
        nv.wait_for_chat_prompt()

        # Type the question and send
        nv.keys("what do you do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=2)

        # Wait for response to arrive
        driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # ---------------------------------------------------------------
        # Beat 5: Edit load_config — add timeout parameter
        # ---------------------------------------------------------------
        # Focus back on the code using reliable method
        nv.focus_code_buffer(expected_text="def load_config")

        # Verify we're in the code buffer
        content = driver.capture_pane()
        assert "def load_config" in content, f"Should be in code buffer:\n{content}"

        # Go to the function signature line
        nv.goto_line(12)

        # Find the closing paren and insert the new parameter
        nv.find_char(")")
        nv.enter_insert()
        nv.type_in_insert(", timeout: int = 30", enter=False, delay=0.3)
        nv.exit_insert()

        # Save to trigger content change
        nv.save(delay=2)

        # Verify the edit persisted
        content = driver.capture_pane()
        assert "timeout" in content, f"Edit should be visible:\n{content}"

        # ---------------------------------------------------------------
        # Beat 6: Watch the cascade unfold
        # ---------------------------------------------------------------
        time.sleep(8)

        # ---------------------------------------------------------------
        # Beat 7: Accept the proposal
        # ---------------------------------------------------------------
        # Open the test file to see the proposal
        test_file = DEMO_PROJECT / "tests" / "test_loader.py"
        nv.edit_file(test_file)

        # Wait for file to load
        driver.wait_for_text("test_load", timeout=10)

        # Position on the test function
        nv.goto_line(13, delay=1)

        # Accept the proposal
        nv.leader_accept()

        # ---------------------------------------------------------------
        # Beat 8: Final stable state
        # ---------------------------------------------------------------
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=15)

        # Verify test file is showing
        assert "test_load" in content, f"Expected test file content:\n{content}"
