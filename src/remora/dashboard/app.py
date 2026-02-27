"""Dashboard Starlette application.

Provides SSE-powered web UI for monitoring graph execution."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from starlette.applications import Starlette

from remora.config import RemoraConfig, load_config
from remora.context import ContextBuilder
from remora.dashboard.state import DashboardState
from remora.dashboard.views import create_routes
from remora.event_bus import EventBus, get_event_bus

logger = logging.getLogger(__name__)


class DashboardApp:
    """Dashboard application wrapper."""

    def __init__(
        self,
        event_bus: EventBus,
        config: RemoraConfig | None = None,
        project_root: Path | None = None,
    ):
        self._event_bus = event_bus
        self._config = config
        self._context_builder = ContextBuilder()
        self._dashboard_state = DashboardState()
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._project_root = project_root or Path.cwd()
        self._app: Starlette | None = None

    async def initialize(self) -> None:
        """Async initialization (fixes MAJ-04)."""
        if self._config is None:
            self._config = await asyncio.to_thread(load_config)

        # Keep dashboard state in sync with events
        self._event_bus.subscribe_all(self._dashboard_state.record)

        routes = create_routes(
            self._event_bus,
            self._config,
            self._dashboard_state,
            self._context_builder,
            self._running_tasks,
            project_root=self._project_root,
        )
        self._app = Starlette(routes=routes)

    @property
    def app(self) -> Starlette:
        """Get the Starlette app (must call initialize() first)."""
        if self._app is None:
            raise RuntimeError("Call initialize() before accessing app")
        return self._app


async def create_app(
    event_bus: EventBus | None = None,
    config: RemoraConfig | None = None,
    project_root: Path | None = None,
) -> Starlette:
    """Factory function to create dashboard app.

    Usage with uvicorn:
        app = asyncio.run(create_app())
        uvicorn.run(app, ...)
    """
    if event_bus is None:
        event_bus = get_event_bus()

    dashboard = DashboardApp(event_bus, config, project_root=project_root)
    await dashboard.initialize()
    return dashboard.app
