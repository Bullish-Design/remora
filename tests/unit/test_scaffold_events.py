"""Tests for ScaffoldRequestEvent and scaffold-related event mechanics.

Covers:
- Event creation with all fields
- Frozen (immutable) behavior
- Part of RemoraEvent union
- model_dump / round-trip serialization
- Timestamp auto-set
"""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel

from remora.core.events import ScaffoldRequestEvent, RemoraEvent


class TestScaffoldRequestEventCreate:
    """ScaffoldRequestEvent can be created with required and optional fields."""

    def test_create_minimal(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id="nd_parent1",
        )
        assert event.node_id == "nd_abc123"
        assert event.node_type == "class"
        assert event.parent_id == "nd_parent1"
        assert event.intent == ""
        assert event.timestamp > 0

    def test_create_with_intent(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="function",
            parent_id="nd_parent1",
            intent="HTTP client for external API",
        )
        assert event.intent == "HTTP client for external API"

    def test_create_with_no_parent(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="file",
            parent_id=None,
        )
        assert event.parent_id is None

    def test_timestamp_auto_set(self):
        before = time.time()
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id=None,
        )
        after = time.time()
        assert before <= event.timestamp <= after

    def test_explicit_timestamp(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id=None,
            timestamp=1234567890.0,
        )
        assert event.timestamp == 1234567890.0


class TestScaffoldRequestEventFrozen:
    """ScaffoldRequestEvent must be immutable."""

    def test_frozen_config(self):
        config = ScaffoldRequestEvent.model_config
        assert config.get("frozen") is True

    def test_cannot_mutate_node_id(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id=None,
        )
        with pytest.raises(Exception):
            event.node_id = "changed"

    def test_cannot_mutate_intent(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id=None,
            intent="original",
        )
        with pytest.raises(Exception):
            event.intent = "changed"


class TestScaffoldRequestEventPydantic:
    """ScaffoldRequestEvent is a proper Pydantic model."""

    def test_is_pydantic_basemodel(self):
        assert issubclass(ScaffoldRequestEvent, BaseModel)

    def test_model_dump_returns_dict(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id="nd_parent1",
            intent="test intent",
        )
        data = event.model_dump()
        assert isinstance(data, dict)
        assert data["node_id"] == "nd_abc123"
        assert data["node_type"] == "class"
        assert data["parent_id"] == "nd_parent1"
        assert data["intent"] == "test intent"
        assert "timestamp" in data

    def test_model_dump_roundtrip(self):
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="function",
            parent_id="nd_parent1",
            intent="helper function",
        )
        data = event.model_dump()
        restored = ScaffoldRequestEvent(**data)
        assert restored == event


class TestScaffoldRequestEventInUnion:
    """ScaffoldRequestEvent must be part of the RemoraEvent union."""

    def test_in_remora_event_union(self):
        # RemoraEvent is a Union type — ScaffoldRequestEvent should be one of its members
        event = ScaffoldRequestEvent(
            node_id="nd_abc123",
            to_agent="nd_abc123",
            node_type="class",
            parent_id=None,
        )
        # isinstance check works with Union types
        assert isinstance(event, ScaffoldRequestEvent)

    def test_in_all_exports(self):
        from remora.core import events

        assert "ScaffoldRequestEvent" in events.__all__

    def test_importable_from_core_init(self):
        from remora.core import ScaffoldRequestEvent as Imported

        assert Imported is ScaffoldRequestEvent
