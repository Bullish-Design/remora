"""Agent state management for the reactive swarm.

This module provides AgentState for persisting agent identity and runtime state.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from remora.core.subscriptions import SubscriptionPattern
from remora.utils import PathLike, normalize_path


@dataclass
class AgentState:
    """State for a single agent in the swarm."""

    agent_id: str
    node_type: str
    name: str
    full_name: str
    file_path: str
    parent_id: str | None = None
    range: tuple[int, int] | None = None
    connections: dict[str, str] = field(default_factory=dict)
    chat_history: list[dict[str, Any]] = field(default_factory=list)
    custom_subscriptions: list[SubscriptionPattern] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["custom_subscriptions"] = [asdict(sub) for sub in self.custom_subscriptions]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        """Create from dictionary."""
        data = dict(data)
        subs_data = data.pop("custom_subscriptions", [])
        custom_subscriptions = [SubscriptionPattern(**sub) for sub in subs_data]
        return cls(custom_subscriptions=custom_subscriptions, **data)


def load(path: PathLike) -> AgentState | None:
    """Load agent state from a JSONL file.

    Reads the last line of the file as the current state snapshot.
    """
    path = normalize_path(path)
    if not path.exists():
        return None

    try:
        lines = path.read_text(encoding="utf-8").strip().split("\n")
        if not lines:
            return None
        last_line = lines[-1]
        data = json.loads(last_line)
        return AgentState.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return None


def save(path: PathLike, state: AgentState) -> None:
    """Save agent state to a JSONL file.

    Appends the state as a new line.
    """
    path = normalize_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    state.last_updated = time.time()
    line = json.dumps(state.to_dict(), default=str) + "\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(line)


__all__ = ["AgentState", "load", "save"]
