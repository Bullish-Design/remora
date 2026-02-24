"""Tests for agent state management."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from remora.agent_state import AgentKVStore
from remora.checkpoint import Checkpoint, KVCheckpoint


class MockWorkspace:
    """Mock workspace for testing."""

    def __init__(self):
        self._kv: dict[str, str] = {}

    @property
    def kv(self):
        mock_kv = MagicMock()
        mock_kv.get = lambda k: self._kv.get(k)
        mock_kv.set = lambda k, v: self._kv.__setitem__(k, v if isinstance(v, str) else json.dumps(v))
        mock_kv.list = lambda prefix: [{"key": k} for k in self._kv.keys() if k.startswith(prefix)]
        mock_kv.delete = lambda k: self._kv.pop(k, None)
        return mock_kv


@pytest.fixture
def workspace():
    return MockWorkspace()


@pytest.fixture
def kv_store(workspace):
    return AgentKVStore(workspace, "agent-123")


def test_kv_store_initialization(kv_store, workspace):
    """KV store should initialize with correct prefix."""
    assert kv_store._agent_id == "agent-123"
    assert kv_store._prefix == "agent:agent-123"


def test_get_messages_empty(kv_store):
    """Get messages should return empty list when no messages."""
    messages = kv_store.get_messages()
    assert messages == []


def test_add_message(kv_store):
    """Add message should store message."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    messages = kv_store.get_messages()
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"


def test_add_multiple_messages(kv_store):
    """Add multiple messages should accumulate."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.add_message({"role": "assistant", "content": "Hi there"})

    messages = kv_store.get_messages()
    assert len(messages) == 2


def test_clear_messages(kv_store):
    """Clear messages should remove all messages."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.clear_messages()

    assert kv_store.get_messages() == []


def test_get_tool_results_empty(kv_store):
    """Get tool results should return empty list when none."""
    results = kv_store.get_tool_results()
    assert results == []


def test_add_tool_result(kv_store):
    """Add tool result should store result."""
    kv_store.add_tool_result({"call_id": "call-1", "name": "read_file", "output": "file content", "is_error": False})

    results = kv_store.get_tool_results()
    assert len(results) == 1
    assert results[0]["name"] == "read_file"


def test_get_metadata_empty(kv_store):
    """Get metadata should return empty dict when none."""
    metadata = kv_store.get_metadata()
    assert metadata == {}


def test_set_metadata(kv_store):
    """Set metadata should store metadata."""
    kv_store.set_metadata({"state": "running", "turn": 5})

    metadata = kv_store.get_metadata()
    assert metadata["state"] == "running"
    assert metadata["turn"] == 5


def test_update_metadata(kv_store):
    """Update metadata should update existing fields."""
    kv_store.set_metadata({"state": "running"})
    kv_store.update_metadata(turn=5, bundle="lint")

    metadata = kv_store.get_metadata()
    assert metadata["state"] == "running"
    assert metadata["turn"] == 5
    assert metadata["bundle"] == "lint"


def test_create_snapshot(kv_store):
    """Create snapshot should store current state."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.set_metadata({"state": "running"})

    snapshot_id = kv_store.create_snapshot("test-snap")

    assert snapshot_id is not None
    assert len(snapshot_id) == 8


def test_restore_snapshot(kv_store):
    """Restore snapshot should restore state."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.set_metadata({"state": "running"})

    snapshot_id = kv_store.create_snapshot("test-snap")

    kv_store.add_message({"role": "user", "content": "Different"})
    kv_store.set_metadata({"state": "completed"})

    kv_store.restore_snapshot(f"snapshot:test-snap:{snapshot_id}")

    messages = kv_store.get_messages()
    assert len(messages) == 1
    assert messages[0]["content"] == "Hello"

    metadata = kv_store.get_metadata()
    assert metadata["state"] == "running"


def test_list_snapshots(kv_store):
    """List snapshots should return all snapshots."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.create_snapshot("snap1")

    kv_store.add_message({"role": "user", "content": "World"})
    kv_store.create_snapshot("snap2")

    snapshots = kv_store.list_snapshots()
    assert len(snapshots) == 2


def test_checkpoint_kv_to_dir(kv_store, tmp_path):
    """KVCheckpoint should write to directory."""
    kv_store.add_message({"role": "user", "content": "Hello"})
    kv_store.set_metadata({"state": "running"})

    entries = []
    entries.append({"key": kv_store._messages_key, "value": json.dumps([{"role": "user", "content": "Hello"}])})
    entries.append({"key": kv_store._metadata_key, "value": json.dumps({"state": "running"})})

    checkpoint = KVCheckpoint(timestamp=datetime.now(), entries=entries)
    checkpoint.to_dir(tmp_path / "kv")

    assert (tmp_path / "kv" / "_metadata.json").exists()
    assert (tmp_path / "kv" / "a" / "_index.json").exists()


def test_checkpoint_from_dir(kv_store, tmp_path):
    """KVCheckpoint should load from directory."""
    entries = [
        {"key": "test:key1", "value": "value1"},
        {"key": "test:key2", "value": "value2"},
    ]
    checkpoint = KVCheckpoint(timestamp=datetime.now(), entries=entries)
    checkpoint.to_dir(tmp_path / "kv")

    loaded = KVCheckpoint.from_dir(tmp_path / "kv")

    assert len(loaded.entries) >= 2


def test_checkpoint_from_workspace(workspace):
    """KVCheckpoint should create from workspace."""
    workspace.kv.set("test:key", "test-value")

    checkpoint = KVCheckpoint.from_workspace(workspace)

    assert len(checkpoint.entries) >= 1


def test_checkpoint_create(tmp_path):
    """Checkpoint.create should create full checkpoint."""
    workspace = MockWorkspace()
    workspace.kv.set("test:key", "test-value")

    checkpoint = Checkpoint.create(agent_id="agent-123", workspace=workspace, base_path=tmp_path)

    assert checkpoint.agent_id == "agent-123"
    assert checkpoint.kv_path.exists()


def test_checkpoint_load(tmp_path):
    """Checkpoint.load should load KV checkpoint."""
    workspace = MockWorkspace()
    workspace.kv.set("test:key", "test-value")

    checkpoint = Checkpoint.create(agent_id="agent-123", workspace=workspace, base_path=tmp_path)

    loaded = checkpoint.load()

    assert loaded.timestamp is not None
