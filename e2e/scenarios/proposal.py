"""Proposal scenario — Accept/reject a proposal.

Builds on the rewrite scenario: after the agent proposes a rewrite,
tests both accepting and rejecting the proposal via code actions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ProposalScenario:
    """Accept/reject proposal scenario."""

    name: str = "proposal"
    description: str = "After rewrite proposal, accept it via code action"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "tests" / "test_loader.py"

        # Launch nv2 on the test file
        nv.open_nvim(target_file, wait_for="test_load_yaml")

        # Position cursor on test_load_yaml (line 13)
        nv.goto_line(13)

        # Trigger rewrite with <leader>rr to get a proposal
        nv.leader_rewrite()

        # Accept the proposal with <leader>ry
        nv.leader_accept()

        # Wait for pane to stabilize
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Capture final state
        _content = driver.capture_pane()
