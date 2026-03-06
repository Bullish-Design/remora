"""Runtime settings for indexing and writeback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IndexerSettings:
    """Configuration for indexer execution."""

    repo_root: Path
    db_path: Path
    enable_writeback: bool = False
    include_globs: tuple[str, ...] = ("**/*.py", "**/*.md")
