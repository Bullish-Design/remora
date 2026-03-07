"""Test that EventStore.append() triggers node projection."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.code.projections import NodeProjection


@pytest.fixture
async def store_with_projection(tmp_path: Path):
    projection = NodeProjection(extension_configs=[])
    s = EventStore(tmp_path / "test.db", projection=projection)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_append_node_discovered_projects_to_table(store_with_projection: EventStore):
    event = NodeDiscoveredEvent(
        node_id="abc123",
        node_type="function",
        name="foo",
        full_name="function:foo",
        file_path="/test.py",
        start_line=1,
        end_line=5,
        source_code="def foo(): pass",
        source_hash="hash1",
    )
    await store_with_projection.append("swarm", event)

    row = store_with_projection._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
    assert row is not None
    assert row["name"] == "foo"


@pytest.mark.asyncio
async def test_append_status_events_update_nodes(store_with_projection: EventStore):
    # First create the node
    await store_with_projection.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="function:foo",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        ),
    )

    # Start the agent
    await store_with_projection.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="abc123", node_name="foo"),
    )
    row = store_with_projection._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
    assert row["status"] == "running"

    # Complete it
    await store_with_projection.append(
        "swarm",
        AgentCompleteEvent(graph_id="s", agent_id="abc123", result_summary="done"),
    )
    row = store_with_projection._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
    assert row["status"] == "idle"


@pytest.mark.asyncio
async def test_append_node_removed_deletes_from_table(store_with_projection: EventStore):
    await store_with_projection.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="foo",
            full_name="function:foo",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        ),
    )
    await store_with_projection.append("swarm", NodeRemovedEvent(node_id="abc123"))

    row = store_with_projection._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
    assert row is None
