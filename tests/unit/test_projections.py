"""Tests for EventLog -> nodes table projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    ScaffoldRequestEvent,
)
from remora.core.code.projections import NodeProjection
from remora.extensions import AgentExtension


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def projection():
    return NodeProjection(extension_configs=[])


def _discovered_event(**overrides) -> NodeDiscoveredEvent:
    defaults = {
        "node_id": "abc123",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "function:calculate_total",
        "file_path": "/src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "source_code": "def calculate_total():\n    return sum(items)",
        "source_hash": "aabb",
    }
    defaults.update(overrides)
    return NodeDiscoveredEvent(**defaults)


class TestProjectNodeDiscovered:
    @pytest.mark.asyncio
    async def test_insert_new_node(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row is not None
        assert row["name"] == "calculate_total"
        assert row["status"] == "idle"

    @pytest.mark.asyncio
    async def test_upsert_existing_node(self, store: EventStore, projection: NodeProjection):
        event1 = _discovered_event(source_hash="v1")
        projection.apply(store._conn, event1)

        event2 = _discovered_event(source_hash="v2", source_code="def calculate_total(x):\n    return x * 2")
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["source_hash"] == "v2"

    @pytest.mark.asyncio
    def dummy_matcher(self, ext_cls, node_type, name, **kwargs):
        return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)

    @pytest.mark.asyncio
    async def test_extension_customizations_applied(self, store: EventStore):
        class TestExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return name.startswith("test_")

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "extension_name": "TestAgent",
                    "custom_system_prompt": "You run tests.",
                }

        proj = NodeProjection(extension_matcher=self.dummy_matcher, extension_configs=[TestExt])
        event = _discovered_event(name="test_foo", full_name="function:test_foo")
        proj.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["extension_name"] == "TestAgent"
        assert row["custom_system_prompt"] == "You run tests."

    @pytest.mark.asyncio
    async def test_extension_matching(self, store: EventStore):
        class TestExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return name.startswith("test_")

            @staticmethod
            def get_extension_data() -> dict:
                return {
                    "extension_name": "TestAgent",
                    "custom_system_prompt": "You run tests.",
                }

        proj = NodeProjection(extension_matcher=self.dummy_matcher, extension_configs=[TestExt])
        event = _discovered_event(name="test_foo", full_name="function:test_foo")
        proj.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["extension_name"] == "TestAgent"
        assert row["custom_system_prompt"] == "You run tests."

    @pytest.mark.asyncio
    async def test_no_extension_match(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["extension_name"] is None

    @pytest.mark.asyncio
    async def test_hydrate_from_projection(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        node = AgentNode.from_row(row)
        assert node.node_id == "abc123"
        assert node.name == "calculate_total"

    @pytest.mark.asyncio
    async def test_byte_offsets_projected(self, store: EventStore, projection: NodeProjection):
        """start_byte and end_byte should be stored in the nodes table."""
        event = _discovered_event(start_byte=100, end_byte=450)
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["start_byte"] == 100
        assert row["end_byte"] == 450

    @pytest.mark.asyncio
    async def test_byte_offsets_hydrate_to_agent_node(self, store: EventStore, projection: NodeProjection):
        """start_byte and end_byte should round-trip through AgentNode.from_row."""
        event = _discovered_event(start_byte=100, end_byte=450)
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        node = AgentNode.from_row(row)
        assert node.start_byte == 100
        assert node.end_byte == 450

    @pytest.mark.asyncio
    async def test_byte_offsets_default_zero(self, store: EventStore, projection: NodeProjection):
        """When not specified, start_byte and end_byte should default to 0."""
        event = _discovered_event()
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["start_byte"] == 0
        assert row["end_byte"] == 0


class TestProjectStatusUpdates:
    @pytest.mark.asyncio
    async def test_agent_start_sets_running(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())

        start = AgentStartEvent(graph_id="swarm", agent_id="abc123", node_name="calculate_total")
        projection.apply(store._conn, start)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "running"

    @pytest.mark.asyncio
    async def test_agent_start_populates_last_trigger_event(self, store: EventStore, projection: NodeProjection):
        """AgentStartEvent should write trigger_event_type into last_trigger_event."""
        projection.apply(store._conn, _discovered_event())

        start = AgentStartEvent(
            graph_id="swarm",
            agent_id="abc123",
            node_name="calculate_total",
            trigger_event_type="ContentChangedEvent",
        )
        projection.apply(store._conn, start)

        row = store._conn.execute(
            "SELECT last_trigger_event FROM nodes WHERE node_id = ?",
            ("abc123",),
        ).fetchone()
        assert row["last_trigger_event"] == "ContentChangedEvent"

    @pytest.mark.asyncio
    async def test_agent_start_default_trigger_event_type(self, store: EventStore, projection: NodeProjection):
        """When trigger_event_type is empty, last_trigger_event should be empty."""
        projection.apply(store._conn, _discovered_event())

        start = AgentStartEvent(graph_id="swarm", agent_id="abc123", node_name="calculate_total")
        projection.apply(store._conn, start)

        row = store._conn.execute(
            "SELECT last_trigger_event FROM nodes WHERE node_id = ?",
            ("abc123",),
        ).fetchone()
        assert row["last_trigger_event"] == ""

    @pytest.mark.asyncio
    async def test_agent_complete_sets_idle(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        projection.apply(
            store._conn,
            AgentStartEvent(graph_id="s", agent_id="abc123", node_name="x"),
        )
        complete = AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done")
        projection.apply(store._conn, complete)

        row = store._conn.execute(
            "SELECT status, last_completed_at FROM nodes WHERE node_id = ?",
            ("abc123",),
        ).fetchone()
        assert row["status"] == "idle"
        assert row["last_completed_at"] is not None

    @pytest.mark.asyncio
    async def test_agent_error_sets_error(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        error = AgentErrorEvent(graph_id="s", agent_id="abc123", error="boom")
        projection.apply(store._conn, error)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "error"

    @pytest.mark.asyncio
    async def test_rediscovery_preserves_running_status(self, store: EventStore, projection: NodeProjection):
        """When a node is 'running' and gets re-discovered, status should stay 'running'."""
        projection.apply(store._conn, _discovered_event())
        start = AgentStartEvent(graph_id="swarm", agent_id="abc123", node_name="calculate_total")
        projection.apply(store._conn, start)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "running"

        # Re-discover while running (e.g., watcher detects file change)
        event2 = _discovered_event(source_hash="v2", source_code="def calculate_total():\n    return sum(items)")
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "running"

    @pytest.mark.asyncio
    async def test_rediscovery_preserves_error_status(self, store: EventStore, projection: NodeProjection):
        """When a node is 'error' and gets re-discovered, status should stay 'error'."""
        projection.apply(store._conn, _discovered_event())
        error = AgentErrorEvent(graph_id="s", agent_id="abc123", error="boom")
        projection.apply(store._conn, error)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "error"

        # Re-discover while in error state
        event2 = _discovered_event(source_hash="v2", source_code="def calculate_total():\n    return sum(items)")
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "error"


class TestAgentCompleteEventTags:
    @pytest.mark.asyncio
    async def test_tags_default_empty(self, store: EventStore, projection: NodeProjection):
        """AgentCompleteEvent.tags defaults to empty tuple."""
        event = AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done")
        assert event.tags == ()

    @pytest.mark.asyncio
    async def test_tags_can_be_set(self, store: EventStore, projection: NodeProjection):
        """AgentCompleteEvent accepts tags for chained workflows."""
        event = AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done", tags=("scaffold",))
        assert event.tags == ("scaffold",)

    @pytest.mark.asyncio
    async def test_tags_multiple_values(self, store: EventStore, projection: NodeProjection):
        """tags supports multiple values."""
        event = AgentCompleteEvent(
            graph_id="s", agent_id="abc123", result_summary="done", tags=("scaffold", "interface")
        )
        assert event.tags == ("scaffold", "interface")

    @pytest.mark.asyncio
    async def test_existing_code_without_tags_works(self, store: EventStore, projection: NodeProjection):
        """Existing callers that don't pass tags should continue to work."""
        projection.apply(store._conn, _discovered_event())
        projection.apply(
            store._conn,
            AgentStartEvent(graph_id="s", agent_id="abc123", node_name="x"),
        )
        # This is how existing code calls it — no tags arg
        complete = AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done")
        projection.apply(store._conn, complete)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "idle"


