"""Tests for session_summarizer composer agent."""

import pytest

from remora_demo.companion.agents.base import InMemoryWorkspace
from remora_demo.companion.agents.composers.session_summarizer import (
    SessionSummarizer,
    SessionSummarizerConfig,
)
from remora_demo.companion.models.events import SessionTick
from remora_demo.companion.models.workspace import (
    Connection,
    EditSummary,
    Question,
    TaskInference,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace():
    return InMemoryWorkspace()


@pytest.fixture
def summarizer(workspace):
    return SessionSummarizer(workspace)


# ---------------------------------------------------------------------------
# Init tests
# ---------------------------------------------------------------------------


class TestSessionSummarizerInit:
    def test_creates_with_defaults(self, workspace):
        s = SessionSummarizer(workspace)
        assert s.name == "session_summarizer"

    def test_creates_with_custom_config(self, workspace):
        config = SessionSummarizerConfig(max_files_shown=3)
        s = SessionSummarizer(workspace, config=config)
        assert s.config.max_files_shown == 3

    def test_has_session_tick_subscription(self, workspace):
        s = SessionSummarizer(workspace)
        targets = [sub.target for sub in s.subscriptions]
        assert SessionTick in targets


# ---------------------------------------------------------------------------
# Basic summary generation
# ---------------------------------------------------------------------------


class TestBasicSummary:
    async def test_produces_markdown_output(self, summarizer, workspace):
        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert result is not None
        assert isinstance(result, str)

    async def test_includes_session_header(self, summarizer, workspace):
        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert "# Session Summary" in result

    async def test_includes_elapsed_time(self, summarizer, workspace):
        tick = SessionTick(elapsed_ms=120000, tick_number=4)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        # 120000ms = 2 minutes
        assert "2m" in result


# ---------------------------------------------------------------------------
# Files touched section
# ---------------------------------------------------------------------------


class TestFilesTouched:
    async def test_shows_files_from_edit_summaries(self, summarizer, workspace):
        # Write some edit summaries to workspace
        await workspace.write(
            "/companion/session/edits/0",
            EditSummary(file="src/main.py", start_line=10, end_line=15, summary="Added function", timestamp=1000.0),
        )
        await workspace.write(
            "/companion/session/edits/1",
            EditSummary(file="src/utils.py", start_line=5, end_line=8, summary="Fixed import", timestamp=1001.0),
        )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert "src/main.py" in result
        assert "src/utils.py" in result

    async def test_deduplicates_files(self, summarizer, workspace):
        # Same file edited twice
        await workspace.write(
            "/companion/session/edits/0",
            EditSummary(file="src/main.py", start_line=10, end_line=15, summary="Edit 1", timestamp=1000.0),
        )
        await workspace.write(
            "/companion/session/edits/1",
            EditSummary(file="src/main.py", start_line=20, end_line=25, summary="Edit 2", timestamp=1001.0),
        )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        # In the Files Touched section, the file should appear only once
        # (it may also appear in Resume Point section)
        files_section = result.split("## Files Touched")[1].split("##")[0]
        assert files_section.count("src/main.py") == 1

    async def test_respects_max_files_shown(self, workspace):
        config = SessionSummarizerConfig(max_files_shown=2)
        s = SessionSummarizer(workspace, config=config)

        for i in range(5):
            await workspace.write(
                f"/companion/session/edits/{i}",
                EditSummary(file=f"src/file_{i}.py", start_line=1, end_line=2, summary="Edit", timestamp=1000.0 + i),
            )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await s.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        # Only 2 files shown in the list, but should mention there are more
        file_count = sum(1 for i in range(5) if f"src/file_{i}.py" in result)
        assert file_count <= 3  # at most max + 1 (in "and N more" note)


# ---------------------------------------------------------------------------
# Key insights section
# ---------------------------------------------------------------------------


class TestKeyInsights:
    async def test_shows_inferred_task(self, summarizer, workspace):
        await workspace.write(
            "/companion/analysis/inferred_task",
            TaskInference(description="Debugging test failures", confidence=0.85, evidence=["test file toggling"]),
        )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert "Debugging test failures" in result

    async def test_shows_connections(self, summarizer, workspace):
        await workspace.write(
            "/companion/analysis/connections/0",
            Connection(from_file="src/a.py", to_file="src/b.py", insight="Shared interface", connection_type="similar"),
        )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert "Shared interface" in result


# ---------------------------------------------------------------------------
# Open threads section
# ---------------------------------------------------------------------------


class TestOpenThreads:
    async def test_shows_questions(self, summarizer, workspace):
        await workspace.write(
            "/companion/analysis/questions/0",
            Question(question="Should this use async?", priority="high", context="Function uses blocking IO"),
        )

        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        result = await workspace.read("/companion/output/session_summary.md")
        assert "Should this use async?" in result


# ---------------------------------------------------------------------------
# Activation tracking
# ---------------------------------------------------------------------------


class TestActivationTracking:
    async def test_records_activation(self, summarizer, workspace):
        tick = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick)

        assert len(summarizer.activations) >= 1
        act = summarizer.activations[-1]
        assert act.agent_name == "session_summarizer"
        assert act.status == "success"


# ---------------------------------------------------------------------------
# Update behavior
# ---------------------------------------------------------------------------


class TestUpdateBehavior:
    async def test_overwrites_on_each_tick(self, summarizer, workspace):
        tick1 = SessionTick(elapsed_ms=30000, tick_number=1)
        await summarizer.on_session_tick(tick1)

        result1 = await workspace.read("/companion/output/session_summary.md")

        tick2 = SessionTick(elapsed_ms=60000, tick_number=2)
        await summarizer.on_session_tick(tick2)

        result2 = await workspace.read("/companion/output/session_summary.md")

        # Second tick has more elapsed time
        assert "1m" in result2
        # Content should differ (different elapsed time)
        assert result1 != result2
