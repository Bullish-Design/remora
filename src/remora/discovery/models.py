"""Core data models for the tree-sitter discovery pipeline."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class NodeType(str, Enum):
    """Type of discovered code node."""

    FILE = "file"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"


class DiscoveryError(RuntimeError):
    """Base exception for discovery errors."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def compute_node_id(file_path: Path, node_type: NodeType, name: str) -> str:
    """Compute a stable node ID.

    Hash: sha256(resolved_file_path:node_type_value:name), truncated to 16 hex chars.
    Stable across reformatting because it does NOT include byte offsets.
    """
    digest_input = f"{file_path.resolve()}:{node_type.value}:{name}".encode("utf-8")
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
