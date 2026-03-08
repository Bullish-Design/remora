from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.core.agents import cairn_bridge
from remora.core.agents.cairn_bridge import CairnWorkspaceService, SyncMode
from remora.core.config import Config


def _dummy_workspace() -> SimpleNamespace:
    return SimpleNamespace(files=SimpleNamespace(write=AsyncMock(return_value=None)))


@pytest.mark.asyncio
async def test_initialize_logs_dotfile_sync_warning_and_summary(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "app.py").write_text("print('ok')\n", encoding="utf-8")
    hidden_dir = project_root / ".venv"
    hidden_dir.mkdir()
    (hidden_dir / "site.py").write_text("x = 1\n", encoding="utf-8")

    workspace = _dummy_workspace()

    async def fake_open_workspace(*_args, **_kwargs):
        return workspace

    monkeypatch.setattr(cairn_bridge, "cairn_open_workspace", fake_open_workspace)

    messages: list[str] = []
    config = Config(
        swarm_root=str(tmp_path / "swarm"),
        workspace_ignore_patterns=(".git", "__pycache__"),
        workspace_ignore_dotfiles=False,
    )
    service = CairnWorkspaceService(
        config=config,
        project_root=project_root,
        progress_callback=messages.append,
    )
    service._manager = MagicMock()

    await service.initialize(sync_mode=SyncMode.FULL)

    assert any("dotfiles are included in workspace sync" in msg for msg in messages)
    assert any("sync summary" in msg for msg in messages)
    assert any(".venv" in msg for msg in messages if "sync summary" in msg)

    written_paths = {call.args[0] for call in workspace.files.write.await_args_list}
    assert "app.py" in written_paths
    assert ".venv/site.py" in written_paths


@pytest.mark.asyncio
async def test_initialize_logs_open_workspace_heartbeat(tmp_path, monkeypatch):
    workspace = _dummy_workspace()

    async def slow_open_workspace(*_args, **_kwargs):
        await asyncio.sleep(0.03)
        return workspace

    monkeypatch.setattr(cairn_bridge, "cairn_open_workspace", slow_open_workspace)
    monkeypatch.setattr(cairn_bridge, "OPEN_WORKSPACE_PROGRESS_INTERVAL_SECONDS", 0.01)

    messages: list[str] = []
    config = Config(swarm_root=str(tmp_path / "swarm"))
    service = CairnWorkspaceService(
        config=config,
        project_root=tmp_path / "project",
        progress_callback=messages.append,
    )
    service._manager = MagicMock()

    await service.initialize(sync_mode=SyncMode.NONE)

    assert any("waiting for stable workspace open" in msg for msg in messages)
    assert any("sync skipped (mode=none)" in msg for msg in messages)


@pytest.mark.asyncio
async def test_sync_prunes_hidden_directories_when_dotfiles_ignored(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "visible.py").write_text("print('visible')\n", encoding="utf-8")
    hidden = project_root / ".hidden"
    hidden.mkdir()
    for idx in range(200):
        (hidden / f"file_{idx}.txt").write_text("x\n", encoding="utf-8")

    workspace = _dummy_workspace()

    async def fake_open_workspace(*_args, **_kwargs):
        return workspace

    monkeypatch.setattr(cairn_bridge, "cairn_open_workspace", fake_open_workspace)

    messages: list[str] = []
    config = Config(
        swarm_root=str(tmp_path / "swarm"),
        workspace_ignore_patterns=(".git", "__pycache__"),
        workspace_ignore_dotfiles=True,
    )
    service = CairnWorkspaceService(
        config=config,
        project_root=project_root,
        progress_callback=messages.append,
    )
    service._manager = MagicMock()

    await service.initialize(sync_mode=SyncMode.FULL)

    summary = next(msg for msg in messages if "sync summary" in msg)
    match = re.search(r"scanned=(\d+)", summary)
    assert match is not None
    assert int(match.group(1)) == 1
    assert "ignored=1" in summary

    written_paths = {call.args[0] for call in workspace.files.write.await_args_list}
    assert written_paths == {"visible.py"}


@pytest.mark.asyncio
async def test_prepare_runtime_handoff_resets_workspace_handles(tmp_path):
    config = Config(swarm_root=str(tmp_path / "swarm"))
    service = CairnWorkspaceService(config=config, project_root=tmp_path / "project")

    service._stable_workspace = object()
    service._agent_workspaces = {"abc": object()}
    old_lock = service._agent_workspaces_lock
    old_manager = MagicMock()
    old_manager.close_all = AsyncMock(return_value=None)
    service._manager = old_manager

    await service.prepare_runtime_handoff()

    old_manager.close_all.assert_awaited_once()
    assert service._stable_workspace is None
    assert service._agent_workspaces == {}
    assert service._agent_workspaces_lock is not old_lock
    assert service._manager is not old_manager
