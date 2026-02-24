"""Tests for workspace management."""

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from remora.workspace import GraphWorkspace, WorkspaceManager


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace for testing."""
    return tmp_path / "test_workspace"


@pytest.mark.asyncio
async def test_create_graph_workspace(tmp_path):
    """GraphWorkspace should create required directories."""
    workspace = await GraphWorkspace.create("test-123", tmp_path)

    assert workspace.id == "test-123"
    assert workspace.root.exists()
    assert (workspace.root / "agents").exists()
    assert (workspace.root / "shared").exists()
    assert (workspace.root / "original").exists()


def test_agent_space_creates_directory(tmp_workspace):
    """agent_space should create directory on first access."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    agent_path = workspace.agent_space("agent-1")

    assert agent_path.exists()
    assert agent_path.name == "agent-1"


def test_agent_space_returns_same_path(tmp_workspace):
    """agent_space should return same path for same agent."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    path1 = workspace.agent_space("agent-1")
    path2 = workspace.agent_space("agent-1")

    assert path1 == path2


def test_shared_space_creates_directory(tmp_workspace):
    """shared_space should create directory on first access."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    shared_path = workspace.shared_space()

    assert shared_path.exists()
    assert shared_path.name == "shared"


def test_original_source_creates_directory(tmp_workspace):
    """original_source should create directory on first access."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    original_path = workspace.original_source()

    assert original_path.exists()
    assert original_path.name == "original"


def test_snapshot_original_file(tmp_workspace, tmp_path):
    """snapshot_original should copy a file to original source."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    test_file = tmp_path / "test.py"
    test_file.write_text("def foo(): pass")

    workspace.snapshot_original(test_file)

    original_file = workspace.original_source() / "test.py"
    assert original_file.exists()
    assert original_file.read_text() == "def foo(): pass"


def test_snapshot_original_directory(tmp_workspace, tmp_path):
    """snapshot_original should copy directory contents to original source."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)

    source_dir = tmp_path / "source"
    source_dir.mkdir()
    (source_dir / "file1.py").write_text("def foo(): pass")
    (source_dir / "file2.py").write_text("class Bar: pass")

    workspace.snapshot_original(source_dir)

    original_dir = workspace.original_source()
    assert (original_dir / "file1.py").exists()
    assert (original_dir / "file2.py").exists()


def test_workspace_manager_create(tmp_path):
    """WorkspaceManager should create and track workspaces."""
    manager = WorkspaceManager()
    manager._base_dir = tmp_path

    workspace = manager.get_or_create("test-1")

    assert workspace.id == "test-1"
    assert manager.get("test-1") is not None


def test_workspace_manager_list(tmp_path):
    """WorkspaceManager should list all workspaces."""
    manager = WorkspaceManager()
    manager._base_dir = tmp_path

    manager.get_or_create("test-1")
    manager.get_or_create("test-2")

    workspaces = manager.list()

    assert len(workspaces) == 2
    ids = {w.id for w in workspaces}
    assert ids == {"test-1", "test-2"}


def test_workspace_manager_get_nonexistent(tmp_path):
    """WorkspaceManager.get should return None for nonexistent workspace."""
    manager = WorkspaceManager()
    manager._base_dir = tmp_path

    result = manager.get("nonexistent")

    assert result is None


def test_workspace_cleanup(tmp_workspace):
    """cleanup should remove workspace directory."""
    workspace = GraphWorkspace(id="test", root=tmp_workspace)
    workspace.agent_space("agent-1")

    assert tmp_workspace.exists()

    workspace.cleanup()

    assert not tmp_workspace.exists()
