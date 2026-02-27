from __future__ import annotations

from pathlib import Path

import pytest

from remora.core.streaming_sync import StreamingSyncManager


class _FakeFiles:
    def __init__(self) -> None:
        self.writes: dict[str, bytes] = {}

    async def write(self, path: str, content: bytes, mode: str = "binary") -> None:
        _ = mode
        self.writes[path] = content


class _FakeWorkspace:
    def __init__(self) -> None:
        self.files = _FakeFiles()


@pytest.mark.asyncio
async def test_streaming_sync_ensure_synced(tmp_path: Path) -> None:
    file_path = tmp_path / "alpha.txt"
    file_path.write_text("hello", encoding="utf-8")

    workspace = _FakeWorkspace()
    sync = StreamingSyncManager(
        project_root=tmp_path,
        workspace=workspace,
        ignore_checker=lambda _path: False,
    )

    assert await sync.ensure_synced("alpha.txt") is True
    assert workspace.files.writes["alpha.txt"] == b"hello"
    assert sync.get_stats().files_synced == 1


@pytest.mark.asyncio
async def test_streaming_sync_respects_ignore(tmp_path: Path) -> None:
    file_path = tmp_path / "skip.txt"
    file_path.write_text("skip", encoding="utf-8")

    workspace = _FakeWorkspace()
    sync = StreamingSyncManager(
        project_root=tmp_path,
        workspace=workspace,
        ignore_checker=lambda path: path.name == "skip.txt",
    )

    assert await sync.ensure_synced("skip.txt") is False
    assert "skip.txt" not in workspace.files.writes
    assert sync.get_stats().files_skipped == 1
