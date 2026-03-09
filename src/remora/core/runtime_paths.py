"""Derived runtime paths shared across Remora entrypoints."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from remora.core.config import Config
from remora.utils import PathLike, normalize_path


@dataclass(frozen=True)
class RuntimePaths:
    """Resolved filesystem layout for one Remora project runtime."""

    project_root: Path
    swarm_root: Path
    events_root: Path
    event_store_path: Path
    subscriptions_path: Path
    models_root: Path
    bootstrap_root: Path

    @classmethod
    def from_config(
        cls,
        config: Config,
        *,
        project_root: PathLike | None = None,
        bootstrap_root: PathLike | None = None,
    ) -> RuntimePaths:
        root = normalize_path(project_root or config.project_path).resolve()

        swarm_root = normalize_path(config.swarm_root)
        if not swarm_root.is_absolute():
            swarm_root = (root / swarm_root).resolve()
        events_root = swarm_root / "events"

        resolved_bootstrap = normalize_path(bootstrap_root or (root / "bootstrap"))
        if not resolved_bootstrap.is_absolute():
            resolved_bootstrap = (root / resolved_bootstrap).resolve()

        return cls(
            project_root=root,
            swarm_root=swarm_root,
            events_root=events_root,
            event_store_path=events_root / "events.db",
            subscriptions_path=swarm_root / "subscriptions.db",
            models_root=swarm_root / "models",
            bootstrap_root=resolved_bootstrap,
        )


__all__ = ["RuntimePaths"]
