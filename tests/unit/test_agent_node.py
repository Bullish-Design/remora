"""Tests for AgentNode unified model."""

from __future__ import annotations

import json
import sqlite3

import pytest

from remora.core.agent_node import AgentNode, ToolSchema


def _make_node(**overrides) -> AgentNode:
    """Helper to create a test AgentNode with sensible defaults."""
    defaults = {
        "node_id": "abc123def456",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "function:calculate_total",
        "file_path": "/src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "aabbccdd11223344",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


class TestAgentNodeCreation:
    def test_create_minimal(self):
        node = _make_node()
        assert node.node_id == "abc123def456"
        assert node.node_type == "function"
        assert node.status == "idle"
        assert node.extension_name is None
        assert node.extra_tools == []
        assert node.extra_subscriptions == []

    def test_create_with_extension_fields(self):
        tool = ToolSchema(
            name="run_test",
            description="Run this test",
            parameters={"type": "object", "properties": {}},
        )
        node = _make_node(
            extension_name="TestAgent",
            custom_system_prompt="You are a test agent.",
            extra_tools=[tool],
        )
        assert node.extension_name == "TestAgent"
        assert len(node.extra_tools) == 1
        assert node.extra_tools[0].name == "run_test"


class TestAgentNodeSerialization:
    def test_to_row_basic(self):
        node = _make_node()
        row = node.to_row()
        assert row["node_id"] == "abc123def456"
        assert row["caller_ids"] == "[]"
        assert row["callee_ids"] == "[]"
        assert row["extra_tools"] == "[]"
        assert row["extra_subscriptions"] == "[]"
        assert row["mounted_workspaces"] == "[]"

    def test_to_row_with_json_fields(self):
        from remora.core.subscriptions import SubscriptionPattern

        tool = ToolSchema(
            name="run_test",
            description="Run test",
            parameters={"type": "object"},
        )
        sub = SubscriptionPattern(event_types=["ContentChangedEvent"])
        node = _make_node(
            caller_ids=["id1", "id2"],
            extra_tools=[tool],
            extra_subscriptions=[sub],
            mounted_workspaces=["/workspace/a"],
        )
        row = node.to_row()
        assert json.loads(row["caller_ids"]) == ["id1", "id2"]
        assert json.loads(row["mounted_workspaces"]) == ["/workspace/a"]
        tools_data = json.loads(row["extra_tools"])
        assert len(tools_data) == 1
        assert tools_data[0]["name"] == "run_test"

    def test_from_row_round_trip(self):
        from remora.core.subscriptions import SubscriptionPattern

        tool = ToolSchema(
            name="run_test",
            description="Run test",
            parameters={"type": "object"},
        )
        sub = SubscriptionPattern(event_types=["ContentChangedEvent"])
        original = _make_node(
            caller_ids=["id1"],
            callee_ids=["id2"],
            extra_tools=[tool],
            extra_subscriptions=[sub],
            mounted_workspaces=["/ws"],
            extension_name="TestAgent",
            custom_system_prompt="You are a test agent.",
            status="running",
            last_trigger_event="ContentChangedEvent",
            last_completed_at=1234567890.0,
        )
        row = original.to_row()

        # Simulate SQLite row (dict with string values for JSON columns)
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        db.execute(f"CREATE TABLE nodes ({cols})")
        db.execute(f"INSERT INTO nodes VALUES ({placeholders})", list(row.values()))
        sqlite_row = db.execute("SELECT * FROM nodes").fetchone()

        restored = AgentNode.from_row(sqlite_row)
        assert restored.node_id == original.node_id
        assert restored.caller_ids == ["id1"]
        assert restored.callee_ids == ["id2"]
        assert len(restored.extra_tools) == 1
        assert restored.extra_tools[0].name == "run_test"
        assert len(restored.extra_subscriptions) == 1
        assert restored.extra_subscriptions[0].event_types == ["ContentChangedEvent"]
        assert restored.extension_name == "TestAgent"
        assert restored.status == "running"
