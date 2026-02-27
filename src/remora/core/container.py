"""Dependency injection container for Remora services."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from remora.core.config import RemoraConfig, load_config
from remora.core.context import ContextBuilder
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore
from remora.utils import PathLike, normalize_path

if TYPE_CHECKING:
    from remora.core.cairn_bridge import CairnWorkspaceService
    from remora.core.executor import GraphExecutor


@dataclass
class RemoraContainer:
    """Central dependency container for Remora services."""

    config: RemoraConfig
    event_bus: EventBus
    context_builder: ContextBuilder
    project_root: Path
    event_store: EventStore | None = None

    _workspace_service: "CairnWorkspaceService | None" = field(default=None, repr=False)
    _executor: "GraphExecutor | None" = field(default=None, repr=False)

    @classmethod
    def create(
        cls,
        *,
        config: RemoraConfig | None = None,
        config_path: PathLike | None = None,
        project_root: PathLike | None = None,
        enable_event_store: bool = True,
        event_store_path: PathLike | None = None,
    ) -> "RemoraContainer":
        resolved_config = config or load_config(config_path)
        resolved_root = normalize_path(project_root or Path.cwd()).resolve()

        event_bus = EventBus()
        context_builder = ContextBuilder()
        event_bus.subscribe_all(context_builder.handle)

        store: EventStore | None = None
        if enable_event_store:
            store_path = normalize_path(
                event_store_path or (resolved_root / ".remora/events/events.db")
            )
            store = EventStore(store_path)

        return cls(
            config=resolved_config,
            event_bus=event_bus,
            context_builder=context_builder,
            project_root=resolved_root,
            event_store=store,
        )

    @classmethod
    def create_for_testing(
        cls,
        *,
        config: RemoraConfig | None = None,
        enable_event_store: bool = False,
    ) -> "RemoraContainer":
        store = EventStore(Path("/tmp/test/events.db")) if enable_event_store else None
        return cls(
            config=config or RemoraConfig(),
            event_bus=EventBus(),
            context_builder=ContextBuilder(),
            project_root=Path("/tmp/test"),
            event_store=store,
        )

    async def get_workspace_service(self, graph_id: str) -> "CairnWorkspaceService":
        if self._workspace_service is None:
            from remora.core.cairn_bridge import CairnWorkspaceService

            self._workspace_service = CairnWorkspaceService(
                config=self.config.workspace,
                graph_id=graph_id,
                project_root=self.project_root,
            )
            await self._workspace_service.initialize()

        return self._workspace_service

    def get_executor(self) -> "GraphExecutor":
        if self._executor is None:
            from remora.core.executor import GraphExecutor

            self._executor = GraphExecutor(
                event_bus=self.event_bus,
                config=self.config,
                context_builder=self.context_builder,
                project_root=self.project_root,
            )

        return self._executor

    async def close(self) -> None:
        if self._workspace_service:
            await self._workspace_service.close()
            self._workspace_service = None

        if self.event_store:
            await self.event_store.close()

        self.event_bus.clear()


@dataclass
class ScopedContainer:
    """A scoped container for a single graph execution."""

    parent: RemoraContainer
    graph_id: str
    workspace_service: "CairnWorkspaceService"

    @classmethod
    async def create(
        cls,
        parent: RemoraContainer,
        graph_id: str,
    ) -> "ScopedContainer":
        workspace_service = await parent.get_workspace_service(graph_id)
        return cls(
            parent=parent,
            graph_id=graph_id,
            workspace_service=workspace_service,
        )

    @property
    def config(self) -> RemoraConfig:
        return self.parent.config

    @property
    def event_bus(self) -> EventBus:
        return self.parent.event_bus

    @property
    def context_builder(self) -> ContextBuilder:
        return self.parent.context_builder


__all__ = ["RemoraContainer", "ScopedContainer"]
