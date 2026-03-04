"""Validation tests for demo scenario definitions.

Ensures scenario data is consistent: files exist, line numbers are
in range, steps reference valid languages, etc.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remora_demo.companion.demo.scenarios import (
    DemoScenario,
    DemoStep,
    coding_scenario,
    get_all_scenarios,
    research_scenario,
)


# ---------------------------------------------------------------------------
# Scenario structure tests
# ---------------------------------------------------------------------------


class TestScenarioStructure:
    def test_coding_scenario_has_steps(self, coding_scn: DemoScenario):
        assert len(coding_scn.steps) >= 3

    def test_research_scenario_has_steps(self, research_scn: DemoScenario):
        assert len(research_scn.steps) >= 3

    def test_get_all_returns_both(self, all_scenarios: list[DemoScenario]):
        assert len(all_scenarios) == 2
        names = {s.name for s in all_scenarios}
        assert len(names) == 2  # unique names

    def test_scenarios_have_narration(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            assert scn.pre_narration, f"{scn.name} missing pre_narration"
            assert scn.post_narration, f"{scn.name} missing post_narration"

    def test_scenarios_have_metadata(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            assert scn.name
            assert scn.description
            assert scn.workspace_path


# ---------------------------------------------------------------------------
# File existence tests
# ---------------------------------------------------------------------------


class TestScenarioFiles:
    def test_workspace_path_exists(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            assert Path(scn.workspace_path).exists(), f"Workspace path missing for {scn.name}: {scn.workspace_path}"

    def test_all_step_files_exist(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                assert Path(step.file).exists(), f"File missing for {scn.name} step {i}: {step.file}"

    def test_step_files_are_readable(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for step in scn.steps:
                content = Path(step.file).read_text()
                assert len(content) > 0, f"Empty file: {step.file}"


# ---------------------------------------------------------------------------
# Line number validation
# ---------------------------------------------------------------------------


class TestScenarioLineNumbers:
    def test_step_lines_in_range(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                path = Path(step.file)
                line_count = len(path.read_text().split("\n"))
                assert 1 <= step.line <= line_count, (
                    f"{scn.name} step {i}: line {step.line} out of range (file has {line_count} lines): {step.file}"
                )

    def test_step_columns_non_negative(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                assert step.col >= 0, f"{scn.name} step {i}: negative column {step.col}"


# ---------------------------------------------------------------------------
# Step metadata validation
# ---------------------------------------------------------------------------


class TestStepMetadata:
    def test_all_steps_have_captions(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                assert step.caption, f"{scn.name} step {i} has no caption"

    def test_pause_seconds_positive(self, all_scenarios: list[DemoScenario]):
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                assert step.pause_seconds > 0, f"{scn.name} step {i}: pause_seconds must be positive"

    def test_language_hint_matches_file_extension(self, all_scenarios: list[DemoScenario]):
        """If a language hint is set, it should be consistent with the file extension."""
        extension_map = {
            ".py": "python",
            ".md": "markdown",
            ".markdown": "markdown",
        }
        for scn in all_scenarios:
            for i, step in enumerate(scn.steps):
                if step.language:
                    ext = Path(step.file).suffix
                    expected = extension_map.get(ext)
                    if expected:
                        assert step.language == expected, (
                            f"{scn.name} step {i}: language '{step.language}' "
                            f"doesn't match extension '{ext}' (expected '{expected}')"
                        )


# ---------------------------------------------------------------------------
# DemoStep construction tests
# ---------------------------------------------------------------------------


class TestDemoStep:
    def test_defaults(self):
        step = DemoStep(file="test.py", line=10)
        assert step.col == 0
        assert step.caption == ""
        assert step.pause_seconds == 3.0
        assert step.language == ""

    def test_custom_values(self):
        step = DemoStep(
            file="main.py",
            line=42,
            col=8,
            caption="Testing",
            pause_seconds=5.0,
            language="python",
        )
        assert step.file == "main.py"
        assert step.line == 42
        assert step.col == 8
        assert step.caption == "Testing"
        assert step.pause_seconds == 5.0
        assert step.language == "python"


class TestDemoScenario:
    def test_defaults(self):
        scn = DemoScenario(
            name="Test",
            description="A test scenario",
            workspace_path="/tmp/test",
        )
        assert scn.steps == []
        assert scn.pre_narration == ""
        assert scn.post_narration == ""

    def test_with_steps(self):
        steps = [DemoStep(file="a.py", line=1), DemoStep(file="b.py", line=2)]
        scn = DemoScenario(
            name="Test",
            description="Testing",
            workspace_path="/tmp",
            steps=steps,
        )
        assert len(scn.steps) == 2
