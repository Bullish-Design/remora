"""Event types for Companion agent system.

Events are the primary mechanism for external triggers (sensors).
Downstream agents typically subscribe to workspace paths instead.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CursorMoved:
    """Emitted when the user's cursor moves to a new position."""

    file: str
    line: int
    col: int
    lingered: bool = False  # True if cursor held at position > 3s


@dataclass(frozen=True)
class ContentEdited:
    """Emitted when file content is modified."""

    file: str
    start_line: int
    end_line: int
    text: str


@dataclass(frozen=True)
class FileChanged:
    """Emitted when a file changes on disk (external to editor)."""

    path: str
    kind: str  # "created" | "modified" | "deleted"


@dataclass(frozen=True)
class SessionTick:
    """Periodic tick for time-based triggers."""

    elapsed_ms: int
    tick_number: int


@dataclass(frozen=True)
class PathChanged:
    """Emitted when a workspace path value changes.

    Used for agent-to-agent communication via workspace subscriptions.
    """

    path: str
    value: Any
    previous: Any = field(default=None)
