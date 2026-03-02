"""Tests for node lifecycle events."""

from __future__ import annotations

import time

from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent


class TestNodeDiscoveredEvent:
    def test_create(self):
        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="calculate_total",
            full_name="function:calculate_total",
            file_path="/src/billing.py",
            start_line=10,
            end_line=25,
            source_code="def calculate_total(): pass",
            source_hash="aabb",
        )
        assert event.node_id == "abc123"
        assert event.node_type == "function"
        assert event.parent_id is None
        assert event.timestamp > 0

    def test_frozen(self):
        import pytest

        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="test",
            full_name="function:test",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        )
        with pytest.raises(AttributeError):
            event.node_id = "changed"

    def test_start_end_byte_defaults(self):
        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="test",
            full_name="function:test",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="",
            source_hash="",
        )
        assert event.start_byte == 0
        assert event.end_byte == 0

    def test_start_end_byte_explicit(self):
        event = NodeDiscoveredEvent(
            node_id="abc123",
            node_type="function",
            name="test",
            full_name="function:test",
            file_path="/test.py",
            start_line=1,
            end_line=5,
            source_code="def test(): pass",
            source_hash="aabb",
            start_byte=100,
            end_byte=200,
        )
        assert event.start_byte == 100
        assert event.end_byte == 200


class TestNodeRemovedEvent:
    def test_create(self):
        event = NodeRemovedEvent(node_id="abc123")
        assert event.node_id == "abc123"
        assert event.timestamp > 0
