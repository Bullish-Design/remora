"""Swarm communication tools for agents."""

from __future__ import annotations

from typing import Any

from structured_agents import Tool

from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionPattern


def build_swarm_tools(externals: dict[str, Any]) -> list[Tool]:
    """Build tools for swarm messaging when externals are provided."""
    emit_event = externals.get("emit_event")
    register_subscription = externals.get("register_subscription")
    agent_id = externals.get("agent_id")
    correlation_id = externals.get("correlation_id")

    async def send_message(to_agent: str, content: str) -> str:
        """Send a direct message from this agent to another."""
        if not emit_event or not agent_id:
            return "Error: Swarm event emitter is not configured."

        event = AgentMessageEvent(
            from_agent=agent_id,
            to_agent=to_agent,
            content=content,
            correlation_id=correlation_id,
        )
        await emit_event("AgentMessageEvent", event)
        return f"Message successfully queued for {to_agent}."

    async def subscribe(
        event_types: list[str] | None = None,
        from_agents: list[str] | None = None,
        path_glob: str | None = None,
    ) -> str:
        """Dynamically subscribe this agent to additional events."""
        if not register_subscription or not agent_id:
            return "Error: Subscription registry is not configured."

        pattern = SubscriptionPattern(
            event_types=event_types,
            from_agents=from_agents,
            to_agent=agent_id,
            path_glob=path_glob,
        )
        await register_subscription(agent_id, pattern)
        return "Subscription successfully registered."

    return [
        Tool.from_function(send_message),
        Tool.from_function(subscribe),
    ]
