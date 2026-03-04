"""Edit cascade scenario — Edit code, watch extensions react to changes.

Opens schema.py, edits the SchemaError class (adding a severity attribute),
saves. The LSP re-parses and the ClassDocGenerator extension reacts to the
content change. Then opens loader.py, edits load_config (adding a timeout
parameter), saves. The FunctionTestScaffold extension reacts. Opens the
panel to show the updated agent state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ExtEditCascadeScenario:
    """Edit code in multiple files, watch extensions react to changes."""

    name: str = "ext_edit_cascade"
    description: str = "Edit SchemaError + load_config, watch extension agents react"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open schema.py and let LSP discover nodes
        # ---------------------------------------------------------------
        schema_file = DEMO_PROJECT / "src" / "configlib" / "schema.py"
        nv.open_nvim(schema_file, wait_for="class SchemaError", lsp_delay=0)
        nv.wait_for_lsp_ready()

        # Open the panel to watch agent activity
        nv.leader_panel()
        nv.focus_right()
        time.sleep(1)
        nv.focus_left()

        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # ---------------------------------------------------------------
        # Beat 2: Edit SchemaError class — add severity attribute
        # ---------------------------------------------------------------
        # Go to __init__ body (line 12), add after the self.field line
        nv.goto_line(12)

        # Open a new line below and type the new attribute
        nv.raw("o", delay=0.3)  # open new line below in insert mode
        nv.type_in_insert('        self.severity = "error"', enter=False)
        nv.exit_insert()

        # Save to trigger content change detection
        nv.save(delay=3)

        # Wait for LSP to re-parse and extension to react
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Verify the edit persisted
        assert "severity" in content, f"Edit should be visible in schema.py:\n{content}"

        # ---------------------------------------------------------------
        # Beat 3: Navigate to loader.py
        # ---------------------------------------------------------------
        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.edit_file(loader_file, delay=3)

        driver.wait_for_text("def load_config", timeout=10)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # ---------------------------------------------------------------
        # Beat 4: Edit load_config — add timeout parameter
        # ---------------------------------------------------------------
        nv.goto_line(12)  # load_config signature

        # Find the closing paren of the signature and insert before it
        nv.find_char(")")
        nv.enter_insert()
        nv.type_in_insert(", timeout: int = 30", enter=False)
        nv.exit_insert()

        # Save to trigger content change
        nv.save(delay=3)

        # Wait for extension reaction
        content = driver.wait_for_stable(stable_seconds=3.0, timeout=20)

        # Verify the edit persisted
        assert "timeout" in content, f"Edit should be visible in loader.py:\n{content}"

        # ---------------------------------------------------------------
        # Beat 5: Final state — panel shows updated agents
        # ---------------------------------------------------------------
        # Briefly focus on panel to capture its state
        nv.focus_right()
        time.sleep(1)
        nv.focus_left()

        content = driver.wait_for_stable(stable_seconds=2.0, timeout=10)

        # Verify panel shows correct agent
        assert "load_config" in content, f"Expected 'load_config' in panel:\n{content}"
