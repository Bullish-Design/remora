"""Tests verifying write isolation behavior."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn, pytest.mark.cairn_isolation]


class TestWriteSemantics:
    """Verify write isolation for agent workspaces."""

    @pytest.mark.asyncio
    async def test_write_creates_agent_only_file(
        self,
        stable_workspace,
        agent_workspace,
    ) -> None:
        """Agent writes should only exist in the agent workspace."""
        path = "agent_only.txt"
        await agent_workspace.write(path, "Agent content")

        assert await agent_workspace.exists(path)
        assert not await stable_workspace.files.exists(path)

    @pytest.mark.asyncio
    async def test_write_does_not_mutate_stable_content(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Agent writes should not mutate stable content."""
        path = path_resolver.to_workspace_path("src/main.py")
        original = await stable_workspace.files.read(path, mode="text")

        await agent_workspace.write(path, "# agent override")

        stable_after = await stable_workspace.files.read(path, mode="text")
        assert stable_after == original
