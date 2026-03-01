"""Swarm communication tools for agents."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.events import AgentMessageEvent
from remora.core.subscriptions import SubscriptionPattern


class SwarmTool:
    """Base class for swarm tools with structured_agents compatible interface."""

    def __init__(self, name: str, description: str, parameters: dict[str, Any]):
        self._schema = ToolSchema(
            name=name,
            description=description,
            parameters=parameters,
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        raise NotImplementedError


class SendMessageTool(SwarmTool):
    """Send a direct message from this agent to another."""

    def __init__(self, externals: dict[str, Any]):
        super().__init__(
            name="send_message",
            description="Send a direct message from this agent to another agent in the swarm.",
            parameters={
                "type": "object",
                "properties": {
                    "to_agent": {
                        "type": "string",
                        "description": "The agent ID to send the message to",
                    },
                    "content": {
                        "type": "string",
                        "description": "The message content",
                    },
                },
                "required": ["to_agent", "content"],
            },
        )
        self._externals = externals

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        emit_event = self._externals.get("emit_event")
        agent_id = self._externals.get("agent_id")
        correlation_id = self._externals.get("correlation_id")

        if not emit_event or not agent_id:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: Swarm event emitter is not configured.",
                is_error=True,
            )

        try:
            event = AgentMessageEvent(
                from_agent=agent_id,
                to_agent=arguments["to_agent"],
                content=arguments["content"],
                correlation_id=correlation_id,
            )
            await emit_event("AgentMessageEvent", event)
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=f"Message successfully queued for {arguments['to_agent']}.",
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(e),
                is_error=True,
            )


class SubscribeTool(SwarmTool):
    """Dynamically subscribe this agent to additional events."""

    def __init__(self, externals: dict[str, Any]):
        super().__init__(
            name="subscribe",
            description="Subscribe this agent to additional event patterns.",
            parameters={
                "type": "object",
                "properties": {
                    "event_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Event types to subscribe to",
                    },
                    "from_agents": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Agent IDs to receive events from",
                    },
                    "path_glob": {
                        "type": "string",
                        "description": "File path glob pattern",
                    },
                },
            },
        )
        self._externals = externals

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        register_subscription = self._externals.get("register_subscription")
        agent_id = self._externals.get("agent_id")

        if not register_subscription or not agent_id:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: Subscription registry is not configured.",
                is_error=True,
            )

        try:
            pattern = SubscriptionPattern(
                event_types=arguments.get("event_types"),
                from_agents=arguments.get("from_agents"),
                to_agent=agent_id,
                path_glob=arguments.get("path_glob"),
            )
            await register_subscription(agent_id, pattern)
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Subscription successfully registered.",
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(e),
                is_error=True,
            )


class UnsubscribeTool(SwarmTool):
    """Remove a subscription from the registry."""

    def __init__(self, externals: dict[str, Any]):
        super().__init__(
            name="unsubscribe",
            description="Remove a subscription by its ID.",
            parameters={
                "type": "object",
                "properties": {
                    "subscription_id": {
                        "type": "integer",
                        "description": "The subscription ID to remove",
                    },
                },
                "required": ["subscription_id"],
            },
        )
        self._externals = externals

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        action = self._externals.get("unsubscribe_subscription")

        if not action:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: Unsubscribe tool is unavailable.",
                is_error=True,
            )

        try:
            result = await action(arguments["subscription_id"])
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=result,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(e),
                is_error=True,
            )


class BroadcastTool(SwarmTool):
    """Broadcast a message to multiple agents via a pattern."""

    def __init__(self, externals: dict[str, Any]):
        super().__init__(
            name="broadcast",
            description="Broadcast a message to multiple agents using a pattern (children, siblings, or file:path).",
            parameters={
                "type": "object",
                "properties": {
                    "to_pattern": {
                        "type": "string",
                        "description": "Pattern: 'children', 'siblings', or 'file:/path/to/file.py'",
                    },
                    "content": {
                        "type": "string",
                        "description": "The message content to broadcast",
                    },
                },
                "required": ["to_pattern", "content"],
            },
        )
        self._externals = externals

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        action = self._externals.get("broadcast")

        if not action:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="Error: Broadcast tool is unavailable.",
                is_error=True,
            )

        try:
            result = await action(arguments["to_pattern"], arguments["content"])
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=result,
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(e),
                is_error=True,
            )


class QueryAgentsTool(SwarmTool):
    """List agent metadata filtered by node type."""

    def __init__(self, externals: dict[str, Any]):
        super().__init__(
            name="query_agents",
            description="Query and list agents in the swarm, optionally filtered by node type.",
            parameters={
                "type": "object",
                "properties": {
                    "filter_type": {
                        "type": "string",
                        "description": "Optional node type filter (e.g., 'function', 'class')",
                    },
                },
            },
        )
        self._externals = externals

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else "unknown"
        query = self._externals.get("query_agents")

        if not query:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output="[]",
                is_error=False,
            )

        try:
            agents = await query(arguments.get("filter_type"))
            if not agents:
                result = []
            elif isinstance(agents[0], dict):
                result = agents
            else:
                result = [asdict(agent) for agent in agents]
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=json.dumps(result),
                is_error=False,
            )
        except Exception as e:
            return ToolResult(
                call_id=call_id,
                name=self._schema.name,
                output=str(e),
                is_error=True,
            )


def build_swarm_tools(externals: dict[str, Any]) -> list[SwarmTool]:
    """Build tools for swarm messaging when externals are provided."""
    return [
        SendMessageTool(externals),
        SubscribeTool(externals),
        UnsubscribeTool(externals),
        BroadcastTool(externals),
        QueryAgentsTool(externals),
    ]
