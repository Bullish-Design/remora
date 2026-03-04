"""Tests for protocol definitions and mock implementations.

Verifies that:
1. MockWorkspace implements WorkspaceProtocol correctly
2. MockKVStore implements KVStoreProtocol correctly
3. Protocol runtime checking works as expected
"""

from __future__ import annotations

import pytest

from remora.core.protocols import WorkspaceProtocol, KVStoreProtocol
from remora.testing import MockWorkspace, MockKVStore


class TestMockWorkspaceProtocolConformance:
    """Test that MockWorkspace implements WorkspaceProtocol."""

    def test_mock_workspace_is_workspace_protocol(self) -> None:
        """MockWorkspace should satisfy WorkspaceProtocol runtime check."""
        workspace = MockWorkspace()
        assert isinstance(workspace, WorkspaceProtocol)

    @pytest.mark.asyncio
    async def test_read_existing_file(self) -> None:
        """Read should return file contents."""
        workspace = MockWorkspace({"/test.txt": "hello world"})
        content = await workspace.read("/test.txt")
        assert content == "hello world"

    @pytest.mark.asyncio
    async def test_read_missing_file_raises(self) -> None:
        """Read should raise FileNotFoundError for missing files."""
        workspace = MockWorkspace()
        with pytest.raises(FileNotFoundError):
            await workspace.read("/missing.txt")

    @pytest.mark.asyncio
    async def test_write_creates_file(self) -> None:
        """Write should create a new file."""
        workspace = MockWorkspace()
        await workspace.write("/new.txt", "content")
        content = await workspace.read("/new.txt")
        assert content == "content"

    @pytest.mark.asyncio
    async def test_write_overwrites_file(self) -> None:
        """Write should overwrite existing file."""
        workspace = MockWorkspace({"/test.txt": "old"})
        await workspace.write("/test.txt", "new")
        content = await workspace.read("/test.txt")
        assert content == "new"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(self) -> None:
        """Write should create parent directories."""
        workspace = MockWorkspace()
        await workspace.write("/a/b/c.txt", "nested")
        content = await workspace.read("/a/b/c.txt")
        assert content == "nested"
        assert "/a" in workspace.dirs
        assert "/a/b" in workspace.dirs

    @pytest.mark.asyncio
    async def test_exists_returns_true_for_file(self) -> None:
        """Exists should return True for existing file."""
        workspace = MockWorkspace({"/test.txt": "content"})
        assert await workspace.exists("/test.txt") is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_missing(self) -> None:
        """Exists should return False for missing file."""
        workspace = MockWorkspace()
        assert await workspace.exists("/missing.txt") is False

    @pytest.mark.asyncio
    async def test_exists_returns_true_for_directory(self) -> None:
        """Exists should return True for directories."""
        workspace = MockWorkspace()
        await workspace.mkdir("/mydir")
        assert await workspace.exists("/mydir") is True

    @pytest.mark.asyncio
    async def test_list_dir_returns_entries(self) -> None:
        """List_dir should return directory entries."""
        workspace = MockWorkspace(
            {
                "/a.txt": "a",
                "/b.txt": "b",
                "/dir/c.txt": "c",
            }
        )
        entries = await workspace.list_dir("/")
        assert "a.txt" in entries
        assert "b.txt" in entries
        assert "dir" in entries

    @pytest.mark.asyncio
    async def test_list_dir_subdirectory(self) -> None:
        """List_dir should work on subdirectories."""
        workspace = MockWorkspace(
            {
                "/src/main.py": "main",
                "/src/utils.py": "utils",
            }
        )
        entries = await workspace.list_dir("/src")
        assert set(entries) == {"main.py", "utils.py"}

    @pytest.mark.asyncio
    async def test_delete_removes_file(self) -> None:
        """Delete should remove a file."""
        workspace = MockWorkspace({"/test.txt": "content"})
        await workspace.delete("/test.txt")
        assert await workspace.exists("/test.txt") is False

    @pytest.mark.asyncio
    async def test_delete_removes_directory(self) -> None:
        """Delete should remove an empty directory."""
        workspace = MockWorkspace()
        await workspace.mkdir("/mydir")
        assert await workspace.exists("/mydir") is True
        await workspace.delete("/mydir")
        assert await workspace.exists("/mydir") is False

    @pytest.mark.asyncio
    async def test_mkdir_creates_directory(self) -> None:
        """Mkdir should create a directory."""
        workspace = MockWorkspace()
        await workspace.mkdir("/newdir")
        assert await workspace.exists("/newdir") is True
        assert "/newdir" in workspace.dirs

    @pytest.mark.asyncio
    async def test_mkdir_creates_parents(self) -> None:
        """Mkdir should create parent directories."""
        workspace = MockWorkspace()
        await workspace.mkdir("/a/b/c")
        assert "/a" in workspace.dirs
        assert "/a/b" in workspace.dirs
        assert "/a/b/c" in workspace.dirs

    @pytest.mark.asyncio
    async def test_path_normalization_without_slash(self) -> None:
        """Paths without leading slash should be normalized."""
        workspace = MockWorkspace({"test.txt": "content"})
        # Access with slash should work
        content = await workspace.read("/test.txt")
        assert content == "content"


