from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from remora.bootstrap.bedrock import BootstrapEvent, build_bedrock


@pytest.fixture
def bedrock_deps():
    cairn = AsyncMock()
    node_store = AsyncMock()

    event_store = AsyncMock()
    event_store.nodes = node_store
    event_store.get_recent_events = AsyncMock(return_value=[{"id": 1, "event_type": "X"}])
    event_store.append = AsyncMock(return_value=42)

    return cairn, node_store, event_store


@pytest.mark.asyncio
async def test_cairn_read_delegates(bedrock_deps) -> None:
    cairn, _, event_store = bedrock_deps
    cairn.read_file.return_value = "hello"

    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=cairn,
        event_store=event_store,
        swarm_id="swarm",
    )

    result = await bedrock["_cairn_read"]("notes.md")
    assert result == "hello"
    cairn.read_file.assert_awaited_once_with("notes.md")


@pytest.mark.asyncio
async def test_cairn_write_delegates(bedrock_deps) -> None:
    cairn, _, event_store = bedrock_deps
    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=cairn,
        event_store=event_store,
        swarm_id="swarm",
    )

    result = await bedrock["_cairn_write"]("notes.md", "content")
    assert result == "ok"
    cairn.write_file.assert_awaited_once_with("notes.md", "content")


@pytest.mark.asyncio
async def test_graph_read_delegates_to_node_store(bedrock_deps) -> None:
    _, node_store, event_store = bedrock_deps
    node_store.read_graph = AsyncMock(return_value='{"ok":true}')

    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=AsyncMock(),
        event_store=event_store,
        swarm_id="swarm",
    )
    selector = {"match": {"kind": "agent"}}
    result = await bedrock["_graph_read"](selector)
    assert result == '{"ok":true}'
    node_store.read_graph.assert_awaited_once_with(selector)


@pytest.mark.asyncio
async def test_graph_write_delegates_to_node_store(bedrock_deps) -> None:
    _, node_store, event_store = bedrock_deps
    node_store.write_graph = AsyncMock(return_value='{"id":"n1"}')

    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=AsyncMock(),
        event_store=event_store,
        swarm_id="swarm",
    )
    result = await bedrock["_graph_write"]("add_node", {"kind": "agent", "attrs": {}})
    assert json.loads(result)["id"] == "n1"
    node_store.write_graph.assert_awaited_once_with("add_node", {"kind": "agent", "attrs": {}})


@pytest.mark.asyncio
async def test_event_read_calls_get_recent_events(bedrock_deps) -> None:
    _, _, event_store = bedrock_deps
    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=AsyncMock(),
        event_store=event_store,
        swarm_id="swarm",
    )

    payload = json.loads(await bedrock["_event_read"]({"limit": 3}))
    assert payload[0]["id"] == 1
    event_store.get_recent_events.assert_awaited_once_with("agent-1", limit=3)


@pytest.mark.asyncio
async def test_event_write_appends_bootstrap_event(bedrock_deps) -> None:
    _, _, event_store = bedrock_deps
    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=AsyncMock(),
        event_store=event_store,
        swarm_id="swarm",
    )

    result = json.loads(await bedrock["_event_write"]("AgentNeededEvent", {"node_id": "file:1"}))
    assert result["event_id"] == 42

    append_args = event_store.append.await_args
    assert append_args.args[0] == "swarm"
    emitted = append_args.args[1]
    assert isinstance(emitted, BootstrapEvent)
    assert emitted.event_type == "AgentNeededEvent"
    assert emitted.from_agent == "agent-1"


@pytest.mark.asyncio
async def test_bedrock_exposes_grail_safe_aliases(bedrock_deps) -> None:
    cairn, _, event_store = bedrock_deps
    cairn.read_file.return_value = "hello"

    bedrock = build_bedrock(
        agent_id="agent-1",
        cairn_externals=cairn,
        event_store=event_store,
        swarm_id="swarm",
    )

    assert "cairn_read" in bedrock
    assert "graph_read" in bedrock
    assert "event_write" in bedrock
    assert await bedrock["cairn_read"]("notes.md") == "hello"
