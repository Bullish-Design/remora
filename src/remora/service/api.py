"""Service layer entry point for Remora."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, AsyncIterator

from remora.core.config import RemoraConfig, load_config
from remora.core.event_bus import EventBus, get_event_bus
from remora.models import ConfigSnapshot, InputResponse, PlanRequest, PlanResponse, RunRequest, RunResponse
from remora.service.datastar import render_patch, render_shell
from remora.service.handlers import (
    ExecutorFactory,
    ServiceDeps,
    default_executor_factory,
    handle_config_snapshot,
    handle_input,
    handle_plan,
    handle_run,
    handle_ui_snapshot,
)
from remora.ui.projector import UiStateProjector, normalize_event
from remora.ui.view import render_dashboard


class RemoraService:
    """Framework-agnostic Remora service API."""

    def __init__(
        self,
        *,
        event_bus: EventBus | None = None,
        config: RemoraConfig | None = None,
        project_root: Path | str | None = None,
        projector: UiStateProjector | None = None,
        executor_factory: ExecutorFactory | None = None,
    ) -> None:
        self._event_bus = event_bus or get_event_bus()
        self._config = config or load_config()
        self._project_root = Path(project_root or Path.cwd()).resolve()
        self._projector = projector or UiStateProjector()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._event_bus.subscribe_all(self._projector.record)

        self._deps = ServiceDeps(
            event_bus=self._event_bus,
            config=self._config,
            project_root=self._project_root,
            projector=self._projector,
            executor_factory=executor_factory or default_executor_factory,
            running_tasks=self._running_tasks,
        )

    def index_html(self) -> str:
        state = self._projector.snapshot()
        return render_shell(render_dashboard(state))

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def subscribe_stream(self) -> AsyncIterator[str]:
        yield render_patch(self._projector.snapshot())
        async with self._event_bus.stream() as events:
            async for _event in events:
                yield render_patch(self._projector.snapshot())

    async def events_stream(self) -> AsyncIterator[str]:
        yield ": open\n\n"
        async with self._event_bus.stream() as events:
            async for event in events:
                envelope = normalize_event(event)
                data = json.dumps(envelope, default=str)
                event_name = envelope.get("type", "event")
                yield f"event: {event_name}\ndata: {data}\n\n"

    async def run(self, request: RunRequest) -> RunResponse:
        return await handle_run(request, self._deps)

    async def input(self, request_id: str, response: str) -> InputResponse:
        return await handle_input(request_id, response, self._deps)

    async def plan(self, request: PlanRequest) -> PlanResponse:
        return await handle_plan(request, self._deps)

    def config_snapshot(self) -> ConfigSnapshot:
        return handle_config_snapshot(self._deps)

    def ui_snapshot(self) -> dict[str, Any]:
        return handle_ui_snapshot(self._deps)


__all__ = ["RemoraService"]
