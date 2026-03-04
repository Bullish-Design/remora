"""Companion Pipeline scenario -- Full agent cascade, recorded to GIF.

Exercises the entire Companion pipeline through a realistic workflow
with deliberate pacing and status-line narration for GIF recording:

1. Open processor.py, let agents index and populate sidebar
2. Navigate through multiple functions, watch sidebar update
3. Switch to test file, show reverse connections
4. Switch to architecture docs, show doc-code connections
5. Return to source, toggle sidebar off/on for finale

Run with:
    devenv shell -- python -m e2e.run --scenario companion_pipeline --gif
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.companion_keys import CompanionKeys, COMPANION_EXAMPLES

# ---------------------------------------------------------------------------
# GIF-friendly timing (longer pauses so viewers can read)
# ---------------------------------------------------------------------------

# Pause after narration echo so the message is visible in the recording
NARRATION_PAUSE = 1.5

# Hold time after sidebar updates so the viewer sees the new content
SIDEBAR_VIEW_PAUSE = 2.5

# Hold time when switching files so the transition is visible
FILE_SWITCH_PAUSE = 1.5


def _narrate(ck: CompanionKeys, msg: str, pause: float = NARRATION_PAUSE) -> None:
    """Echo a narration message in the Neovim command line.

    This shows up in the recording as a status-bar caption.
    """
    # Escape any single quotes in the message
    safe = msg.replace("'", "''")
    ck.ex(f"echo '{safe}'", delay=pause)


@dataclass
class CompanionPipelineScenario:
    """Full pipeline: indexing -> cursor -> context -> search -> connections -> sidebar."""

    name: str = "companion_pipeline"
    description: str = "Full agent pipeline: index, navigate, connect, compose (GIF)"

    def run(self, driver: TmuxDriver) -> None:
        ck = CompanionKeys(driver)

        processor_file = COMPANION_EXAMPLES / "src" / "processor.py"
        validator_file = COMPANION_EXAMPLES / "src" / "validators.py"
        test_file = COMPANION_EXAMPLES / "tests" / "test_processor.py"
        docs_file = COMPANION_EXAMPLES / "docs" / "architecture.md"

        # ==================================================================
        # Phase 1: Launch and initial indexing
        # ==================================================================
        ck.open_companion(
            processor_file,
            wait_for="DataProcessor",
            lsp_delay=5.0,  # Embedding model load time
            with_sidebar=True,
        )

        content = driver.capture_pane()
        assert "DataProcessor" in content, f"Expected 'DataProcessor' in pane:\n{content}"

        _narrate(ck, "Companion started -- agents indexing workspace...")

        # Wait for initial agent cascade to complete
        # cursor_tracker -> context_extractor -> embedding_searcher ->
        # connection_finder -> sidebar_composer
        content = ck.wait_for_agents_to_settle(stable_seconds=4.0, timeout=30)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # ==================================================================
        # Phase 2: Navigate through processor.py
        # ==================================================================
        _narrate(ck, "Navigating to DataProcessor class...")

        ck.navigate_to_class("DataProcessor")
        time.sleep(0.5)
        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        _narrate(ck, "Moving to load_data() -- sidebar updates automatically")

        ck.navigate_to_function("load_data")
        time.sleep(0.5)
        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        _narrate(ck, "Jumping to process_batch() -- watch similar code change")

        ck.navigate_to_function("process_batch")
        time.sleep(0.5)
        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # ==================================================================
        # Phase 3: Cross-file -- validators.py
        # ==================================================================
        _narrate(ck, "Opening validators.py -- cross-file navigation")

        ck.edit_file(str(validator_file), delay=FILE_SWITCH_PAUSE)
        driver.wait_for_text("validate", timeout=10)
        time.sleep(1.0)

        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)

        content = driver.capture_pane()
        assert "validate" in content.lower() or "def " in content, f"Expected validator code visible:\n{content}"
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # ==================================================================
        # Phase 4: Test file -- reverse connections
        # ==================================================================
        _narrate(ck, "Switching to test_processor.py -- reverse connections")

        ck.edit_file(str(test_file), delay=FILE_SWITCH_PAUSE)
        driver.wait_for_text("test_", timeout=10)
        time.sleep(1.0)

        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        _narrate(ck, "Sidebar shows connection back to processor.py")

        ck.navigate_to_function("test_")
        time.sleep(0.5)
        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=2.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # ==================================================================
        # Phase 5: Architecture docs -- doc-code connections
        # ==================================================================
        _narrate(ck, "Opening architecture.md -- doc-code connections")

        ck.edit_file(str(docs_file), delay=FILE_SWITCH_PAUSE)
        driver.wait_for_text("Architecture", timeout=10)
        time.sleep(1.0)

        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # ==================================================================
        # Phase 6: Return to processor.py -- finale
        # ==================================================================
        _narrate(ck, "Back to processor.py -- full circle")

        ck.edit_file(str(processor_file), delay=FILE_SWITCH_PAUSE)
        driver.wait_for_text("DataProcessor", timeout=10)
        time.sleep(1.0)

        ck.refresh_sidebar(settle=2.0)
        ck.wait_for_agents_to_settle(stable_seconds=3.0, timeout=15)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # Toggle sidebar off and on to show responsiveness
        _narrate(ck, "Toggling sidebar off...")
        ck.toggle_sidebar(settle=1.0)
        time.sleep(1.0)

        _narrate(ck, "...and back on. Ambient knowledge, always ready.")
        ck.toggle_sidebar(settle=1.0)
        time.sleep(SIDEBAR_VIEW_PAUSE)

        # Final hold for the recording
        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        assert "def " in content or "class " in content, f"Expected code visible in final state:\n{content}"