class TestNodeRemoved:
    @pytest.mark.asyncio
    async def test_remove_deletes_row(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        projection.apply(store._conn, NodeRemovedEvent(node_id="abc123"))

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row is None


# ============================================================================
# Projection integration tests — scaffold status
# ============================================================================


@pytest.mark.skip(reason="Scaffold projection disabled until AST-based detection lands")
class TestScaffoldStatusProjection:
    """NodeProjection assigns status='scaffold' for stub source_code."""


@pytest.mark.skip(reason="Scaffold projection disabled until AST-based detection lands")
class TestScaffoldFollowUpEvents:
    """Verify that NodeProjection emits ScaffoldRequestEvent as a follow-up
    when a stub node is discovered (status='scaffold')."""

    @pytest.mark.asyncio
    async def test_stub_node_returns_scaffold_request(self, store: EventStore, projection: NodeProjection):
        """Discovering a stub node should return a ScaffoldRequestEvent follow-up."""
        stub_event = _discovered_event(
            source_code="def calculate_total(): ...",
            parent_id="parent_1",
        )
        follow_ups = projection.apply(store._conn, stub_event)

        assert len(follow_ups) == 1
        assert isinstance(follow_ups[0], ScaffoldRequestEvent)
        assert follow_ups[0].node_id == "abc123"
        assert follow_ups[0].to_agent == "abc123"
        assert follow_ups[0].node_type == "function"
        assert follow_ups[0].parent_id == "parent_1"

    @pytest.mark.asyncio
    async def test_non_stub_node_returns_no_follow_up(self, store: EventStore, projection: NodeProjection):
        """Discovering a non-stub node should return an empty list."""
        event = _discovered_event(
            source_code="def calculate_total():\n    return sum(items)",
        )
        follow_ups = projection.apply(store._conn, event)

        assert follow_ups == []

    @pytest.mark.asyncio
    async def test_non_discovered_events_return_empty(self, store: EventStore, projection: NodeProjection):
        """Non-NodeDiscoveredEvent events should return an empty list."""
        projection.apply(store._conn, _discovered_event())  # need the node first
        start = AgentStartEvent(graph_id="swarm", agent_id="abc123", node_name="x")
        follow_ups = projection.apply(store._conn, start)
        assert follow_ups == []

    @pytest.mark.asyncio
    async def test_stub_rediscovery_while_running_no_follow_up(self, store: EventStore, projection: NodeProjection):
        """Re-discovering a stub while running should NOT emit ScaffoldRequestEvent
        (status is preserved as 'running', not set to 'scaffold')."""
        # First discover as stub
        stub_event = _discovered_event(source_code="def calculate_total(): ...")
        projection.apply(store._conn, stub_event)

        # Mark as running
        start = AgentStartEvent(graph_id="swarm", agent_id="abc123", node_name="x")
        projection.apply(store._conn, start)

        # Re-discover while running — status stays 'running', no scaffold follow-up
        stub_event2 = _discovered_event(source_code="def calculate_total(): ...", source_hash="v2")
        follow_ups = projection.apply(store._conn, stub_event2)
        assert follow_ups == []

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "running"

    @pytest.mark.asyncio
    async def test_event_store_reappends_follow_ups(self, tmp_path):
        """EventStore.append() should re-append follow-up events from projection."""
        projection = NodeProjection()
        es = EventStore(tmp_path / "test_followup.db", projection=projection)
        await es.initialize()

        try:
            stub_event = _discovered_event(source_code="class Foo: ...")
            await es.append("swarm", stub_event)

            # The follow-up ScaffoldRequestEvent should have been appended
            events = []
            async for ev in es.replay("swarm"):
                events.append(ev)

            event_types = [e["event_type"] for e in events]
            assert "NodeDiscoveredEvent" in event_types
            assert "ScaffoldRequestEvent" in event_types
        finally:
            await es.close()

    @pytest.mark.asyncio
    async def test_scaffold_request_matches_default_direct_subscription(
        self, store: EventStore, projection: NodeProjection
    ):
        """ScaffoldRequestEvent with to_agent should match the default direct-message subscription.

        register_defaults() creates SubscriptionPattern(to_agent=agent_id) which
        is a wildcard (no event_types filter). ScaffoldRequestEvent has to_agent=node_id,
        so the subscription should match.
        """
        from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry

        registry = SubscriptionRegistry(connection=store._conn, lock=store._lock)

        # Register default subscriptions for agent "abc123"
        await registry.register_defaults("abc123", "/src/billing.py")

        # Create a ScaffoldRequestEvent as it would come from the projection
        scaffold_event = ScaffoldRequestEvent(
            node_id="abc123",
            to_agent="abc123",
            node_type="function",
            parent_id="parent_1",
        )

        # The default direct-message subscription should match
        matching = await registry.get_matching_agents(scaffold_event)
        assert "abc123" in matching
