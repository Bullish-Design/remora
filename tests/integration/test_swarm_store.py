"""Integration tests for SubscriptionRegistry pattern matching.

These tests verify subscription pattern matching logic including
to_agent, event_types, path_glob, from_agents, tags, and combined conditions.
"""

from __future__ import annotations

import pytest

from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.events.events import AgentMessageEvent, ContentChangedEvent, FileSavedEvent


@pytest.mark.asyncio
async def test_subscription_pattern_to_agent():
    """Test subscription pattern matching for to_agent field."""
    pattern = SubscriptionPattern(to_agent="agent_b")

    event = AgentMessageEvent(
        from_agent="agent_a",
        to_agent="agent_b",
        content="Hello",
    )

    assert pattern.matches(event) is True

    event_wrong = AgentMessageEvent(
        from_agent="agent_a",
        to_agent="agent_c",
        content="Hello",
    )
    assert pattern.matches(event_wrong) is False


@pytest.mark.asyncio
async def test_subscription_pattern_event_types():
    """Test subscription pattern matching for event types."""
    pattern = SubscriptionPattern(event_types=["ContentChangedEvent"])

    event = ContentChangedEvent(path="src/main.py", diff=None)
    assert pattern.matches(event) is True

    event_wrong = FileSavedEvent(path="src/main.py")
    assert pattern.matches(event_wrong) is False


@pytest.mark.asyncio
async def test_subscription_pattern_path_glob():
    """Test subscription pattern matching for path glob."""
    pattern = SubscriptionPattern(path_glob="src/*.py")

    event = ContentChangedEvent(path="src/main.py", diff=None)
    assert pattern.matches(event) is True

    event2 = ContentChangedEvent(path="src/utils/helper.py", diff=None)
    assert pattern.matches(event2) is False

    event3 = ContentChangedEvent(path="tests/test_main.py", diff=None)
    assert pattern.matches(event3) is False


@pytest.mark.asyncio
async def test_subscription_pattern_from_agents():
    """Test subscription pattern matching for from_agents."""
    pattern = SubscriptionPattern(from_agents=["agent_a", "agent_c"])

    event = AgentMessageEvent(
        from_agent="agent_a",
        to_agent="agent_b",
        content="Hello",
    )
    assert pattern.matches(event) is True

    event_b = AgentMessageEvent(
        from_agent="agent_b",
        to_agent="agent_c",
        content="Hello",
    )
    assert pattern.matches(event_b) is False


@pytest.mark.asyncio
async def test_subscription_pattern_tags():
    """Test subscription pattern matching for tags."""
    pattern = SubscriptionPattern(tags=["important", "review"])

    event = AgentMessageEvent(
        from_agent="agent_a",
        to_agent="agent_b",
        content="Hello",
        tags=["important"],
    )
    assert pattern.matches(event) is True

    event_no_tag = AgentMessageEvent(
        from_agent="agent_a",
        to_agent="agent_b",
        content="Hello",
        tags=[],
    )
    assert (pattern_no_tag := pattern.matches(event_no_tag)) is False


@pytest.mark.asyncio
async def test_subscription_pattern_combined():
    """Test subscription pattern with multiple conditions (AND logic)."""
    pattern = SubscriptionPattern(
        event_types=["ContentChangedEvent"],
        path_glob="src/*.py",
    )

    event = ContentChangedEvent(path="src/main.py", diff=None)
    assert pattern.matches(event) is True

    event_wrong_type = FileSavedEvent(path="src/main.py")
    assert pattern.matches(event_wrong_type) is False

    event_wrong_path = ContentChangedEvent(path="tests/test.py", diff=None)
    assert pattern.matches(event_wrong_path) is False


@pytest.mark.asyncio
async def test_subscription_registry_register(tmp_path):
    """Test registering a subscription."""
    registry = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await registry.initialize()

    pattern = SubscriptionPattern(to_agent="agent_a")
    sub = await registry.register("agent_a", pattern)

    assert sub.agent_id == "agent_a"
    assert sub.pattern.to_agent == "agent_a"

    await registry.close()


@pytest.mark.asyncio
async def test_subscription_registry_get_matching_agents(tmp_path):
    """Test that get_matching_agents correctly routes events."""
    registry = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await registry.initialize()

    await registry.register("agent_a", SubscriptionPattern(to_agent="agent_a"))
    await registry.register("agent_b", SubscriptionPattern(to_agent="agent_b"))
    await registry.register(
        "agent_content",
        SubscriptionPattern(event_types=["ContentChangedEvent"], path_glob="src/*.py"),
    )

    event = AgentMessageEvent(from_agent="user", to_agent="agent_a", content="Hello")
    matching = await registry.get_matching_agents(event)
    assert "agent_a" in matching
    assert "agent_b" not in matching

    event2 = ContentChangedEvent(path="src/main.py")
    matching2 = await registry.get_matching_agents(event2)
    assert "agent_content" in matching2

    await registry.close()
