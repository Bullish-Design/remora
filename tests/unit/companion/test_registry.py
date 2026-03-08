"""Tests for NodeAgentRegistry."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.companion.config import CompanionConfig
from remora.companion.registry import NodeAgentRegistry


def make_registry(max_active=5):
    cairn = MagicMock()
    cairn.get_agent_workspace = AsyncMock(return_value=MagicMock())
    event_bus = AsyncMock()
    config = CompanionConfig(max_active_agents=max_active)
    return NodeAgentRegistry(cairn_service=cairn, event_bus=event_bus, config=config)


def make_node(node_id="node_abc"):
    node = MagicMock()
    node.node_id = node_id
    node.node_type = "function"
    node.name = "my_func"
    node.file_path = "src/foo.py"
    node.callee_ids = []
    node.caller_ids = []
    return node


@pytest.mark.asyncio
async def test_get_or_create_creates_agent():
    registry = make_registry()
    node = make_node()
    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance
        agent = await registry.get_or_create(node)
        assert agent is mock_instance
        mock_instance.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_get_or_create_returns_cached():
    registry = make_registry()
    node = make_node()
    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance
        agent1 = await registry.get_or_create(node)
        agent2 = await registry.get_or_create(node)
        assert agent1 is agent2
        assert MockAgent.call_count == 1


@pytest.mark.asyncio
async def test_evict_lru_when_at_capacity():
    registry = make_registry(max_active=2)
    agents_created = []
    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        def make_mock_agent(*args, **kwargs):
            m = AsyncMock()
            m._last_visited = float(len(agents_created))
            agents_created.append(m)
            return m

        MockAgent.side_effect = make_mock_agent
        await registry.get_or_create(make_node("node_a"))
        await registry.get_or_create(make_node("node_b"))
        await registry.get_or_create(make_node("node_c"))
        assert registry.get("node_a") is None
        assert registry.get("node_b") is not None
        assert registry.get("node_c") is not None


@pytest.mark.asyncio
async def test_explicit_evict():
    registry = make_registry()
    node = make_node()
    with patch("remora.companion.registry.NodeAgent") as MockAgent:
        mock_instance = AsyncMock()
        mock_instance._last_visited = 1000.0
        MockAgent.return_value = mock_instance
        await registry.get_or_create(node)
        assert registry.get("node_abc") is not None
        await registry.evict("node_abc")
        assert registry.get("node_abc") is None
