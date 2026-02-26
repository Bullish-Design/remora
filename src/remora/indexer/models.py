"""Node State data models for the indexer."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Literal

from fsdantic import VersionedKVRecord
from pydantic import Field, field_serializer


class NodeState(VersionedKVRecord):
    """State for a single code node.

    Inherits from VersionedKVRecord:
    - created_at: float (auto-set)
    - updated_at: float (auto-updated)
    - version: int (auto-incremented)

    Key format: "node:{file_path}:{node_name}"
    """

    updated_at: float = Field(default_factory=time.time)
    key: str = Field(description="Unique key: 'node:{file_path}:{node_name}'")
    file_path: str = Field(description="Absolute path to source file")
    node_name: str = Field(description="Name of function, class, or module")
    node_type: Literal["function", "class", "module"] = Field(description="Type of code node")

    source_hash: str = Field(description="SHA256 of node source code")
    file_hash: str = Field(description="SHA256 of entire file")

    signature: str | None = Field(default=None)
    docstring: str | None = Field(default=None)
    imports: list[str] = Field(default_factory=list)
    decorators: list[str] = Field(default_factory=list)

    callers: list[str] | None = Field(default=None)
    callees: list[str] | None = Field(default=None)

    related_tests: list[str] | None = Field(default=None)

    line_count: int | None = Field(default=None)
    complexity: int | None = Field(default=None)

    docstring_outdated: bool = Field(default=False)
    has_type_hints: bool = Field(default=True)

    update_source: Literal["file_change", "cold_start", "manual", "adhoc"] = Field()


class FileIndex(VersionedKVRecord):
    """Tracking entry for a source file."""

    updated_at: float = Field(default_factory=time.time)
    file_path: str = Field(description="Absolute path")
    file_hash: str = Field(description="SHA256 of file contents")
    node_count: int = Field(description="Number of nodes in file")
    last_scanned: datetime = Field(description="When file was last indexed")

    @field_serializer("last_scanned")
    def _serialize_last_scanned(self, value: datetime) -> str:
        return value.isoformat()
