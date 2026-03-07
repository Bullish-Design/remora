"""LSP-specific tools for agent execution.

These tools are the editor-integrated tools that agents use in the LSP path:
- rewrite_self: Propose a source code change to the agent's own body
- message_node: Send a message to another agent
- read_node: Read another agent's source code

They follow the same interface as SwarmTool (schema + execute) so the
structured_agents kernel can dispatch them uniformly.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine

from structured_agents.types import ToolCall, ToolResult, ToolSchema

from remora.core.agents.agent_node import AgentNode
from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)

# Callback types for LSP-specific side effects
CreateProposalFn = Callable[[AgentNode, str, str], Coroutine[Any, Any, None]]
MessageNodeFn = Callable[[str, str, str, str], Coroutine[Any, Any, None]]
EmitToolEventFn = Callable[[str, str, str, dict[str, Any]], Coroutine[Any, Any, None]]


class RewriteSelfTool:
    """Propose a rewrite of the agent's own source code.

    This is a side-effect tool — the kernel receives a confirmation string
    but the real work (proposal creation, diagnostics, code lenses) is done
    by the ``create_proposal`` callback injected by the caller.
    """

    def __init__(
        self,
        agent: AgentNode,
        create_proposal: CreateProposalFn,
        emit_tool_event: EmitToolEventFn | None = None,
    ) -> None:
        self._agent = agent
        self._create_proposal = create_proposal
        self._emit_tool_event = emit_tool_event
        self._schema = ToolSchema(
            name="rewrite_self",
            description="Rewrite the agent's own source code with new implementation",
            parameters={
                "type": "object",
                "properties": {
                    "new_source": {
                        "type": "string",
                        "description": "The new source code for this function/class",
                    }
                },
                "required": ["new_source"],
            },
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        new_source = arguments.get("new_source", "")
        try:
            await self._create_proposal(self._agent, new_source, self._agent.node_id)
            if self._emit_tool_event:
                await self._emit_tool_event(
                    self._agent.node_id,
                    "rewrite_self",
                    f"proposal created — {len(new_source)} chars",
                    {"tool_name": "rewrite_self", "target_id": self._agent.node_id},
                )
            return ToolResult(
                call_id=call_id,
                name="rewrite_self",
                output=f"Proposal created with {len(new_source)} chars of new source.",
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name="rewrite_self",
                output=f"Error creating proposal: {exc}",
                is_error=True,
            )


class MessageNodeTool:
    """Send a message to another agent to request changes.

    This is a side-effect tool — triggers the target agent via the
    ``message_node`` callback.
    """

    def __init__(
        self,
        agent: AgentNode,
        message_node: MessageNodeFn,
        emit_tool_event: EmitToolEventFn | None = None,
    ) -> None:
        self._agent = agent
        self._message_node = message_node
        self._emit_tool_event = emit_tool_event
        self._schema = ToolSchema(
            name="message_node",
            description="Send a message to another agent to request changes",
            parameters={
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "string",
                        "description": "The node_id of the target agent",
                    },
                    "message": {
                        "type": "string",
                        "description": "Message to send to the target agent",
                    },
                },
                "required": ["target_id", "message"],
            },
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        target_id = arguments.get("target_id", "")
        message = arguments.get("message", "")

        # Resolve symbolic target names
        if target_id == "parent" and self._agent.parent_id:
            logger.info(
                "message_node: resolved 'parent' -> %s for agent %s",
                self._agent.parent_id,
                self._agent.node_id,
            )
            target_id = self._agent.parent_id

        if not target_id or target_id == "parent":
            error_msg = f"Cannot resolve message target: {target_id!r}"
            logger.warning(
                "message_node: unresolved target_id=%r for agent %s (no parent?)",
                target_id,
                self._agent.node_id,
            )
            return ToolResult(
                call_id=call_id,
                name="message_node",
                output=error_msg,
                is_error=True,
            )

        try:
            correlation_id = ""  # Will be set by caller context
            await self._message_node(self._agent.node_id, target_id, message, correlation_id)
            if self._emit_tool_event:
                await self._emit_tool_event(
                    self._agent.node_id,
                    f"message_node({target_id})",
                    f"sent — {len(message)} chars",
                    {"tool_name": "message_node", "target_id": target_id},
                )
            return ToolResult(
                call_id=call_id,
                name="message_node",
                output=f"Message sent to {target_id} ({len(message)} chars).",
                is_error=False,
            )
        except Exception as exc:
            return ToolResult(
                call_id=call_id,
                name="message_node",
                output=f"Error sending message: {exc}",
                is_error=True,
            )


class ReadNodeTool:
    """Read another agent's source code.

    Unlike rewrite_self and message_node, this returns data to the LLM
    so it can reason about the target agent's code.
    """

    def __init__(
        self,
        agent: AgentNode,
        event_store: EventStore,
        emit_tool_event: EmitToolEventFn | None = None,
    ) -> None:
        self._agent = agent
        self._event_store = event_store
        self._emit_tool_event = emit_tool_event
        self._schema = ToolSchema(
            name="read_node",
            description="Read another agent's source code",
            parameters={
                "type": "object",
                "properties": {
                    "target_id": {
                        "type": "string",
                        "description": "The node_id of the target agent",
                    }
                },
                "required": ["target_id"],
            },
        )

    @property
    def schema(self) -> ToolSchema:
        return self._schema

    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult:
        call_id = context.id if context else ""
        target_id = arguments.get("target_id", "")

        # Resolve symbolic target names
        if target_id == "parent" and self._agent.parent_id:
            logger.info("read_node: resolved 'parent' -> %s for agent %s", self._agent.parent_id, self._agent.node_id)
            target_id = self._agent.parent_id

        target = await self._event_store.nodes.get_node(target_id)
        if target:
            result_text = json.dumps(
                {
                    "name": target.name,
                    "type": target.node_type,
                    "source": target.source_code,
                    "file": target.file_path,
                },
                indent=2,
            )
            logger.info("read_node: returning %d chars for node %s", len(result_text), target_id)
            if self._emit_tool_event:
                await self._emit_tool_event(
                    self._agent.node_id,
                    f"read_node({target_id})",
                    f"{target.name} ({target.node_type}) — {len(target.source_code)} chars",
                    {"tool_name": "read_node", "target_id": target_id},
                )
            return ToolResult(
                call_id=call_id,
                name="read_node",
                output=result_text,
                is_error=False,
            )
        else:
            logger.warning("read_node: node %s not found", target_id)
            if self._emit_tool_event:
                await self._emit_tool_event(
                    self._agent.node_id,
                    f"read_node({target_id}) — not found",
                    "not found",
                    {"tool_name": "read_node", "target_id": target_id},
                )
            return ToolResult(
                call_id=call_id,
                name="read_node",
                output=f"Error: node {target_id!r} not found",
                is_error=True,
            )


def build_lsp_tools(
    agent: AgentNode,
    event_store: EventStore,
    *,
    create_proposal: CreateProposalFn,
    message_node: MessageNodeFn,
    emit_tool_event: EmitToolEventFn | None = None,
) -> list[RewriteSelfTool | MessageNodeTool | ReadNodeTool]:
    """Build the LSP-specific tool set for an agent.

    These tools are injected as ``extra_tools`` when running agents in
    the LSP path.  They provide editor-integrated capabilities that the
    core/CLI path does not need.
    """
    return [
        RewriteSelfTool(agent, create_proposal, emit_tool_event),
        MessageNodeTool(agent, message_node, emit_tool_event),
        ReadNodeTool(agent, event_store, emit_tool_event),
    ]


__all__ = [
    "RewriteSelfTool",
    "MessageNodeTool",
    "ReadNodeTool",
    "build_lsp_tools",
]
