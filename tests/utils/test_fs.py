import asyncio
from pathlib import Path

import pytest

from remora.utils.fs import managed_workspace


@pytest.mark.asyncio
async def test_managed_workspace_creates_and_cleans_up(tmp_path: Path) -> None:
    workspace = tmp_path / "test_workspace"
    
    assert not workspace.exists()
    
    async with managed_workspace(workspace) as path:
        assert path == workspace
        assert workspace.exists()
        assert workspace.is_dir()
        
        # Add a file to ensure it cleans up non-empty directories
        (workspace / "test.txt").write_text("test")
        
    assert not workspace.exists()


@pytest.mark.asyncio
async def test_managed_workspace_cleans_up_on_exception(tmp_path: Path) -> None:
    workspace = tmp_path / "test_workspace_err"
    
    class TestException(Exception):
        pass
        
    try:
        async with managed_workspace(workspace):
            assert workspace.exists()
            raise TestException("Trigger Error!")
    except TestException:
        pass
        
    assert not workspace.exists()
