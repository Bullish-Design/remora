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

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class GoldenPathScenario:
    """Full golden path demo scenario."""

    name: str = "golden_path"
    description: str = "Complete demo: startup -> chat -> edit -> cascade -> accept"

    def run(self, driver: TmuxDriver) -> None:
        # ---------------------------------------------------------------
        # Beat 1: Open nv2 on loader.py
        # ---------------------------------------------------------------
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        driver.send_keys(f"nv2 {target_file}")
        driver.wait_for_text("def load_config", timeout=15)
        time.sleep(3)  # LSP startup + background scan

        # ---------------------------------------------------------------
        # Beat 2: Explore the file — scroll through functions
        # ---------------------------------------------------------------
        # Move down through the file slowly for visual effect
        for _ in range(5):
            driver.send_raw("j")
            time.sleep(0.3)
        time.sleep(1)

        # Go back to top
        driver.send_raw("g")
        time.sleep(0.1)
        driver.send_raw("g")
        time.sleep(1)

        # ---------------------------------------------------------------
        # Beat 3: Open the Remora agent panel
        # ---------------------------------------------------------------
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("a")
        time.sleep(2)

        # ---------------------------------------------------------------
        # Beat 4: Position on load_config and chat
        # ---------------------------------------------------------------
        # Go to load_config function
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("12")
        time.sleep(1)

        # Chat with the agent
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("c")
        time.sleep(1)

        # Type the question
        driver.send_keys("what do you do?")
        time.sleep(4)  # Wait for mock response

        # ---------------------------------------------------------------
        # Beat 5: Edit load_config — add timeout parameter
        # ---------------------------------------------------------------
        # Focus back on the code (the panel input might have focus)
        # Use Ctrl-w h to go to the left window
        driver.send_raw("C-w")
        time.sleep(0.1)
        driver.send_raw("h")
        time.sleep(0.5)

        # Go to the function signature line
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("12")
        time.sleep(0.5)

        # Find the closing paren and insert the new parameter
        driver.send_raw("f)")
        time.sleep(0.2)
        driver.send_raw("i")
        time.sleep(0.2)
        driver.send_keys(", timeout: int = 30", enter=False)
        time.sleep(0.3)

        # Exit insert mode
        driver.send_raw("Escape")
        time.sleep(0.5)

        # Save to trigger content change
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("w")
        time.sleep(2)

        # ---------------------------------------------------------------
        # Beat 6: Watch the cascade unfold
        # ---------------------------------------------------------------
        # The mock LLM will:
        # 1. load_config agent detects change, messages test_load_yaml
        # 2. test_load_yaml agent reads source, then proposes rewrite
        time.sleep(8)  # Give the cascade time to complete

        # ---------------------------------------------------------------
        # Beat 7: Accept the proposal
        # ---------------------------------------------------------------
        # Open the test file to see the proposal
        driver.send_raw(":")
        time.sleep(0.2)
        test_file = DEMO_PROJECT / "tests" / "test_loader.py"
        driver.send_keys(f"e {test_file}")
        time.sleep(2)

        # Position on the test function
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("13")
        time.sleep(1)

        # Accept the proposal
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("y")
        time.sleep(3)

        # ---------------------------------------------------------------
        # Beat 8: Final stable state
        # ---------------------------------------------------------------
        driver.wait_for_stable(stable_seconds=3.0, timeout=15)

        # Capture final state for verification
        _content = driver.capture_pane()
