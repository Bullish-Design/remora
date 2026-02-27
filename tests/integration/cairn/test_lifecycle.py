"""Tests verifying workspace lifecycle management."""

from pathlib import Path

import pytest

from remora.cairn_bridge import CairnWorkspaceService

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_lifecycle]


class TestWorkspaceLifecycle:
    """Verify proper workspace open/close/cleanup behavior."""

    @pytest.mark.asyncio
    async def test_service_initialize_creates_databases(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Initialize should create stable.db in workspace directory."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="lifecycle-test",
            project_root=project_root,
        )

        try:
            await service.initialize(sync=True)

            workspace_dir = Path(workspace_config.base_path) / "lifecycle-test"
            assert workspace_dir.exists()
            assert (workspace_dir / "stable.db").exists()
        finally:
            await service.close()

    @pytest.mark.asyncio
    async def test_agent_workspace_creates_database(
        self,
        workspace_service,
        workspace_config,
    ) -> None:
        """Getting agent workspace should create agent database file."""
        agent_id = "lifecycle-agent"

        await workspace_service.get_agent_workspace(agent_id)

        workspace_dir = Path(workspace_config.base_path) / "test-graph"
        assert (workspace_dir / f"{agent_id}.db").exists()

    @pytest.mark.asyncio
    async def test_close_releases_resources(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Close should release all workspace resources."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="close-test",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        await service.get_agent_workspace("agent-1")
        await service.get_agent_workspace("agent-2")

        await service.close()

        assert service._stable_workspace is None
        assert len(service._agent_workspaces) == 0

    @pytest.mark.asyncio
    async def test_reopen_preserves_data(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Closing and reopening should preserve written data."""
        service1 = CairnWorkspaceService(
            workspace_config,
            graph_id="reopen-test",
            project_root=project_root,
        )
        await service1.initialize(sync=True)

        ws1 = await service1.get_agent_workspace("agent-1")
        await ws1.write("test_file.txt", "Persistent content")

        await service1.close()

        service2 = CairnWorkspaceService(
            workspace_config,
            graph_id="reopen-test",
            project_root=project_root,
        )
        await service2.initialize(sync=False)

        ws2 = await service2.get_agent_workspace("agent-1")
        content = await ws2.read("test_file.txt")

        assert content == "Persistent content"

        await service2.close()

    @pytest.mark.asyncio
    async def test_multiple_graph_isolation(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Different graph_ids should have isolated workspaces."""
        service1 = CairnWorkspaceService(
            workspace_config,
            graph_id="graph-1",
            project_root=project_root,
        )
        service2 = CairnWorkspaceService(
            workspace_config,
            graph_id="graph-2",
            project_root=project_root,
        )

        try:
            await service1.initialize(sync=True)
            await service2.initialize(sync=True)

            ws1 = await service1.get_agent_workspace("agent-1")
            ws2 = await service2.get_agent_workspace("agent-1")

            await ws1.write("graph_specific.txt", "Graph 1 content")

            exists = await ws2.exists("graph_specific.txt")
            assert not exists
        finally:
            await service1.close()
            await service2.close()
