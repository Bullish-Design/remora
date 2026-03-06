"""Core models for extracted entities and persistence records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EntityKind = Literal["class", "function", "method", "md_section", "md_heading"]


@dataclass(frozen=True)
class ExtractedEntity:
    """Extracted declaration/section from a syntax tree."""

    kind: EntityKind
    language: str
    name: str
    semantic_key: str
    start_byte: int
    end_byte: int
    start_row: int
    start_col: int
    header_line: str
    graph_id: str | None


@dataclass(frozen=True)
class FileSnapshot:
    """File metadata tracked by the index."""

    rel_path: str
    language: str
    content_hash: bytes
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class ChangedRange:
    """Byte range where tree structure changed."""

    start_byte: int
    end_byte: int
