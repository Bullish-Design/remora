"""Companion Connections scenario -- Show test↔code and doc↔code connections.

Opens nv2 on processor.py, demonstrates the Companion's ability to
detect and display connections between:
- Source code and its test file (test_processor.py)
- Source code and documentation that references it (CQRS docs)

This scenario showcases the connection_finder agent's intelligence.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.companion_keys import CompanionKeys, COMPANION_EXAMPLES


@dataclass
class CompanionConnectionsScenario:
    """Show connection detection between code, tests, and docs."""

    name: str = "companion_connections"
    description: str = "Demonstrate test↔code and doc↔code connection detection"

    def run(self, driver: TmuxDriver) -> None:
        ck = CompanionKeys(driver)
        processor_file = COMPANION_EXAMPLES / "src" / "processor.py"
        test_file = COMPANION_EXAMPLES / "tests" / "test_processor.py"
        docs_file = COMPANION_EXAMPLES / "docs" / "architecture.md"

        # ------------------------------------------------------------------
        # 1. Open processor.py with Companion
        # ------------------------------------------------------------------
        ck.open_companion(
            processor_file,
            wait_for="DataProcessor",
            lsp_delay=3.0,
            with_sidebar=True,
        )

        content = driver.capture_pane()
        assert "DataProcessor" in content, f"Expected 'DataProcessor' in pane:\n{content}"

        # ------------------------------------------------------------------
        # 2. Navigate to DataProcessor class
        # ------------------------------------------------------------------
        ck.navigate_to_class("DataProcessor")
        time.sleep(1.0)

        # Trigger cursor update
        ck.refresh_sidebar(settle=2.0)

        # Wait for connection_finder to process
        # It should find:
        # - test_processor.py (contains tests for DataProcessor)
        content = ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=20)

        # ------------------------------------------------------------------
        # 3. Look for CQRS pattern references
        # ------------------------------------------------------------------
        # The processor.py mentions "CQRS pattern" in the docstring
        # The docs/architecture.md and docs/cqrs_notes.md reference it

        # Navigate to the CQRS mention in the docstring
        ck.raw("/", delay=0.2)
        ck.keys("CQRS", delay=0.5)
        time.sleep(0.5)

        # Refresh sidebar
        ck.refresh_sidebar(settle=2.0)
        content = ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)

        # ------------------------------------------------------------------
        # 4. Jump to test file to show reverse connection
        # ------------------------------------------------------------------
        # Open test_processor.py
        ck.edit_file(str(test_file), delay=2.0)

        # Wait for content to load
        driver.wait_for_text("test_", timeout=10)
        time.sleep(1.0)

        # Open/refresh sidebar for test file
        ck.toggle_sidebar(settle=1.0)  # Ensure sidebar is visible
        ck.refresh_sidebar(settle=2.0)

        # The sidebar should now show connection back to processor.py
        content = ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)

        # ------------------------------------------------------------------
        # 5. Jump to architecture docs
        # ------------------------------------------------------------------
        ck.edit_file(str(docs_file), delay=2.0)

        # Wait for markdown content
        driver.wait_for_text("Architecture", timeout=10)
        time.sleep(1.0)

        # Refresh sidebar
        ck.refresh_sidebar(settle=2.0)
        content = ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)

        # ------------------------------------------------------------------
        # 6. Return to processor.py for final state
        # ------------------------------------------------------------------
        ck.edit_file(str(processor_file), delay=2.0)
        driver.wait_for_text("DataProcessor", timeout=10)
        time.sleep(1.0)

        # Final sidebar refresh
        ck.refresh_sidebar(settle=2.0)
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Verify we're looking at the code
        assert "def " in content or "class " in content, f"Expected code visible in final state:\n{content}"
