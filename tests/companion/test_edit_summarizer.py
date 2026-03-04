"""Tests for the edit_summarizer extractor agent.

The edit summarizer subscribes to ContentEdited events, generates brief
heuristic summaries of what changed, and writes EditSummary objects to
/companion/session/edits/*.
"""

from __future__ import annotations

import time

import pytest

from remora_demo.companion.agents.base import InMemoryWorkspace
from remora_demo.companion.agents.extractors.edit_summarizer import (
    EditSummarizer,
    EditSummarizerConfig,
)
from remora_demo.companion.models.events import ContentEdited
from remora_demo.companion.models.workspace import EditSummary


@pytest.fixture
def workspace() -> InMemoryWorkspace:
    return InMemoryWorkspace()


@pytest.fixture
def summarizer(workspace: InMemoryWorkspace) -> EditSummarizer:
    return EditSummarizer(workspace)


# -- Construction --


class TestEditSummarizerInit:
    def test_creates_with_defaults(self, workspace: InMemoryWorkspace) -> None:
        agent = EditSummarizer(workspace)
        assert agent.name == "edit_summarizer"

    def test_creates_with_custom_config(self, workspace: InMemoryWorkspace) -> None:
        cfg = EditSummarizerConfig(max_history=50)
        agent = EditSummarizer(workspace, config=cfg)
        assert agent.config.max_history == 50

    def test_has_content_edited_subscription(self, summarizer: EditSummarizer) -> None:
        targets = [s.target for s in summarizer.subscriptions]
        assert ContentEdited in targets


# -- Summary generation --


class TestSummaryContent:
    async def test_summarizes_python_edit(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="src/processor.py",
            start_line=10,
            end_line=15,
            text="def process_batch(self, items):\n    for item in items:\n        self.handle(item)",
        )
        await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        assert len(paths) == 1

        summary: EditSummary = await workspace.read(paths[0])
        assert summary is not None
        assert summary.file == "src/processor.py"
        assert summary.start_line == 10
        assert summary.end_line == 15
        assert len(summary.summary) > 0

    async def test_summarizes_markdown_edit(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="docs/architecture.md",
            start_line=1,
            end_line=3,
            text="# Architecture Overview\n\nThis document describes the system.",
        )
        await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        assert len(paths) == 1

        summary: EditSummary = await workspace.read(paths[0])
        assert "architecture.md" in summary.file

    async def test_summary_includes_file_name(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="src/utils/helpers.py",
            start_line=5,
            end_line=5,
            text="    return True",
        )
        await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        summary: EditSummary = await workspace.read(paths[0])
        assert "helpers.py" in summary.summary


# -- Multiple edits --


class TestMultipleEdits:
    async def test_multiple_edits_create_separate_entries(
        self, workspace: InMemoryWorkspace, summarizer: EditSummarizer
    ) -> None:
        for i in range(3):
            event = ContentEdited(
                file=f"src/file_{i}.py",
                start_line=1,
                end_line=5,
                text=f"# edit {i}",
            )
            await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        assert len(paths) == 3

    async def test_timestamps_increase(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        for i in range(2):
            event = ContentEdited(
                file=f"src/file_{i}.py",
                start_line=1,
                end_line=2,
                text="x = 1",
            )
            await summarizer.on_content_edited(event)

        paths = sorted(await workspace.list("/companion/session/edits/*"))
        s0: EditSummary = await workspace.read(paths[0])
        s1: EditSummary = await workspace.read(paths[1])
        assert s1.timestamp >= s0.timestamp


# -- Edge cases --


class TestEdgeCases:
    async def test_empty_text_edit(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="src/main.py",
            start_line=1,
            end_line=1,
            text="",
        )
        await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        assert len(paths) == 1
        summary: EditSummary = await workspace.read(paths[0])
        assert len(summary.summary) > 0  # Should still produce a summary

    async def test_single_line_edit(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="config.yaml",
            start_line=10,
            end_line=10,
            text="debug: true",
        )
        await summarizer.on_content_edited(event)

        paths = await workspace.list("/companion/session/edits/*")
        summary: EditSummary = await workspace.read(paths[0])
        assert summary.start_line == 10
        assert summary.end_line == 10


# -- Activation tracking --


class TestActivationTracking:
    async def test_records_activation(self, workspace: InMemoryWorkspace, summarizer: EditSummarizer) -> None:
        event = ContentEdited(
            file="src/main.py",
            start_line=1,
            end_line=5,
            text="import os",
        )
        await summarizer.on_content_edited(event)

        assert len(summarizer.activations) >= 1
        last = summarizer.activations[-1]
        assert last.agent_name == "edit_summarizer"
        assert last.status == "success"
