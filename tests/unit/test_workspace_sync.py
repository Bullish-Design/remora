"""Tests for remora.workspace.sync — bidirectional sync utilities."""

from __future__ import annotations

import pytest
from pathlib import Path

from remora.testing.mock_workspace import MockWorkspace
from remora.workspace.sync import SyncChange, SyncResult, WorkspaceSync


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_disk(tmp_path: Path) -> Path:
    """Create a temporary disk directory with some files."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hello')")
    (tmp_path / "src" / "util.py").write_text("def add(a, b): return a + b")
    (tmp_path / "README.md").write_text("# Project")
    return tmp_path


@pytest.fixture
def empty_workspace() -> MockWorkspace:
    """Empty workspace — all disk files are new."""
    return MockWorkspace()


@pytest.fixture
def matching_workspace() -> MockWorkspace:
    """Workspace whose content matches the disk files from tmp_disk."""
    return MockWorkspace(
        {
            "/src/main.py": "print('hello')",
            "/src/util.py": "def add(a, b): return a + b",
            "/README.md": "# Project",
        }
    )


@pytest.fixture
def stale_workspace() -> MockWorkspace:
    """Workspace with outdated content compared to tmp_disk."""
    return MockWorkspace(
        {
            "/src/main.py": "print('old')",
            "/src/util.py": "def add(a, b): return a + b",
            "/README.md": "# Old Readme",
        }
    )


# ---------------------------------------------------------------------------
# SyncChange / SyncResult dataclass tests
# ---------------------------------------------------------------------------


class TestSyncChange:
    def test_added_change(self) -> None:
        c = SyncChange(path="/new.py", change_type="added")
        assert c.change_type == "added"
        assert c.disk_path is None

    def test_modified_change_with_disk_path(self, tmp_path: Path) -> None:
        p = tmp_path / "f.py"
        p.write_text("x")
        c = SyncChange(path="/f.py", change_type="modified", disk_path=p)
        assert c.disk_path == p

    def test_deleted_change(self) -> None:
        c = SyncChange(path="/gone.py", change_type="deleted")
        assert c.change_type == "deleted"


class TestSyncResult:
    def test_empty_result(self) -> None:
        r = SyncResult()
        assert r.synced == []
        assert r.skipped == []
        assert r.errors == []
        assert r.total_changes == 0

    def test_total_changes(self) -> None:
        r = SyncResult(
            synced=[SyncChange("/a", "added")],
            skipped=[SyncChange("/b", "modified")],
            errors=[("/c", "fail")],
        )
        assert r.total_changes == 3


# ---------------------------------------------------------------------------
# scan_disk_changes tests
# ---------------------------------------------------------------------------


class TestScanDiskChanges:
    @pytest.mark.asyncio
    async def test_all_new_files(self, tmp_disk: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_disk)
        changes = await sync.scan_disk_changes(tmp_disk)
        paths = {c.path for c in changes}
        assert "/src/main.py" in paths
        assert "/src/util.py" in paths
        assert "/README.md" in paths
        assert all(c.change_type == "added" for c in changes)

    @pytest.mark.asyncio
    async def test_no_changes_when_matching(self, tmp_disk: Path, matching_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(matching_workspace, tmp_disk)
        changes = await sync.scan_disk_changes(tmp_disk)
        assert changes == []

    @pytest.mark.asyncio
    async def test_detects_modified(self, tmp_disk: Path, stale_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(stale_workspace, tmp_disk)
        changes = await sync.scan_disk_changes(tmp_disk)
        paths = {c.path for c in changes}
        # main.py and README.md differ; util.py matches
        assert "/src/main.py" in paths
        assert "/README.md" in paths
        assert "/src/util.py" not in paths
        assert all(c.change_type == "modified" for c in changes)

    @pytest.mark.asyncio
    async def test_custom_workspace_prefix(self, tmp_disk: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_disk)
        changes = await sync.scan_disk_changes(tmp_disk, workspace_prefix="/project")
        paths = {c.path for c in changes}
        assert "/project/src/main.py" in paths
        assert "/project/README.md" in paths

    @pytest.mark.asyncio
    async def test_empty_disk_dir(self, tmp_path: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_path)
        changes = await sync.scan_disk_changes(tmp_path)
        assert changes == []

    @pytest.mark.asyncio
    async def test_disk_path_set_on_changes(self, tmp_disk: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_disk)
        changes = await sync.scan_disk_changes(tmp_disk)
        for c in changes:
            assert c.disk_path is not None
            assert c.disk_path.exists()


# ---------------------------------------------------------------------------
# scan_deleted tests
# ---------------------------------------------------------------------------


class TestScanDeleted:
    @pytest.mark.asyncio
    async def test_detects_deleted_files(self, tmp_path: Path) -> None:
        """Workspace has a file that no longer exists on disk."""
        ws = MockWorkspace(
            {
                "/keep.py": "kept",
                "/gone.py": "deleted",
            }
        )
        # Only create keep.py on disk
        (tmp_path / "keep.py").write_text("kept")

        sync = WorkspaceSync(ws, tmp_path)
        deleted = await sync.scan_deleted(tmp_path)
        paths = {c.path for c in deleted}
        assert "/gone.py" in paths
        assert "/keep.py" not in paths
        assert all(c.change_type == "deleted" for c in deleted)

    @pytest.mark.asyncio
    async def test_no_deletions_when_all_present(self, tmp_disk: Path, matching_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(matching_workspace, tmp_disk)
        deleted = await sync.scan_deleted(tmp_disk)
        assert deleted == []

    @pytest.mark.asyncio
    async def test_deleted_with_prefix(self, tmp_path: Path) -> None:
        ws = MockWorkspace(
            {
                "/proj/a.py": "a",
                "/proj/b.py": "b",
            }
        )
        (tmp_path / "a.py").write_text("a")
        # b.py missing on disk

        sync = WorkspaceSync(ws, tmp_path)
        deleted = await sync.scan_deleted(tmp_path, workspace_prefix="/proj")
        paths = {c.path for c in deleted}
        assert "/proj/b.py" in paths
        assert "/proj/a.py" not in paths


# ---------------------------------------------------------------------------
# sync_from_disk tests
# ---------------------------------------------------------------------------


class TestSyncFromDisk:
    @pytest.mark.asyncio
    async def test_sync_new_files(self, tmp_disk: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_disk)
        result = await sync.sync_from_disk(tmp_disk)
        assert len(result.synced) == 3
        assert result.errors == []
        # Verify workspace now has the files
        assert await empty_workspace.read("/src/main.py") == "print('hello')"
        assert await empty_workspace.read("/README.md") == "# Project"

    @pytest.mark.asyncio
    async def test_sync_modified_files(self, tmp_disk: Path, stale_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(stale_workspace, tmp_disk)
        result = await sync.sync_from_disk(tmp_disk)
        assert len(result.synced) == 2  # main.py and README.md
        assert await stale_workspace.read("/src/main.py") == "print('hello')"
        assert await stale_workspace.read("/README.md") == "# Project"
        # util.py unchanged
        assert await stale_workspace.read("/src/util.py") == "def add(a, b): return a + b"

    @pytest.mark.asyncio
    async def test_dry_run_does_not_modify(self, tmp_disk: Path, empty_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(empty_workspace, tmp_disk)
        result = await sync.sync_from_disk(tmp_disk, dry_run=True)
        assert len(result.synced) == 3  # Reports changes
        # But workspace is still empty
        assert not await empty_workspace.exists("/src/main.py")

    @pytest.mark.asyncio
    async def test_sync_with_deletions(self, tmp_path: Path) -> None:
        ws = MockWorkspace(
            {
                "/keep.py": "kept",
                "/gone.py": "to delete",
            }
        )
        (tmp_path / "keep.py").write_text("kept")
        # gone.py is missing on disk

        sync = WorkspaceSync(ws, tmp_path)
        result = await sync.sync_from_disk(tmp_path, include_deleted=True)
        # No changes for keep.py (content matches), 1 deletion for gone.py
        deleted = [c for c in result.synced if c.change_type == "deleted"]
        assert len(deleted) == 1
        assert deleted[0].path == "/gone.py"

    @pytest.mark.asyncio
    async def test_sync_no_changes(self, tmp_disk: Path, matching_workspace: MockWorkspace) -> None:
        sync = WorkspaceSync(matching_workspace, tmp_disk)
        result = await sync.sync_from_disk(tmp_disk)
        assert result.synced == []
        assert result.errors == []

    @pytest.mark.asyncio
    async def test_sync_error_handling(self, tmp_disk: Path) -> None:
        """Write errors are captured, not raised."""

        class FailingWorkspace(MockWorkspace):
            async def write(self, path: str, content: str | bytes) -> None:
                raise OSError("disk full")

            async def exists(self, path: str) -> bool:
                return False

        ws = FailingWorkspace()
        sync = WorkspaceSync(ws, tmp_disk)
        result = await sync.sync_from_disk(tmp_disk)
        assert len(result.errors) == 3
        assert result.synced == []

    @pytest.mark.asyncio
    async def test_sync_skips_added_without_disk_path(self) -> None:
        """Changes without a disk_path for added/modified are skipped."""
        ws = MockWorkspace()
        sync = WorkspaceSync(ws, Path("/nonexistent"))
        # Manually construct a bad change
        change = SyncChange(path="/x.py", change_type="added", disk_path=None)

        # Directly test the logic path: override scan to return our change
        original_scan = sync.scan_disk_changes

        async def fake_scan(disk_dir, workspace_prefix="/"):
            return [change]

        sync.scan_disk_changes = fake_scan  # type: ignore[assignment]
        result = await sync.sync_from_disk(Path("/nonexistent"))
        assert len(result.skipped) == 1


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestSyncEdgeCases:
    @pytest.mark.asyncio
    async def test_nested_directories(self, tmp_path: Path) -> None:
        """Deeply nested directory structures sync correctly."""
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (nested / "deep.py").write_text("deep")

        ws = MockWorkspace()
        sync = WorkspaceSync(ws, tmp_path)
        result = await sync.sync_from_disk(tmp_path)
        assert len(result.synced) == 1
        assert result.synced[0].path == "/a/b/c/deep.py"
        assert await ws.read("/a/b/c/deep.py") == "deep"

    @pytest.mark.asyncio
    async def test_prefix_with_trailing_slash(self, tmp_path: Path) -> None:
        """Trailing slash in prefix is normalized."""
        (tmp_path / "f.py").write_text("x")

        ws = MockWorkspace()
        sync = WorkspaceSync(ws, tmp_path)
        changes = await sync.scan_disk_changes(tmp_path, workspace_prefix="/proj/")
        assert changes[0].path == "/proj/f.py"

    @pytest.mark.asyncio
    async def test_workspace_read_error_treated_as_modified(self, tmp_path: Path) -> None:
        """If workspace.read() raises, treat file as modified."""
        (tmp_path / "bad.py").write_text("new content")

        class BadReadWorkspace(MockWorkspace):
            async def read(self, path: str) -> str:
                raise RuntimeError("corrupt")

        ws = BadReadWorkspace({"/bad.py": "old"})
        sync = WorkspaceSync(ws, tmp_path)
        changes = await sync.scan_disk_changes(tmp_path)
        assert len(changes) == 1
        assert changes[0].change_type == "modified"
