"""Tests for SubscriptionRegistry."""

import pytest
from pathlib import Path

from remora.core.events import AgentMessageEvent, ContentChangedEvent
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry


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
