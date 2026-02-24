from dataclasses import dataclass, field
from collections import deque
from remora.event_bus import Event

from .workspace_registry import workspace_registry

MAX_EVENTS = 200


@dataclass
class DashboardState:
    events: deque = field(default_factory=lambda: deque(maxlen=MAX_EVENTS))
    blocked: dict[str, dict] = field(default_factory=dict)
    agent_states: dict[str, dict] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    total_agents: int = 0
    completed_agents: int = 0

    def record(self, event: Event):
        self.events.append(event.model_dump())

        if event.category == "agent" and event.agent_id:
            if event.action == "started":
                self.agent_states[event.agent_id] = {
                    "state": "started",
                    "name": event.payload.get("name", event.agent_id),
                    "workspace_id": event.payload.get("workspace_id"),
                }
                self.total_agents += 1

            elif event.action == "blocked":
                key = f"{event.agent_id}:{event.payload.get('question', '')}"
                self.blocked[key] = {
                    "agent_id": event.agent_id,
                    "question": event.payload.get("question", ""),
                    "options": event.payload.get("options", []),
                    "msg_id": event.payload.get("msg_id", ""),
                    "workspace_id": event.payload.get("workspace_id", ""),
                }

            elif event.action == "resumed":
                question = event.payload.get("question", "")
                if question:
                    key = f"{event.agent_id}:{question}"
                    self.blocked.pop(key, None)

            elif event.action in ("completed", "failed", "cancelled"):
                if event.agent_id in self.agent_states:
                    self.agent_states[event.agent_id]["state"] = event.action
                    self.completed_agents += 1
                    ws_id = self.agent_states[event.agent_id].get("workspace_id")
                    if ws_id:
                        workspace_registry.unregister(event.agent_id)

        if event.category == "agent" and event.action == "completed":
            self.results.insert(
                0,
                {
                    "agent_id": event.agent_id,
                    "content": event.payload.get("result", str(event.payload)),
                    "timestamp": event.timestamp.isoformat(),
                },
            )
            if len(self.results) > 50:
                self.results.pop()

    def get_signals(self) -> dict:
        return {
            "events": list(self.events),
            "blocked": list(self.blocked.values()),
            "agentStates": self.agent_states,
            "progress": {"total": self.total_agents, "completed": self.completed_agents},
            "results": self.results[:10],
        }
