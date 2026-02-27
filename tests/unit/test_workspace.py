from pathlib import Path

import pytest

from remora.workspace import (
    WorkspaceConfig,
    create_shared_workspace,
    create_workspace,
    restore_workspace,
    snapshot_workspace,
)


@pytest.mark.asyncio
async def test_create_workspace_creates_database(tmp_path: Path) -> None:
    config = WorkspaceConfig(base_path=tmp_path)
    handle = await create_workspace("agent-1", config)

    assert handle.db_path.exists()
    await handle.workspace.files.write("/metadata.txt", "hello")
    content = await handle.workspace.files.read("/metadata.txt")
    assert content == "hello"

    await handle.close()


@pytest.mark.asyncio
async def test_create_shared_workspace_groups_workspaces(tmp_path: Path) -> None:
    config = WorkspaceConfig(base_path=tmp_path)
    handle = await create_shared_workspace("graph-1", config)

    expected_dir = tmp_path / "shared" / "graph-1"
    assert expected_dir.exists()
    assert handle.db_path.parent == expected_dir

    await handle.close()


@pytest.mark.asyncio
async def test_snapshot_and_restore_workspace(tmp_path: Path) -> None:
    config = WorkspaceConfig(base_path=tmp_path)
    handle = await create_workspace("agent-copy", config)

    await handle.workspace.files.write("/node.txt", "payload")
    snapshot_dir = tmp_path / "snapshots" / "agent-copy"
    snapshot_path = await snapshot_workspace(handle, snapshot_dir)

    assert snapshot_path.exists()
    await handle.close()

    restored = await restore_workspace(snapshot_path)
    content = await restored.workspace.files.read("/node.txt")
    assert content == "payload"

    await restored.close()
