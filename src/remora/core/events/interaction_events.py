"""Reactive swarm and editor-interaction events."""

from __future__ import annotations

import time

from pydantic import Field

from remora.core.events.agent_events import _FrozenEvent


class AgentMessageEvent(_FrozenEvent):
    """Message sent between agents."""

    from_agent: str
    to_agent: str
    content: str
    tags: tuple[str, ...] = ()
    correlation_id: str | None = None
    timestamp: float = Field(default_factory=time.time)


class FileSavedEvent(_FrozenEvent):
    """A file was saved to disk."""

    path: str
    timestamp: float = Field(default_factory=time.time)


class ContentChangedEvent(_FrozenEvent):
    """File content was modified."""

    path: str
    diff: str | None = None
    timestamp: float = Field(default_factory=time.time)


class CursorFocusEvent(_FrozenEvent):
    """Cursor moved to focus on a specific agent (debounced)."""

    focused_agent_id: str | None
    file_path: str
    line: int
    timestamp: float = Field(default_factory=time.time)


class ManualTriggerEvent(_FrozenEvent):
    """Manual trigger to start an agent."""

    to_agent: str
    reason: str
    timestamp: float = Field(default_factory=time.time)


__all__ = [
    "AgentMessageEvent",
    "FileSavedEvent",
    "ContentChangedEvent",
    "CursorFocusEvent",
    "ManualTriggerEvent",
]
