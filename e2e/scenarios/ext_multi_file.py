"""Multi-file extension scenario — Navigate across files, see different extensions.

Opens schema.py (ClassDocGenerator for SchemaError, FunctionTestScaffold for
validate), then navigates to loader.py (FunctionTestScaffold for all three
functions), then to merge.py (FunctionTestScaffold for deep_merge and
merge_dicts). Shows that different node types in different files get the
correct extension assignments.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from e2e.harness import TmuxDriver
from e2e.keys import NvimKeys

DEMO_PROJECT = Path(__file__).parent.parent.parent / "remora_demo" / "project"


@dataclass
class ExtMultiFileScenario:
    """Navigate across files to show different extensions per node type."""

    name: str = "ext_multi_file"
    description: str = "Navigate schema.py -> loader.py -> merge.py, see extension diversity"

    def run(self, driver: TmuxDriver) -> None:
        nv = NvimKeys(driver)

        # ---------------------------------------------------------------
        # Beat 1: Open schema.py — class gets ClassDocGenerator,
        #         function gets FunctionTestScaffold
        # ---------------------------------------------------------------
        schema_file = DEMO_PROJECT / "src" / "configlib" / "schema.py"
        nv.open_nvim(schema_file, wait_for="class SchemaError")

        # Open the panel so we see agent assignments
        nv.leader_panel()
        nv.focus_right()
        time.sleep(1)
        nv.focus_left()

        # Scroll through — class first, then function
        nv.goto_line(8)  # class SchemaError line
        time.sleep(1)
        nv.goto_line(16)  # def validate line
        time.sleep(1)

        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # ---------------------------------------------------------------
        # Beat 2: Navigate to loader.py — three functions, all get
        #         FunctionTestScaffold
        # ---------------------------------------------------------------
        loader_file = DEMO_PROJECT / "src" / "configlib" / "loader.py"
        nv.edit_file(loader_file, delay=3)

        driver.wait_for_text("def load_config", timeout=10)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Scroll through the functions
        nv.goto_line(12)  # load_config
        time.sleep(0.5)
        nv.goto_line(29)  # detect_format
        time.sleep(0.5)
        nv.goto_line(39)  # load_yaml
        time.sleep(0.5)

        # ---------------------------------------------------------------
        # Beat 3: Navigate to merge.py — two functions, both get
        #         FunctionTestScaffold
        # ---------------------------------------------------------------
        merge_file = DEMO_PROJECT / "src" / "configlib" / "merge.py"
        nv.edit_file(merge_file, delay=3)

        driver.wait_for_text("def deep_merge", timeout=10)
        driver.wait_for_stable(stable_seconds=2.0, timeout=15)

        # Scroll through
        nv.goto_line(8)  # deep_merge
        time.sleep(0.5)
        nv.goto_line(19)  # merge_dicts
        time.sleep(0.5)

        # ---------------------------------------------------------------
        # Beat 4: Final stable state
        # ---------------------------------------------------------------
        driver.wait_for_stable(stable_seconds=2.0, timeout=10)
        _content = driver.capture_pane()
