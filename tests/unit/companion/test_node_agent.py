"""Tests for NodeAgent core logic."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from remora.companion.config import CompanionConfig
from remora.companion.node_agent import NodeAgent, NodeMessage


def make_agent():
    node = MagicMock()
    node.node_id = "node_abc"
    node.node_type = "function"
    node.name = "my_func"
    node.file_path = "src/foo.py"
    node.start_line = 10
    node.callee_ids = []
    node.caller_ids = []
    node.to_system_prompt.return_value = "You are my_func."

    workspace = MagicMock()
    workspace.read = AsyncMock(side_effect=FileNotFoundError)
    workspace.write = AsyncMock()
    workspace.list_dir = AsyncMock(return_value=[])

    event_bus = AsyncMock()
    config = CompanionConfig(model_name="test", model_base_url="http://localhost", model_api_key="")
    return NodeAgent(node=node, workspace=workspace, event_bus=event_bus, config=config)


@pytest.mark.asyncio
async def test_node_message_factory():
    msg = NodeMessage.user("hello")
    assert msg.role == "user"
    assert msg.content == "hello"
    msg2 = NodeMessage.assistant("response")
    assert msg2.role == "assistant"


@pytest.mark.asyncio
async def test_on_cursor_focus_emits_sidebar():
    agent = make_agent()
    with patch("remora.companion.node_agent.compose_sidebar", new_callable=AsyncMock) as mock_compose:
        mock_compose.return_value = "# my_func\nfirst visit"
        await agent.on_cursor_focus()
        agent._event_bus.emit.assert_called_once()
        emitted = agent._event_bus.emit.call_args[0][0]
        assert emitted.node_id == "node_abc"
        assert "my_func" in emitted.markdown


@pytest.mark.asyncio
async def test_send_returns_response():
    agent = make_agent()
    mock_result = MagicMock()
    mock_result.final_message.content = "The bug is on line 42."
    mock_result.turn_count = 2

    mock_kernel = AsyncMock()
    mock_kernel.run = AsyncMock(return_value=mock_result)

    with patch("remora.companion.node_agent.create_kernel", return_value=mock_kernel):
        with patch("remora.companion.node_agent.run_post_exchange_swarms", new_callable=AsyncMock):
            with patch("remora.companion.node_agent.compose_sidebar", new_callable=AsyncMock, return_value=""):
                response = await agent.send("Why does this break?")

    assert response.node_id == "node_abc"
    assert response.turn_count == 2
    assert "42" in response.message.content
    assert len(agent._history) == 2
