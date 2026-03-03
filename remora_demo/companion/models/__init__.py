"""Companion data models: workspace schema, events, and indexing types."""

from remora_demo.companion.models.events import (
    ContentEdited,
    CursorMoved,
    FileChanged,
    PathChanged,
    SessionTick,
)
from remora_demo.companion.models.workspace import (
    Connection,
    CursorPosition,
    Definition,
    EditSummary,
    NavEvent,
    Question,
    SimilarResult,
    Structure,
    TaskInference,
    Term,
    UnsupportedClaim,
    VaultLink,
)

__all__ = [
    # Events
    "CursorMoved",
    "ContentEdited",
    "FileChanged",
    "SessionTick",
    "PathChanged",
    # Workspace schema
    "CursorPosition",
    "Term",
    "Structure",
    "EditSummary",
    "NavEvent",
    "SimilarResult",
    "Definition",
    "VaultLink",
    "Connection",
    "Question",
    "TaskInference",
    "UnsupportedClaim",
]
