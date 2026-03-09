"""Tests for EventStore timeline/routed-message/correlation query APIs."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.events import AgentMessageEvent, AgentStartEvent, ManualTriggerEvent
from remora.core.store.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db")
    await es.initialize()
    yield es
    await es.close()


class TestGetAgentTimeline:
    """Tests for EventStore.get_agent_timeline()."""

    @pytest.mark.asyncio
    async def test_returns_events_for_agent_as_from(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_a", limit=10)
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentMessageEvent"
        assert results[0]["from_agent"] == "agent_a"

    @pytest.mark.asyncio
    async def test_returns_events_for_agent_as_to(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_b", limit=10)
        assert len(results) == 1
        assert results[0]["to_agent"] == "agent_b"

    @pytest.mark.asyncio
    async def test_excludes_unrelated_events(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_c", limit=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, store: EventStore):
        for i in range(5):
            event = AgentMessageEvent(
                from_agent="agent_a",
                to_agent="agent_b",
                content=f"msg_{i}",
            )
            await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_a", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_newest_first_order(self, store: EventStore):
        for i in range(3):
            event = AgentMessageEvent(
                from_agent="agent_a",
                to_agent="agent_b",
                content=f"msg_{i}",
                timestamp=float(100 + i),
            )
            await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_a", limit=10)
        assert len(results) == 3
        assert results[0]["timestamp"] >= results[1]["timestamp"]
        assert results[1]["timestamp"] >= results[2]["timestamp"]

    @pytest.mark.asyncio
    async def test_result_dict_structure(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_a", limit=1)
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "event_type" in result
        assert "payload" in result
        assert "timestamp" in result
        assert "agent_id" in result
        assert "from_agent" in result
        assert "to_agent" in result
        assert "correlation_id" in result

    @pytest.mark.asyncio
    async def test_includes_agent_id_only_events(self, store: EventStore):
        event = AgentStartEvent(
            graph_id="swarm",
            agent_id="agent_a",
            node_name="test_node",
        )
        await store.append("swarm", event)

        results = await store.get_agent_timeline("agent_a", limit=10)
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentStartEvent"
        assert results[0]["agent_id"] == "agent_a"


class TestGetRoutedMessages:
    """Tests for EventStore.get_routed_messages()."""

    @pytest.mark.asyncio
    async def test_excludes_agent_id_only_events(self, store: EventStore):
        event = AgentStartEvent(graph_id="swarm", agent_id="agent_a", node_name="test_node")
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_a", limit=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_includes_from_agent_events(self, store: EventStore):
        event = AgentMessageEvent(from_agent="agent_a", to_agent="agent_b", content="hi")
        await store.append("swarm", event)

        results = await store.get_routed_messages("agent_a", limit=10)
        assert len(results) == 1


class TestGetEventsForCorrelation:
    """Tests for EventStore.get_events_for_correlation()."""

    @pytest.mark.asyncio
    async def test_returns_events_with_matching_correlation(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="human",
            to_agent="agent_a",
            content="hello",
            correlation_id="corr_42",
        )
        await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_42")
        assert len(results) == 1
        assert results[0]["correlation_id"] == "corr_42"

    @pytest.mark.asyncio
    async def test_excludes_different_correlation(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="human",
            to_agent="agent_a",
            content="hello",
            correlation_id="corr_42",
        )
        await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_99")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_chronological_order(self, store: EventStore):
        for i in range(3):
            event = AgentMessageEvent(
                from_agent="human",
                to_agent="agent_a",
                content=f"msg_{i}",
                correlation_id="corr_1",
                timestamp=float(100 + i),
            )
            await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_1")
        assert len(results) == 3
        assert results[0]["timestamp"] <= results[1]["timestamp"]
        assert results[1]["timestamp"] <= results[2]["timestamp"]

    @pytest.mark.asyncio
    async def test_result_dict_structure(self, store: EventStore):
        event = AgentMessageEvent(
            from_agent="human",
            to_agent="agent_a",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_events_for_correlation("corr_1")
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "event_type" in result
        assert "payload" in result
        assert "timestamp" in result
        assert "agent_id" in result
        assert "from_agent" in result
        assert "to_agent" in result
        assert "correlation_id" in result

    @pytest.mark.asyncio
    async def test_multiple_event_types(self, store: EventStore):
        msg = AgentMessageEvent(
            from_agent="human",
            to_agent="agent_a",
            content="do something",
            correlation_id="corr_1",
            timestamp=100.0,
        )
        trigger = ManualTriggerEvent(
            to_agent="agent_a",
            reason="test",
            timestamp=101.0,
        )
        reply = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="human",
            content="done",
            correlation_id="corr_1",
            timestamp=102.0,
        )

        await store.append("swarm", msg)
        await store.append("swarm", trigger)
        await store.append("swarm", reply)

        results = await store.get_events_for_correlation("corr_1")
        assert len(results) == 2
        assert results[0]["event_type"] == "AgentMessageEvent"
        assert results[1]["event_type"] == "AgentMessageEvent"
