"""Property-based tests using Hypothesis for Remora core modules.

Covers:
1. Event serialization/deserialization roundtrips
2. SubscriptionPattern matching invariants
3. EventStore append/replay ordering guarantees
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentMessageEvent,
    AgentStartEvent,
    ContentChangedEvent,
    CursorFocusEvent,
    FileSavedEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    ManualTriggerEvent,
    NodeDiscoveredEvent,
    NodeRemovedEvent,
    ScaffoldRequestEvent,
)
from remora.core.subscriptions import SubscriptionPattern


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Identifiers: short non-empty strings (agent IDs, graph IDs, etc.)
_ident = st.text(
    alphabet=st.characters(whitelist_categories=("L", "N", "Pd"), whitelist_characters="_-"),
    min_size=1,
    max_size=30,
)
# Paths: POSIX-style paths
_path = st.from_regex(r"[a-z][a-z0-9_/]*\.[a-z]{1,4}", fullmatch=True)
# Short content
_content = st.text(min_size=0, max_size=200)
# Tags: tuple of short strings
_tags = st.tuples(*[_ident for _ in range(3)]).map(lambda t: tuple(s for s in t if s))
# Positive ints
_pos_int = st.integers(min_value=0, max_value=10_000)
# Timestamp: realistic float
_ts = st.floats(min_value=1.0e9, max_value=2.0e9, allow_nan=False, allow_infinity=False)


def _remora_events() -> st.SearchStrategy:
    """Strategy that generates any Remora event type."""
    return st.one_of(
        st.builds(
            AgentStartEvent,
            graph_id=_ident,
            agent_id=_ident,
            node_name=_ident,
            trigger_event_type=_ident,
            timestamp=_ts,
        ),
        st.builds(
            AgentCompleteEvent,
            graph_id=_ident,
            agent_id=_ident,
            result_summary=_content,
            response=_content,
            tags=_tags,
            timestamp=_ts,
        ),
        st.builds(
            AgentErrorEvent,
            graph_id=_ident,
            agent_id=_ident,
            error=_content,
            timestamp=_ts,
        ),
        st.builds(
            AgentMessageEvent,
            from_agent=_ident,
            to_agent=_ident,
            content=_content,
            tags=_tags,
            timestamp=_ts,
        ),
        st.builds(
            FileSavedEvent,
            path=_path,
            timestamp=_ts,
        ),
        st.builds(
            ContentChangedEvent,
            path=_path,
            diff=st.one_of(st.none(), _content),
            timestamp=_ts,
        ),
        st.builds(
            ManualTriggerEvent,
            to_agent=_ident,
            reason=_content,
            timestamp=_ts,
        ),
        st.builds(
            HumanInputRequestEvent,
            graph_id=_ident,
            agent_id=_ident,
            request_id=_ident,
            question=_content,
            timestamp=_ts,
        ),
        st.builds(
            HumanInputResponseEvent,
            request_id=_ident,
            response=_content,
            timestamp=_ts,
        ),
        st.builds(
            NodeRemovedEvent,
            node_id=_ident,
            timestamp=_ts,
        ),
    )


def _subscription_patterns() -> st.SearchStrategy[SubscriptionPattern]:
    """Strategy that generates SubscriptionPattern instances."""
    return st.builds(
        SubscriptionPattern,
        event_types=st.one_of(st.none(), st.lists(_ident, min_size=1, max_size=3)),
        from_agents=st.one_of(st.none(), st.lists(_ident, min_size=1, max_size=3)),
        to_agent=st.one_of(st.none(), _ident),
        path_glob=st.one_of(st.none(), st.just("**/*.py"), st.just("src/**")),
        tags=st.one_of(st.none(), st.lists(_ident, min_size=1, max_size=3)),
    )


# ---------------------------------------------------------------------------
# 1. Event Serialization Roundtrip
# ---------------------------------------------------------------------------


@given(event=_remora_events())
@settings(max_examples=200, deadline=None)
def test_event_serialization_roundtrip(event):
    """Any Remora event survives JSON serialization and deserialization."""
    event_cls = type(event)
    json_str = event.model_dump_json()
    restored = event_cls.model_validate_json(json_str)
    assert restored == event


@given(event=_remora_events())
@settings(max_examples=200, deadline=None)
def test_event_dict_roundtrip(event):
    """Any Remora event survives dict serialization and deserialization."""
    event_cls = type(event)
    data = event.model_dump()
    restored = event_cls.model_validate(data)
    assert restored == event


@given(event=_remora_events())
@settings(max_examples=100, deadline=None)
def test_event_is_frozen(event):
    """All Remora events should be frozen (immutable)."""
    assert event.model_config.get("frozen") is True
    # Pick an existing field name and try to overwrite it — should raise
    field_name = next(iter(type(event).model_fields))
    with pytest.raises(Exception):
        setattr(event, field_name, "mutated_value")


# ---------------------------------------------------------------------------
# 2. SubscriptionPattern Matching Invariants
# ---------------------------------------------------------------------------


@given(pattern=_subscription_patterns(), event=_remora_events())
@settings(max_examples=300, deadline=None)
def test_subscription_match_is_deterministic(pattern, event):
    """Pattern.matches() should be deterministic for the same inputs."""
    result1 = pattern.matches(event)
    result2 = pattern.matches(event)
    assert result1 == result2


@given(event=_remora_events())
@settings(max_examples=100, deadline=None)
def test_empty_pattern_matches_everything(event):
    """A SubscriptionPattern with all None fields matches any event."""
    pattern = SubscriptionPattern()
    assert pattern.matches(event) is True


@given(event=_remora_events())
@settings(max_examples=100, deadline=None)
def test_wrong_event_type_filter_rejects(event):
    """A pattern filtering for a non-existent event type should not match."""
    pattern = SubscriptionPattern(event_types=["__NoSuchEventType__"])
    assert pattern.matches(event) is False


@given(
    agent_id=_ident,
    content=_content,
    ts=_ts,
)
@settings(max_examples=100, deadline=None)
def test_to_agent_filter_matches_correctly(agent_id, content, ts):
    """to_agent pattern matches AgentMessageEvent with matching to_agent."""
    event = AgentMessageEvent(
        from_agent="sender",
        to_agent=agent_id,
        content=content,
        timestamp=ts,
    )
    match_pattern = SubscriptionPattern(to_agent=agent_id)
    nomatch_pattern = SubscriptionPattern(to_agent=f"__not_{agent_id}__")
    assert match_pattern.matches(event) is True
    assert nomatch_pattern.matches(event) is False


@given(
    from_agent=_ident,
    to_agent=_ident,
    content=_content,
    ts=_ts,
)
@settings(max_examples=100, deadline=None)
def test_from_agents_filter_matches_correctly(from_agent, to_agent, content, ts):
    """from_agents pattern matches AgentMessageEvent with matching from_agent."""
    event = AgentMessageEvent(
        from_agent=from_agent,
        to_agent=to_agent,
        content=content,
        timestamp=ts,
    )
    match_pattern = SubscriptionPattern(from_agents=[from_agent])
    nomatch_pattern = SubscriptionPattern(from_agents=[f"__not_{from_agent}__"])
    assert match_pattern.matches(event) is True
    assert nomatch_pattern.matches(event) is False


@given(path=_path, ts=_ts)
@settings(max_examples=100, deadline=None)
def test_path_glob_filter_on_file_saved(path, ts):
    """path_glob='**' should match any FileSavedEvent."""
    event = FileSavedEvent(path=path, timestamp=ts)
    pattern = SubscriptionPattern(path_glob="**")
    assert pattern.matches(event) is True


@given(tags=_tags, ts=_ts)
@settings(max_examples=100, deadline=None)
def test_tags_filter_matches_when_overlapping(tags, ts):
    """tags filter matches when event has at least one overlapping tag."""
    if not tags:
        return  # Skip empty tags — no overlap possible
    event = AgentMessageEvent(
        from_agent="a",
        to_agent="b",
        content="test",
        tags=tags,
        timestamp=ts,
    )
    # Pattern with first tag from event — should match
    pattern = SubscriptionPattern(tags=[tags[0]])
    assert pattern.matches(event) is True

    # Pattern with a non-overlapping tag — should not match
    pattern_no_match = SubscriptionPattern(tags=["__no_overlap_tag__"])
    assert pattern_no_match.matches(event) is False


# ---------------------------------------------------------------------------
# 3. EventStore Append/Replay Invariants
# ---------------------------------------------------------------------------


@given(
    events=st.lists(
        st.builds(
            AgentStartEvent,
            graph_id=st.just("test-graph"),
            agent_id=_ident,
            node_name=_ident,
            timestamp=_ts,
        ),
        min_size=1,
        max_size=10,
    )
)
@settings(max_examples=10, deadline=None)
def test_event_store_replay_preserves_order(events, tmp_path_factory):
    """Events appended to EventStore are replayed in insertion order."""
    from remora.core.event_store import EventStore

    tmp_path = tmp_path_factory.mktemp("eventstore")

    async def _run():
        store = EventStore(tmp_path / "events.db")
        await store.initialize()

        for event in events:
            await store.append("test-graph", event)

        records = [r async for r in store.replay("test-graph")]
        assert len(records) == len(events)

        # Records should be ordered by (timestamp, id) — the EventStore contract
        sort_keys = [(r["timestamp"], r["id"]) for r in records]
        assert sort_keys == sorted(sort_keys)

        # IDs should all be unique
        ids = [r["id"] for r in records]
        assert len(set(ids)) == len(ids)

        # All events should be present (same count of event types)
        replayed_types = sorted(r["event_type"] for r in records)
        input_types = sorted(type(e).__name__ for e in events)
        assert replayed_types == input_types

        count = await store.get_event_count("test-graph")
        assert count == len(events)

        await store.close()

    asyncio.run(_run())


@given(
    n_events=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=10, deadline=None)
def test_event_store_delete_removes_all(n_events, tmp_path_factory):
    """Deleting a graph removes all its events."""
    from remora.core.event_store import EventStore

    tmp_path = tmp_path_factory.mktemp("eventstore")

    async def _run():
        store = EventStore(tmp_path / "events.db")
        await store.initialize()

        for i in range(n_events):
            event = AgentStartEvent(
                graph_id="delete-graph",
                agent_id=f"agent-{i}",
                node_name=f"node-{i}",
            )
            await store.append("delete-graph", event)

        deleted = await store.delete_graph("delete-graph")
        assert deleted == n_events

        remaining = await store.get_event_count("delete-graph")
        assert remaining == 0

        await store.close()

    asyncio.run(_run())


@given(
    graph_ids=st.lists(
        _ident,
        min_size=1,
        max_size=5,
        unique=True,
    ),
)
@settings(max_examples=10, deadline=None)
def test_event_store_graph_isolation(graph_ids, tmp_path_factory):
    """Events in different graphs are isolated from each other."""
    from remora.core.event_store import EventStore

    tmp_path = tmp_path_factory.mktemp("eventstore")

    async def _run():
        store = EventStore(tmp_path / "events.db")
        await store.initialize()

        # Append 2 events per graph
        for gid in graph_ids:
            for i in range(2):
                event = AgentStartEvent(
                    graph_id=gid,
                    agent_id=f"agent-{gid}-{i}",
                    node_name=f"node-{i}",
                )
                await store.append(gid, event)

        # Each graph should have exactly 2 events
        for gid in graph_ids:
            count = await store.get_event_count(gid)
            assert count == 2, f"Graph {gid} has {count} events, expected 2"

        # Graph IDs should include all our graphs
        stored_ids = await store.get_graph_ids()
        stored_graph_id_set = {r["graph_id"] for r in stored_ids}
        for gid in graph_ids:
            assert gid in stored_graph_id_set

        await store.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# 4. SubscriptionPattern Serialization Roundtrip
# ---------------------------------------------------------------------------


@given(pattern=_subscription_patterns())
@settings(max_examples=200, deadline=None)
def test_subscription_pattern_roundtrip(pattern):
    """SubscriptionPattern survives JSON roundtrip."""
    json_str = pattern.model_dump_json()
    restored = SubscriptionPattern.model_validate_json(json_str)
    assert restored == pattern
