"""Tests for NodeStateStore."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fsdantic import Fsdantic

from remora.hub.models import FileIndex, NodeState
from remora.constants import HUB_DB_NAME
from remora.hub.store import NodeStateStore


@pytest.fixture
async def store(tmp_path: Path):
    """Create a temporary store for testing."""
    db_path = tmp_path / f"test_{HUB_DB_NAME}"
    workspace = await Fsdantic.open(path=str(db_path))
    store = NodeStateStore(workspace)
    yield store
    await workspace.close()


class TestNodeStateStore:
    @pytest.mark.asyncio
    async def test_set_and_get(self, store: NodeStateStore):
        state = NodeState(
            key="node:/project/foo.py:bar",
            file_path="/project/foo.py",
            node_name="bar",
            node_type="function",
            source_hash="abc123",
            file_hash="def456",
            update_source="file_change",
        )

        await store.set(state)
        retrieved = await store.get("node:/project/foo.py:bar")

        assert retrieved is not None
        assert retrieved.node_name == "bar"
        assert retrieved.source_hash == "abc123"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self, store: NodeStateStore):
        result = await store.get("node:/nonexistent:missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_many(self, store: NodeStateStore):
        for i in range(3):
            state = NodeState(
                key=f"node:/project/file.py:func{i}",
                file_path="/project/file.py",
                node_name=f"func{i}",
                node_type="function",
                source_hash=f"hash{i}",
                file_hash="filehash",
                update_source="cold_start",
            )
            await store.set(state)

        keys = [
            "node:/project/file.py:func0",
            "node:/project/file.py:func1",
            "node:/project/file.py:missing",
        ]
        result = await store.get_many(keys)

        assert len(result) == 2
        assert "node:/project/file.py:func0" in result
        assert "node:/project/file.py:func1" in result
        assert "node:/project/file.py:missing" not in result

    @pytest.mark.asyncio
    async def test_invalidate_file_removes_all_nodes(self, store: NodeStateStore):
        for name in ["foo", "bar", "baz"]:
            state = NodeState(
                key=f"node:/project/test.py:{name}",
                file_path="/project/test.py",
                node_name=name,
                node_type="function",
                source_hash=f"hash_{name}",
                file_hash="file_hash",
                update_source="file_change",
            )
            await store.set(state)

        await store.set_file_index(
            FileIndex(
                file_path="/project/test.py",
                file_hash="file_hash",
                node_count=3,
                last_scanned=datetime.now(timezone.utc),
            )
        )

        deleted = await store.invalidate_file("/project/test.py")

        assert len(deleted) == 3
        assert await store.get("node:/project/test.py:foo") is None
        assert await store.get_file_index("/project/test.py") is None

    @pytest.mark.asyncio
    async def test_stats(self, store: NodeStateStore):
        for i in range(5):
            state = NodeState(
                key=f"node:/project/file{i}.py:func",
                file_path=f"/project/file{i}.py",
                node_name="func",
                node_type="function",
                source_hash=f"hash{i}",
                file_hash=f"filehash{i}",
                update_source="cold_start",
            )
            await store.set(state)
            await store.set_file_index(
                FileIndex(
                    file_path=f"/project/file{i}.py",
                    file_hash=f"filehash{i}",
                    node_count=1,
                    last_scanned=datetime.now(timezone.utc),
                )
            )

        stats = await store.stats()

        assert stats["nodes"] == 5
        assert stats["files"] == 5
