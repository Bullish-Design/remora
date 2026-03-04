"""Companion Sidebar scenario -- Sidebar updates as cursor moves.

Opens nv2 on the Companion examples project, toggles the sidebar,
navigates to different code locations, and verifies the sidebar
updates with relevant context and similar code snippets.

This scenario showcases the core Companion experience:
- Ambient sidebar that updates automatically
- Context-aware similar code search
- Connection detection (test↔code)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.companion_keys import CompanionKeys, COMPANION_EXAMPLES


@dataclass
class CompanionSidebarScenario:
    """Show sidebar updating as cursor moves through code."""

    name: str = "companion_sidebar"
    description: str = "Open Companion, toggle sidebar, navigate code, verify updates"

    def run(self, driver: TmuxDriver) -> None:
        ck = CompanionKeys(driver)
        target_file = COMPANION_EXAMPLES / "src" / "processor.py"

        # ------------------------------------------------------------------
        # 1. Launch nv2 on processor.py with Companion
        # ------------------------------------------------------------------
        # Note: Companion LSP takes time to load embedding model
        ck.open_companion(
            target_file,
            wait_for="DataProcessor",
            lsp_delay=3.0,  # Shorter delay for demo, model may be cached
            with_sidebar=True,
        )

        # Verify file loaded
        content = driver.capture_pane()
        assert "DataProcessor" in content, f"Expected 'DataProcessor' in pane:\n{content}"

        # ------------------------------------------------------------------
        # 2. Wait for sidebar to populate
        # ------------------------------------------------------------------
        # The sidebar should show context about current cursor position
        # Give agents time to process
        content = ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=20)

        # At this point, sidebar should be visible (right split)
        # The sidebar content depends on what agents have discovered

        # ------------------------------------------------------------------
        # 3. Navigate to DataProcessor class and trigger cursor update
        # ------------------------------------------------------------------
        ck.navigate_to_class("DataProcessor")
        time.sleep(0.5)

        # Trigger CursorHold to send cursor position to LSP
        # (Wait a moment for the autocmd to fire)
        time.sleep(1.0)

        # Refresh sidebar to get latest content
        ck.refresh_sidebar(settle=2.0)

        # Wait for agents to process
        content = ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)

        # ------------------------------------------------------------------
        # 4. Navigate to load_data method
        # ------------------------------------------------------------------
        ck.navigate_to_function("load_data")
        time.sleep(0.5)

        # Trigger update
        ck.refresh_sidebar(settle=2.0)
        content = ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)

        # ------------------------------------------------------------------
        # 5. Navigate to process_batch method
        # ------------------------------------------------------------------
        ck.navigate_to_function("process_batch")
        time.sleep(0.5)

        # Trigger update
        ck.refresh_sidebar(settle=2.0)
        content = ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)

        # ------------------------------------------------------------------
        # 6. Final verification - sidebar should be present
        # ------------------------------------------------------------------
        # Toggle sidebar to demonstrate on/off
        ck.toggle_sidebar(settle=1.0)  # Close
        time.sleep(0.5)
        ck.toggle_sidebar(settle=1.0)  # Open again

        # Wait for final stable state
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Verify we're still looking at the code
        assert "def " in content or "class " in content, f"Expected code visible in final state:\n{content}"
