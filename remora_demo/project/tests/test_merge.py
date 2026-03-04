"""Tests for configlib.merge."""

from __future__ import annotations

from configlib.merge import deep_merge, merge_dicts


def test_deep_merge() -> None:
    """Test recursive dict merging."""
    base = {"a": 1, "b": {"x": 10, "y": 20}}
    override = {"b": {"y": 99, "z": 30}, "c": 3}
    result = deep_merge(base, override)
    assert result == {"a": 1, "b": {"x": 10, "y": 99, "z": 30}, "c": 3}


def test_merge_override() -> None:
    """Test that later dicts override earlier ones."""
    result = merge_dicts({"a": 1}, {"a": 2}, {"a": 3})
    assert result["a"] == 3
