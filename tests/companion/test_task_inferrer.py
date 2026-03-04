"""Tests for the task_inferrer analyzer agent.

The task inferrer watches navigation/context patterns and infers
what the user is currently working on. It writes a TaskInference
to /companion/analysis/inferred_task.
"""

from __future__ import annotations

import pytest

from remora_demo.companion.agents.base import InMemoryWorkspace
from remora_demo.companion.agents.analyzers.task_inferrer import (
    TaskInferrer,
    TaskInferrerConfig,
)
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import (
    CursorPosition,
    NavEvent,
    Structure,
    TaskInference,
)


@pytest.fixture
def workspace() -> InMemoryWorkspace:
    return InMemoryWorkspace()


@pytest.fixture
def inferrer(workspace: InMemoryWorkspace) -> TaskInferrer:
    return TaskInferrer(workspace, config=TaskInferrerConfig(debounce_ms=0))


# -- Construction --


class TestTaskInferrerInit:
    def test_creates_with_defaults(self, workspace: InMemoryWorkspace) -> None:
        agent = TaskInferrer(workspace)
        assert agent.name == "task_inferrer"

    def test_creates_with_custom_config(self, workspace: InMemoryWorkspace) -> None:
        cfg = TaskInferrerConfig(nav_history_size=20, min_confidence=0.5)
        agent = TaskInferrer(workspace, config=cfg)
        assert agent.config.nav_history_size == 20
        assert agent.config.min_confidence == 0.5

    def test_has_context_subscription(self, inferrer: TaskInferrer) -> None:
        targets = [s.target for s in inferrer.subscriptions]
        assert "/companion/context/*" in targets


# -- Pattern Detection --


class TestExplorationPattern:
    """When the user visits many different files quickly, infer 'exploring codebase'."""

    async def test_many_file_switches_infer_exploration(
        self, workspace: InMemoryWorkspace, inferrer: TaskInferrer
    ) -> None:
        # Simulate visiting 5+ different files
        files = ["src/a.py", "src/b.py", "src/c.py", "src/d.py", "src/e.py", "src/f.py"]
        for i, f in enumerate(files):
            await workspace.write("/companion/context/file_path", f)
            await workspace.write(
                "/companion/context/cursor_position",
                CursorPosition(line=1, col=0),
            )
            await workspace.write(
                f"/companion/context/nav_history/{i}",
                NavEvent(file=f, line=1, timestamp=float(1000 + i * 2000), duration_ms=1500),
            )

        # Trigger inference
        change = PathChanged(path="/companion/context/file_path", value="src/f.py")
        await inferrer.on_context_change(change)

        task: TaskInference | None = await workspace.read("/companion/analysis/inferred_task")
        assert task is not None
        assert task.confidence > 0
        assert "explor" in task.description.lower()

    async def test_single_file_no_exploration(self, workspace: InMemoryWorkspace, inferrer: TaskInferrer) -> None:
        """Staying in one file should NOT infer exploration."""
        await workspace.write("/companion/context/file_path", "src/main.py")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=10, col=0),
        )

        change = PathChanged(path="/companion/context/file_path", value="src/main.py")
        await inferrer.on_context_change(change)

        task: TaskInference | None = await workspace.read("/companion/analysis/inferred_task")
        # Should either be None or not exploration
        if task is not None:
            assert "explor" not in task.description.lower()


class TestDebuggingPattern:
    """When the user toggles between test and implementation files, infer 'debugging'."""

    async def test_test_impl_toggling_infers_debugging(
        self, workspace: InMemoryWorkspace, inferrer: TaskInferrer
    ) -> None:
        # Simulate toggling between impl and test
        toggle_sequence = [
            "src/processor.py",
            "tests/test_processor.py",
            "src/processor.py",
            "tests/test_processor.py",
        ]
        for i, f in enumerate(toggle_sequence):
            await workspace.write(
                f"/companion/context/nav_history/{i}",
                NavEvent(file=f, line=10, timestamp=float(1000 + i * 3000), duration_ms=2500),
            )
        await workspace.write("/companion/context/file_path", "tests/test_processor.py")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=10, col=0),
        )

        change = PathChanged(path="/companion/context/file_path", value="tests/test_processor.py")
        await inferrer.on_context_change(change)

        task: TaskInference | None = await workspace.read("/companion/analysis/inferred_task")
        assert task is not None
        assert "debug" in task.description.lower() or "test" in task.description.lower()


class TestDocWritingPattern:
    """When the user is in markdown files, infer 'writing documentation'."""

    async def test_markdown_file_infers_doc_writing(self, workspace: InMemoryWorkspace, inferrer: TaskInferrer) -> None:
        await workspace.write("/companion/context/file_path", "docs/architecture.md")
        await workspace.write("/companion/context/content_type", "markdown")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=15, col=0),
        )
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="heading", name="Architecture Overview", depth=2),
        )

        change = PathChanged(path="/companion/context/file_path", value="docs/architecture.md")
        await inferrer.on_context_change(change)

        task: TaskInference | None = await workspace.read("/companion/analysis/inferred_task")
        assert task is not None
        assert "doc" in task.description.lower() or "writ" in task.description.lower()


class TestFocusedCodingPattern:
    """When the user stays in one code file, infer 'focused coding'."""

    async def test_single_code_file_infers_focused_coding(
        self, workspace: InMemoryWorkspace, inferrer: TaskInferrer
    ) -> None:
        await workspace.write("/companion/context/file_path", "src/processor.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=42, col=0),
        )
        await workspace.write(
            "/companion/context/structure",
            Structure(structure_type="function", name="process_batch", parent="DataProcessor"),
        )
        # Only one file in nav history — focused
        await workspace.write(
            "/companion/context/nav_history/0",
            NavEvent(file="src/processor.py", line=42, timestamp=1000.0, duration_ms=10000),
        )

        change = PathChanged(path="/companion/context/file_path", value="src/processor.py")
        await inferrer.on_context_change(change)

        task: TaskInference | None = await workspace.read("/companion/analysis/inferred_task")
        assert task is not None
        assert task.confidence > 0


# -- Confidence threshold --


class TestConfidenceThreshold:
    async def test_low_confidence_below_threshold_not_written(self, workspace: InMemoryWorkspace) -> None:
        """If no clear pattern, confidence is low; if below min threshold, no task written."""
        cfg = TaskInferrerConfig(debounce_ms=0, min_confidence=0.99)
        agent = TaskInferrer(workspace, config=cfg)

        await workspace.write("/companion/context/file_path", "src/main.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=1, col=0),
        )

        change = PathChanged(path="/companion/context/file_path", value="src/main.py")
        await agent.on_context_change(change)

        task = await workspace.read("/companion/analysis/inferred_task")
        # With threshold 0.99, a vague single-file signal shouldn't pass
        assert task is None


# -- Activation tracking --


class TestActivationTracking:
    async def test_records_activation(self, workspace: InMemoryWorkspace, inferrer: TaskInferrer) -> None:
        await workspace.write("/companion/context/file_path", "src/main.py")
        await workspace.write("/companion/context/content_type", "code")
        await workspace.write(
            "/companion/context/cursor_position",
            CursorPosition(line=1, col=0),
        )

        change = PathChanged(path="/companion/context/file_path", value="src/main.py")
        await inferrer.on_context_change(change)

        assert len(inferrer.activations) >= 1
        last = inferrer.activations[-1]
        assert last.agent_name == "task_inferrer"
        assert last.status == "success"
