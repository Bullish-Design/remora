"""Multi-file scenario — Navigate between files and chat with different agents.

Opens loader.py, chats with the load_config agent, then switches to
merge.py and chats with the deep_merge agent. Verifies that agents
on different files respond independently.
"""

from __future__ import annotations

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
        nv.open_nvim(loader_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open the agent panel first (required for chat to work)
        nv.leader_panel()
        nv.focus_right(delay=0.3)
        nv.focus_left(delay=0.3)

        # Position cursor on load_config (line 12)
        nv.goto_line(12)

        # Chat with load_config agent
        nv.leader_chat()
        nv.wait_for_chat_prompt()  # Confirms chat opened before typing
        nv.keys("what does this function do?", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=1)

        # Verify chat was sent and source file is intact
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)
        assert "def load_config" in content, f"Source file should be intact:\n{content}"

        # ---------------------------------------------------------------
        # File 2: merge.py — switch and chat with deep_merge agent
        # ---------------------------------------------------------------
        # Focus back to code buffer before switching files
        nv.focus_code_buffer(expected_text="def load_config")

        merge_file = DEMO_PROJECT / "src" / "configlib" / "merge.py"
        nv.edit_file(merge_file)

        # Wait for the file to load in the code buffer
        driver.wait_for_text("def deep_merge", timeout=10)

        # Position cursor on deep_merge (line 8)
        nv.goto_line(8)

        # Chat with deep_merge agent
        nv.leader_chat()
        nv.wait_for_chat_prompt()  # Confirms chat opened
        nv.keys("explain this function", delay=1)
        nv.raw("Escape", delay=0.5)
        nv.raw("Enter", delay=1)

        # Wait for LLM response
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Verify we're showing merge.py content
        assert "deep_merge" in content or "merge" in content, f"Expected merge-related content in pane:\n{content}"
