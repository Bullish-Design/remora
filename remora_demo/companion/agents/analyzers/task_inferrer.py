"""Task inferrer analyzer agent.

Infers what the user is currently working on by analyzing navigation
patterns and context signals. Writes a TaskInference to
/companion/analysis/inferred_task.

Subscribes to: /companion/context/*
Reads: /companion/context/nav_history/*, /companion/context/file_path,
       /companion/context/content_type, /companion/context/structure
Writes to: /companion/analysis/inferred_task
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from remora_demo.companion.agents.base import AgentBase, WorkspaceInterface, subscribe
from remora_demo.companion.models.events import PathChanged
from remora_demo.companion.models.workspace import NavEvent, Structure, TaskInference


@dataclass
class TaskInferrerConfig:
    """Configuration for task inferrer."""

    debounce_ms: int = 500
    nav_history_size: int = 20
    min_confidence: float = 0.3
    # Thresholds for pattern detection
    exploration_file_threshold: int = 4  # files visited to trigger exploration
    test_toggle_threshold: int = 3  # test/impl switches to trigger debugging
    test_patterns: list[str] | None = None

    def __post_init__(self) -> None:
        if self.test_patterns is None:
            self.test_patterns = ["test_", "_test.py", "tests/", "spec_", "_spec."]


class TaskInferrer(AgentBase):
    """Infers current task from navigation and context patterns.

    Detects patterns like:
    - Exploration: many different files visited quickly
    - Debugging: toggling between test and implementation files
    - Documentation: working in markdown files
    - Focused coding: staying in one code file for extended time
    """

    def __init__(
        self,
        workspace: WorkspaceInterface,
        config: TaskInferrerConfig | None = None,
    ) -> None:
        super().__init__("task_inferrer")
        self.workspace = workspace
        self.config = config or TaskInferrerConfig()

    @subscribe("/companion/context/*", debounce_ms=500)
    async def on_context_change(self, change: PathChanged) -> None:
        """Analyze context changes for task patterns."""
        await self._infer_task()

    async def _infer_task(self) -> None:
        """Analyze current state and infer the user's task."""
        import time
        import uuid

        from remora_demo.companion.agents.base import AgentActivation

        activation = AgentActivation(
            id=str(uuid.uuid4())[:8],
            agent_name=self.name,
            trigger="/companion/context/*",
            started_at=time.time(),
            status="running",
        )
        self._activations.append(activation)

        try:
            await self._do_infer_task()
            activation.status = "success"
        except Exception as e:
            activation.status = "error"
            activation.error = str(e)
            raise
        finally:
            activation.ended_at = time.time()

    async def _do_infer_task(self) -> None:
        """Core inference logic."""
        file_path = await self.workspace.read("/companion/context/file_path")
        content_type = await self.workspace.read("/companion/context/content_type")
        structure: Structure | None = await self.workspace.read("/companion/context/structure")

        if not file_path:
            return

        self.record_input("/companion/context/file_path", file_path)

        # Collect navigation history
        nav_history = await self._collect_nav_history()

        # Score each pattern
        candidates: list[TaskInference] = []

        exploration = self._detect_exploration(nav_history)
        if exploration:
            candidates.append(exploration)

        debugging = self._detect_debugging(nav_history)
        if debugging:
            candidates.append(debugging)

        doc_writing = self._detect_doc_writing(file_path, content_type, structure)
        if doc_writing:
            candidates.append(doc_writing)

        focused_coding = self._detect_focused_coding(file_path, content_type, structure, nav_history)
        if focused_coding:
            candidates.append(focused_coding)

        # Pick the highest-confidence inference
        if not candidates:
            return

        best = max(candidates, key=lambda t: t.confidence)

        # Apply threshold
        if best.confidence < self.config.min_confidence:
            return

        # Write to workspace
        await self.workspace.write("/companion/analysis/inferred_task", best)
        self.record_output("/companion/analysis/inferred_task")

    async def _collect_nav_history(self) -> list[NavEvent]:
        """Read navigation history from workspace."""
        paths = await self.workspace.list("/companion/context/nav_history/*")
        events: list[NavEvent] = []
        for path in paths:
            val = await self.workspace.read(path)
            if isinstance(val, NavEvent):
                events.append(val)
        # Sort by timestamp
        events.sort(key=lambda e: e.timestamp)
        return events[-self.config.nav_history_size :]

    def _detect_exploration(self, nav_history: list[NavEvent]) -> TaskInference | None:
        """Detect codebase exploration pattern.

        Signal: many unique files visited in the history.
        """
        if not nav_history:
            return None

        unique_files = {e.file for e in nav_history}
        file_count = len(unique_files)

        if file_count < self.config.exploration_file_threshold:
            return None

        # Confidence scales with number of unique files
        confidence = min(0.9, 0.3 + (file_count - self.config.exploration_file_threshold) * 0.15)

        return TaskInference(
            description="Exploring codebase",
            confidence=confidence,
            evidence=[
                f"Visited {file_count} different files",
                f"Recent files: {', '.join(Path(f).name for f in list(unique_files)[:5])}",
            ],
        )

    def _detect_debugging(self, nav_history: list[NavEvent]) -> TaskInference | None:
        """Detect debugging/testing pattern.

        Signal: toggling between test files and implementation files.
        """
        if len(nav_history) < 2:
            return None

        test_patterns = self.config.test_patterns or []
        toggle_count = 0

        for i in range(1, len(nav_history)):
            prev_file = nav_history[i - 1].file
            curr_file = nav_history[i].file

            if prev_file == curr_file:
                continue

            prev_is_test = any(p in prev_file for p in test_patterns)
            curr_is_test = any(p in curr_file for p in test_patterns)

            if prev_is_test != curr_is_test:
                toggle_count += 1

        if toggle_count < self.config.test_toggle_threshold:
            return None

        confidence = min(0.9, 0.4 + (toggle_count - self.config.test_toggle_threshold) * 0.15)

        return TaskInference(
            description="Debugging / running tests",
            confidence=confidence,
            evidence=[
                f"Toggled between test and implementation {toggle_count} times",
            ],
        )

    def _detect_doc_writing(
        self,
        file_path: str,
        content_type: str | None,
        structure: Structure | None,
    ) -> TaskInference | None:
        """Detect documentation writing pattern.

        Signal: current file is markdown/docs.
        """
        if content_type != "markdown":
            return None

        evidence = [f"Currently in markdown file: {Path(file_path).name}"]
        confidence = 0.5

        if structure and structure.structure_type == "heading":
            evidence.append(f"Under heading: {structure.name}")
            confidence = 0.6

        # Boost if in a docs directory
        if "docs/" in file_path or "doc/" in file_path:
            evidence.append("File is in a documentation directory")
            confidence = min(0.85, confidence + 0.15)

        return TaskInference(
            description="Writing documentation",
            confidence=confidence,
            evidence=evidence,
        )

    def _detect_focused_coding(
        self,
        file_path: str,
        content_type: str | None,
        structure: Structure | None,
        nav_history: list[NavEvent],
    ) -> TaskInference | None:
        """Detect focused coding in a single file.

        Signal: most recent history is in the same file, content is code.
        """
        if content_type != "code":
            return None

        # Count how many of the recent nav events are in the current file
        if not nav_history:
            same_file_count = 0
            total = 0
        else:
            recent = nav_history[-5:]  # Look at last 5 events
            same_file_count = sum(1 for e in recent if e.file == file_path)
            total = len(recent)

        if total == 0:
            # No history yet — mild signal from being in a code file
            confidence = 0.35
        elif same_file_count / total >= 0.8:
            confidence = 0.7
        elif same_file_count / total >= 0.5:
            confidence = 0.5
        else:
            return None

        evidence = [f"Working in {Path(file_path).name}"]

        if structure:
            evidence.append(
                f"Focused on {structure.structure_type} '{structure.name}'"
                + (f" in {structure.parent}" if structure.parent else "")
            )
            confidence = min(0.85, confidence + 0.1)

        return TaskInference(
            description="Focused coding",
            confidence=confidence,
            evidence=evidence,
        )

    async def process(self, data: Any) -> None:
        """Process method for AgentBase compatibility."""
        if isinstance(data, PathChanged):
            await self.on_context_change(data)
