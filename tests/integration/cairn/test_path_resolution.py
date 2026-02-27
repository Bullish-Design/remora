"""Tests verifying path resolution edge cases."""

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.cairn]


class TestPathResolution:
    """Verify path resolution works correctly."""

    @pytest.mark.asyncio
    async def test_absolute_path_normalization(
        self,
        workspace_service,
        agent_workspace,
        project_root,
    ) -> None:
        """Absolute paths should be normalized to workspace paths."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        abs_path = str(project_root / "src" / "new_file.py")
        await externals["write_file"](abs_path, "# Content")

        workspace_path = "src/new_file.py"
        content = await agent_workspace.read(workspace_path)
        assert content == "# Content"

    @pytest.mark.asyncio
    async def test_relative_path_handling(
        self,
        workspace_service,
        agent_workspace,
    ) -> None:
        """Relative paths should work correctly."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        await externals["write_file"]("src/relative.py", "# Relative")

        content = await agent_workspace.read("src/relative.py")
        assert content == "# Relative"

    @pytest.mark.asyncio
    async def test_path_with_dots(
        self,
        workspace_service,
        agent_workspace,
    ) -> None:
        """Paths with . and .. should be handled."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        await externals["write_file"]("./src/dotted.py", "# Dotted")

        content = await agent_workspace.read("src/dotted.py")
        assert content == "# Dotted"

    @pytest.mark.asyncio
    async def test_deeply_nested_paths(
        self,
        workspace_service,
        agent_workspace,
    ) -> None:
        """Deeply nested paths should work."""
        externals = workspace_service.get_externals("test-agent", agent_workspace)

        deep_path = "a/b/c/d/e/f/deep.txt"
        await externals["write_file"](deep_path, "Deep content")

        content = await agent_workspace.read(deep_path)
        assert content == "Deep content"
