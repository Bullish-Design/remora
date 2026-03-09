from __future__ import annotations

from pathlib import Path

import pytest

from remora.bootstrap.coordinator import (
    emit_agent_needed_events,
    emit_agent_needed_events_for_nodes,
    find_unassigned_modules,
    find_unassigned_nodes,
)
from remora.core.code.projections import NodeProjection
from remora.core.events.code_events import NodeDiscoveredEvent
from remora.core.store.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path) -> EventStore:
    event_store = EventStore(tmp_path / "events.db", projection=NodeProjection())
    await event_store.initialize()

    await event_store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="module:src/app.py",
            node_type="file",
            name="app.py",
            full_name="src.app",
            file_path="src/app.py",
            start_line=1,
            end_line=20,
            source_code="print('x')\n",
            source_hash="hash",
        ),
    )
    await event_store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="function:src/app.py:build_app",
            node_type="function",
            name="build_app",
            full_name="function:build_app",
            file_path="src/app.py",
            start_line=3,
            end_line=10,
            source_code="def build_app():\n    return {}\n",
            source_hash="hash2",
        ),
    )
    await event_store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="function:src/other.py:other_fn",
            node_type="function",
            name="other_fn",
            full_name="function:other_fn",
            file_path="src/other.py",
            start_line=1,
            end_line=2,
            source_code="def other_fn():\n    return 1\n",
            source_hash="hash3",
        ),
    )

    yield event_store
    await event_store.close()


@pytest.mark.asyncio
async def test_find_unassigned_modules_filters_assigned(store: EventStore) -> None:
    plans = await find_unassigned_modules(store)
    assert len(plans) == 1
    assert plans[0].node_id == "module:src/app.py"

    await store.nodes.write_graph(
        "add_node",
        {
            "id": plans[0].agent_id,
            "kind": "agent",
            "attrs": {
                "assigned_node_id": "module:src/app.py",
            },
        },
    )

    plans_after = await find_unassigned_modules(store)
    assert plans_after == []


@pytest.mark.asyncio
async def test_emit_agent_needed_events_appends_bootstrap_events(store: EventStore) -> None:
    count = await emit_agent_needed_events(store, swarm_id="swarm", coordinator_id="coordinator")
    assert count == 1

    replayed = [event async for event in store.replay("swarm")]
    needed = [event for event in replayed if event["event_type"] == "AgentNeededEvent"]
    assert len(needed) == 1
    payload = needed[0]["payload"]
    assert payload["node_id"] == "module:src/app.py"
    assert payload["agent_id"].startswith("agent-")


@pytest.mark.asyncio
async def test_find_unassigned_nodes_filters_by_file_and_assigned_targets(store: EventStore) -> None:
    plans = await find_unassigned_nodes(store, file_path="src/app.py")
    assert [plan.node_id for plan in plans] == [
        "module:src/app.py",
        "function:src/app.py:build_app",
    ]

    await store.nodes.write_graph(
        "add_node",
        {
            "id": "agent-build-app",
            "kind": "agent",
            "attrs": {
                "assigned_node_id": "function:src/app.py:build_app",
            },
        },
    )

    plans_after = await find_unassigned_nodes(store, file_path="src/app.py")
    assert [plan.node_id for plan in plans_after] == ["module:src/app.py"]


@pytest.mark.asyncio
async def test_emit_agent_needed_events_for_nodes_filters_by_file(store: EventStore) -> None:
    count = await emit_agent_needed_events_for_nodes(
        store,
        swarm_id="swarm",
        coordinator_id="coordinator",
        file_path="src/app.py",
    )
    assert count == 2

    replayed = [event async for event in store.replay("swarm")]
    needed = [event for event in replayed if event["event_type"] == "AgentNeededEvent"]
    assert len(needed) == 2
    assert {event["payload"]["node_id"] for event in needed} == {
        "module:src/app.py",
        "function:src/app.py:build_app",
    }


@pytest.mark.asyncio
async def test_emit_agent_needed_events_for_nodes_filters_by_node_type(store: EventStore) -> None:
    count = await emit_agent_needed_events_for_nodes(
        store,
        swarm_id="swarm",
        coordinator_id="coordinator",
        node_types={"function"},
    )
    assert count == 2

    replayed = [event async for event in store.replay("swarm")]
    needed = [event for event in replayed if event["event_type"] == "AgentNeededEvent"]
    node_ids = {event["payload"]["node_id"] for event in needed}
    assert node_ids == {
        "function:src/app.py:build_app",
        "function:src/other.py:other_fn",
    }
