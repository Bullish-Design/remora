"""Framework-agnostic service handlers for the Remora API."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.config import Config
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.event_store import EventStore
from remora.core.events import HumanInputResponseEvent
from remora.models import ConfigSnapshot, InputResponse
from remora.ui.projector import UiStateProjector
from remora.utils import PathResolver

if TYPE_CHECKING:
    from remora.core.subscriptions import SubscriptionRegistry
    from remora.core.swarm_state import SwarmState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ServiceDeps:
    event_bus: EventBus
    config: Config
    project_root: Path
    projector: UiStateProjector
    event_store: EventStore | None = None
    swarm_state: "SwarmState | None" = None
    subscriptions: "SubscriptionRegistry | None" = None


async def handle_input(request_id: str, response: str, deps: ServiceDeps) -> InputResponse:
    if not request_id or not response:
        raise ValueError("request_id and response are required")
    event = HumanInputResponseEvent(request_id=request_id, response=response)
    await deps.event_bus.emit(event)
    return InputResponse(request_id=request_id)


def handle_config_snapshot(deps: ServiceDeps) -> ConfigSnapshot:
    return ConfigSnapshot.from_config(deps.config)


def handle_ui_snapshot(deps: ServiceDeps) -> dict[str, Any]:
    return deps.projector.snapshot()


def _normalize_target(target_path: str, project_root: Path) -> Path:
    resolver = PathResolver(project_root)
    path_obj = Path(target_path)
    if path_obj.is_absolute():
        resolved = path_obj.resolve()
    else:
        resolved = (project_root / path_obj).resolve()
    if not resolver.is_within_project(resolved):
        raise ValueError("target_path must be within the service project root")
    if not resolved.exists():
        raise ValueError("target_path does not exist")
    return resolved


async def handle_swarm_emit(request: Any, deps: ServiceDeps) -> dict[str, Any]:
    """Handle swarm.emit - emit an event to the swarm."""
    if deps.event_store is None:
        raise ValueError("event store not configured")

    from remora.core.events import AgentMessageEvent, ContentChangedEvent

    event_type = getattr(request, "event_type", None)
    data = getattr(request, "data", {}) or {}

    if event_type == "AgentMessageEvent":
        event = AgentMessageEvent(
            from_agent=data.get("from_agent", "api"),
            to_agent=data.get("to_agent", ""),
            content=data.get("content", ""),
            tags=data.get("tags", []),
        )
    elif event_type == "ContentChangedEvent":
        from remora.utils import to_project_relative

        path = to_project_relative(deps.project_root, data.get("path", ""))
        event = ContentChangedEvent(path=path, diff=data.get("diff"))
    else:
        raise ValueError(f"Unknown event type: {event_type}")

    event_id = await deps.event_store.append(deps.config.swarm_id, event)
    return {"event_id": event_id}


def handle_swarm_list_agents(deps: ServiceDeps) -> list[dict[str, Any]]:
    """List all agents in the swarm."""
    if deps.swarm_state is None:
        raise ValueError("swarm state not configured")
    return deps.swarm_state.list_agents()


def handle_swarm_get_agent(agent_id: str, deps: ServiceDeps) -> dict[str, Any]:
    """Get a specific agent."""
    if deps.swarm_state is None:
        raise ValueError("swarm state not configured")
    agent = deps.swarm_state.get_agent(agent_id)
    if agent is None:
        raise ValueError("agent not found")
    return agent


async def handle_swarm_get_subscriptions(agent_id: str, deps: ServiceDeps) -> list[dict[str, Any]]:
    """Get subscriptions for an agent."""
    if deps.subscriptions is None:
        raise ValueError("subscriptions not configured")
    subs = await deps.subscriptions.get_subscriptions(agent_id)
    return [
        {
            "id": sub.id,
            "pattern": {
                "event_types": sub.pattern.event_types,
                "from_agents": sub.pattern.from_agents,
                "to_agent": sub.pattern.to_agent,
                "path_glob": sub.pattern.path_glob,
                "tags": sub.pattern.tags,
            },
            "is_default": sub.is_default,
        }
        for sub in subs
    ]


__all__ = [
    "ServiceDeps",
    "handle_config_snapshot",
    "handle_input",
    "handle_ui_snapshot",
    "handle_swarm_emit",
    "handle_swarm_list_agents",
    "handle_swarm_get_agent",
    "handle_swarm_get_subscriptions",
]
