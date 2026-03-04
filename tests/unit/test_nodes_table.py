"""Tests for the nodes table in EventStore."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.event_store import EventStore


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
async def test_nodes_table_exists(store: EventStore):
    """The nodes table should be created during initialization."""
    conn = store._conn
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='nodes'")
    assert cursor.fetchone() is not None


@pytest.mark.asyncio
async def test_nodes_table_schema(store: EventStore):
    """The nodes table should have all required columns."""
    conn = store._conn
    cursor = conn.execute("PRAGMA table_info(nodes)")
    columns = {row[1] for row in cursor.fetchall()}
    expected = {
        "node_id",
        "node_type",
        "name",
        "full_name",
        "file_path",
        "start_line",
        "end_line",
        "source_code",
        "source_hash",
        "parent_id",
        "caller_ids",
        "callee_ids",
        "status",
        "last_trigger_event",
        "last_completed_at",
        "extension_name",
        "custom_system_prompt",
        "mounted_workspaces",
        "extra_tools",
        "extra_subscriptions",
    }
    assert expected.issubset(columns)


@pytest.mark.asyncio
async def test_nodes_table_indexes(store: EventStore):
    """The nodes table should have required indexes."""
    conn = store._conn
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
    indexes = {row[0] for row in cursor.fetchall()}
    assert "idx_nodes_file_path" in indexes
    assert "idx_nodes_parent_id" in indexes
    assert "idx_nodes_node_type" in indexes
