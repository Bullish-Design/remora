"""Tests verifying error handling and recovery."""

import pytest

from remora.core.cairn_bridge import CairnWorkspaceService

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestErrorRecovery:
    """Verify system handles errors gracefully."""

    @pytest.mark.asyncio
    async def test_read_missing_file_raises(
        self,
        agent_workspace,
    ) -> None:
        """Reading non-existent file should raise appropriate error."""
        with pytest.raises(Exception):
            await agent_workspace.read("does/not/exist.txt")

    @pytest.mark.asyncio
    async def test_workspace_survives_partial_failure(
        self,
        workspace_service,
    ) -> None:
        """Workspace should remain usable after operation failure."""
        ws = await workspace_service.get_agent_workspace("error-test")

        await ws.write("success.txt", "Good content")

        with pytest.raises(Exception):
            await ws.read("missing.txt")

        await ws.write("after_error.txt", "Still works")
        content = await ws.read("success.txt")
        assert content == "Good content"

    @pytest.mark.asyncio
    async def test_close_after_error_is_safe(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Closing service after errors should not raise."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="error-close",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        ws = await service.get_agent_workspace("agent-1")

        try:
            await ws.read("missing.txt")
        except Exception:
            pass

        await service.close()

    @pytest.mark.asyncio
    async def test_double_close_is_safe(
        self,
        workspace_config,
        project_root,
    ) -> None:
        """Calling close() twice should not raise."""
        service = CairnWorkspaceService(
            workspace_config,
            graph_id="double-close",
            project_root=project_root,
        )
        await service.initialize(sync=True)

        await service.close()
        await service.close()
