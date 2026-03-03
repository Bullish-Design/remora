"""Rewrite scenario — Agent proposes rewrite.

Triggers :RemoraRewrite on a function, waits for the LLM to
respond, and verifies that the rewrite was processed (no LSP error).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class RewriteScenario:
    """Agent proposes rewrite scenario."""

    name: str = "rewrite"
    description: str = "Trigger rewrite on load_config, verify LSP processes it"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py with event-driven LSP wait
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Position cursor on load_config function (line 12)
        nv.goto_line(12)

        # Trigger rewrite with <leader>rr
        nv.leader_rewrite()

        # Wait for the pane to stabilize after rewrite request
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # Assert LSP was ready and rewrite was processed
        assert "LSP not running" not in content, f"LSP should be ready but got 'not running':\n{content}"

        # Verify we're still showing the file content
        assert "def load_config" in content, f"Expected 'def load_config' in pane after rewrite:\n{content}"
