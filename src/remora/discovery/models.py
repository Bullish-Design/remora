"""Core data models for the tree-sitter discovery pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from remora.errors import DiscoveryError as BaseDiscoveryError

# NodeType is now a simple string - any value is valid.
# The type is determined by the capture prefix in .scm files (e.g., @class.def → "class")
NodeType = str


class DiscoveryError(BaseDiscoveryError):
    pass


def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Compute a stable node ID.

    Hash: sha256(resolved_file_path:node_type:name), truncated to 16 hex chars.
    Stable across reformatting because it does NOT include byte offsets.
    """
    digest_input = f"{file_path.resolve()}:{node_type}:{name}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()[:16]


@dataclass(frozen=True)
class CSTNode:
    """A discovered code node (file, class, function, or method).

    This is a frozen dataclass — instances are immutable after creation.
    The `full_name` property returns a qualified name like 'ClassName.method_name'.
    """

    node_id: str
    node_type: NodeType
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
    start_line: int
    end_line: int
    _full_name: str = ""  # Set via __post_init__ or factory; hidden from repr

    def __post_init__(self) -> None:
        if not self._full_name:
            object.__setattr__(self, "_full_name", self.name)

    @property
    def full_name(self) -> str:
        """Qualified name including parent class, e.g. 'Greeter.greet'."""
        return self._full_name
