from dataclasses import dataclass, field
from typing import Any

from remora.event_bus import Event


@dataclass
class HubState:
    """Runtime state for the hub - kept in memory, rebuilt from events."""

    events: list[dict] = field(default_factory=list)
    blocked: dict[str, dict[str, Any]] = field(default_factory=dict)
    agent_states: dict[str, dict[str, Any]] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0

    def record(self, event: Event) -> None:
        """Process event and update state."""
        self.events.append(event.model_dump(mode="json"))
        if len(self.events) > 200:
            self.events = self.events[-200:]

        if event.category == "agent" and event.agent_id:
            agent_id = event.agent_id
            payload = event.payload or {}

            if event.action == "started":
                self.agent_states[agent_id] = {
                    "state": "started",
                    "name": payload.get("name", agent_id),
                    "workspace_id": payload.get("workspace_id"),
                    "parent_id": payload.get("parent_id"),
                }
                self.total_agents += 1

            elif event.action == "blocked":
                key = f"{agent_id}:{payload.get('question', '')}"
                self.blocked[key] = {
                    "agent_id": agent_id,
                    "question": payload.get("question", ""),
                    "options": payload.get("options", []),
                    "msg_id": payload.get("msg_id", ""),
                    "workspace_id": payload.get("workspace_id", ""),
                }

            elif event.action == "resumed":
                question = payload.get("question", "")
                if question:
                    key = f"{agent_id}:{question}"
                    self.blocked.pop(key, None)

            elif event.action in ("completed", "failed", "cancelled"):
                if agent_id in self.agent_states:
                    self.agent_states[agent_id]["state"] = event.action
                    if event.action == "completed":
                        self.completed_agents += 1

        if event.category == "agent" and event.action == "completed":
            self.results.insert(
                0,
                {
                    "agent_id": event.agent_id,
                    "content": event.payload.get("result", str(event.payload)),
                    "timestamp": event.timestamp.isoformat() if event.timestamp else "",
                },
            )
            if len(self.results) > 50:
                self.results = self.results[:50]

    def get_view_data(self) -> dict[str, Any]:
        """Data needed to render the dashboard view."""
        return {
            "events": self.events,
            "blocked": list(self.blocked.values()),
            "agentStates": self.agent_states,
            "progress": {"total": self.total_agents, "completed": self.completed_agents},
            "results": self.results[:10],
        }
