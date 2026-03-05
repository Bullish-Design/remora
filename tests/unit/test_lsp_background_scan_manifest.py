from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from lsprotocol import types as lsp

from remora.core.config import Config


class _StopSentinel(Exception):
    pass


class _FakeWorkspace:
    def __init__(self, root_path: str) -> None:
        self.root_path = root_path
        self.root_uri = f"file://{root_path}"


class _BlockingDB:
    def __init__(self, block_after_call: int) -> None:
        self.block_after_call = block_after_call
        self.calls = 0
        self.entered_block = asyncio.Event()

    async def update_edges(self, _nodes) -> None:
        self.calls += 1
        if self.calls >= self.block_after_call:
            self.entered_block.set()
            await asyncio.Future()


class _FakeWatcher:
    def parse_and_inject_ids(self, uri: str, text: str, _old_nodes: list[dict]) -> list[dict]:
        _ = text
        node_id = f"{uri}#0"
        return [
            {
                "node_id": node_id,
                "node_type": "function",
                "name": "fn",
                "full_name": "fn",
                "file_path": uri,
                "start_line": 1,
                "end_line": 1,
                "source_code": "def fn(): pass",
                "source_hash": f"hash:{node_id}",
                "start_byte": 0,
                "end_byte": 0,
            }
        ]


class _FakeServer:
    def __init__(self, root_path: str, db: _BlockingDB) -> None:
        self.workspace = _FakeWorkspace(root_path)
        self.db = db
        self.watcher = _FakeWatcher()
        self.event_store = None
        self.subscriptions = None
        self.runner = None
        self._features: dict[str, object] = {}
        self.notify_calls = 0

    def feature(self, uri):
        def _decorator(fn):
            self._features[uri] = fn
            return fn

        return _decorator

    def user_recently_active(self, window_seconds: float) -> bool:
        _ = window_seconds
        return False

    async def notify_agents_updated(self) -> None:
        self.notify_calls += 1

    def start_io(self) -> None:
        raise _StopSentinel()


class _FakeRunner:
    def __init__(self, **kwargs) -> None:
        _ = kwargs

    async def run_forever(self) -> None:
        await asyncio.Future()

    async def run_from_event_store(self, _event_store) -> None:
        await asyncio.Future()


@pytest.mark.asyncio
async def test_background_scan_saves_partial_manifest_before_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for idx in range(12):
        (tmp_path / f"file_{idx:02d}.py").write_text(f"def fn_{idx}():\n    return {idx}\n", encoding="utf-8")

    db = _BlockingDB(block_after_call=11)
    fake_server = _FakeServer(str(tmp_path), db)

    import remora.lsp.__main__ as lsp_main_mod
    import remora.lsp.runner as runner_mod

    monkeypatch.setattr(lsp_main_mod, "_setup_logging", lambda: logging.getLogger("test"))
    monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)
    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeRunner)
    monkeypatch.setattr("remora.core.config.load_config", lambda path=None: Config())

    with pytest.raises(_StopSentinel):
        lsp_main_mod.main()

    scheduled_tasks: list[asyncio.Task] = []

    def _capture_ensure_future(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "ensure_future", _capture_ensure_future)
    initialized_handler = fake_server._features[lsp.INITIALIZED]
    await initialized_handler(lsp.InitializedParams())

    scan_task = next(t for t in scheduled_tasks if t.get_coro().__name__ == "_background_scan")

    await asyncio.wait_for(db.entered_block.wait(), timeout=5.0)
    scan_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await scan_task

    manifest_path = tmp_path / ".remora" / "scan-manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(manifest) >= 10

    for task in scheduled_tasks:
        if task is not scan_task and not task.done():
            task.cancel()
