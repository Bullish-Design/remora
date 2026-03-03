"""Workspace schema types for Companion.

These types define the structure of data stored in Cairn workspace paths.
All agents read/write these types to shared workspace state.
"""

from dataclasses import dataclass, field


@dataclass
class CursorPosition:
    """Current cursor position in editor."""

    line: int
    col: int


@dataclass
class Term:
    """A key term extracted from content that may need definition or search."""

    term: str
    needs_definition: bool
    context: str  # Surrounding sentence/line for context


@dataclass
class Structure:
    """Parsed document structure at cursor position.

    For code: function/class/module hierarchy.
    For markdown: heading hierarchy.
    """

    structure_type: str  # "function" | "class" | "module" | "section" | "heading"
    name: str
    parent: str | None = None
    depth: int = 0


@dataclass
class EditSummary:
    """Summary of a content edit for task inference."""

    file: str
    start_line: int
    end_line: int
    summary: str  # Brief description of what changed
    timestamp: float


@dataclass
class NavEvent:
    """Navigation event for tracking cursor history."""

    file: str
    line: int
    timestamp: float
    duration_ms: int  # How long cursor stayed at this position


@dataclass
class SimilarResult:
    """Result from embedding similarity search."""

    file: str
    snippet: str
    score: float  # Similarity score 0-1
    content_type: str  # "code" | "markdown"
    start_line: int = 0
    end_line: int = 0


@dataclass
class Definition:
    """Definition of a term, from vault or external source."""

    term: str
    definition: str
    source: str  # "vault" | "codebase" | "external" | "inferred"
    source_path: str | None = None  # Path to source file/note


@dataclass
class VaultLink:
    """Link to related note in Obsidian vault."""

    note: str  # Wikilink-style name (e.g., "CQRS Notes")
    path: str  # Actual file path
    relevance: float  # Relevance score 0-1
    excerpt: str  # Relevant excerpt from the note


@dataclass
class Connection:
    """A discovered connection between current context and other content."""

    from_file: str
    to_file: str
    insight: str  # Human-readable description of the connection
    connection_type: str  # "implements" | "tests" | "references" | "similar"


@dataclass
class Question:
    """A question worth considering based on current context."""

    question: str
    priority: str  # "high" | "medium" | "low"
    context: str  # Why this question is relevant


@dataclass
class TaskInference:
    """Inferred task based on user behavior patterns."""

    description: str
    confidence: float  # 0-1
    evidence: list[str] = field(default_factory=list)


@dataclass
class UnsupportedClaim:
    """A claim in prose that lacks supporting sources."""

    claim: str
    location: str  # File and line reference
    suggestions: list[str] = field(default_factory=list)  # Suggested sources
