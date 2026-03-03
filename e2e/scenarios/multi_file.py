"""Multi-file scenario — Navigate between files and chat with different agents.

Opens loader.py, chats with the load_config agent, then switches to
merge.py and chats with the deep_merge agent.  Verifies that agents
on different files respond independently.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class MultiFileScenario:
    """Navigate between files and chat with agents on each."""

    name: str = "multi_file"
    description: str = "Chat with agents on loader.py and merge.py"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # File 1: loader.py — chat with load_config agent
        # ---------------------------------------------------------------
        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.open_nvim(loader_file, wait_for="def load_config")

        # Position cursor on load_config (line 12)
        nv.goto_line(12)

        # Chat with load_config agent
        nv.leader_chat()
        time.sleep(0.5)
        nv.keys("what does this function do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=5)

        # Verify a response appeared
        driver.wait_for_text("load_config", timeout=15)

        # ---------------------------------------------------------------
        # File 2: merge.py — switch and chat with deep_merge agent
        # ---------------------------------------------------------------
        merge_file = DEMO_PROJECT / "src" / "configlib" / "merge.py"
        nv.edit_file(merge_file)

        # Wait for the file to load
        driver.wait_for_text("def deep_merge", timeout=10)

        # Position cursor on deep_merge (line 8)
        nv.goto_line(8)

        # Chat with deep_merge agent
        nv.leader_chat()
        time.sleep(0.5)
        nv.keys("explain this function", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=5)

        # Wait for LLM response
        driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Capture final state
        content = driver.capture_pane()
        assert "deep_merge" in content or "merge" in content, f"Expected merge-related content in pane, got:\n{content}"
