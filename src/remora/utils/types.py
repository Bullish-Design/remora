"""Common type definitions and utilities."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse

type PathLike = Path | str


def normalize_path(path: PathLike) -> Path:
    """Convert any path-like value to a Path object."""
    if isinstance(path, str):
        if path.startswith("file://"):
            parsed = urlparse(path)
            if parsed.scheme == "file":
                uri_path = unquote(parsed.path)
                if parsed.netloc and parsed.netloc not in {"", "localhost"}:
                    # Preserve UNC-style host paths for file://host/share semantics.
                    return Path(f"//{parsed.netloc}{uri_path}")
                return Path(uri_path)
        return Path(path)
    return path


__all__ = ["PathLike", "normalize_path"]