class TestMockKVStoreProtocolConformance:
    """Test that MockKVStore implements KVStoreProtocol."""

    def test_mock_kvstore_is_kvstore_protocol(self) -> None:
        """MockKVStore should satisfy KVStoreProtocol runtime check."""
        kv = MockKVStore()
        assert isinstance(kv, KVStoreProtocol)

    @pytest.mark.asyncio
    async def test_get_existing_key(self) -> None:
        """Get should return value for existing key."""
        kv = MockKVStore({"key1": "value1"})
        value = await kv.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_default(self) -> None:
        """Get should return default for missing key."""
        kv = MockKVStore()
        value = await kv.get("missing", default="default")
        assert value == "default"

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self) -> None:
        """Get should return None for missing key with no default."""
        kv = MockKVStore()
        value = await kv.get("missing")
        assert value is None

    @pytest.mark.asyncio
    async def test_set_creates_key(self) -> None:
        """Set should create a new key."""
        kv = MockKVStore()
        await kv.set("key1", "value1")
        value = await kv.get("key1")
        assert value == "value1"

    @pytest.mark.asyncio
    async def test_set_overwrites_key(self) -> None:
        """Set should overwrite existing key."""
        kv = MockKVStore({"key1": "old"})
        await kv.set("key1", "new")
        value = await kv.get("key1")
        assert value == "new"

    @pytest.mark.asyncio
    async def test_set_complex_value(self) -> None:
        """Set should handle complex values."""
        kv = MockKVStore()
        await kv.set("key1", {"nested": {"data": [1, 2, 3]}})
        value = await kv.get("key1")
        assert value == {"nested": {"data": [1, 2, 3]}}

    @pytest.mark.asyncio
    async def test_delete_existing_key(self) -> None:
        """Delete should remove key and return True."""
        kv = MockKVStore({"key1": "value1"})
        result = await kv.delete("key1")
        assert result is True
        assert await kv.exists("key1") is False

    @pytest.mark.asyncio
    async def test_delete_missing_key(self) -> None:
        """Delete should return False for missing key."""
        kv = MockKVStore()
        result = await kv.delete("missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_returns_true(self) -> None:
        """Exists should return True for existing key."""
        kv = MockKVStore({"key1": "value1"})
        assert await kv.exists("key1") is True

    @pytest.mark.asyncio
    async def test_exists_returns_false(self) -> None:
        """Exists should return False for missing key."""
        kv = MockKVStore()
        assert await kv.exists("missing") is False

    @pytest.mark.asyncio
    async def test_list_keys_all(self) -> None:
        """List_keys should return all keys."""
        kv = MockKVStore({"a": 1, "b": 2, "c": 3})
        keys = await kv.list_keys()
        assert set(keys) == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_list_keys_with_prefix(self) -> None:
        """List_keys should filter by prefix."""
        kv = MockKVStore(
            {
                "user:1": "alice",
                "user:2": "bob",
                "session:abc": "data",
            }
        )
        keys = await kv.list_keys(prefix="user:")
        assert set(keys) == {"user:1", "user:2"}

    @pytest.mark.asyncio
    async def test_list_keys_empty_result(self) -> None:
        """List_keys should return empty list when no matches."""
        kv = MockKVStore({"a": 1})
        keys = await kv.list_keys(prefix="nonexistent:")
        assert keys == []
