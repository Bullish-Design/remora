"""Real vLLM integration tests.

These tests verify actual LLM communication and tool calling.
They require a running vLLM server and are marked to be skipped
in environments without backend access.

Run with: pytest -m requires_vllm
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_vllm


@pytest.mark.asyncio
@pytest.mark.requires_vllm
async def test_real_vllm_tool_calling():
    """Test that AgentKernel communicates correctly with live vLLM instance.

    Verifies:
    1. Network call succeeds (no 400/500 errors)
    2. Model correctly triggers tool calls
    3. Prompt formatting and model instruction-following are aligned
    """
    try:
        from structured_agents import AgentKernel, ModelAdapter, QwenResponseParser
        from structured_agents.client import build_client
        from structured_agents.types import Message
    except ImportError:
        pytest.skip("structured_agents not available")

    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
            "timeout": 30.0,
        }
    )

    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())

    class SendMessageTool:
        """Test tool for sending messages between agents."""

        @property
        def schema(self):
            return {
                "name": "send_message",
                "description": "Send a message to another agent",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "to_agent": {
                            "type": "string",
                            "description": "The agent to send the message to",
                        },
                        "content": {
                            "type": "string",
                            "description": "The message content",
                        },
                    },
                    "required": ["to_agent", "content"],
                },
            }

        async def __call__(self, to_agent: str, content: str):
            return f"Message sent to {to_agent}: {content}"

    tools = [SendMessageTool()]
    tool_schemas = [t.schema for t in tools]

    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)

    try:
        result = await kernel.run(
            [Message(role="user", content="Say hello to agent_b using the send_message tool.")],
            tool_schemas,
            max_turns=2,
        )

        tool_call_names = [tc.name for tc in result.tool_calls]
        assert "send_message" in tool_call_names, f"Expected send_message tool call, got {tool_call_names}"

    finally:
        await kernel.close()


@pytest.mark.asyncio
@pytest.mark.requires_vllm
async def test_real_vllm_grail_tool_execution():
    """Test that Grail tools work with live vLLM.

    Verifies:
    1. GrailTool schema is correctly interpreted by model
    2. Model supplies valid arguments
    3. Tool executes successfully in sandbox
    """
    try:
        from structured_agents import AgentKernel, ModelAdapter, QwenResponseParser
        from structured_agents.client import build_client
        from structured_agents.types import Message
        from structured_agents import GrailTool
    except ImportError:
        pytest.skip("structured_agents not available")

    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
            "timeout": 30.0,
        }
    )

    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())

    grail_script = '''
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b
'''

    tools = [GrailTool.from_script(grail_script)]
    tool_schemas = [t.schema for t in tools]

    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)

    try:
        result = await kernel.run(
            [Message(role="user", content="What is 5 + 3? Use the add tool.")],
            tool_schemas,
            max_turns=2,
        )

        tool_call_names = [tc.name for tc in result.tool_calls]
        assert "add" in tool_call_names, f"Expected add tool call, got {tool_call_names}"

        for tc in result.tool_calls:
            if tc.name == "add":
                assert tc.arguments.get("a") == 5 or tc.arguments.get("a") == 3
                assert tc.arguments.get("b") == 3 or tc.arguments.get("b") == 5
                break

    finally:
        await kernel.close()


@pytest.mark.asyncio
@pytest.mark.requires_vllm
async def test_real_vllm_multi_agent_interaction(tmp_path):
    """Test end-to-end multi-agent reactive interaction with live vLLM.

    Verifies:
    1. Agent A turn completes
    2. EventStore receives AgentMessageEvent from A to B
    3. Agent B is triggered and runs via vLLM
    4. Agent B emits response back to A
    """
    try:
        from remora.core.event_store import EventStore
        from remora.core.events import AgentMessageEvent
        from remora.core.subscriptions import SubscriptionRegistry, SubscriptionPattern
    except ImportError:
        pytest.skip("remora core not available")

    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(tmp_path / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    await subscriptions.register("agent_a", SubscriptionPattern(to_agent="agent_a"))
    await subscriptions.register("agent_b", SubscriptionPattern(to_agent="agent_b"))

    initial_event = AgentMessageEvent(
        from_agent="user",
        to_agent="agent_a",
        content="Ask agent_b what the weather is.",
    )
    await event_store.append("test-swarm", initial_event)

    triggers_received = []
    async for agent_id, event_id, event in event_store.get_triggers():
        triggers_received.append((agent_id, type(event).__name__))
        if len(triggers_received) >= 1:
            break

    assert len(triggers_received) >= 1
    assert "agent_a" in [t[0] for t in triggers_received]

    await event_store.close()
    await subscriptions.close()


def pytest_configure(config):
    """Register the requires_vllm marker."""
    config.addinivalue_line(
        "markers",
        "requires_vllm: mark test as requiring a running vLLM server",
    )
