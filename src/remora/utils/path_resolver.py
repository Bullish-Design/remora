from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PathResolver:
    """Normalize paths for workspace-backed operations."""

    project_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_root", self.project_root.resolve())

    def to_workspace_path(self, path: str | Path) -> str:
        """Convert a path to a workspace-relative POSIX path."""
        path_obj = Path(path)
        if path_obj.is_absolute():
            try:
                rel = path_obj.resolve().relative_to(self.project_root)
            except ValueError:
                logger.warning(
                    "Path is outside project root; using absolute path in workspace lookup",
                    extra={"path": str(path_obj), "project_root": str(self.project_root)},
                )
                return path_obj.as_posix().lstrip("/")
            return rel.as_posix()
        return path_obj.as_posix().lstrip("/")

    def to_project_path(self, path: str | Path) -> Path:
        """Convert a workspace-relative path to an absolute project path."""
        path_obj = Path(path)
        if path_obj.is_absolute():
            return path_obj
        return (self.project_root / path_obj).resolve()

    def is_within_project(self, path: str | Path) -> bool:
        """Check whether a path is inside the project root."""
        path_obj = Path(path)
        if not path_obj.is_absolute():
            return True
        try:
            path_obj.resolve().relative_to(self.project_root)
        except ValueError:
            return False
        return True
