"""Service layer entry point for Remora."""

from __future__ import annotations

from collections.abc import AsyncIterator
import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.config import Config, load_config
from remora.core.events.event_bus import EventBus
from remora.core.store.event_store import EventStore
from remora.models import ConfigSnapshot, InputResponse
from remora.service.handlers import (
    ServiceDeps,
    build_default_runtime,
    handle_config_snapshot,
    handle_input,
    handle_swarm_emit,
    handle_swarm_get_agent,
    handle_swarm_get_subscriptions,
    handle_swarm_list_agents,
    handle_ui_snapshot,
    render_event_sse,
    render_index_html,
    render_state_patch,
    resolve_bundle_default,
)
from remora.ui.projector import UiStateProjector
from remora.utils import PathLike

if TYPE_CHECKING:
    from remora.companion.registry import NodeAgentRegistry
    from remora.core.agents.cairn_bridge import CairnWorkspaceService
    from remora.core.events.subscriptions import SubscriptionRegistry


def _resolve_project_root(project_root: PathLike | None) -> Path:
    if project_root is None:
        return Path.cwd().resolve()
    return Path(project_root).expanduser().resolve()


class RemoraService:
    """Framework-agnostic Remora service API."""

    @classmethod
    def create_default(
        cls,
        *,
        config: Config | None = None,
        config_path: PathLike | None = None,
        project_root: PathLike | None = None,
        enable_event_store: bool = True,
        enable_companion: bool = False,
        companion_auto_index: bool = False,
    ) -> RemoraService:
        resolved_config = config or load_config(config_path)
        resolved_root = _resolve_project_root(project_root)
        event_bus = EventBus()
        event_store, subscriptions, workspace_service = build_default_runtime(
            config=resolved_config,
            project_root=resolved_root,
            event_bus=event_bus,
            enable_event_store=enable_event_store,
        )

        return cls(
            config=resolved_config,
            project_root=resolved_root,
            event_bus=event_bus,
            event_store=event_store,
            subscriptions=subscriptions,
            workspace_service=workspace_service,
            enable_companion=enable_companion,
            companion_auto_index=companion_auto_index,
        )

    def __init__(
        self,
        *,
        config: Config,
        project_root: Path,
        event_bus: EventBus,
        event_store: EventStore | None = None,
        projector: UiStateProjector | None = None,
        subscriptions: SubscriptionRegistry | None = None,
        workspace_service: CairnWorkspaceService | None = None,
        companion_registry: NodeAgentRegistry | None = None,
        enable_companion: bool = False,
        companion_auto_index: bool = False,
    ) -> None:
        self._config = config
        self._project_root = project_root
        self._event_bus = event_bus
        self._event_store = event_store
        self._projector = projector or UiStateProjector()
        self._subscriptions = subscriptions
        self._workspace_service = workspace_service
        self._companion_registry = companion_registry
        self._enable_companion = enable_companion
        self._companion_auto_index = companion_auto_index
        self._bundle_default = resolve_bundle_default(self._config)
        self._event_bus.subscribe_all(self._projector.record)

        self._deps = ServiceDeps(
            event_bus=self._event_bus,
            config=self._config,
            project_root=self._project_root,
            projector=self._projector,
            event_store=self._event_store,
            subscriptions=self._subscriptions,
            workspace_service=self._workspace_service,
        )

    def index_html(self) -> str:
        return render_index_html(self._projector, self._bundle_default)

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def subscribe_stream(self) -> AsyncIterator[str]:
        yield render_state_patch(self._projector, self._bundle_default)
        async with self._event_bus.stream() as events:
            async for _event in events:
                yield render_state_patch(self._projector, self._bundle_default)

    async def events_stream(self) -> AsyncIterator[str]:
        yield ": open\n\n"
        async with self._event_bus.stream() as events:
            async for event in events:
                yield render_event_sse(event)

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

    @property
    def subscription_registry(self) -> SubscriptionRegistry | None:
        """Return the raw SubscriptionRegistry instance."""
        return self._subscriptions

    @property
    def companion_registry(self) -> NodeAgentRegistry | None:
        """Return the optional NodeAgentRegistry instance."""
        return self._companion_registry

    def set_companion_registry(self, registry: NodeAgentRegistry) -> None:
        """Wire in the companion registry after construction."""
        self._companion_registry = registry

    def get_workspace_service(self) -> CairnWorkspaceService | None:
        return self._workspace_service

    async def emit_event(self, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
        """Emit an event to the swarm."""
        request = type("EventRequest", (), {"event_type": event_type, "data": data})()
        return await handle_swarm_emit(request, self._deps)

    async def list_agents(self) -> list[dict[str, Any]]:
        """List all agents in the swarm."""
        return await handle_swarm_list_agents(self._deps)

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        """Get a specific agent."""
        return await handle_swarm_get_agent(agent_id, self._deps)

    async def get_agent_subscriptions(self, agent_id: str) -> list[dict[str, Any]]:
        """Get subscriptions for an agent."""
        return await handle_swarm_get_subscriptions(agent_id, self._deps)

    async def _call_optional_lifecycle(self, target: Any, method_name: str) -> None:
        """Invoke a lifecycle method when present, awaiting async results."""
        if target is None:
            return
        method = getattr(target, method_name, None)
        if not callable(method):
            return
        result = method()
        if inspect.isawaitable(result):
            await result

    async def initialize_runtime(self) -> None:
        """Initialize runtime dependencies required by HTTP handlers."""
        await self._call_optional_lifecycle(self._event_store, "initialize")
        await self._call_optional_lifecycle(self._subscriptions, "initialize")
        if self._enable_companion and self._companion_registry is None:
            if self._event_store is None:
                raise RuntimeError("companion startup requires event_store")
            if self._workspace_service is None:
                raise RuntimeError("companion startup requires workspace_service")

            from remora.companion.config import CompanionConfig
            from remora.companion.startup import start_companion
            from remora.core.agents.cairn_bridge import SyncMode

            # Companion does not require a full workspace ingest at HTTP startup.
            await self._workspace_service.initialize(sync_mode=SyncMode.NONE)
            companion_config = CompanionConfig(
                workspace_path=self._project_root,
                auto_index=self._companion_auto_index,
                model_name=self._config.model_default,
                model_base_url=self._config.model_base_url,
                model_api_key=self._config.model_api_key,
            )
            registry = await start_companion(
                event_store=self._event_store,
                event_bus=self._event_bus,
                cairn_service=self._workspace_service,
                config=companion_config,
            )
            self.set_companion_registry(registry)

    async def close_runtime(self) -> None:
        """Close runtime dependencies owned by the service."""
        await self._call_optional_lifecycle(self._workspace_service, "close")
        await self._call_optional_lifecycle(self._event_store, "close")
        await self._call_optional_lifecycle(self._subscriptions, "close")

__all__ = ["RemoraService"]
