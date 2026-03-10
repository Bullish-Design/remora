"""Tests for the Starlette adapter HTTP routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.testclient import TestClient
from tests.unit.conftest import make_node

from remora.adapters.starlette import create_app
from remora.core.config import Config
from remora.core.events.event_bus import EventBus
from remora.service.api import RemoraService


def _make_service(*, with_event_store: bool = True, with_companion: bool = True):
    event_store = MagicMock() if with_event_store else None
    if event_store is not None:
        event_store.nodes = MagicMock()
        event_store.initialize = AsyncMock()
        event_store.close = AsyncMock()
    workspace_service = MagicMock()
    workspace_service.close = AsyncMock()
    registry = MagicMock() if with_companion else None
    service = RemoraService(
        config=Config(),
        project_root=Path("/tmp"),
        event_bus=EventBus(),
        event_store=event_store,
        workspace_service=workspace_service,
        companion_registry=registry,
    )
    return service, event_store, workspace_service, registry


class TestCors:
    def test_allows_localhost_8766_origin(self):
        service, *_ = _make_service()
        app = create_app(service)

        with TestClient(app) as client:
            response = client.options(
                "/companion/chat",
                headers={
                    "Origin": "http://localhost:8766",
                    "Access-Control-Request-Method": "POST",
                },
            )

        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:8766"

    def test_lifespan_initializes_and_closes_runtime(self):
        service, event_store, workspace_service, _registry = _make_service()
        app = create_app(service)

        with TestClient(app) as _client:
            pass

        assert event_store is not None
        event_store.initialize.assert_awaited_once()
        event_store.close.assert_awaited_once()
        workspace_service.close.assert_awaited_once()


class TestGraphDataRoute:
    def test_returns_nodes_and_deduped_call_edges(self):
        service, *_ = _make_service()
        service.list_agents = AsyncMock(
            return_value=[
                {
                    "node_id": "a",
                    "name": "alpha",
                    "node_type": "function",
                    "status": "idle",
                    "file_path": "src/a.py",
                    "full_name": "pkg.a",
                    "callee_ids": ["b", "b"],
                },
                {
                    "node_id": "b",
                    "name": "beta",
                    "node_type": "function",
                    "status": "running",
                    "file_path": "src/b.py",
                    "full_name": "pkg.b",
                    "parent_id": "p",
                    "callee_ids": [],
                },
            ]
        )
        app = create_app(service)

        with TestClient(app) as client:
            response = client.get("/graph/data")

        assert response.status_code == 200
        payload = response.json()
        assert len(payload["nodes"]) == 2
        assert len(payload["edges"]) == 1
        assert payload["edges"][0]["data"]["id"] == "a--calls--b"
        node_b = [item for item in payload["nodes"] if item["data"]["id"] == "b"][0]
        assert node_b["data"]["parent"] == "p"

    def test_requires_event_store(self):
        service, *_ = _make_service(with_event_store=False)
        app = create_app(service)

        with TestClient(app) as client:
            response = client.get("/graph/data")

        assert response.status_code == 400
        assert response.json()["error"] == "event store not configured"


class TestCompanionRoutes:
    def test_companion_sidebar_returns_markdown(self):
        service, event_store, workspace_service, _registry = _make_service()
        node = make_node(node_id="node-1")
        event_store.nodes.get_node = AsyncMock(return_value=node)
        workspace = MagicMock()
        workspace_service.get_agent_workspace = AsyncMock(return_value=workspace)
        app = create_app(service)

        with patch("remora.adapters.starlette.compose_sidebar", new=AsyncMock(return_value="# Sidebar")):
            with TestClient(app) as client:
                response = client.get("/companion/sidebar/node-1")

        assert response.status_code == 200
        assert response.json() == {"node_id": "node-1", "markdown": "# Sidebar"}

    def test_companion_sidebar_requires_registry(self):
        service, *_ = _make_service(with_companion=False)
        app = create_app(service)

        with TestClient(app) as client:
            response = client.get("/companion/sidebar/node-1")

        assert response.status_code == 503
        assert response.json()["error"] == "companion not configured — start companion first"

    def test_companion_chat_returns_reply(self):
        service, event_store, _workspace_service, registry = _make_service()
        node = make_node(node_id="node-1")
        event_store.nodes.get_node = AsyncMock(return_value=node)
        agent = MagicMock()
        agent.send = AsyncMock(return_value=SimpleNamespace(text="hello back"))
        registry.get_or_create = AsyncMock(return_value=agent)
        app = create_app(service)

        with TestClient(app) as client:
            response = client.post("/companion/chat", json={"node_id": "node-1", "message": "hi"})

        assert response.status_code == 200
        assert response.json() == {"node_id": "node-1", "reply": "hello back"}
        registry.get_or_create.assert_awaited_once_with(node)
        agent.send.assert_awaited_once_with("hi")

    def test_companion_workspace_lists_files(self):
        service, event_store, workspace_service, _registry = _make_service()
        node = make_node(node_id="node-1")
        event_store.nodes.get_node = AsyncMock(return_value=node)
        workspace = MagicMock()
        workspace.list_keys = AsyncMock(return_value=["chat/session.md", "notes.md"])
        workspace_service.get_agent_workspace = AsyncMock(return_value=workspace)
        app = create_app(service)

        with TestClient(app) as client:
            response = client.get("/companion/workspace/node-1")

        assert response.status_code == 200
        assert response.json() == {"node_id": "node-1", "files": ["chat/session.md", "notes.md"]}
