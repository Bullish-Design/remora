from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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
    pass


class _FakeServer:
    def __init__(self, root_path: str, db: _BlockingDB) -> None:
        self.workspace = _FakeWorkspace(root_path)
        self.db = db
        self.watcher = None
        self.event_store = None
        self.subscriptions = None
        self.runner = None
        self._features: dict[str, object] = {}
        self.notify_calls = 0
        self.user_activity_windows: list[float] = []

    def feature(self, uri):
        def _decorator(fn):
            self._features[uri] = fn
            return fn

        return _decorator

    def user_recently_active(self, window_seconds: float) -> bool:
        self.user_activity_windows.append(window_seconds)
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


class _SimpleDB:
    async def update_edges(self, _nodes) -> None:
        return None


class _FakeCairnService:
    async def initialize(self, *, sync_mode=None) -> None:
        _ = sync_mode
        return None


class _FakeEventBus:
    def __init__(self) -> None:
        self.subscriptions: list[tuple[object, object]] = []

    def subscribe(self, event_type, handler) -> None:
        self.subscriptions.append((event_type, handler))


class _ChunkTrackingEventStore:
    def __init__(self) -> None:
        self.chunk_sizes: list[int] = []
        self.nodes = self
        self._conn = None
        self._node_store = None

    def rebind_runtime_primitives(self) -> None:
        return None

    async def list_nodes(self, file_path: str):
        _ = file_path
        return []

    async def batch_append(self, source: str, events: list[object]) -> None:
        _ = source
        self.chunk_sizes.append(len(events))

    async def checkpoint_wal(self, mode: str) -> None:
        _ = mode
        return None

    def close(self) -> None:
        return None


def mock_parse_content(uri, text, language=None):
    from remora.core.code.discovery import CSTNode
    nodes = []
    for idx in range(20):
        node_id = f"{uri}#{idx}"
        nodes.append(
            CSTNode(
                node_id=node_id,
                node_type="function",
                name=f"fn_{idx}",
                full_name=f"fn_{idx}",
                file_path=uri,
                text=f"def fn_{idx}(): pass",
                start_line=idx + 1,
                end_line=idx + 1,
                start_byte=0,
                end_byte=0,
            )
        )
    return nodes


def _is_background_scan_task(task: asyncio.Task) -> bool:
    coro = task.get_coro()
    qualname = getattr(coro, "__qualname__", "")
    return "BackgroundScanner.run" in qualname


@pytest.mark.asyncio
async def test_background_scan_saves_partial_manifest_before_completion(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    for idx in range(12):
        (tmp_path / f"file_{idx:02d}.py").write_text(f"def fn_{idx}():\n    return {idx}\n", encoding="utf-8")

    db = _BlockingDB(block_after_call=11)
    fake_server = _FakeServer(str(tmp_path), db)

    import remora.lsp.__main__ as lsp_main_mod
    import remora.runner.agent_runner as runner_mod

    monkeypatch.setattr(lsp_main_mod, "_setup_logging", lambda: logging.getLogger("test"))
    monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)
    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeRunner)
    monkeypatch.setattr("remora.core.config.load_config", lambda path=None: Config())

    with pytest.raises(_StopSentinel):
        lsp_main_mod._run_server()

    scheduled_tasks: list[asyncio.Task] = []

    def _capture_ensure_future(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "ensure_future", _capture_ensure_future)
    initialized_handler = fake_server._features[lsp.INITIALIZED]
    await initialized_handler(lsp.InitializedParams())

    scan_task = next(t for t in scheduled_tasks if _is_background_scan_task(t))

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


