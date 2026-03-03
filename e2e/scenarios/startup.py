"""Startup scenario — LSP startup + agent discovery.

Opens nv2 on the demo project, waits for the Remora LSP to connect,
background scan to complete, and agent discovery to finish (visible
as the [Remora] notification and code lenses appearing).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

# The demo project that nv2 opens
DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class StartupScenario:
    """LSP startup + agent discovery scenario."""

    name: str = "startup"
    description: str = "Open nv2 on demo project, verify LSP connects and discovers agents"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)
        target_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"

        # Launch nv2 on loader.py and wait for content + LSP startup
        nv.open_nvim(target_file, wait_for="load_config")

        # Wait for the Remora plugin initialization notification
        driver.wait_for_text("[Remora]", timeout=15)

        # Verify the buffer is showing the loader.py content
        content = driver.capture_pane()
        assert "def load_config" in content, f"Expected 'def load_config' in pane, got:\n{content}"

        # Wait for the pane to stabilize (LSP done processing)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)
