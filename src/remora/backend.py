"""Helpers for guarding backend-specific dependencies."""

from __future__ import annotations

from types import ModuleType


class BackendDependencyMissing(RuntimeError):
    """Raised when backend extras are missing."""


def require_backend_extra() -> ModuleType:
    """Import ``structured_agents`` and raise a friendly error if unavailable."""
    try:
        import structured_agents

        return structured_agents
    except (ImportError, RuntimeError) as exc:  # pragma: no cover - optional dependency
        raise BackendDependencyMissing(
            "Grail validation skipped: install `remora[backend]` to enable structured-agents features."
        ) from exc
