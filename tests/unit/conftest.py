"""Shared fixtures and helpers for unit tests."""

from __future__ import annotations

from typing import Any

from remora.core.agents.agent_node import AgentNode


def make_node(**overrides: Any) -> AgentNode:
    """Create a test AgentNode with sensible defaults.

    This is the canonical helper for creating test nodes. All unit tests
    that need an AgentNode should use this instead of defining their own.
    """
    defaults: dict[str, Any] = {
        "node_id": "rm_test123",
        "node_type": "function",
        "name": "test_func",
        "full_name": "test.test_func",
        "file_path": "file:///tmp/test.py",
        "start_line": 1,
        "end_line": 5,
        "source_code": "def test_func(): pass",
        "source_hash": "abc123hash",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)
