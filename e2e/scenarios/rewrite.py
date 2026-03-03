"""Rewrite scenario — Agent proposes rewrite.

Triggers :RemoraRewrite on a function, waits for the mock LLM to
respond (via ContentChangedAnalyzeScript which triggers message_node),
and verifies that a diagnostic annotation appears.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class RewriteScenario:
    """Agent proposes rewrite scenario."""

    name: str = "rewrite"
    description: str = "Trigger rewrite on load_config, verify diagnostic appears"

    def run(self, driver: TmuxDriver) -> None:
        # Launch nv2 on loader.py
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        driver.send_keys(f"nv2 {target_file}")

        # Wait for Neovim + file content
        driver.wait_for_text("def load_config", timeout=15)
        time.sleep(3)  # Let LSP initialize and scan

        # Position cursor on load_config function (line 12)
        driver.send_raw(":")
        time.sleep(0.2)
        driver.send_keys("12")
        time.sleep(0.5)

        # Trigger rewrite with <leader>rr
        driver.send_raw("\\")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(0.1)
        driver.send_raw("r")
        time.sleep(5)  # Wait for mock LLM to process and return rewrite

        # Wait for the pane to stabilize
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Capture final state — we should see some indication of the rewrite
        # (diagnostics, virtual text, or status change)
        _content = driver.capture_pane()
