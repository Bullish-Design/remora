"""Reject scenario — Trigger rewrite then reject the proposal.

Exercises the <leader>rn (reject) keybinding. Triggers a rewrite on
a function, waits for the proposal to appear, rejects it, and verifies
the file is unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class RejectScenario:
    """Trigger rewrite on a function, then reject the proposal."""

    name: str = "reject"
    description: str = "Trigger rewrite on detect_format, reject the proposal"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py with event-driven LSP wait
        nv.open_nvim(target_file, wait_for="def load_config", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Position cursor on detect_format (line 29)
        nv.goto_line(29)

        # Trigger rewrite with <leader>rr
        nv.leader_rewrite()

        # Wait for the LLM to produce a proposal
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # Assert LSP was ready and processed the rewrite
        assert "LSP not running" not in content, f"LSP should be ready but got 'not running':\n{content}"

        # Reject the proposal with <leader>rn
        nv.leader_reject()

        # Wait for pane to stabilize after rejection
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Verify detect_format is still present and unchanged
        assert "def detect_format" in content, f"Expected 'def detect_format' in pane after rejection:\n{content}"
