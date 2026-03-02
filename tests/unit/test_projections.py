"""Tests for EventLog -> nodes table projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.projections import NodeProjection
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
        "source_code": "def calculate_total(): pass",
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

        event2 = _discovered_event(source_hash="v2", source_code="def calculate_total(x): pass")
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["source_hash"] == "v2"

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

        proj = NodeProjection(extension_configs=[TestExt])
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


class TestProjectNodeRemoved:
    @pytest.mark.asyncio
    async def test_remove_deletes_row(self, store: EventStore, projection: NodeProjection):
        projection.apply(store._conn, _discovered_event())
        projection.apply(store._conn, NodeRemovedEvent(node_id="abc123"))

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row is None
