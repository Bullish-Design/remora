"""Integration tests for SwarmStore (SwarmState) and SubscriptionRegistry.

These tests verify:
1. Agent persistence across restarts (KV-backed registry)
2. Subscription pattern matching logic
"""

from __future__ import annotations

import pytest

from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry
from remora.core.swarm_state import AgentMetadata, SwarmState
from remora.core.events import AgentMessageEvent, ContentChangedEvent, FileSavedEvent


def test_swarm_state_persistence(tmp_path):
    """Test that agents survive runner reboots (state persistence)."""
    db_path = tmp_path / "swarm.db"

    swarm1 = SwarmState(db_path)
    swarm1.initialize()

    meta = AgentMetadata(
        agent_id="agent_a",
        node_type="function",
        name="agent_a",
        full_name="src.main.agent_a",
        file_path="src/main.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    )
    swarm1.upsert(meta)
    swarm1.close()

    swarm2 = SwarmState(db_path)
    swarm2.initialize()

    recovered = swarm2.get_agent("agent_a")
    assert recovered is not None
    assert recovered["agent_id"] == "agent_a"
    assert recovered["file_path"] == "src/main.py"
    assert recovered["node_type"] == "function"
    swarm2.close()


def test_swarm_state_upsert_updates_existing(tmp_path):
    """Test that upserting an agent updates existing data."""
    db_path = tmp_path / "swarm.db"

    swarm = SwarmState(db_path)
    swarm.initialize()

    meta1 = AgentMetadata(
        agent_id="agent_a",
        node_type="function",
        name="agent_a",
        full_name="src.main.agent_a",
        file_path="src/main.py",
        parent_id=None,
        start_line=1,
        end_line=10,
    )
    swarm.upsert(meta1)

    meta2 = AgentMetadata(
        agent_id="agent_a",
        node_type="class",
        name="AgentA",
        full_name="src.main.AgentA",
        file_path="src/models.py",
        parent_id=None,
        start_line=20,
        end_line=50,
    )
    swarm.upsert(meta2)

    recovered = swarm.get_agent("agent_a")
    assert recovered is not None
    assert recovered["node_type"] == "class"
    assert recovered["file_path"] == "src/models.py"
    assert recovered["start_line"] == 20

    swarm.close()


def test_swarm_state_list_agents(tmp_path):
    """Test listing all agents."""
    db_path = tmp_path / "swarm.db"

    swarm = SwarmState(db_path)
    swarm.initialize()

    swarm.upsert(AgentMetadata(
        agent_id="agent_a",
        node_type="function",
        name="a",
        full_name="a",
        file_path="a.py",
        start_line=1,
        end_line=5,
    ))
    swarm.upsert(AgentMetadata(
        agent_id="agent_b",
        node_type="function",
        name="b",
        full_name="b",
        file_path="b.py",
        start_line=1,
        end_line=5,
    ))

    agents = swarm.list_agents()
    assert len(agents) == 2
    agent_ids = {a["agent_id"] for a in agents}
    assert agent_ids == {"agent_a", "agent_b"}

    swarm.close()


def test_swarm_state_mark_orphaned(tmp_path):
    """Test marking an agent as orphaned."""
    db_path = tmp_path / "swarm.db"

    swarm = SwarmState(db_path)
    swarm.initialize()

    swarm.upsert(AgentMetadata(
        agent_id="agent_a",
        node_type="function",
        name="a",
        full_name="a",
        file_path="a.py",
        start_line=1,
        end_line=5,
    ))

    swarm.mark_orphaned("agent_a")

    active = swarm.list_agents(status="active")
    assert len(active) == 0

    orphaned = swarm.list_agents(status="orphaned")
    assert len(orphaned) == 1
    assert orphaned[0]["agent_id"] == "agent_a"

    swarm.close()


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
