"""Frontend module.

This module provides state management for the dashboard.
The actual views are provided by hub/views.py using datastar-py.
Routes for the Hub are in hub/server.py using Starlette.
"""

from remora.event_bus import Event, EventBus, get_event_bus
from remora.interactive import WorkspaceInboxCoordinator

from remora.frontend.registry import WorkspaceInfo, WorkspaceRegistry, workspace_registry
from remora.frontend.state import DashboardState, EventAggregator, dashboard_state

__all__ = [
    "Event",
    "EventBus",
    "get_event_bus",
    "WorkspaceInboxCoordinator",
    "WorkspaceInfo",
    "WorkspaceRegistry",
    "workspace_registry",
    "DashboardState",
    "EventAggregator",
    "dashboard_state",
]
