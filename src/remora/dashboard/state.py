"""Dashboard state management - tracks agent events and UI state."""

from collections import deque
from dataclasses import dataclass, field
from typing import Any

from remora.events import RemoraEvent

MAX_EVENTS = 200


@dataclass
class DashboardState:
    """Runtime state for the dashboard - rebuilt from events via EventBus."""

    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0
    failed_agents: int = 0

    def record(self, event: RemoraEvent) -> None:
        """Process event and update state."""
        from remora.events import (
            AgentStartEvent,
            AgentCompleteEvent,
            AgentErrorEvent,
            GraphStartEvent,
            HumanInputRequestEvent,
            HumanInputResponseEvent,
        )

        event_dict = {
            "event_type": type(event).__name__,
            "graph_id": getattr(event, "graph_id", ""),
            "agent_id": getattr(event, "agent_id", ""),
            "timestamp": getattr(event, "timestamp", 0),
        }
        self.events.append(event_dict)

        if isinstance(event, GraphStartEvent):
            self.total_agents = event.node_count
            self.completed_agents = 0
            self.failed_agents = 0

        elif isinstance(event, AgentStartEvent):
            self.agent_states[event.agent_id] = {
                "state": "started",
                "name": event.agent_id,
            }
            if self.total_agents == 0:
                self.total_agents += 1

        elif isinstance(event, HumanInputRequestEvent):
            key = event.request_id
            self.blocked[key] = {
                "agent_id": event.agent_id,
                "question": event.question,
                "options": getattr(event, "options", []),
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
                    "content": str(getattr(event, "result_summary", "")),
                    "timestamp": getattr(event, "timestamp", 0),
                },
            )
            if len(self.results) > 50:
                self.results.pop()

    def get_view_data(self) -> dict[str, Any]:
        """Data needed to render the dashboard view."""
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
        }
