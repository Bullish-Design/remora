"""Tests for hub server endpoints."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from remora.hub.server import HubServer
from remora.workspace import WorkspaceManager


@pytest.fixture
def temp_workspace():
    """Create a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def hub_server(temp_workspace):
    """Create a hub server instance."""
    server = HubServer(
        workspace_path=temp_workspace / "hub.workspace",
        host="127.0.0.1",
        port=8765,
        workspace_base=temp_workspace / "workspaces",
    )
    return server


class TestExecuteGraph:
    """Tests for POST /graph/execute endpoint."""

    @pytest.mark.asyncio
    async def test_execute_graph_auto_generates_id(self, hub_server, temp_workspace):
        """Test that graph_id is auto-generated when not provided."""
        workspace_manager = WorkspaceManager(base_dir=temp_workspace / "workspaces")

        import uuid

        graph_id = uuid.uuid4().hex[:8]

        workspace = await workspace_manager.create(graph_id)

        metadata = {
            "graph_id": graph_id,
            "bundle": "default",
            "target": "test target",
            "target_path": "",
            "created_at": "2024-01-01T00:00:00",
            "status": "running",
        }
        await workspace.save_metadata(metadata)

        loaded = await workspace.load_metadata()
        assert loaded["graph_id"] == graph_id
        assert loaded["bundle"] == "default"

        await workspace_manager.delete(graph_id)

    @pytest.mark.asyncio
    async def test_execute_graph_with_target_path(self, temp_workspace):
        """Test that target_path is properly handled."""
        test_file = temp_workspace / "test.py"
        test_file.write_text("print('hello')")

        workspace_manager = WorkspaceManager(base_dir=temp_workspace / "workspaces")

        graph_id = "test-graph-1"
        workspace = await workspace_manager.create(graph_id)

        await workspace.snapshot_original(test_file)

        original_dir = workspace.original_source()
        copied_file = original_dir / "test.py"
        assert copied_file.exists()
        assert copied_file.read_text() == "print('hello')"

        await workspace_manager.delete(graph_id)

    @pytest.mark.asyncio
    async def test_workspace_list_all(self, temp_workspace):
        """Test listing all workspaces including persisted ones."""
        workspace_manager = WorkspaceManager(base_dir=temp_workspace / "workspaces")

        ws1 = await workspace_manager.create("ws-1")
        ws2 = await workspace_manager.create("ws-2")

        await ws1.save_metadata(
            {
                "graph_id": "ws-1",
                "bundle": "default",
                "target": "",
                "target_path": "",
                "created_at": "2024-01-01",
                "status": "running",
            }
        )
        await ws2.save_metadata(
            {
                "graph_id": "ws-2",
                "bundle": "lint",
                "target": "",
                "target_path": "",
                "created_at": "2024-01-02",
                "status": "completed",
            }
        )

        all_workspaces = await workspace_manager.list_all()

        assert len(all_workspaces) == 2
        ids = {ws.id for ws in all_workspaces}
        assert ids == {"ws-1", "ws-2"}

        ws1_meta = await ws1.load_metadata()
        ws2_meta = await ws2.load_metadata()

        assert ws1_meta["bundle"] == "default"
        assert ws2_meta["bundle"] == "lint"
        assert ws2_meta["status"] == "completed"

        await workspace_manager.delete("ws-1")
        await workspace_manager.delete("ws-2")


class TestListGraphs:
    """Tests for GET /graph/list endpoint."""

    @pytest.mark.asyncio
    async def test_list_graphs_returns_all_workspaces(self, temp_workspace):
        """Test that list_graphs returns all workspaces with their metadata."""
        workspace_manager = WorkspaceManager(base_dir=temp_workspace / "workspaces")

        ws1 = await workspace_manager.create("graph-1")
        ws2 = await workspace_manager.create("graph-2")

        await ws1.save_metadata(
            {
                "graph_id": "graph-1",
                "bundle": "default",
                "target": "Analyze this",
                "target_path": "/path/to/file.py",
                "created_at": "2024-01-15T10:30:00Z",
                "status": "running",
            }
        )

        await ws2.save_metadata(
            {
                "graph_id": "graph-2",
                "bundle": "lint",
                "target": "",
                "target_path": "",
                "created_at": "2024-01-16T12:00:00Z",
                "status": "completed",
            }
        )

        workspaces = await workspace_manager.list_all()

        graphs = []
        for ws in workspaces:
            metadata = await ws.load_metadata()
            graphs.append(
                {
                    "graph_id": ws.id,
                    "bundle": metadata.get("bundle", "default") if metadata else "default",
                    "target": metadata.get("target", "") if metadata else "",
                    "target_path": metadata.get("target_path", "") if metadata else "",
                    "created_at": metadata.get("created_at", "") if metadata else "",
                    "status": metadata.get("status", "unknown") if metadata else "unknown",
                }
            )

        assert len(graphs) == 2

        g1 = next(g for g in graphs if g["graph_id"] == "graph-1")
        assert g1["bundle"] == "default"
        assert g1["target_path"] == "/path/to/file.py"
        assert g1["status"] == "running"

        g2 = next(g for g in graphs if g["graph_id"] == "graph-2")
        assert g2["bundle"] == "lint"
        assert g2["status"] == "completed"

        await workspace_manager.delete("graph-1")
        await workspace_manager.delete("graph-2")
