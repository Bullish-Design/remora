"""Integration test: full EventLog -> nodes table -> AgentNode pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore
from remora.core.events.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
)
from remora.core.code.projections import NodeProjection
from remora.extensions import AgentExtension


class _TestExtension(AgentExtension):
    @staticmethod
    def matches(node_type: str, name: str) -> bool:
        return name.startswith("test_")

    @staticmethod
    def get_extension_data() -> dict:
        return {
            "extension_name": "TestAgent",
            "custom_system_prompt": "You are a test runner.",
        }


@pytest.fixture
async def store(tmp_path: Path):
    def dummy_matcher(ext_cls, node_type, name, **kwargs):
        return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)

    proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=[_TestExtension])
    s = EventStore(tmp_path / "test.db", projection=proj)
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_full_lifecycle(store: EventStore):
    # 1. Discover a test function
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_test_foo",
            node_type="function",
            name="test_foo",
            full_name="function:test_foo",
            file_path="/tests/test_billing.py",
            start_line=10,
            end_line=20,
            source_code="def test_foo(): assert True",
            source_hash="hash1",
        ),
    )

    # Verify extension was matched
    node = await store.nodes.get_node("node_test_foo")
    assert node is not None
    assert node.extension_name == "TestAgent"
    assert node.custom_system_prompt == "You are a test runner."
    assert node.status == "idle"

    # 2. Start the agent
    await store.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="node_test_foo", node_name="test_foo"),
    )
    node = await store.nodes.get_node("node_test_foo")
    assert node.status == "running"

    # 3. Complete the agent
    await store.append(
        "swarm",
        AgentCompleteEvent(graph_id="s", agent_id="node_test_foo", result_summary="done"),
    )
    node = await store.nodes.get_node("node_test_foo")
    assert node.status == "idle"
    assert node.last_completed_at is not None

    # 4. Verify prompt generation
    prompt = node.to_system_prompt()
    assert "test_foo" in prompt
    assert "TestAgent" in prompt

    # 5. Verify LSP output
    lens = node.to_code_lens()
    assert lens.command.command == "remora.selectAgent"

    # 6. Remove the node
    await store.append("swarm", NodeRemovedEvent(node_id="node_test_foo"))
    node = await store.nodes.get_node("node_test_foo")
    assert node is None


@pytest.mark.asyncio
async def test_re_discovery_preserves_status(store: EventStore):
    """Re-discovering a node should update source but preserve runtime status."""
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_1",
            node_type="function",
            name="calc",
            full_name="function:calc",
            file_path="/src/a.py",
            start_line=1,
            end_line=5,
            source_code="v1",
            source_hash="h1",
        ),
    )
    await store.append(
        "swarm",
        AgentStartEvent(graph_id="s", agent_id="node_1", node_name="calc"),
    )

    # Re-discover with new source
    await store.append(
        "swarm",
        NodeDiscoveredEvent(
            node_id="node_1",
            node_type="function",
            name="calc",
            full_name="function:calc",
            file_path="/src/a.py",
            start_line=1,
            end_line=8,
            source_code="v2",
            source_hash="h2",
        ),
    )

    node = await store.nodes.get_node("node_1")
    assert node.source_hash == "h2"
    assert node.end_line == 8
    # Status preserved from before re-discovery (projection upsert preserves status)
    assert node.status == "running"
