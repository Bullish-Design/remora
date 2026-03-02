"""Tests for SubscriptionRegistry."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from remora.core.events import AgentMessageEvent, ContentChangedEvent
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.tools.swarm import SubscribeTool


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_subscriptions.db"


@pytest.mark.asyncio
async def test_register_subscription(temp_db: Path) -> None:
    registry = SubscriptionRegistry(temp_db)
    await registry.initialize()

    pattern = SubscriptionPattern(to_agent="agent-123")
    sub = await registry.register("agent-123", pattern)

    assert sub.agent_id == "agent-123"
    assert sub.pattern.to_agent == "agent-123"
    assert not sub.is_default

    await registry.close()


@pytest.mark.asyncio
async def test_register_defaults(temp_db: Path) -> None:
    registry = SubscriptionRegistry(temp_db)
    await registry.initialize()

    subs = await registry.register_defaults("agent-abc", "src/main.py")

    assert len(subs) == 2
    assert subs[0].pattern.to_agent == "agent-abc"
    assert subs[0].is_default

    await registry.close()


@pytest.mark.asyncio
async def test_get_matching_agents(temp_db: Path) -> None:
    registry = SubscriptionRegistry(temp_db)
    await registry.initialize()

    await registry.register("agent-1", SubscriptionPattern(to_agent="agent-1"))
    await registry.register("agent-2", SubscriptionPattern(event_types=["ContentChangedEvent"]))

    event = AgentMessageEvent(
        from_agent="user",
        to_agent="agent-1",
        content="hello",
    )
    matching = await registry.get_matching_agents(event)
    assert "agent-1" in matching

    file_event = ContentChangedEvent(path="src/main.py")
    matching = await registry.get_matching_agents(file_event)
    assert "agent-2" in matching

    await registry.close()


@pytest.mark.asyncio
async def test_unregister_all(temp_db: Path) -> None:
    registry = SubscriptionRegistry(temp_db)
    await registry.initialize()

    await registry.register("agent-1", SubscriptionPattern(to_agent="agent-1"))
    await registry.register_defaults("agent-2", "src/main.py")

    count = await registry.unregister_all("agent-1")
    assert count >= 1

    subs = await registry.get_subscriptions("agent-1")
    assert len(subs) == 0

    await registry.close()


@pytest.mark.asyncio
async def test_unregister_by_id(temp_db: Path) -> None:
    registry = SubscriptionRegistry(temp_db)
    await registry.initialize()

    pattern = SubscriptionPattern(to_agent="agent-x")
    sub = await registry.register("agent-x", pattern)

    removed = await registry.unregister(sub.id)
    assert removed

    subs = await registry.get_subscriptions("agent-x")
    assert len(subs) == 0

    await registry.close()


@pytest.mark.asyncio
async def test_pattern_matching_event_types() -> None:
    pattern = SubscriptionPattern(event_types=["AgentMessageEvent", "ContentChangedEvent"])

    msg_event = AgentMessageEvent(from_agent="a", to_agent="b", content="test")
    assert pattern.matches(msg_event)

    file_event = ContentChangedEvent(path="test.py")
    assert pattern.matches(file_event)

    start_event = type("CustomEvent", (), {"graph_id": "x", "node_count": 1})()
    assert not pattern.matches(start_event)


@pytest.mark.asyncio
async def test_pattern_matching_path_glob() -> None:
    pattern = SubscriptionPattern(path_glob="src/*.py")

    event1 = ContentChangedEvent(path="src/main.py")
    assert pattern.matches(event1)

    event2 = ContentChangedEvent(path="tests/test_main.py")
    assert not pattern.matches(event2)


@pytest.mark.asyncio
async def test_pattern_matching_tags() -> None:
    pattern = SubscriptionPattern(tags=["important", "urgent"])

    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="test",
        tags=["urgent"],
    )
    assert pattern.matches(event)

    event_no_tags = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="test",
    )
    assert not pattern.matches(event_no_tags)


class TestSubscribeToolPattern:
    """Verify SubscribeTool does not self-reference the subscribing agent."""

    @pytest.mark.asyncio
    async def test_subscribe_tool_does_not_set_to_agent(self) -> None:
        """SubscribeTool should NOT set to_agent=agent_id (the subscriber).

        The to_agent field filters events by their *destination*. Setting it
        to the subscribing agent's own ID would make the subscription only
        match events explicitly addressed to that agent — which is already
        covered by the default direct-message subscription.
        """
        captured_patterns: list[SubscriptionPattern] = []

        async def fake_register(agent_id: str, pattern: SubscriptionPattern) -> None:
            captured_patterns.append(pattern)

        tool = SubscribeTool(
            externals={
                "agent_id": "my-agent",
                "register_subscription": fake_register,
            }
        )

        from structured_agents.types import ToolCall

        ctx = ToolCall(id="call-1", name="subscribe", arguments={})
        result = await tool.execute(
            {"event_types": ["ContentChangedEvent"], "from_agents": ["other-agent"]},
            ctx,
        )

        assert not result.is_error
        assert len(captured_patterns) == 1
        pattern = captured_patterns[0]
        # to_agent must be None — not the subscribing agent's own ID
        assert pattern.to_agent is None, (
            f"SubscribeTool set to_agent={pattern.to_agent!r}, but should leave it None to avoid self-referencing"
        )
        assert pattern.event_types == ["ContentChangedEvent"]
        assert pattern.from_agents == ["other-agent"]

    @pytest.mark.asyncio
    async def test_subscribe_tool_pattern_matches_external_events(self) -> None:
        """A subscription from SubscribeTool should match events NOT addressed to the subscriber."""
        captured_patterns: list[SubscriptionPattern] = []

        async def fake_register(agent_id: str, pattern: SubscriptionPattern) -> None:
            captured_patterns.append(pattern)

        tool = SubscribeTool(
            externals={
                "agent_id": "watcher-agent",
                "register_subscription": fake_register,
            }
        )

        from structured_agents.types import ToolCall

        ctx = ToolCall(id="call-2", name="subscribe", arguments={})
        await tool.execute({"event_types": ["AgentMessageEvent"]}, ctx)

        pattern = captured_patterns[0]
        # An event sent from agent-A to agent-B should match (watcher subscribes to all AgentMessageEvents)
        event = AgentMessageEvent(from_agent="agent-A", to_agent="agent-B", content="hi")
        assert pattern.matches(event), (
            "Subscription pattern from SubscribeTool should match events not addressed to the subscribing agent"
        )
