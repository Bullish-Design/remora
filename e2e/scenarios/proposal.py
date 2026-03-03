"""Proposal scenario — Accept/reject a proposal.

Builds on the rewrite scenario: after the agent proposes a rewrite,
tests both accepting and rejecting the proposal via code actions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ProposalScenario:
    """Accept/reject proposal scenario."""

    name: str = "proposal"
    description: str = "After rewrite proposal, accept it via code action"

    def run(self, driver: TmuxDriver) -> None:
        # Launch nv2 on the test file (test agent will get the rewrite proposal)
        target_file = DEMO_PROJECT / "tests" / "test_loader.py"
        driver.send_keys(f"nv2 {target_file}")

        # Wait for Neovim + file content
        driver.wait_for_text("test_load_yaml", timeout=15)
        time.sleep(3)  # Let LSP initialize

        # Position cursor on test_load_yaml (line 13)
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("13")
        time.sleep(0.5)

        # Trigger rewrite with <leader>rr to get a proposal
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(5)  # Wait for mock LLM to process

        # Accept the proposal with <leader>ry
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("y")
        time.sleep(3)  # Wait for acceptance to process

        # Wait for pane to stabilize
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Capture final state
        _content = driver.capture_pane()
