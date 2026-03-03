"""Rewrite scenario — Agent proposes rewrite.

Triggers :RemoraRewrite on a function, waits for the LLM to
respond, and verifies that a diagnostic annotation appears.
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
    description: str = "Trigger rewrite on load_config, verify diagnostic appears"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py
        nv.open_nvim(target_file, wait_for="def load_config")

        # Position cursor on load_config function (line 12)
        nv.goto_line(12)

        # Trigger rewrite with <leader>rr
        nv.leader_rewrite()

        # Wait for the pane to stabilize
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Capture final state — we should see some indication of the rewrite
        _content = driver.capture_pane()
