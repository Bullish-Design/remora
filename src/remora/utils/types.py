"""Common type definitions and utilities."""

from __future__ import annotations

from pathlib import Path
from typing import TypeAlias

PathLike: TypeAlias = Path | str


def normalize_path(path: PathLike) -> Path:
    """Convert any path-like value to a Path object."""
    return Path(path) if isinstance(path, str) else path


__all__ = ["PathLike", "normalize_path"]
