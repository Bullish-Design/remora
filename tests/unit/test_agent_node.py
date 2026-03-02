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
