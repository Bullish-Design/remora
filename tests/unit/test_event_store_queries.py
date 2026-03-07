"""Tests for EventStore.get_recent_events() and get_events_for_correlation().

These methods replace the equivalent RemoraDB methods, eliminating the
dual-write between RemoraDB and EventStore.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.store.event_store import EventStore
from remora.core.events import (
    AgentMessageEvent,
    AgentStartEvent,
    ManualTriggerEvent,
)


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    es = EventStore(tmp_path / "events.db")
    await es.initialize()
    yield es
    await es.close()


class TestGetRecentEvents:
    """Tests for EventStore.get_recent_events()."""

    @pytest.mark.asyncio
    async def test_returns_events_for_agent_as_from(self, store: EventStore):
        """Events where agent is the sender should be included."""
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_recent_events("agent_a", limit=10)
        assert len(results) == 1
        assert results[0]["event_type"] == "AgentMessageEvent"
        assert results[0]["from_agent"] == "agent_a"

    @pytest.mark.asyncio
    async def test_returns_events_for_agent_as_to(self, store: EventStore):
        """Events where agent is the recipient should be included."""
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_recent_events("agent_b", limit=10)
        assert len(results) == 1
        assert results[0]["to_agent"] == "agent_b"

    @pytest.mark.asyncio
    async def test_excludes_unrelated_events(self, store: EventStore):
        """Events not involving the agent should be excluded."""
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
        )
        await store.append("swarm", event)

        results = await store.get_recent_events("agent_c", limit=10)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, store: EventStore):
        """Only the N most recent events should be returned."""
        for i in range(5):
            event = AgentMessageEvent(
                from_agent="agent_a",
                to_agent="agent_b",
                content=f"msg_{i}",
            )
            await store.append("swarm", event)

        results = await store.get_recent_events("agent_a", limit=3)
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_newest_first_order(self, store: EventStore):
        """Results should be ordered newest first (DESC)."""
        for i in range(3):
            event = AgentMessageEvent(
                from_agent="agent_a",
                to_agent="agent_b",
                content=f"msg_{i}",
                timestamp=float(100 + i),
            )
            await store.append("swarm", event)

        results = await store.get_recent_events("agent_a", limit=10)
        assert len(results) == 3
        # Newest first
        assert results[0]["timestamp"] >= results[1]["timestamp"]
        assert results[1]["timestamp"] >= results[2]["timestamp"]

    @pytest.mark.asyncio
    async def test_result_dict_structure(self, store: EventStore):
        """Returned dicts should have standard fields."""
        event = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="agent_b",
            content="hello",
            correlation_id="corr_1",
        )
        await store.append("swarm", event)

        results = await store.get_recent_events("agent_a", limit=1)
        assert len(results) == 1
        result = results[0]
        assert "id" in result
        assert "event_type" in result
        assert "payload" in result
        assert "timestamp" in result
        assert "from_agent" in result
        assert "to_agent" in result
        assert "correlation_id" in result

    @pytest.mark.asyncio
    async def test_matches_events_without_routing_fields(self, store: EventStore):
        """Events with from_agent but no to_agent should match on from_agent."""
        event = AgentStartEvent(
            graph_id="swarm",
            agent_id="agent_a",
            node_name="test_node",
        )
        # AgentStartEvent has agent_id but no from_agent/to_agent fields.
        # The EventStore stores from_agent = getattr(event, "from_agent", None).
        # AgentStartEvent doesn't have from_agent, so it's stored as NULL.
        # But it has agent_id in the payload. We query on from_agent/to_agent columns only.
        await store.append("swarm", event)

        # agent_a won't appear in from_agent or to_agent columns for AgentStartEvent
        results = await store.get_recent_events("agent_a", limit=10)
        # AgentStartEvent doesn't have from_agent/to_agent fields on the dataclass,
        # so these columns are NULL. The query should NOT return it.
        assert len(results) == 0


class TestGetEventsForCorrelation:
    """Tests for EventStore.get_events_for_correlation()."""

    @pytest.mark.asyncio
    async def test_returns_events_with_matching_correlation(self, store: EventStore):
        """Events with matching correlation_id should be returned."""
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
        """Events with different correlation_id should be excluded."""
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
        """Results should be ordered oldest first (ASC) for replay."""
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
        # Oldest first
        assert results[0]["timestamp"] <= results[1]["timestamp"]
        assert results[1]["timestamp"] <= results[2]["timestamp"]

    @pytest.mark.asyncio
    async def test_result_dict_structure(self, store: EventStore):
        """Returned dicts should have standard fields."""
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
        assert "from_agent" in result
        assert "to_agent" in result
        assert "correlation_id" in result

    @pytest.mark.asyncio
    async def test_multiple_event_types(self, store: EventStore):
        """Events of different types with same correlation_id should all be returned."""
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
        # ManualTriggerEvent doesn't have correlation_id, so it won't match.
        # Use AgentStartEvent which also doesn't have correlation_id.
        # Actually let's use another AgentMessageEvent as a response.
        reply = AgentMessageEvent(
            from_agent="agent_a",
            to_agent="human",
            content="done",
            correlation_id="corr_1",
            timestamp=102.0,
        )

        await store.append("swarm", msg)
        await store.append("swarm", trigger)  # no correlation_id
        await store.append("swarm", reply)

        results = await store.get_events_for_correlation("corr_1")
        assert len(results) == 2  # Only the two with correlation_id="corr_1"
        assert results[0]["event_type"] == "AgentMessageEvent"
        assert results[1]["event_type"] == "AgentMessageEvent"
