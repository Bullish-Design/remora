"""Remora error hierarchy.

All Remora-specific errors inherit from RemoraError.
"""

from __future__ import annotations


class RemoraError(Exception):
    """Base class for all Remora errors."""

    pass


class ConfigError(RemoraError):
    """Configuration loading or validation error."""

    pass


class DiscoveryError(RemoraError):
    """Error during code discovery."""

    pass


class GraphError(RemoraError):
    """Error in graph construction or validation."""

    pass


class ExecutionError(RemoraError):
    """Error during agent execution."""

    pass


class CheckpointError(RemoraError):
    """Error during checkpoint save or restore."""

    pass


class WorkspaceError(RemoraError):
    """Error in workspace operations."""

    pass


__all__ = [
    "RemoraError",
    "ConfigError",
    "DiscoveryError",
    "GraphError",
    "ExecutionError",
    "CheckpointError",
    "WorkspaceError",
]
