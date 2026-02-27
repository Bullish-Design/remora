from __future__ import annotations

import asyncio
import queue
import threading
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora.config import BundleConfig, ExecutionConfig, ModelConfig, RemoraConfig, WorkspaceConfig
from remora.dashboard.app import create_app
from remora.event_bus import EventBus
from remora.events import GraphStartEvent, HumanInputResponseEvent
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


def _emit_event(event_bus: EventBus, event: object) -> None:
    asyncio.run(event_bus.emit(event))


def _read_first_event_line(response, done: threading.Event, lines: queue.Queue[str]) -> None:
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode() if isinstance(raw, bytes) else raw
        lines.put(line)
        if line.startswith("event:"):
            done.set()
            break


def _read_until_contains(response, text: str, done: threading.Event, buffer: queue.Queue[str]) -> None:
    collected: list[str] = []
    for raw in response.iter_lines():
        if not raw:
            continue
        line = raw.decode() if isinstance(raw, bytes) else raw
        collected.append(line)
        if text in line:
            buffer.put(line)
            done.set()
            break
        if len(collected) > 200:
            break


def test_dashboard_events_stream_emits_event(tmp_path: Path) -> None:
    event_bus = EventBus()
    app = asyncio.run(create_app(event_bus=event_bus, config=_build_config(tmp_path)))

    with TestClient(app) as client:
        with client.stream("GET", "/events") as response:
            assert response.status_code == 200
            done = threading.Event()
            lines: queue.Queue[str] = queue.Queue()
            thread = threading.Thread(
                target=_read_first_event_line,
                args=(response, done, lines),
                daemon=True,
            )
            thread.start()

            _emit_event(event_bus, GraphStartEvent(graph_id="dash-events", node_count=1))

            assert done.wait(timeout=5)
            thread.join(timeout=1)

            event_line = lines.get(timeout=1)
            assert "GraphStartEvent" in event_line


def test_dashboard_subscribe_stream_returns_html(tmp_path: Path) -> None:
    event_bus = EventBus()
    app = asyncio.run(create_app(event_bus=event_bus, config=_build_config(tmp_path)))

    with TestClient(app) as client:
        with client.stream("GET", "/subscribe") as response:
            assert response.status_code == 200
            done = threading.Event()
            buffer: queue.Queue[str] = queue.Queue()
            thread = threading.Thread(
                target=_read_until_contains,
                args=(response, "Remora Dashboard", done, buffer),
                daemon=True,
            )
            thread.start()

            assert done.wait(timeout=5)
            thread.join(timeout=1)
            assert "Remora Dashboard" in buffer.get(timeout=1)


def test_dashboard_input_emits_event(tmp_path: Path) -> None:
    event_bus = EventBus()
    events: queue.Queue[object] = queue.Queue()

    def _record(event: object) -> None:
        events.put(event)

    event_bus.subscribe_all(_record)
    app = asyncio.run(create_app(event_bus=event_bus, config=_build_config(tmp_path)))

    with TestClient(app) as client:
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
    event_bus = EventBus()
    app = asyncio.run(create_app(event_bus=event_bus, config=_build_config(tmp_path)))

    client_a = TestClient(app)
    client_b = TestClient(app)

    with client_a, client_b:
        with client_a.stream("GET", "/events") as response_a, client_b.stream("GET", "/events") as response_b:
            done_a = threading.Event()
            done_b = threading.Event()
            lines_a: queue.Queue[str] = queue.Queue()
            lines_b: queue.Queue[str] = queue.Queue()

            thread_a = threading.Thread(
                target=_read_first_event_line,
                args=(response_a, done_a, lines_a),
                daemon=True,
            )
            thread_b = threading.Thread(
                target=_read_first_event_line,
                args=(response_b, done_b, lines_b),
                daemon=True,
            )
            thread_a.start()
            thread_b.start()

            _emit_event(event_bus, GraphStartEvent(graph_id="dash-multi", node_count=1))

            assert done_a.wait(timeout=5)
            assert done_b.wait(timeout=5)

            thread_a.join(timeout=1)
            thread_b.join(timeout=1)

            assert "GraphStartEvent" in lines_a.get(timeout=1)
            assert "GraphStartEvent" in lines_b.get(timeout=1)


def test_dashboard_websocket_stream_emits_event(tmp_path: Path) -> None:
    event_bus = EventBus()
    app = asyncio.run(create_app(event_bus=event_bus, config=_build_config(tmp_path)))

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            thread = threading.Thread(
                target=_emit_event,
                args=(event_bus, GraphStartEvent(graph_id="dash-ws", node_count=1)),
                daemon=True,
            )
            thread.start()
            payload = websocket.receive_json()
            thread.join(timeout=1)

            assert payload["event_type"] == "GraphStartEvent"