@pytest.mark.asyncio
async def test_initialized_handler_does_not_block_on_companion_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "one_file.py").write_text("def only_fn():\n    return 1\n", encoding="utf-8")

    event_store = _ChunkTrackingEventStore()
    fake_server = _FakeServer(str(tmp_path), _SimpleDB())
    fake_server.event_store = event_store
    event_bus = _FakeEventBus()
    cairn_service = _FakeCairnService()

    import remora.lsp.__main__ as lsp_main_mod
    import remora.runner.agent_runner as runner_mod

    monkeypatch.setattr(lsp_main_mod, "_setup_logging", lambda: logging.getLogger("test"))
    monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)
    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeRunner)
    monkeypatch.setattr("remora.core.config.load_config", lambda path=None: Config())

    with pytest.raises(_StopSentinel):
        lsp_main_mod._run_server(event_store=event_store, event_bus=event_bus, cairn_service=cairn_service)

    scheduled_tasks: list[asyncio.Task] = []

    def _capture_ensure_future(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    companion_started = asyncio.Event()
    unblock_companion = asyncio.Event()

    class _Registry:
        _router = None

    async def _slow_start_companion(*, event_store, event_bus, cairn_service, config):
        _ = (event_store, event_bus, cairn_service, config)
        companion_started.set()
        await unblock_companion.wait()
        return _Registry()

    monkeypatch.setattr(asyncio, "ensure_future", _capture_ensure_future)
    monkeypatch.setattr("remora.companion.startup.start_companion", _slow_start_companion)

    initialized_handler = fake_server._features[lsp.INITIALIZED]
    await asyncio.wait_for(initialized_handler(lsp.InitializedParams()), timeout=0.2)
    await asyncio.wait_for(companion_started.wait(), timeout=1.0)

    unblock_companion.set()
    await asyncio.sleep(0)

    for task in scheduled_tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*scheduled_tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_background_scan_uses_aggressive_preemption_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / "one_file.py").write_text("def only_fn():\n    return 1\n", encoding="utf-8")

    event_store = _ChunkTrackingEventStore()
    fake_server = _FakeServer(str(tmp_path), _SimpleDB())
    fake_server.event_store = event_store

    import remora.lsp.__main__ as lsp_main_mod
    import remora.runner.agent_runner as runner_mod

    recorded_sleep_delays: list[float] = []
    original_sleep = asyncio.sleep

    async def _capture_sleep(delay: float):
        recorded_sleep_delays.append(delay)
        await original_sleep(0)

    monkeypatch.setattr(lsp_main_mod, "_setup_logging", lambda: logging.getLogger("test"))
    monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)
    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeRunner)
    monkeypatch.setattr("remora.core.config.load_config", lambda path=None: Config())
    monkeypatch.setattr(asyncio, "sleep", _capture_sleep)
    monkeypatch.setattr("remora.core.code.discovery.parse_content", mock_parse_content)

    with pytest.raises(_StopSentinel):
        lsp_main_mod._run_server(event_store=event_store)

    scheduled_tasks: list[asyncio.Task] = []

    def _capture_ensure_future(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "ensure_future", _capture_ensure_future)
    initialized_handler = fake_server._features[lsp.INITIALIZED]
    await initialized_handler(lsp.InitializedParams())

    scan_task = next(t for t in scheduled_tasks if _is_background_scan_task(t))
    await asyncio.wait_for(scan_task, timeout=5.0)

    assert event_store.chunk_sizes == [8, 8, 4]
    assert 0.05 in recorded_sleep_delays
    assert fake_server.user_activity_windows
    assert set(fake_server.user_activity_windows) == {5.0}
    assert fake_server.notify_calls == 1

    for task in scheduled_tasks:
        if task is not scan_task and not task.done():
            task.cancel()


@pytest.mark.asyncio
async def test_initialized_registers_bootstrap_user_question_bridge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_server = _FakeServer(str(tmp_path), _SimpleDB())
    fake_server.protocol = SimpleNamespace(notify=MagicMock())
    event_bus = _FakeEventBus()

    import remora.lsp.__main__ as lsp_main_mod
    import remora.runner.agent_runner as runner_mod
    from remora.bootstrap.bedrock import BootstrapEvent

    monkeypatch.setattr(lsp_main_mod, "_setup_logging", lambda: logging.getLogger("test"))
    monkeypatch.setattr(lsp_main_mod, "_get_server", lambda: fake_server)
    monkeypatch.setattr(runner_mod, "AgentRunner", _FakeRunner)
    monkeypatch.setattr("remora.core.config.load_config", lambda path=None: Config())

    with pytest.raises(_StopSentinel):
        lsp_main_mod._run_server(event_bus=event_bus)

    scheduled_tasks: list[asyncio.Task] = []

    def _capture_ensure_future(coro):
        task = asyncio.create_task(coro)
        scheduled_tasks.append(task)
        return task

    monkeypatch.setattr(asyncio, "ensure_future", _capture_ensure_future)
    initialized_handler = fake_server._features[lsp.INITIALIZED]
    await initialized_handler(lsp.InitializedParams())

    bridge_handler = None
    for event_type, handler in event_bus.subscriptions:
        if event_type is BootstrapEvent:
            bridge_handler = handler
            break
    assert bridge_handler is not None

    await bridge_handler(
        BootstrapEvent(
            event_type="HumanInputRequestEvent",
            node_id="function:app.py:foo",
            from_agent="agent-foo",
            payload={
                "kind": "user_question",
                "request_id": "req-99",
                "question": "What should this function return?",
                "node_id": "function:app.py:foo",
            },
        )
    )

    fake_server.protocol.notify.assert_called_once_with(
        "$/remora/requestInput",
        {
            "agent_id": "agent-foo",
            "prompt": "What should this function return?",
            "request_id": "req-99",
            "node_id": "function:app.py:foo",
            "question": "What should this function return?",
        },
    )

    for task in scheduled_tasks:
        if not task.done():
            task.cancel()
