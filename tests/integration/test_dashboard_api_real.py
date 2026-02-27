from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
from datetime import datetime
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora.adapters.starlette import create_app
from remora.core.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.core.container import RemoraContainer
from remora.core.events import GraphStartEvent, HumanInputResponseEvent
from remora.service.api import RemoraService
from tests.integration.helpers import load_vllm_config, write_bundle


pytestmark = pytest.mark.integration


def _build_config(tmp_path: Path) -> RemoraConfig:
    vllm_config = load_vllm_config()
    bundle_dir = tmp_path / "smoke_bundle"
    bundle_path = write_bundle(bundle_dir)
    return RemoraConfig(
        bundles=BundleConfig(path=str(bundle_dir), mapping={"function": bundle_path.name}),
        model=ModelConfig(
            base_url=vllm_config["base_url"],
            api_key=vllm_config["api_key"],
            default_model=vllm_config["model"],
        ),
        execution=ExecutionConfig(max_turns=1, timeout=120),
        workspace=WorkspaceConfig(base_path=str(tmp_path / "workspaces")),
    )


def _log(message: str) -> None:
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    thread_name = threading.current_thread().name
    print(f"[{timestamp}][{thread_name}] {message}", flush=True)




async def _stream_until(
    app,
    path: str,
    *,
    match_text: str | None = None,
    emit_after_first_chunk: callable | None = None,
    on_first_chunk: callable | None = None,
    timeout: float = 5.0,
) -> tuple[int, str]:
    response_started = asyncio.Event()
    first_chunk = asyncio.Event()
    done = asyncio.Event()
    status_code: int | None = None
    body_parts: list[bytes] = []

    async def send(message: dict) -> None:
        nonlocal status_code
        if message["type"] == "http.response.start":
            status_code = int(message["status"])
            response_started.set()
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                body_parts.append(body)
                if not first_chunk.is_set():
                    first_chunk.set()
                    if on_first_chunk:
                        await on_first_chunk()
                if match_text:
                    joined = b"".join(body_parts)
                    if match_text.encode() in joined:
                        done.set()
                else:
                    done.set()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "headers": [],
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("testclient", 123),
    }

    task = asyncio.create_task(app(scope, receive, send))
    emitter_task: asyncio.Task | None = None
    if emit_after_first_chunk is not None:
        async def _emit() -> None:
            await asyncio.wait_for(first_chunk.wait(), timeout=timeout)
            await emit_after_first_chunk()

        emitter_task = asyncio.create_task(_emit())

    try:
        await asyncio.wait_for(response_started.wait(), timeout=timeout)
        await asyncio.wait_for(done.wait(), timeout=timeout)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        if emitter_task:
            with contextlib.suppress(asyncio.CancelledError):
                await emitter_task

    if status_code is None:
        raise AssertionError("Response never started")

    body_text = b"".join(body_parts).decode("utf-8", errors="replace")
    return status_code, body_text


def test_dashboard_events_stream_emits_event(tmp_path: Path) -> None:
    _log("test_dashboard_events_stream_emits_event start")
    container = RemoraContainer.create(config=_build_config(tmp_path), project_root=tmp_path)
    event_bus = container.event_bus
    _log("creating app")
    service = RemoraService(container=container)
    app = create_app(service)

    async def _run() -> tuple[int, str]:
        async def _emit() -> None:
            _log("emitting GraphStartEvent for /events")
            await event_bus.emit(GraphStartEvent(graph_id="dash-events", node_count=1))

        return await _stream_until(
            app,
            "/events",
            match_text="event: GraphStartEvent",
            emit_after_first_chunk=_emit,
        )

    status, body = asyncio.run(_run())
    assert status == 200
    assert "GraphStartEvent" in body


def test_dashboard_subscribe_stream_returns_html(tmp_path: Path) -> None:
    _log("test_dashboard_subscribe_stream_returns_html start")
    container = RemoraContainer.create(config=_build_config(tmp_path), project_root=tmp_path)
    _log("creating app")
    service = RemoraService(container=container)
    app = create_app(service)

    async def _run() -> tuple[int, str]:
        return await _stream_until(
            app,
            "/subscribe",
            match_text="Remora Dashboard",
        )

    status, body = asyncio.run(_run())
    assert status == 200
    assert "Remora Dashboard" in body


def test_dashboard_input_emits_event(tmp_path: Path) -> None:
    _log("test_dashboard_input_emits_event start")
    container = RemoraContainer.create(config=_build_config(tmp_path), project_root=tmp_path)
    event_bus = container.event_bus
    events: queue.Queue[object] = queue.Queue()

    def _record(event: object) -> None:
        events.put(event)

    event_bus.subscribe_all(_record)
    _log("creating app")
    service = RemoraService(container=container)
    app = create_app(service)

    _log("starting TestClient")
    with TestClient(app) as client:
        _log("posting /input request")
        response = client.post(
            "/input",
            json={"request_id": "req-123", "response": "yes"},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("status") == "submitted"

        event = events.get(timeout=2)
        assert isinstance(event, HumanInputResponseEvent)
        assert event.request_id == "req-123"
        assert event.response == "yes"


def test_dashboard_events_stream_multiple_clients(tmp_path: Path) -> None:
    _log("test_dashboard_events_stream_multiple_clients start")
    container = RemoraContainer.create(config=_build_config(tmp_path), project_root=tmp_path)
    event_bus = container.event_bus
    _log("creating app")
    service = RemoraService(container=container)
    app = create_app(service)

    async def _run() -> tuple[tuple[int, str], tuple[int, str]]:
        ready = asyncio.Event()
        ready_count = 0
        lock = asyncio.Lock()

        async def _mark_ready() -> None:
            nonlocal ready_count
            async with lock:
                ready_count += 1
                if ready_count >= 2:
                    ready.set()

        async def _emit() -> None:
            await ready.wait()
            _log("emitting GraphStartEvent for multi-client /events")
            await event_bus.emit(GraphStartEvent(graph_id="dash-multi", node_count=1))

        emit_task = asyncio.create_task(_emit())
        task_a = asyncio.create_task(
            _stream_until(
                app,
                "/events",
                match_text="event: GraphStartEvent",
                emit_after_first_chunk=None,
                on_first_chunk=_mark_ready,
            )
        )
        task_b = asyncio.create_task(
            _stream_until(
                app,
                "/events",
                match_text="event: GraphStartEvent",
                emit_after_first_chunk=None,
                on_first_chunk=_mark_ready,
            )
        )

        results = await asyncio.gather(task_a, task_b)
        await emit_task
        return results[0], results[1]

    (status_a, body_a), (status_b, body_b) = asyncio.run(_run())
    assert status_a == 200
    assert status_b == 200
    assert "GraphStartEvent" in body_a
    assert "GraphStartEvent" in body_b
