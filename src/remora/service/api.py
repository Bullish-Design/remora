"""Service layer entry point for Remora."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, TYPE_CHECKING

from remora.core.config import RemoraConfig, load_config
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import SwarmState
from remora.models import ConfigSnapshot, InputResponse
from remora.service.datastar import render_patch, render_shell
from remora.service.handlers import (
    ServiceDeps,
    handle_config_snapshot,
    handle_input,
    handle_swarm_emit,
    handle_swarm_get_agent,
    handle_swarm_get_subscriptions,
    handle_swarm_list_agents,
    handle_ui_snapshot,
)
from remora.ui.projector import UiStateProjector, normalize_event
from remora.utils import PathLike, normalize_path
from remora.ui.view import render_dashboard


class RemoraService:
    """Framework-agnostic Remora service API."""

    @classmethod
    def create_default(
        cls,
        *,
        config: RemoraConfig | None = None,
        config_path: PathLike | None = None,
        project_root: PathLike | None = None,
        enable_event_store: bool = True,
    ) -> "RemoraService":
        resolved_config = config or load_config(config_path)
        resolved_root = normalize_path(project_root or Path.cwd()).resolve()
        event_bus = EventBus()
        event_store: EventStore | None = None
        swarm_state: SwarmState | None = None
        subscriptions: SubscriptionRegistry | None = None

        swarm_root = resolved_root / ".remora"

        if enable_event_store:
            store_path = swarm_root / "events" / "events.db"
            event_store = EventStore(store_path)

        subscriptions_path = swarm_root / "subscriptions.db"
        swarm_state_path = swarm_root / "swarm_state.db"

        subscriptions = SubscriptionRegistry(subscriptions_path)
        swarm_state = SwarmState(swarm_state_path)

        return cls(
            config=resolved_config,
            project_root=resolved_root,
            event_bus=event_bus,
            event_store=event_store,
            swarm_state=swarm_state,
            subscriptions=subscriptions,
        )

    def __init__(
        self,
        *,
        config: RemoraConfig,
        project_root: Path,
        event_bus: EventBus,
        event_store: EventStore | None = None,
        projector: UiStateProjector | None = None,
        swarm_state: SwarmState | None = None,
        subscriptions: SubscriptionRegistry | None = None,
    ) -> None:
        self._config = config
        self._project_root = project_root
        self._event_bus = event_bus
        self._event_store = event_store
        self._projector = projector or UiStateProjector()
        self._swarm_state = swarm_state
        self._subscriptions = subscriptions
        self._bundle_default = _resolve_bundle_default(self._config)
        self._event_bus.subscribe_all(self._projector.record)

        self._deps = ServiceDeps(
            event_bus=self._event_bus,
            config=self._config,
            project_root=self._project_root,
            projector=self._projector,
            event_store=self._event_store,
            swarm_state=self._swarm_state,
            subscriptions=self._subscriptions,
        )

    def index_html(self) -> str:
        state = self._projector.snapshot()
        return render_shell(render_dashboard(state, bundle_default=self._bundle_default))

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def subscribe_stream(self) -> AsyncIterator[str]:
        yield render_patch(self._projector.snapshot(), bundle_default=self._bundle_default)
        async with self._event_bus.stream() as events:
            async for _event in events:
                yield render_patch(self._projector.snapshot(), bundle_default=self._bundle_default)

    async def events_stream(self) -> AsyncIterator[str]:
        yield ": open\n\n"
        async with self._event_bus.stream() as events:
            async for event in events:
                envelope = normalize_event(event)
                data = json.dumps(envelope, default=str)
                event_name = envelope.get("type", "event")
                yield f"event: {event_name}\ndata: {data}\n\n"

    async def replay_events(
        self,
        graph_id: str,
        *,
        event_types: list[str] | None = None,
        after_id: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._event_store is None:
            raise ValueError("event store is not configured")
        async for record in self._event_store.replay(
            graph_id,
            event_types=event_types,
            after_id=after_id,
        ):
            yield record

    async def input(self, request_id: str, response: str) -> InputResponse:
        return await handle_input(request_id, response, self._deps)

    def config_snapshot(self) -> ConfigSnapshot:
        return handle_config_snapshot(self._deps)

    def ui_snapshot(self) -> dict[str, Any]:
        return handle_ui_snapshot(self._deps)

    @property
    def has_event_store(self) -> bool:
        return self._event_store is not None

    def get_swarm_state(self) -> SwarmState | None:
        return self._swarm_state

    def get_subscriptions(self) -> SubscriptionRegistry | None:
        return self._subscriptions

    async def emit_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Emit an event to the swarm."""
        request = type("EventRequest", (), {"event_type": event_type, "data": data})()
        return await handle_swarm_emit(request, self._deps)

    def list_agents(self) -> list[dict[str, Any]]:
        """List all agents in the swarm."""
        return handle_swarm_list_agents(self._deps)

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get a specific agent."""
        return handle_swarm_get_agent(agent_id, self._deps)

    async def get_subscriptions(self, agent_id: str) -> list[dict[str, Any]]:
        """Get subscriptions for an agent."""
        return await handle_swarm_get_subscriptions(agent_id, self._deps)


def _resolve_bundle_default(config: RemoraConfig) -> str:
    snapshot = ConfigSnapshot.from_config(config)
    mapping = snapshot.bundles.get("mapping", {})
    if isinstance(mapping, dict) and mapping:
        return next(iter(mapping))
    return ""


__all__ = ["RemoraService"]
