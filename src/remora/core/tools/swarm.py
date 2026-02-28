"""Swarm communication tools for agents."""

from __future__ import annotations

from dataclasses import asdict
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

    async def unsubscribe_tool(subscription_id: int) -> str:
        """Remove a subscription from the registry."""
        action = externals.get("unsubscribe_subscription")
        if not action:
            return "Error: Unsubscribe tool is unavailable."
        return await action(subscription_id)

    async def broadcast_tool(to_pattern: str, content: str) -> str:
        """Broadcast a message to multiple agents via a pattern."""
        action = externals.get("broadcast")
        if not action:
            return "Error: Broadcast tool is unavailable."
        return await action(to_pattern, content)

    async def query_agents_tool(filter_type: str | None = None) -> list[dict[str, Any]]:
        """List agent metadata filtered by node type."""
        query = externals.get("query_agents")
        if not query:
            return []
        agents = await query(filter_type)
        if not agents:
            return []
        if isinstance(agents[0], dict):
            return agents
        return [asdict(agent) for agent in agents]

    tools: list[Tool] = [
        Tool.from_function(send_message),
        Tool.from_function(subscribe),
        Tool.from_function(unsubscribe_tool),
        Tool.from_function(broadcast_tool),
        Tool.from_function(query_agents_tool),
    ]

    return tools
