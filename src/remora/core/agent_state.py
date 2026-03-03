"""Agent state models for Remora.

Defines typed state models for agent persistence using Cairn's
AgentStateManager.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class AgentTurnState(BaseModel):
    """State persisted between agent turns.

    Tracks turn-by-turn execution state for an agent.
    """

    turn_number: int = 0
    last_response: str | None = None
    last_tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    accumulated_context: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def model_post_init(self, __context: Any) -> None:
        """Update timestamp on any modification."""
        pass

    def record_turn(
        self,
        response: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
    ) -> "AgentTurnState":
        """Record a new turn with optional response and tool calls.

        Returns a new state instance with updated values.
        """
        return AgentTurnState(
            turn_number=self.turn_number + 1,
            last_response=response,
            last_tool_calls=tool_calls or [],
            accumulated_context=self.accumulated_context,
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
        )


class AgentMemory(BaseModel):
    """Long-term agent memory stored in KV.

    Stores learned information that persists across sessions.
    """

    facts: list[str] = Field(default_factory=list)
    learned_patterns: dict[str, str] = Field(default_factory=dict)
    file_summaries: dict[str, str] = Field(default_factory=dict)

    def add_fact(self, fact: str) -> None:
        """Add a fact to memory (in place)."""
        if fact not in self.facts:
            self.facts.append(fact)

    def add_pattern(self, name: str, pattern: str) -> None:
        """Add or update a learned pattern."""
        self.learned_patterns[name] = pattern

    def add_file_summary(self, path: str, summary: str) -> None:
        """Add or update a file summary."""
        self.file_summaries[path] = summary


class AgentExecutionMetrics(BaseModel):
    """Metrics tracked during agent execution.

    Useful for monitoring and debugging agent behavior.
    """

    total_turns: int = 0
    total_tokens_used: int = 0
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    files_read: int = 0
    files_written: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None

    @property
    def duration_seconds(self) -> float | None:
        """Get execution duration in seconds."""
        if self.start_time is None or self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds()

    def record_tool_call(self, success: bool = True) -> None:
        """Record a tool call (in place)."""
        self.total_tool_calls += 1
        if success:
            self.successful_tool_calls += 1
        else:
            self.failed_tool_calls += 1


__all__ = [
    "AgentTurnState",
    "AgentMemory",
    "AgentExecutionMetrics",
]
