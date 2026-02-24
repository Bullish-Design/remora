"""Frontend helpers for dashboard + event streaming."""

from remora.event_bus import Event, EventBus, get_event_bus
from remora.interactive import WorkspaceInboxCoordinator

from remora.frontend.registry import WorkspaceInfo, WorkspaceRegistry, workspace_registry
from remora.frontend.routes import RespondSignals, get_coordinator, register_routes
from remora.frontend.state import DashboardState, EventAggregator, dashboard_state
from remora.frontend.views import dashboard_view

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
    "dashboard_view",
    "register_routes",
    "get_coordinator",
    "RespondSignals",
]
