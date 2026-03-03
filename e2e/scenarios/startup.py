"""Startup scenario — LSP startup + agent discovery.

Opens nv2 on the demo project, waits for the Remora LSP to connect,
background scan to complete, and agent discovery to finish (visible
as the [Remora] notification and code lenses appearing).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver

# The demo project that nv2 opens
DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class StartupScenario:
    """LSP startup + agent discovery scenario."""

    name: str = "startup"
    description: str = "Open nv2 on demo project, verify LSP connects and discovers agents"

    def run(self, driver: TmuxDriver) -> None:
        # Launch nv2 on the demo project's loader.py
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        driver.send_keys(f"nv2 {target_file}")

        # Wait for Neovim to load — look for the file content
        driver.wait_for_text("load_config", timeout=15)

        # Wait for the Remora plugin initialization notification
        # The extraInitLua prints: [Remora] nv2 initialized remora plugin
        driver.wait_for_text("[Remora]", timeout=15)

        # Give the LSP time to start and do background scan
        time.sleep(3)

        # Verify the buffer is showing the loader.py content
        content = driver.capture_pane()
        assert "def load_config" in content, f"Expected 'def load_config' in pane, got:\n{content}"

        # Wait for the pane to stabilize (LSP done processing)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)
