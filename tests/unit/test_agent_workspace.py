from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from remora.core.agents.workspace import AgentWorkspace


def _workspace_with_read(side_effect) -> SimpleNamespace:
    return SimpleNamespace(
        files=SimpleNamespace(
            read=AsyncMock(side_effect=side_effect),
            write=AsyncMock(return_value=None),
            exists=AsyncMock(return_value=False),
            list_dir=AsyncMock(return_value=[]),
            remove=AsyncMock(return_value=None),
        )
    )


@pytest.mark.asyncio
async def test_read_normalizes_leading_slash_paths() -> None:
    workspace = _workspace_with_read(["ok"])
    agent_workspace = AgentWorkspace(workspace, "agent-1")

    result = await agent_workspace.read("/meta.json")

    assert result == "ok"
    workspace.files.read.assert_awaited_once_with("meta.json", mode="text")


@pytest.mark.asyncio
async def test_read_missing_does_not_retry_stable_when_sync_fails() -> None:
    workspace = _workspace_with_read(FileNotFoundError("missing"))
    stable = _workspace_with_read(FileNotFoundError("missing"))
    ensure_file_synced = AsyncMock(return_value=False)
    agent_workspace = AgentWorkspace(
        workspace,
        "agent-1",
        stable_workspace=stable,
        ensure_file_synced=ensure_file_synced,
    )

    with pytest.raises(FileNotFoundError):
        await agent_workspace.read("/meta.json")

    assert workspace.files.read.await_count == 1
    assert stable.files.read.await_count == 1
    ensure_file_synced.assert_awaited_once_with("meta.json")


@pytest.mark.asyncio
async def test_read_retries_stable_after_successful_sync() -> None:
    workspace = _workspace_with_read(FileNotFoundError("missing"))
    stable = _workspace_with_read([FileNotFoundError("missing"), "synced-content"])
    ensure_file_synced = AsyncMock(return_value=True)
    agent_workspace = AgentWorkspace(
        workspace,
        "agent-1",
        stable_workspace=stable,
        ensure_file_synced=ensure_file_synced,
    )

    result = await agent_workspace.read("meta.json")

    assert result == "synced-content"
    assert stable.files.read.await_count == 2
    ensure_file_synced.assert_awaited_once_with("meta.json")
