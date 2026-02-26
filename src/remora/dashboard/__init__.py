"""Remora Dashboard Package.

Provides the web dashboard for monitoring agent execution and triggering graphs.
"""

from remora.dashboard.app import create_app
from remora.dashboard.state import DashboardState

__all__ = ["create_app", "DashboardState"]
