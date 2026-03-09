from __future__ import annotations

from pathlib import Path

import pytest

from remora.bootstrap.coordinator import emit_agent_needed_events, find_unassigned_modules
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
