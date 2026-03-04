"""Tests for the service/ package — handlers, api, and datastar.

Covers handler functions, RemoraService lifecycle, the get_subscriptions
name collision bug (S1), and datastar rendering.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.config import Config
from remora.core.event_bus import EventBus
from remora.core.events import HumanInputResponseEvent
from remora.models import ConfigSnapshot, InputResponse
from remora.service.handlers import (
    ServiceDeps,
    _normalize_target,
    handle_config_snapshot,
    handle_input,
    handle_swarm_emit,
    handle_swarm_get_agent,
    handle_swarm_get_subscriptions,
    handle_swarm_list_agents,
    handle_ui_snapshot,
)
from remora.ui.projector import UiStateProjector


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def event_bus():
    return EventBus()


@pytest.fixture
def deps(event_bus, tmp_path):
    return ServiceDeps(
        event_bus=event_bus,
        config=Config(),
        project_root=tmp_path,
        projector=UiStateProjector(),
    )


# ── handle_input ───────────────────────────────────────────────────────────


class TestHandleInput:
    """Tests for handle_input handler."""

    @pytest.mark.asyncio
    async def test_emits_event_and_returns_response(self, deps):
        emitted = []
        deps.event_bus.subscribe(HumanInputResponseEvent, lambda e: emitted.append(e))

        result = await handle_input("req_1", "yes", deps)

        assert isinstance(result, InputResponse)
        assert result.request_id == "req_1"
        assert len(emitted) == 1
        assert emitted[0].request_id == "req_1"
        assert emitted[0].response == "yes"

    @pytest.mark.asyncio
    async def test_empty_request_id_raises(self, deps):
        with pytest.raises(ValueError, match="request_id and response are required"):
            await handle_input("", "yes", deps)

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, deps):
        with pytest.raises(ValueError, match="request_id and response are required"):
            await handle_input("req_1", "", deps)


# ── handle_config_snapshot ─────────────────────────────────────────────────


class TestHandleConfigSnapshot:
    """Tests for handle_config_snapshot handler."""

    def test_returns_config_snapshot(self, deps):
        result = handle_config_snapshot(deps)
        assert isinstance(result, ConfigSnapshot)
        assert "base_url" in result.model
        assert "default_model" in result.model

    def test_snapshot_reflects_config(self):
        config = Config(model_default="custom-model")
        deps = ServiceDeps(
            event_bus=EventBus(),
            config=config,
            project_root=Path("/tmp"),
            projector=UiStateProjector(),
        )
        result = handle_config_snapshot(deps)
        assert result.model["default_model"] == "custom-model"


# ── handle_ui_snapshot ─────────────────────────────────────────────────────


class TestHandleUiSnapshot:
    """Tests for handle_ui_snapshot handler."""

    def test_returns_dict(self, deps):
        result = handle_ui_snapshot(deps)
        assert isinstance(result, dict)

    def test_returns_projector_snapshot(self, deps):
        # Record something into projector to verify
        result = handle_ui_snapshot(deps)
        # UiStateProjector.snapshot() returns a dict with known keys
        assert isinstance(result, dict)


# ── handle_swarm_emit ──────────────────────────────────────────────────────


class TestHandleSwarmEmit:
    """Tests for handle_swarm_emit handler."""

    @pytest.mark.asyncio
    async def test_no_event_store_raises(self, deps):
        request = MagicMock(event_type="AgentMessageEvent", data={})
        with pytest.raises(ValueError, match="event store not configured"):
            await handle_swarm_emit(request, deps)

    @pytest.mark.asyncio
    async def test_unknown_event_type_raises(self, deps):
        mock_store = MagicMock()
        deps.event_store = mock_store

        request = MagicMock(event_type="UnknownEvent", data={})
        with pytest.raises(ValueError, match="Unknown event type"):
            await handle_swarm_emit(request, deps)

    @pytest.mark.asyncio
    async def test_agent_message_event(self, deps):
        mock_store = AsyncMock()
        mock_store.append = AsyncMock(return_value=42)
        deps.event_store = mock_store

        request = MagicMock(
            event_type="AgentMessageEvent",
            data={"from_agent": "a1", "to_agent": "a2", "content": "hello"},
        )
        result = await handle_swarm_emit(request, deps)

        assert result == {"event_id": 42}
        mock_store.append.assert_awaited_once()
        event_arg = mock_store.append.call_args[0][1]
        assert event_arg.from_agent == "a1"
        assert event_arg.to_agent == "a2"
        assert event_arg.content == "hello"

    @pytest.mark.asyncio
    async def test_content_changed_event(self, deps, tmp_path):
        # Create a file so path validation passes
        test_file = tmp_path / "test.py"
        test_file.write_text("content")

        mock_store = AsyncMock()
        mock_store.append = AsyncMock(return_value=99)
        deps.event_store = mock_store

        request = MagicMock(
            event_type="ContentChangedEvent",
            data={"path": str(test_file), "diff": "some diff"},
        )
        result = await handle_swarm_emit(request, deps)

        assert result == {"event_id": 99}


# ── handle_swarm_list_agents ───────────────────────────────────────────────


class TestHandleSwarmListAgents:
    """Tests for handle_swarm_list_agents handler."""

    @pytest.mark.asyncio
    async def test_no_event_store_raises(self, deps):
        with pytest.raises(ValueError, match="event store not configured"):
            await handle_swarm_list_agents(deps)

    @pytest.mark.asyncio
    async def test_returns_agent_list(self, deps):
        mock_store = AsyncMock()
        mock_store.list_nodes = AsyncMock(return_value=[])
        deps.event_store = mock_store

        result = await handle_swarm_list_agents(deps)
        assert result == []


# ── handle_swarm_get_agent ─────────────────────────────────────────────────


class TestHandleSwarmGetAgent:
    """Tests for handle_swarm_get_agent handler."""

    @pytest.mark.asyncio
    async def test_no_event_store_raises(self, deps):
        with pytest.raises(ValueError, match="event store not configured"):
            await handle_swarm_get_agent("agent_1", deps)

    @pytest.mark.asyncio
    async def test_agent_not_found_raises(self, deps):
        mock_store = AsyncMock()
        mock_store.get_node = AsyncMock(return_value=None)
        deps.event_store = mock_store

        with pytest.raises(ValueError, match="agent not found"):
            await handle_swarm_get_agent("nonexistent", deps)


# ── handle_swarm_get_subscriptions ─────────────────────────────────────────


class TestHandleSwarmGetSubscriptions:
    """Tests for handle_swarm_get_subscriptions handler."""

    @pytest.mark.asyncio
    async def test_no_subscriptions_raises(self, deps):
        with pytest.raises(ValueError, match="subscriptions not configured"):
            await handle_swarm_get_subscriptions("agent_1", deps)

    @pytest.mark.asyncio
    async def test_returns_subscription_list(self, deps):
        mock_sub = MagicMock()
        mock_sub.id = "sub_1"
        mock_sub.pattern.event_types = ["AgentMessageEvent"]
        mock_sub.pattern.from_agents = []
        mock_sub.pattern.to_agent = "agent_1"
        mock_sub.pattern.path_glob = None
        mock_sub.pattern.tags = []
        mock_sub.is_default = True

        mock_registry = AsyncMock()
        mock_registry.get_subscriptions = AsyncMock(return_value=[mock_sub])
        deps.subscriptions = mock_registry

        result = await handle_swarm_get_subscriptions("agent_1", deps)

        assert len(result) == 1
        assert result[0]["id"] == "sub_1"
        assert result[0]["is_default"] is True
        assert result[0]["pattern"]["to_agent"] == "agent_1"


# ── _normalize_target ──────────────────────────────────────────────────────


class TestNormalizeTarget:
    """Tests for _normalize_target path resolution."""

    def test_relative_path(self, tmp_path):
        target = tmp_path / "src"
        target.mkdir()
        result = _normalize_target("src", tmp_path)
        assert result == target.resolve()

    def test_absolute_path(self, tmp_path):
        target = tmp_path / "src"
        target.mkdir()
        result = _normalize_target(str(target), tmp_path)
        assert result == target.resolve()

    def test_outside_project_raises(self, tmp_path):
        with pytest.raises(ValueError, match="within the service project root"):
            _normalize_target("/etc/passwd", tmp_path)

    def test_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(ValueError, match="does not exist"):
            _normalize_target("nonexistent", tmp_path)


# ── RemoraService ──────────────────────────────────────────────────────────


class TestRemoraService:
    """Tests for the RemoraService class."""

    def test_init_stores_config(self):
        from remora.service.api import RemoraService

        config = Config()
        svc = RemoraService(
            config=config,
            project_root=Path("/tmp"),
            event_bus=EventBus(),
        )
        assert svc._config is config
        assert svc._project_root == Path("/tmp")

    def test_event_bus_property(self):
        from remora.service.api import RemoraService

        bus = EventBus()
        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=bus,
        )
        assert svc.event_bus is bus

    def test_has_event_store_false_by_default(self):
        from remora.service.api import RemoraService

        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
        )
        assert svc.has_event_store is False

    def test_has_event_store_true_when_provided(self):
        from remora.service.api import RemoraService

        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
            event_store=MagicMock(),
        )
        assert svc.has_event_store is True

    def test_get_subscriptions_name_collision_fixed(self):
        """Verify the S1 name collision is resolved.

        The old get_subscriptions() no-arg getter is now the
        ``subscription_registry`` property, and the async per-agent
        lookup is ``get_agent_subscriptions(agent_id)``.
        """
        from remora.service.api import RemoraService

        mock_registry = MagicMock()
        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
            subscriptions=mock_registry,
        )

        # No-arg registry access is now a property — no TypeError.
        assert svc.subscription_registry is mock_registry
        # The async per-agent method exists under its new name.
        assert hasattr(svc, "get_agent_subscriptions")

    def test_config_snapshot(self):
        from remora.service.api import RemoraService

        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
        )
        result = svc.config_snapshot()
        assert isinstance(result, ConfigSnapshot)

    def test_ui_snapshot(self):
        from remora.service.api import RemoraService

        svc = RemoraService(
            config=Config(),
            project_root=Path("/tmp"),
            event_bus=EventBus(),
        )
        result = svc.ui_snapshot()
        assert isinstance(result, dict)


# ── datastar ───────────────────────────────────────────────────────────────


class TestDatastar:
    """Tests for datastar rendering helpers."""

    def test_render_shell_returns_html(self):
        from remora.service.datastar import render_shell

        html = render_shell("<p>test</p>")
        assert "<!DOCTYPE html>" in html
        assert "<p>test</p>" in html
        assert "Remora" in html

    def test_render_shell_custom_title(self):
        from remora.service.datastar import render_shell

        html = render_shell(title="Custom Title")
        assert "Custom Title" in html

    def test_render_shell_custom_init_path(self):
        from remora.service.datastar import render_shell

        html = render_shell(init_path="/custom")
        assert "/custom" in html

    def test_render_patch_returns_string(self):
        from remora.service.datastar import render_patch

        result = render_patch({})
        assert isinstance(result, str)

    def test_render_signals_returns_string(self):
        from remora.service.datastar import render_signals

        result = render_signals({"key": "value"})
        assert isinstance(result, str)
