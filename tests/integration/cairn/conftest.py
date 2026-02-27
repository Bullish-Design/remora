"""Cairn integration test fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from remora.cairn_bridge import CairnWorkspaceService
from remora.config import WorkspaceConfig
from remora.utils import PathResolver
from tests.integration.helpers import agentfs_available_sync


@pytest.fixture(scope="session")
def cairn_available() -> bool:
    """Skip Cairn tests when AgentFS is unavailable."""
    if not agentfs_available_sync():
        pytest.skip("AgentFS (fsdantic) is unavailable")
    return True


@pytest.fixture(autouse=True)
def _require_cairn(cairn_available: bool) -> None:
    """Ensure Cairn availability is checked for every test in this suite."""
    _ = cairn_available


@pytest.fixture
def workspace_config(tmp_path: Path) -> WorkspaceConfig:
    """Create a workspace config pointing to temp directory."""
    return WorkspaceConfig(base_path=str(tmp_path / "workspaces"))


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a project root with sample files."""
    root = tmp_path / "project"
    root.mkdir()

    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (root / "src" / "utils.py").write_text("def helper():\n    return 42\n", encoding="utf-8")
    (root / "README.md").write_text("# Test Project\n", encoding="utf-8")

    return root


@pytest.fixture
async def workspace_service(
    cairn_available: bool,
    workspace_config: WorkspaceConfig,
    project_root: Path,
) -> AsyncIterator[CairnWorkspaceService]:
    """Create and initialize a CairnWorkspaceService."""
    _ = cairn_available
    service = CairnWorkspaceService(
        workspace_config,
        graph_id="test-graph",
        project_root=project_root,
    )
    await service.initialize(sync=True)
    try:
        yield service
    finally:
        await service.close()


@pytest.fixture
async def stable_workspace(workspace_service: CairnWorkspaceService) -> Any:
    """Get the stable workspace from the service."""
    return workspace_service._stable_workspace


@pytest.fixture
async def agent_workspace(
    workspace_service: CairnWorkspaceService,
) -> AsyncIterator[Any]:
    """Create an agent workspace."""
    workspace = await workspace_service.get_agent_workspace("test-agent")
    yield workspace


@pytest.fixture
def path_resolver(project_root: Path) -> PathResolver:
    """Create a path resolver for the project."""
    return PathResolver(project_root)


@pytest.fixture
def list_workspace_files():
    """Factory for listing files in a workspace."""

    async def _list_files(workspace: Any, path: str = "/") -> list[str]:
        try:
            return await workspace.files.list_dir(path, output="name")
        except Exception:
            return []

    return _list_files


@pytest.fixture
def read_workspace_file():
    """Factory for reading files from workspace."""

    async def _read_file(workspace: Any, path: str) -> str | None:
        try:
            return await workspace.files.read(path, mode="text")
        except Exception:
            return None

    return _read_file


@pytest.fixture
def write_workspace_file():
    """Factory for writing files to workspace."""

    async def _write_file(workspace: Any, path: str, content: str) -> bool:
        try:
            await workspace.files.write(path, content)
            return True
        except Exception:
            return False

    return _write_file
