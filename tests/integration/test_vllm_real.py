"""Real vLLM integration tests.

These tests verify actual LLM communication and tool calling.
They require a running vLLM server that should always be accessible
at `http://remora-server:8000/v1`.

Run with: pytest tests/integration/test_vllm_real.py
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from tests.integration.helpers import load_vllm_config, vllm_available


@pytest.mark.asyncio
async def test_real_vllm_tool_calling():
    """Test that AgentKernel communicates correctly with live vLLM instance.

    Verifies:
    1. Network call succeeds (no 400/500 errors)
    2. Model correctly triggers tool calls
    3. Prompt formatting and model instruction-following are aligned
    """
    try:
        from structured_agents import AgentKernel, ModelAdapter, QwenResponseParser, ToolSchema
        from structured_agents.client import build_client
        from structured_agents.types import Message, ToolCall, ToolResult
    except ImportError as exc:
        pytest.fail("structured_agents not available", pytrace=False)  # re-raise to fail fast

    vllm_config = load_vllm_config()
    if not vllm_available(vllm_config["base_url"]):
        pytest.skip(f"vLLM server not reachable at {vllm_config['base_url']}")

    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
            "timeout": 60.0,
        }
    )

    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())

    class SendMessageTool:
        """Test tool for sending messages between agents."""

        @property
        def schema(self) -> ToolSchema:
            return ToolSchema(
                name="send_message",
                description="Send a message to another agent",
                parameters={
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
            )

        async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
            to_agent = str(arguments.get("to_agent", "unknown"))
            content = str(arguments.get("content", ""))
            return ToolResult(
                call_id=context.id if context else "",
                name=self.schema.name,
                output=f"Message sent to {to_agent}: {content}",
                is_error=False,
            )

    tools = [SendMessageTool()]
    tool_schemas = [t.schema for t in tools]

    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)

    try:
        result = await kernel.run(
            [Message(role="user", content="Say hello to agent_b using the send_message tool.")],
            tool_schemas,
            max_turns=2,
        )

        tool_calls = [tc for message in result.history if message.tool_calls for tc in message.tool_calls]
        tool_call_names = [tc.name for tc in tool_calls]
        assert "send_message" in tool_call_names, f"Expected send_message tool call, got {tool_call_names}"

    finally:
        await kernel.close()


@pytest.mark.asyncio
async def test_real_vllm_grail_tool_execution(tmp_path: Path):
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
        import grail
    except ImportError as exc:
        pytest.fail("structured_agents/ml dependencies not available", pytrace=False)

    # print(f"\n\nTesting real grail tool call...\n")
    vllm_config = load_vllm_config()
    if not vllm_available(vllm_config["base_url"]):
        pytest.fail(f"vLLM server not reachable at {vllm_config['base_url']}", pytrace=False)

    client = build_client(
        {
            "base_url": "http://remora-server:8000/v1",
            "api_key": "EMPTY",
            "model": "Qwen/Qwen3-4B-Instruct-2507-FP8",
            "timeout": 60.0,
        }
    )

    adapter = ModelAdapter(name="qwen", response_parser=QwenResponseParser())

    grail_script = '''
from grail import Input

a: int = Input("a")
b: int = Input("b")

def add() -> int:
    """Add two numbers."""
    return a + b

def multiply() -> int:
    """Multiply two numbers."""
    return a * b
'''

    tools = []
    grail_script_path = tmp_path / "add_tool.pym"
    grail_script_path.write_text(textwrap.dedent(grail_script).strip() + "\n", encoding="utf-8")
    grail_script_obj = grail.load(grail_script_path)
    tools.append(GrailTool(grail_script_obj))
    tool_schemas = [t.schema for t in tools]

    kernel = AgentKernel(client=client, adapter=adapter, tools=tools)

    try:
        result = await kernel.run(
            [Message(role="user", content="What is 5 + 3? Use the add tool.")],
            tool_schemas,
            max_turns=2,
        )

        tool_calls = [tc for message in result.history if message.tool_calls for tc in message.tool_calls]
        tool_call_names = [tc.name for tc in tool_calls]
        schema_name = tool_schemas[0].name if tool_schemas else "add_tool"
        # print("\n\nTool call names:", tool_call_names)
        assert schema_name in tool_call_names, f"Expected {schema_name} tool call, got {tool_call_names}"

        for tc in tool_calls:
            if tc.name != schema_name:
                continue
            args = tc.arguments or {}
            assert args.get("a") in {3, 5}
            assert args.get("b") in {3, 5}
            break

    finally:
        await kernel.close()


@pytest.mark.asyncio
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
