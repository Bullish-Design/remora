"""Regression tests for sidebar-response-missing bug and related invariants."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.events.agent_events import AgentTextResponseEvent, HumanChatEvent
from remora.core.events.interaction_events import AgentMessageEvent
from remora.core.store.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db")
    await es.initialize()
    yield es
    await es.close()


class TestPanelClosedReplay:
    """Regression: panel closed during run, later open shows AgentTextResponse."""

    @pytest.mark.asyncio
    async def test_agent_text_response_visible_in_timeline(self, store: EventStore):
        event = AgentTextResponseEvent(
            agent_id="agent_x",
            correlation_id="corr_1",
            summary="Answer to question",
            payload={"content": "Here is the answer."},
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_x", limit=10)
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentTextResponse"
        assert results[0]["agent_id"] == "agent_x"
        assert results[0]["payload"]["content"] == "Here is the answer."

    @pytest.mark.asyncio
    async def test_agent_text_response_not_in_routed_messages(self, store: EventStore):
        event = AgentTextResponseEvent(
            agent_id="agent_x",
            correlation_id="corr_1",
            summary="Answer",
            payload={"content": "text"},
        )
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_x", limit=10)
        assert len(results) == 0


class TestLiveReplayEnvelopeParity:
    """Invariant: live and replayed events have the same top-level fields."""

    @pytest.mark.asyncio
    async def test_replayed_event_has_agent_id_at_top_level(self, store: EventStore):
        event = AgentTextResponseEvent(
            agent_id="agent_y",
            correlation_id="corr_2",
            payload={"content": "response"},
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_y", limit=1)
        assert "agent_id" in results[0]
        assert results[0]["agent_id"] == "agent_y"

    @pytest.mark.asyncio
    async def test_replayed_event_has_stable_id(self, store: EventStore):
        event = AgentMessageEvent(from_agent="a", to_agent="b", content="hi", correlation_id="c1")
        await store.append("swarm", event)

        results = await store.get_agent_timeline("a", limit=1)
        assert results[0]["id"] is not None
        assert isinstance(results[0]["id"], int)


class TestChatHistoryCompleteness:
    """Invariant: agent responses appear in correlation-scoped history."""

    @pytest.mark.asyncio
    async def test_text_response_retrievable_by_correlation(self, store: EventStore):
        event = AgentTextResponseEvent(
            agent_id="agent_z",
            correlation_id="corr_session_1",
            payload={"content": "I can help with that."},
        )
        await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_session_1")
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentTextResponse"
        assert results[0]["payload"]["content"] == "I can help with that."

    @pytest.mark.asyncio
    async def test_full_conversation_round_trip(self, store: EventStore):
        human_msg = HumanChatEvent(
            agent_id="agent_z",
            to_agent="agent_z",
            message="What can you do?",
            correlation_id="corr_rt_1",
        )
        agent_resp = AgentTextResponseEvent(
            agent_id="agent_z",
            correlation_id="corr_rt_1",
            payload={"content": "Many things."},
            summary="Many things.",
        )
        await store.append("swarm", human_msg)
        await store.append("swarm", agent_resp)

        timeline = await store.get_agent_timeline("agent_z", limit=10)
        assert len(timeline) == 2
        event_types = {ev["event_type"] for ev in timeline}
        assert "HumanChatEvent" in event_types
        assert "AgentTextResponse" in event_types

        corr = await store.get_events_for_correlation("corr_rt_1")
        assert len(corr) == 2
