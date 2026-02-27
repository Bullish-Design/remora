"""Tests verifying read fall-through from agent to stable workspace."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestReadFallThrough:
    """Verify reads fall through from agent to stable workspace."""

    @pytest.mark.asyncio
    async def test_read_falls_through_to_stable(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Agent can read files from stable that it hasn't modified."""
        file_path = path_resolver.to_workspace_path("src/utils.py")

        stable_content = await stable_workspace.files.read(file_path, mode="text")
        assert stable_content is not None

        agent_content = await agent_workspace.read(file_path)
        assert agent_content == stable_content

    @pytest.mark.asyncio
    async def test_agent_write_shadows_stable(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """Agent's write should shadow (override) stable for reads."""
        file_path = path_resolver.to_workspace_path("src/main.py")

        original = await stable_workspace.files.read(file_path, mode="text")

        new_content = "# Shadowed by agent"
        await agent_workspace.write(file_path, new_content)

        agent_read = await agent_workspace.read(file_path)
        assert agent_read == new_content
        assert agent_read != original

    @pytest.mark.asyncio
    async def test_exists_checks_both_layers(
        self,
        stable_workspace,
        agent_workspace,
        path_resolver,
    ) -> None:
        """exists() should return True if file is in either layer."""
        stable_file = path_resolver.to_workspace_path("README.md")
        assert await agent_workspace.exists(stable_file)

        agent_file = "agent_only.txt"
        await agent_workspace.write(agent_file, "Agent content")
        assert await agent_workspace.exists(agent_file)

        missing_file = "does_not_exist.txt"
        assert not await agent_workspace.exists(missing_file)

    @pytest.mark.asyncio
    async def test_list_dir_combines_both_layers(
        self,
        stable_workspace,
        agent_workspace,
    ) -> None:
        """list_dir should show files from both agent and stable."""
        stable_files = set(await stable_workspace.files.list_dir("src", output="name"))

        await agent_workspace.write("src/agent_added.py", "# New file")

        agent_files = set(await agent_workspace.list_dir("src"))

        assert "main.py" in agent_files
        assert "utils.py" in agent_files
        assert "agent_added.py" in agent_files
        assert stable_files.issubset(agent_files)
