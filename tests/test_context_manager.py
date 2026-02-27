import asyncio
from types import SimpleNamespace

import pytest
from structured_agents.events import ToolResultEvent

from remora.core.context import ContextBuilder
from remora.core.events import AgentCompleteEvent
from remora.core.executor import ResultSummary


def _dummy_node(node_id: str) -> SimpleNamespace:
    return SimpleNamespace(node_id=node_id)


@pytest.mark.asyncio
async def test_tool_result_event_tracks_recent_actions() -> None:
    builder = ContextBuilder()
    event = ToolResultEvent(
        turn=1,
        tool_name="lint",
        call_id="call-1",
        is_error=False,
        duration_ms=0,
        output_preview="Found 2 issues",
    )

    await builder.handle(event)

    recent = builder.get_recent_actions()
    assert len(recent) == 1
    assert recent[0].tool == "lint"
    assert recent[0].outcome == "success"


@pytest.mark.asyncio
async def test_agent_complete_event_accumulates_knowledge() -> None:
    builder = ContextBuilder()
    event = AgentCompleteEvent(
        graph_id="graph-1",
        agent_id="agent-1",
        result_summary="Refactored foo",
    )

    await builder.handle(event)

    knowledge = builder.get_knowledge()
    assert knowledge["agent-1"] == "Refactored foo"


def test_ingest_summary_populates_long_track() -> None:
    builder = ContextBuilder()
    summary = ResultSummary(
        agent_id="agent-2",
        success=True,
        output="Done",
        error=None,
    )

    builder.ingest_summary(summary)

    knowledge = builder.get_knowledge()
    assert "agent-2" in knowledge
    assert knowledge["agent-2"].startswith("success")


@pytest.mark.asyncio
async def test_build_context_for_includes_recent_actions() -> None:
    builder = ContextBuilder()
    event = ToolResultEvent(
        turn=1,
        tool_name="formatter",
        call_id="call-2",
        is_error=False,
        duration_ms=0,
        output_preview="Formatted code",
    )

    await builder.handle(event)
    context = builder.build_context_for(_dummy_node("node-1"))

    assert "## Recent Actions" in context
    assert "formatter" in context
