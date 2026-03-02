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

        from remora.core.agent_context import AgentContext
        from unittest.mock import AsyncMock

        ctx = AgentContext(
            agent_id="my-agent",
            emit_event=AsyncMock(),
            register_subscription=fake_register,
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        tool = SubscribeTool(ctx)

        from structured_agents.types import ToolCall

        ctx_call = ToolCall(id="call-1", name="subscribe", arguments={})
        result = await tool.execute(
            {"event_types": ["ContentChangedEvent"], "from_agents": ["other-agent"]},
            ctx_call,
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

        from remora.core.agent_context import AgentContext
        from unittest.mock import AsyncMock

        ctx = AgentContext(
            agent_id="watcher-agent",
            emit_event=AsyncMock(),
            register_subscription=fake_register,
            unsubscribe_subscription=AsyncMock(),
            broadcast=AsyncMock(),
            query_agents=AsyncMock(),
        )
        tool = SubscribeTool(ctx)

        from structured_agents.types import ToolCall

        ctx_call = ToolCall(id="call-2", name="subscribe", arguments={})
        await tool.execute({"event_types": ["AgentMessageEvent"]}, ctx_call)

        pattern = captured_patterns[0]
        # An event sent from agent-A to agent-B should match (watcher subscribes to all AgentMessageEvents)
        event = AgentMessageEvent(from_agent="agent-A", to_agent="agent-B", content="hi")
        assert pattern.matches(event), (
            "Subscription pattern from SubscribeTool should match events not addressed to the subscribing agent"
        )


class TestSubscriptionCache:
    """Verify in-memory subscription cache for O(1) lookup."""

    @pytest.mark.asyncio
    async def test_cache_avoids_repeated_db_reads(self, temp_db: Path) -> None:
        """After first get_matching_agents call, subsequent calls use cache (no DB read)."""
        registry = SubscriptionRegistry(temp_db)
        await registry.initialize()

        await registry.register("agent-1", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        event = ContentChangedEvent(path="src/main.py")

        # First call populates the cache
        result1 = await registry.get_matching_agents(event)
        assert "agent-1" in result1

        # Second call should use cache — verify by checking _cache is populated
        assert registry._cache is not None, "Cache should be populated after get_matching_agents"

        # Cache should still return correct results
        result2 = await registry.get_matching_agents(event)
        assert result1 == result2

        await registry.close()

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_register(self, temp_db: Path) -> None:
        """Registering a new subscription invalidates the cache."""
        registry = SubscriptionRegistry(temp_db)
        await registry.initialize()

        await registry.register("agent-1", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        event = ContentChangedEvent(path="src/main.py")

        # Populate cache
        result1 = await registry.get_matching_agents(event)
        assert "agent-1" in result1

        # Register a new subscription — should invalidate cache
        await registry.register("agent-2", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        assert registry._cache is None, "Cache should be invalidated after register"

        # Next call re-populates cache with updated data
        result2 = await registry.get_matching_agents(event)
        assert "agent-1" in result2
        assert "agent-2" in result2

        await registry.close()

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_unregister(self, temp_db: Path) -> None:
        """Unregistering a subscription invalidates the cache."""
        registry = SubscriptionRegistry(temp_db)
        await registry.initialize()

        sub = await registry.register("agent-1", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        event = ContentChangedEvent(path="src/main.py")

        result1 = await registry.get_matching_agents(event)
        assert "agent-1" in result1

        await registry.unregister(sub.id)
        assert registry._cache is None, "Cache should be invalidated after unregister"

        result2 = await registry.get_matching_agents(event)
        assert "agent-1" not in result2

        await registry.close()

    @pytest.mark.asyncio
    async def test_cache_invalidated_on_unregister_all(self, temp_db: Path) -> None:
        """unregister_all invalidates the cache."""
        registry = SubscriptionRegistry(temp_db)
        await registry.initialize()

        await registry.register("agent-1", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        event = ContentChangedEvent(path="src/main.py")

        await registry.get_matching_agents(event)  # Populate cache
        assert registry._cache is not None

        await registry.unregister_all("agent-1")
        assert registry._cache is None, "Cache should be invalidated after unregister_all"

        result = await registry.get_matching_agents(event)
        assert "agent-1" not in result

        await registry.close()

    @pytest.mark.asyncio
    async def test_cache_indexes_by_event_type(self, temp_db: Path) -> None:
        """Cache should index subscriptions by event_type for efficient lookup."""
        registry = SubscriptionRegistry(temp_db)
        await registry.initialize()

        # Register subscriptions for different event types
        await registry.register("agent-1", SubscriptionPattern(event_types=["ContentChangedEvent"]))
        await registry.register("agent-2", SubscriptionPattern(event_types=["AgentMessageEvent"]))
        await registry.register("agent-3", SubscriptionPattern())  # wildcard — matches all

        content_event = ContentChangedEvent(path="src/main.py")
        msg_event = AgentMessageEvent(from_agent="a", to_agent="b", content="hi")

        content_matches = await registry.get_matching_agents(content_event)
        assert "agent-1" in content_matches
        assert "agent-2" not in content_matches
        assert "agent-3" in content_matches  # wildcard matches

        msg_matches = await registry.get_matching_agents(msg_event)
        assert "agent-1" not in msg_matches
        assert "agent-2" in msg_matches
        assert "agent-3" in msg_matches  # wildcard matches

        await registry.close()
