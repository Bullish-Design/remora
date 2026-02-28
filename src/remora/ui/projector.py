"""Project events into UI-ready state snapshots."""

from __future__ import annotations

import time
from collections import deque
from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any

from structured_agents.events import Event as StructuredEvent

from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    HumanInputRequestEvent,
    HumanInputResponseEvent,
    KernelEndEvent,
    KernelStartEvent,
    ModelRequestEvent,
    ModelResponseEvent,
    RemoraEvent,
    ToolCallEvent,
    ToolResultEvent,
    TurnCompleteEvent,
)

MAX_EVENTS = 200


class EventKind(str, Enum):
    """Categories of events for UI display."""

    GRAPH = "graph"
    AGENT = "agent"
    HUMAN = "human"
    TOOL = "tool"
    MODEL = "model"
    KERNEL = "kernel"
    TURN = "turn"
    EVENT = "event"


def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "__dict__"):
        return _to_jsonable(vars(value))
    return str(value)


def normalize_event(event: StructuredEvent | RemoraEvent) -> dict[str, Any]:
    """Wrap an event in a UI-friendly envelope."""
    kind = _event_kind(event)
    timestamp = getattr(event, "timestamp", None) or time.time()
    payload = _event_payload(event)
    return {
        "kind": kind,
        "type": type(event).__name__,
        "graph_id": getattr(event, "graph_id", ""),
        "agent_id": getattr(event, "agent_id", ""),
        "timestamp": timestamp,
        "payload": payload,
    }


def _event_kind(event: StructuredEvent | RemoraEvent) -> EventKind:
    if isinstance(event, (AgentStartEvent, AgentCompleteEvent, AgentErrorEvent)):
        return EventKind.AGENT
    if isinstance(event, (HumanInputRequestEvent, HumanInputResponseEvent)):
        return EventKind.HUMAN
    if isinstance(event, (ToolCallEvent, ToolResultEvent)):
        return EventKind.TOOL
    if isinstance(event, (ModelRequestEvent, ModelResponseEvent)):
        return EventKind.MODEL
    if isinstance(event, (KernelStartEvent, KernelEndEvent)):
        return EventKind.KERNEL
    if isinstance(event, TurnCompleteEvent):
        return EventKind.TURN
    return EventKind.EVENT


def _event_payload(event: StructuredEvent | RemoraEvent) -> dict[str, Any]:
    if is_dataclass(event):
        payload: dict[str, Any] = asdict(event)
    elif hasattr(event, "__dict__"):
        payload = dict(vars(event))
    else:
        payload = {"value": str(event)}
    return _to_jsonable(payload)


@dataclass(slots=True)
class UiStateProjector:
    """Reduce the event stream into a JSON-serializable UI state."""

    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0
    failed_agents: int = 0
    recent_targets: deque[str] = field(default_factory=lambda: deque(maxlen=10))

    def record_target(self, target_path: str) -> None:
        cleaned = target_path.strip()
        if not cleaned:
            return
        try:
            self.recent_targets.remove(cleaned)
        except ValueError:
            pass
        self.recent_targets.appendleft(cleaned)

    def record(self, event: StructuredEvent | RemoraEvent) -> None:
        envelope = normalize_event(event)
        self.events.append(envelope)

        if isinstance(event, AgentStartEvent):
            self.agent_states[event.agent_id] = {
                "state": "started",
                "name": event.node_name or event.agent_id,
            }
            if self.total_agents == 0:
                self.total_agents += 1

        elif isinstance(event, HumanInputRequestEvent):
            self.blocked[event.request_id] = {
                "agent_id": event.agent_id,
                "question": event.question,
                "options": list(event.options) if event.options else [],
                "request_id": event.request_id,
            }

        elif isinstance(event, HumanInputResponseEvent):
            self.blocked.pop(event.request_id, None)

        elif isinstance(event, (AgentCompleteEvent, AgentErrorEvent)):
            if event.agent_id in self.agent_states:
                state_map = {
                    AgentCompleteEvent: "completed",
                    AgentErrorEvent: "failed",
                }
                self.agent_states[event.agent_id]["state"] = state_map[type(event)]
            if isinstance(event, AgentCompleteEvent):
                self.completed_agents += 1
            elif isinstance(event, AgentErrorEvent):
                self.completed_agents += 1
                self.failed_agents += 1

        if isinstance(event, AgentCompleteEvent):
            self.results.insert(
                0,
                {
                    "agent_id": event.agent_id,
                    "content": str(event.result_summary),
                    "timestamp": getattr(event, "timestamp", 0),
                },
            )
            if len(self.results) > 50:
                self.results.pop()

    def snapshot(self) -> dict[str, Any]:
        return {
            "events": list(self.events),
            "blocked": list(self.blocked.values()),
            "agent_states": self.agent_states,
            "progress": {
                "total": self.total_agents,
                "completed": self.completed_agents,
                "failed": self.failed_agents,
            },
            "results": self.results[:10],
            "recent_targets": list(self.recent_targets),
        }

    def reset(self) -> None:
        self.events.clear()
        self.blocked.clear()
        self.agent_states.clear()
        self.results.clear()
        self.total_agents = 0
        self.completed_agents = 0
        self.failed_agents = 0
        self.recent_targets.clear()


__all__ = ["EventKind", "UiStateProjector", "normalize_event"]
