"""Node State Hub data models.

These models define the structure of metadata stored by the Hub daemon
and read by the HubClient.

Key design:
- Inherit from VersionedKVRecord for automatic versioning
- Use Pydantic validation at all boundaries
- Keep models JSON-serializable for FSdantic storage
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fsdantic import VersionedKVRecord
from pydantic import Field, field_serializer


class NodeState(VersionedKVRecord):
    """State for a single code node.

    Inherits from VersionedKVRecord (fsdantic.models):
    - created_at: float (Unix timestamp, auto-set)
    - updated_at: float (Unix timestamp, auto-updated)
    - version: int (auto-incremented on save)

    Key format: "node:{file_path}:{node_name}"
    Stored with prefix "node:" in repository.
    """

    # === Identity ===
    key: str = Field(description="Unique key: 'node:{file_path}:{node_name}'")
    file_path: str = Field(description="Absolute path to the source file")
    node_name: str = Field(description="Name of the function, class, or module")
    node_type: Literal["function", "class", "module"] = Field(
        description="Type of code node"
    )

    # === Content Hashes (for change detection) ===
    source_hash: str = Field(description="SHA256 of the node's source code")
    file_hash: str = Field(description="SHA256 of the entire file")

    # === Static Analysis Results ===
    signature: str | None = Field(
        default=None,
        description="Function/class signature: 'def foo(x: int) -> str'",
    )
    docstring: str | None = Field(
        default=None,
        description="First line of docstring (truncated to 100 chars)",
    )
    imports: list[str] = Field(
        default_factory=list,
        description="Imports used by this node",
    )
    decorators: list[str] = Field(
        default_factory=list,
        description="Decorators: ['@staticmethod', '@cached']",
    )

    # === Cross-File Analysis (Computed Lazily) ===
    callers: list[str] | None = Field(
        default=None,
        description="Nodes that call this: ['bar.py:process']",
    )
    callees: list[str] | None = Field(
        default=None,
        description="Nodes this calls: ['os.path.join']",
    )

    # === Test Discovery ===
    related_tests: list[str] | None = Field(
        default=None,
        description="Test functions that exercise this node",
    )

    # === Quality Metrics ===
    line_count: int | None = Field(default=None, description="Lines of code")
    complexity: int | None = Field(default=None, description="Cyclomatic complexity")

    # === Flags ===
    docstring_outdated: bool = Field(
        default=False,
        description="True if signature changed but docstring didn't",
    )
    has_type_hints: bool = Field(
        default=True,
        description="True if function has type annotations",
    )

    # === Update Metadata ===
    update_source: Literal["file_change", "cold_start", "manual", "adhoc"] = Field(
        description="What triggered this update",
    )


class FileIndex(VersionedKVRecord):
    """Tracking entry for a source file.

    Used for efficient change detection during cold start
    and freshness checking.

    Key format: file_path (absolute)
    Stored with prefix "file:" in repository.
    """

    file_path: str = Field(description="Absolute path to the file")
    file_hash: str = Field(description="SHA256 of file contents")
    node_count: int = Field(description="Number of nodes in this file")
    last_scanned: datetime = Field(description="When this file was last indexed")

    @field_serializer("last_scanned")
    def _serialize_last_scanned(self, value: datetime) -> str:
        return value.isoformat()


class HubStatus(VersionedKVRecord):
    """Hub daemon status information.

    Stored as a singleton with key "status".
    """

    running: bool = Field(description="Whether daemon is currently running")
    pid: int | None = Field(default=None, description="Daemon process ID")
    project_root: str = Field(description="Project root being watched")
    indexed_files: int = Field(default=0, description="Number of files indexed")
    indexed_nodes: int = Field(default=0, description="Number of nodes indexed")
    started_at: datetime | None = Field(default=None, description="When daemon started")
    last_update: datetime | None = Field(default=None, description="Last index update")

    @field_serializer("started_at", "last_update")
    def _serialize_optional_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.isoformat()
