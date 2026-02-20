"""Two-Track Memory models for Remora.

This module defines the Short Track data structures that provide
clean, distilled context to FunctionGemma.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class RecentAction(BaseModel):
    """A single action in the agent's recent history.

    This is a distilled summary of a tool call, not the raw result.
    The rolling window typically keeps the last 10 actions.
    """

    turn: int
    """Which turn this action occurred on."""

    tool: str
    """Name of the tool that was called."""

    summary: str
    """Human-readable summary of what happened (1-2 sentences max)."""

    outcome: Literal["success", "error", "partial"]
    """Overall outcome of the action."""


class KnowledgeEntry(BaseModel):
    """A piece of working knowledge learned during the session.

    Knowledge entries are key-value pairs that persist across turns
    and help the model maintain state without re-reading tool outputs.
    """

    key: str
    """Unique identifier for this knowledge (e.g., 'lint_errors_remaining')."""

    value: Any
    """The knowledge value (structured data, not raw text)."""

    source_turn: int
    """Turn number when this knowledge was acquired."""

    supersedes: str | None = None
    """If set, this entry replaces a previous entry with this key."""


class DecisionPacket(BaseModel):
    """The Short Track - what the model sees.

    This is a projection of the Long Track (event stream), optimized
    for FunctionGemma's context requirements. It provides clean,
    structured state rather than raw tool outputs.

    Key design principles:
    - Keep it small (target: <2K tokens when serialized)
    - Structure over prose (JSON-friendly fields)
    - Recent over complete (rolling window, not full history)
    """

    # === Identity ===
    agent_id: str
    """Unique identifier for this agent run."""

    turn: int = 0
    """Current turn number (0-indexed)."""

    # === Goal Context ===
    goal: str
    """High-level goal (e.g., 'Fix lint errors in foo.py')."""

    operation: str
    """Operation type (e.g., 'lint', 'test', 'docstring')."""

    node_id: str
    """Target node identifier."""

    node_summary: str = ""
    """Brief description of the target code."""

    # === Recent Actions (Rolling Window) ===
    recent_actions: list[RecentAction] = Field(default_factory=list)
    """Last N actions (typically 10). Oldest actions are dropped."""

    # === Working Knowledge ===
    knowledge: dict[str, KnowledgeEntry] = Field(default_factory=dict)
    """Key-value pairs of learned information."""

    # === Error State ===
    last_error: str | None = None
    """Most recent error summary (if any)."""

    error_count: int = 0
    """Total errors encountered this session."""

    # === Hub Context (Injected via Pull Hook) ===
    hub_context: dict[str, Any] | None = None
    """External context from Node State Hub (Phase 2)."""

    hub_freshness: datetime | None = None
    """When hub_context was last updated."""

    # === Metadata ===
    packet_version: str = "1.0"
    """Schema version for forward compatibility."""

    def add_action(
        self,
        tool: str,
        summary: str,
        outcome: Literal["success", "error", "partial"],
        max_actions: int = 10,
    ) -> None:
        """Add an action to recent history, maintaining rolling window."""
        action = RecentAction(
            turn=self.turn,
            tool=tool,
            summary=summary,
            outcome=outcome,
        )
        self.recent_actions.append(action)
        while len(self.recent_actions) > max_actions:
            self.recent_actions.pop(0)

    def update_knowledge(self, key: str, value: Any) -> None:
        """Update or add a knowledge entry."""
        self.knowledge[key] = KnowledgeEntry(
            key=key,
            value=value,
            source_turn=self.turn,
        )

    def record_error(self, error_summary: str) -> None:
        """Record an error occurrence."""
        self.last_error = error_summary
        self.error_count += 1

    def clear_error(self) -> None:
        """Clear the last error (but keep count)."""
        self.last_error = None
