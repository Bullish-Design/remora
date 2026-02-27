"""Tests verifying copy-on-write isolation between stable and agent workspaces."""

import pytest

from tests.integration.helpers import WorkspaceStateSnapshot

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_isolation]


class TestStableWorkspaceIsolation:
    """Verify agent writes don't affect stable workspace."""

    @pytest.mark.asyncio
    async def test_agent_write_does_not_affect_stable(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Writing to agent workspace should not modify stable."""
        stable_before = await WorkspaceStateSnapshot.capture(
            stable_workspace,
            ["src/main.py", "src/utils.py", "README.md"],
        )

        new_path = path_resolver.to_workspace_path("src/new_file.py")
        await agent_workspace.write(new_path, "# New file content")

        stable_after = await WorkspaceStateSnapshot.capture(
            stable_workspace,
            ["src/main.py", "src/utils.py", "README.md", new_path],
        )

        assert new_path not in stable_after.files

        stable_before.assert_unchanged(
            WorkspaceStateSnapshot(
                {k: v for k, v in stable_after.files.items() if k != new_path}
            )
        )

    @pytest.mark.asyncio
    async def test_agent_modify_does_not_affect_stable(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Modifying existing file in agent should not modify stable."""
        file_path = path_resolver.to_workspace_path("src/main.py")

        original_content = await stable_workspace.files.read(file_path, mode="text")

        new_content = "# Modified by agent\ndef modified():\n    pass\n"
        await agent_workspace.write(file_path, new_content)

        agent_content = await agent_workspace.read(file_path)
        assert agent_content == new_content

        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content == original_content

    @pytest.mark.asyncio
    async def test_agent_delete_does_not_affect_stable(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Deleting file in agent workspace should not delete from stable."""
        file_path = path_resolver.to_workspace_path("src/utils.py")

        assert await stable_workspace.files.exists(file_path)
        original_content = await stable_workspace.files.read(file_path, mode="text")

        await agent_workspace.write(file_path, "")

        assert await stable_workspace.files.exists(file_path)
        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content == original_content

    @pytest.mark.asyncio
    async def test_multiple_agent_writes_isolated_from_stable(
        self,
        workspace_service,
        stable_workspace,
    ) -> None:
        """Multiple writes across multiple agents should not affect stable."""
        agents = ["agent-1", "agent-2", "agent-3"]

        stable_files = ["src/main.py", "src/utils.py"]
        stable_before = await WorkspaceStateSnapshot.capture(stable_workspace, stable_files)

        for agent_id in agents:
            ws = await workspace_service.get_agent_workspace(agent_id)
            await ws.write(f"agent_output_{agent_id}.txt", f"Output from {agent_id}")
            await ws.write("src/main.py", f"# Modified by {agent_id}")

        stable_after = await WorkspaceStateSnapshot.capture(stable_workspace, stable_files)
        stable_before.assert_unchanged(stable_after)

        for agent_id in agents:
            exists = await stable_workspace.files.exists(f"agent_output_{agent_id}.txt")
            assert not exists
