"""Proposal scenario — Accept a proposal.

Builds on the rewrite scenario: after the agent proposes a rewrite,
tests accepting the proposal via <leader>ry.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ProposalScenario:
    """Accept proposal scenario."""

    name: str = "proposal"
    description: str = "After rewrite proposal, accept it via code action"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "tests" / "test_loader.py"

        # Launch nv2 on the test file with event-driven LSP wait
        nv.open_nvim(target_file, wait_for="test_load_yaml", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Position cursor on test_load_yaml (line 13)
        nv.goto_line(13)

        # Trigger rewrite with <leader>rr to get a proposal
        nv.leader_rewrite()

        # Wait for proposal to be processed
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=30)

        # Assert LSP was ready
        assert "LSP not running" not in content, f"LSP should be ready but got 'not running':\n{content}"

        # Accept the proposal with <leader>ry
        nv.leader_accept()

        # Wait for pane to stabilize after acceptance
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Verify we're still showing the test file
        assert "test_load" in content, f"Expected 'test_load' in pane after acceptance:\n{content}"
