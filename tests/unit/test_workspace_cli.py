"""Tests for workspace CLI commands.

Tests the workspace inspection CLI commands using mocked workspaces.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from remora.cli.workspace import workspace


class TestWorkspaceStats:
    """Tests for workspace stats command."""

    def test_stats_shows_statistics(self) -> None:
        """Stats command should display workspace statistics."""
        runner = CliRunner()

        mock_stats = MagicMock()
        mock_stats.file_count = 10
        mock_stats.dir_count = 3
        mock_stats.total_size = 1024
        mock_stats.kv_count = 5

        mock_inspector = MagicMock()
        mock_inspector.stats = AsyncMock(return_value=mock_stats)
        mock_inspector.format_stats = MagicMock(return_value="Workspace Statistics:\n  Files: 10")
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["stats", "/tmp/test.db"])

        assert result.exit_code == 0
        assert "Workspace Statistics" in result.output


class TestWorkspaceTree:
    """Tests for workspace tree command."""

    def test_tree_shows_tree(self) -> None:
        """Tree command should display directory tree."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.tree = AsyncMock(return_value=".\n├── src/\n│   └── main.py\n└── README.md")
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["tree", "/tmp/test.db"])

        assert result.exit_code == 0
        assert "src/" in result.output
        assert "main.py" in result.output

    def test_tree_with_path_option(self) -> None:
        """Tree command should accept path option."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.tree = AsyncMock(return_value="src/\n└── main.py")
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["tree", "/tmp/test.db", "--path", "/src"])

        assert result.exit_code == 0
        mock_inspector.tree.assert_called_once_with("/src", max_depth=-1)


class TestWorkspaceLs:
    """Tests for workspace ls command."""

    def test_ls_lists_entries(self) -> None:
        """Ls command should list directory entries."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.list_dir = AsyncMock(return_value=["main.py", "utils.py", "tests"])
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["ls", "/tmp/test.db"])

        assert result.exit_code == 0
        assert "main.py" in result.output
        assert "utils.py" in result.output
        assert "tests" in result.output

    def test_ls_empty_directory(self) -> None:
        """Ls command should handle empty directories."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.list_dir = AsyncMock(return_value=[])
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["ls", "/tmp/test.db"])

        assert result.exit_code == 0
        assert "empty" in result.output.lower()


class TestWorkspaceCat:
    """Tests for workspace cat command."""

    def test_cat_shows_file_contents(self) -> None:
        """Cat command should display file contents."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.read_file = AsyncMock(return_value="print('hello world')")
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["cat", "/tmp/test.db", "/src/main.py"])

        assert result.exit_code == 0
        assert "print('hello world')" in result.output

    def test_cat_file_not_found(self) -> None:
        """Cat command should handle missing files."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.read_file = AsyncMock(side_effect=FileNotFoundError("File not found"))
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["cat", "/tmp/test.db", "/missing.txt"])

        assert result.exit_code != 0
        assert "File not found" in result.output


class TestWorkspaceKvList:
    """Tests for workspace kv-list command."""

    def test_kv_list_shows_keys(self) -> None:
        """Kv-list command should list KV keys."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.get_kv_keys = AsyncMock(return_value=["agent:1:state", "agent:1:memory", "config"])
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["kv-list", "/tmp/test.db"])

        assert result.exit_code == 0
        assert "agent:1:state" in result.output
        assert "Keys (3)" in result.output

    def test_kv_list_with_prefix(self) -> None:
        """Kv-list command should filter by prefix."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.get_kv_keys = AsyncMock(return_value=["agent:1:state", "agent:1:memory"])
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["kv-list", "/tmp/test.db", "--prefix", "agent:"])

        assert result.exit_code == 0
        mock_inspector.get_kv_keys.assert_called_once_with("agent:")


class TestWorkspaceKvGet:
    """Tests for workspace kv-get command."""

    def test_kv_get_shows_value(self) -> None:
        """Kv-get command should display value."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.get_kv_value = AsyncMock(return_value="test_value")
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["kv-get", "/tmp/test.db", "my_key"])

        assert result.exit_code == 0
        assert "test_value" in result.output

    def test_kv_get_json_value(self) -> None:
        """Kv-get command should pretty-print JSON values."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.get_kv_value = AsyncMock(return_value={"nested": {"data": 123}})
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["kv-get", "/tmp/test.db", "json_key"])

        assert result.exit_code == 0
        assert '"nested"' in result.output
        assert '"data"' in result.output

    def test_kv_get_key_not_found(self) -> None:
        """Kv-get command should handle missing keys."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        mock_inspector.get_kv_value = AsyncMock(return_value=None)
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["kv-get", "/tmp/test.db", "missing_key"])

        assert result.exit_code != 0
        assert "Key not found" in result.output


class TestWorkspaceFind:
    """Tests for workspace find command."""

    def test_find_matches_pattern(self) -> None:
        """Find command should match files by pattern."""
        runner = CliRunner()

        mock_inspector = MagicMock()
        # Root returns some files and a dir
        mock_inspector.list_dir = AsyncMock(
            side_effect=[
                ["main.py", "utils.py", "src"],  # root
                ["app.py", "helpers.py"],  # src/
            ]
        )
        mock_inspector.close = AsyncMock()
        mock_inspector.__aenter__ = AsyncMock(return_value=mock_inspector)
        mock_inspector.__aexit__ = AsyncMock()

        with patch(
            "remora.cli.workspace.RemoraWorkspaceInspector.open",
            new=AsyncMock(return_value=mock_inspector),
        ):
            result = runner.invoke(workspace, ["find", "/tmp/test.db", "*.py"])

        assert result.exit_code == 0
        assert "main.py" in result.output
        assert "utils.py" in result.output
