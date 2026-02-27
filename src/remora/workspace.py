"""Cairn workspace helpers for Remora v0.4."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from fsdantic.client import Fsdantic
from fsdantic.workspace import Workspace
from structured_agents.types import RunResult


@dataclass(frozen=True)
class WorkspaceConfig:
    """Configuration overrides for Cairn workspaces."""

    base_path: Path = Path(".remora/workspaces")
    cleanup_after: str = "1h"


class CairnWorkspace:
    """Wrapper for an fsdantic workspace plus the backing sqlite path."""

    def __init__(self, workspace: Workspace, db_path: Path) -> None:
        self.workspace = workspace
        self.db_path = db_path

    async def close(self) -> None:
        await self.workspace.close()


def _resolve_base_path(config: WorkspaceConfig) -> Path:
    base_path = Path(config.base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    return base_path


async def _open_workspace(db_path: Path) -> CairnWorkspace:
    workspace = await Fsdantic.open(path=str(db_path))
    return CairnWorkspace(workspace=workspace, db_path=db_path)


async def create_workspace(agent_id: str, config: WorkspaceConfig) -> CairnWorkspace:
    """Create an isolated workspace for a single agent."""
    base_path = _resolve_base_path(config)
    agent_dir = base_path / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    db_path = agent_dir / "workspace.db"
    return await _open_workspace(db_path)


async def create_shared_workspace(graph_id: str, config: WorkspaceConfig) -> CairnWorkspace:
    """Create a shared workspace for a graph run."""
    base_path = _resolve_base_path(config)
    shared_dir = base_path / "shared" / graph_id
    shared_dir.mkdir(parents=True, exist_ok=True)
    db_path = shared_dir / "workspace.db"
    return await _open_workspace(db_path)


async def snapshot_workspace(workspace: CairnWorkspace, snapshot_dir: Path | str) -> Path:
    """Snapshot the workspace sqlite directory to a safe location."""
    snapshot_dir_path = Path(snapshot_dir)
    await workspace.workspace.raw.get_database().commit()
    if snapshot_dir_path.exists():
        shutil.rmtree(snapshot_dir_path)
    shutil.copytree(workspace.db_path.parent, snapshot_dir_path)
    return snapshot_dir_path / workspace.db_path.name


async def restore_workspace(snapshot: Path | str) -> CairnWorkspace:
    """Restore a workspace from a snapshot file."""
    snapshot_path = Path(snapshot)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"Snapshot not found: {snapshot_path}")
    return await _open_workspace(snapshot_path)


class CairnDataProvider:
    """Populates Grail `files` using Cairn workspaces."""

    def __init__(self, workspace: Workspace | CairnWorkspace) -> None:
        target = workspace.workspace if isinstance(workspace, CairnWorkspace) else workspace
        self._files = target.files

    async def load_files(self, node: Any) -> dict[str, str | bytes]:
        files: dict[str, str | bytes] = {}

        main_path = getattr(node, "file_path", None)
        if main_path:
            try:
                content = await self._files.read(str(main_path))
                files[str(main_path)] = content
            except Exception:
                files[str(main_path)] = ""

        related = getattr(node, "related_files", None) or []
        for rel_path in related:
            try:
                content = await self._files.read(str(rel_path))
                files[str(rel_path)] = content
            except Exception:
                files[str(rel_path)] = ""

        return files

    async def load_file(self, path: str) -> str | bytes:
        try:
            return await self._files.read(path)
        except Exception:
            return ""


@dataclass(frozen=True)
class ResultSummary:
    """Summary of an agent run for context + dashboard consumers."""

    agent_id: str
    success: bool
    turn_count: int
    termination_reason: str
    final_message: str | None
    payload: dict[str, Any]
    writes: list[tuple[str, str]]
    deleted_files: list[str]
    errors: list[str]
    tool_results: list[dict[str, Any]]

    def brief(self) -> str:
        status = "success" if self.success else "failed"
        message = self.final_message or "no output"
        return f"{status} ({self.turn_count} turns): {message}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CairnResultHandler:
    """Persists Remora tool results back into the Cairn workspace."""

    async def handle(
        self,
        agent_id: str,
        run_result: RunResult,
        payload: dict[str, Any],
        workspace: Workspace | CairnWorkspace,
    ) -> ResultSummary:
        files = workspace.workspace if isinstance(workspace, CairnWorkspace) else workspace
        file_manager = files.files

        writes = self._collect_writes(payload)
        for path, content in writes:
            await file_manager.write(path, content)

        deleted_files: list[str] = []
        for path in payload.get("deleted_files", []):
            deleted_files.append(path)
            try:
                await file_manager.agent_fs.fs.delete_file(path)
            except Exception:
                pass

        errors: list[str] = []
        if payload.get("error"):
            errors.append(str(payload["error"]))

        final_message = run_result.final_message.content
        final_tool_result = run_result.final_tool_result
        if final_tool_result and final_tool_result.is_error:
            errors.append(final_tool_result.output)

        tool_results: list[dict[str, Any]] = []
        if final_tool_result is not None:
            tool_results.append(
                {
                    "name": final_tool_result.name,
                    "call_id": final_tool_result.call_id,
                    "output": final_tool_result.output,
                    "is_error": final_tool_result.is_error,
                }
            )

        success = not errors and payload.get("status") != "failed"

        return ResultSummary(
            agent_id=agent_id,
            success=success,
            turn_count=run_result.turn_count,
            termination_reason=run_result.termination_reason,
            final_message=final_message,
            payload=payload,
            writes=writes,
            deleted_files=deleted_files,
            errors=errors,
            tool_results=tool_results,
        )

    def _collect_writes(self, payload: dict[str, Any]) -> list[tuple[str, str]]:
        writes: list[tuple[str, str]] = []

        if "written_file" in payload and "content" in payload:
            writes.append((payload["written_file"], payload["content"]))

        for fix in payload.get("lint_fixes", []):
            if "path" in fix and "content" in fix:
                writes.append((fix["path"], fix["content"]))

        for test_file in payload.get("generated_tests", []):
            if "path" in test_file and "content" in test_file:
                writes.append((test_file["path"], test_file["content"]))

        return writes


__all__ = [
    "CairnDataProvider",
    "CairnResultHandler",
    "CairnWorkspace",
    "WorkspaceConfig",
    "ResultSummary",
    "create_workspace",
    "create_shared_workspace",
    "snapshot_workspace",
    "restore_workspace",
]
