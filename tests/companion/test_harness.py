"""Integration tests for DemoHarness.

Tests the harness configuration, frame capture, and the scenario
execution plumbing — without running the full pipeline (which
requires the embedding model). Full pipeline tests are in
test_pipeline.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import remora_demo.companion.runtime as _runtime_mod
from remora_demo.companion.demo.harness import DemoConfig, DemoHarness
from remora_demo.companion.demo.renderer import RenderConfig
from remora_demo.companion.demo.scenarios import DemoScenario, DemoStep


# ---------------------------------------------------------------------------
# DemoConfig tests
# ---------------------------------------------------------------------------


class TestDemoConfig:
    def test_defaults(self):
        cfg = DemoConfig()
        assert cfg.agent_settle_time == 0.8
        assert cfg.step_transition_time == 0.5
        assert cfg.capture_frames is False
        assert cfg.auto_advance is True
        assert cfg.interactive is False

    def test_render_config_embedded(self):
        cfg = DemoConfig()
        assert isinstance(cfg.render, RenderConfig)
        assert cfg.render.total_width == 100

    def test_custom_values(self):
        cfg = DemoConfig(
            agent_settle_time=0.1,
            step_transition_time=0.1,
            capture_frames=True,
            interactive=True,
        )
        assert cfg.agent_settle_time == 0.1
        assert cfg.capture_frames is True
        assert cfg.interactive is True


# ---------------------------------------------------------------------------
# DemoHarness construction tests
# ---------------------------------------------------------------------------


class TestDemoHarnessConstruction:
    def test_default_construction(self):
        harness = DemoHarness()
        assert harness.config is not None
        assert harness._renderer is not None
        assert harness._runtime is None
        assert harness._frame_count == 0

    def test_custom_config(self):
        cfg = DemoConfig(agent_settle_time=0.05, step_transition_time=0.05)
        harness = DemoHarness(cfg)
        assert harness.config.agent_settle_time == 0.05


# ---------------------------------------------------------------------------
# Frame capture tests
# ---------------------------------------------------------------------------


class TestFrameCapture:
    def test_capture_frame_creates_file(self, tmp_path: Path):
        cfg = DemoConfig(
            capture_frames=True,
            capture_dir=tmp_path / "frames",
        )
        harness = DemoHarness(cfg)
        # Set up some editor content so the renderer has something to draw
        harness._renderer.editor.file_path = "test.py"
        harness._renderer.editor.lines = ["import sys", "print('hello')"]
        harness._renderer.editor.cursor_line = 1

        harness._capture_frame("Test Scenario", 0)

        expected_file = tmp_path / "frames" / "test_scenario_step_00.txt"
        assert expected_file.exists()
        content = expected_file.read_text()
        assert "test.py" in content
        assert harness._frame_count == 1

    def test_capture_frame_increments_count(self, tmp_path: Path):
        cfg = DemoConfig(
            capture_frames=True,
            capture_dir=tmp_path / "frames",
        )
        harness = DemoHarness(cfg)
        harness._renderer.editor.lines = ["x = 1"]
        harness._renderer.editor.file_path = "x.py"

        harness._capture_frame("Demo", 0)
        harness._capture_frame("Demo", 1)
        harness._capture_frame("Demo", 2)
        assert harness._frame_count == 3

    def test_capture_creates_directory(self, tmp_path: Path):
        deep_dir = tmp_path / "a" / "b" / "c" / "frames"
        cfg = DemoConfig(capture_frames=True, capture_dir=deep_dir)
        harness = DemoHarness(cfg)
        harness._renderer.editor.lines = ["x = 1"]
        harness._renderer.editor.file_path = "x.py"

        harness._capture_frame("Demo", 0)
        assert deep_dir.exists()


# ---------------------------------------------------------------------------
# Scenario run integration (with mocked runtime)
# ---------------------------------------------------------------------------


class TestHarnessRunWithMockedRuntime:
    """Tests that run scenarios with the CompanionRuntime mocked out.

    This verifies the harness plumbing without needing the embedding model.
    """

    @pytest.fixture
    def fast_config(self) -> DemoConfig:
        return DemoConfig(
            agent_settle_time=0.01,
            step_transition_time=0.01,
            render=RenderConfig(total_width=80, total_height=30),
        )

    @pytest.fixture
    def mini_scenario(self, examples_dir: Path) -> DemoScenario:
        """A tiny scenario with a single step for fast testing."""
        src = examples_dir / "src"
        return DemoScenario(
            name="Mini Test",
            description="Minimal test scenario",
            workspace_path=str(examples_dir),
            steps=[
                DemoStep(
                    file=str(src / "processor.py"),
                    line=1,
                    caption="Opening processor",
                    pause_seconds=0.01,
                ),
            ],
            pre_narration="",
            post_narration="",
        )

    async def test_run_scenario_calls_runtime_lifecycle(
        self,
        fast_config: DemoConfig,
        mini_scenario: DemoScenario,
    ):
        """Verify that run_scenario starts and stops the runtime."""
        harness = DemoHarness(fast_config)

        mock_runtime = AsyncMock()
        mock_runtime.start = AsyncMock()
        mock_runtime.stop = AsyncMock()
        mock_runtime.on_cursor_moved = AsyncMock()
        mock_runtime.get_sidebar = AsyncMock(return_value="# Sidebar")
        mock_runtime.indexer = MagicMock()
        mock_runtime.indexer.store.stats.return_value = {"total_chunks": 10}

        with (
            patch.object(
                _runtime_mod,
                "CompanionRuntime",
                return_value=mock_runtime,
            ),
            patch.object(
                _runtime_mod,
                "CompanionConfig",
            ),
        ):
            # Suppress terminal output
            with (
                patch.object(harness._renderer, "setup"),
                patch.object(harness._renderer, "teardown"),
                patch.object(harness._renderer, "render_to_terminal"),
            ):
                await harness.run_scenario(mini_scenario)

        mock_runtime.start.assert_awaited_once()
        mock_runtime.stop.assert_awaited_once()
        mock_runtime.on_cursor_moved.assert_awaited()

    async def test_run_scenario_updates_renderer_state(
        self,
        fast_config: DemoConfig,
        mini_scenario: DemoScenario,
    ):
        """Verify the harness updates the renderer editor/sidebar state."""
        harness = DemoHarness(fast_config)

        mock_runtime = AsyncMock()
        mock_runtime.start = AsyncMock()
        mock_runtime.stop = AsyncMock()
        mock_runtime.on_cursor_moved = AsyncMock()
        mock_runtime.get_sidebar = AsyncMock(return_value="# Test Sidebar\n\nContent here")
        mock_runtime.indexer = MagicMock()
        mock_runtime.indexer.store.stats.return_value = {"total_chunks": 5}

        with (
            patch.object(
                _runtime_mod,
                "CompanionRuntime",
                return_value=mock_runtime,
            ),
            patch.object(
                _runtime_mod,
                "CompanionConfig",
            ),
        ):
            with (
                patch.object(harness._renderer, "setup"),
                patch.object(harness._renderer, "teardown"),
                patch.object(harness._renderer, "render_to_terminal"),
            ):
                await harness.run_scenario(mini_scenario)

        # After running, the renderer should have been updated with file content
        assert len(harness._renderer.editor.lines) > 0
        assert harness._renderer.editor.file_path == mini_scenario.steps[0].file
        assert harness._renderer.sidebar.markdown == "# Test Sidebar\n\nContent here"
