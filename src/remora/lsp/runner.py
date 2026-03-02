from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ConfigDict

from remora.lsp.extensions import load_extensions_from_disk
from remora.lsp.models import (
    AgentErrorEvent,
    AgentEvent,
    AgentMessageEvent,
    ASTAgentNode,
    HumanChatEvent,
    RewriteProposal,
    RewriteProposalEvent,
    generate_id,
)

if TYPE_CHECKING:
    from remora.core.swarm_executor import SwarmExecutor
    from remora.lsp.server import RemoraLanguageServer

logger = logging.getLogger("remora.lsp.runner")

MAX_CHAIN_DEPTH = 10


# ---------------------------------------------------------------------------
# LLM client adapter — wraps structured_agents OpenAICompatibleClient
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    """Normalized tool call that handle_response expects."""

    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class LLMResponse:
    """Normalized response from the LLM."""

    content: str | None
    tool_calls: list[ToolCall]


class LLMClient:
    """Thin adapter over structured_agents.client for the LSP runner."""

    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY") -> None:
        from structured_agents.client import build_client

        self._client = build_client(
            {
                "base_url": base_url,
                "api_key": api_key,
                "model": model,
            }
        )
        self.model = model
        logger.info("LLMClient initialized: model=%s base_url=%s", model, base_url)

    async def chat(self, messages: list[dict], tools: list[dict]) -> LLMResponse:
        """Send a chat completion and return a normalized LLMResponse."""
        response = await self._client.chat_completion(
            messages=messages,
            tools=tools or None,
            tool_choice="auto" if tools else "none",
        )

        tool_calls: list[ToolCall] = []
        if response.tool_calls:
            for tc in response.tool_calls:
                fn = tc.get("function", {})
                raw_args = fn.get("arguments", "{}")
                if isinstance(raw_args, str):
                    try:
                        parsed = json.loads(raw_args)
                    except json.JSONDecodeError:
                        parsed = {"raw": raw_args}
                else:
                    parsed = raw_args
                tool_calls.append(
                    ToolCall(
                        name=fn.get("name", ""),
                        arguments=parsed,
                        id=tc.get("id", ""),
                    )
                )

        return LLMResponse(content=response.content, tool_calls=tool_calls)

    async def close(self) -> None:
        if hasattr(self._client, "close"):
            await self._client.close()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class Trigger(BaseModel):
    model_config = ConfigDict(frozen=False)

    agent_id: str
    correlation_id: str
    context: dict = Field(default_factory=dict)


class AgentRunner:
    """Asynchronous agent execution coordinator for the Remora LSP server."""

    def __init__(self, server: "RemoraLanguageServer", llm: LLMClient | None = None) -> None:
        self.server = server
        self.llm = llm
        self.executor: "SwarmExecutor | None" = None
        self.queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._running = False

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            trigger = await self.queue.get()
            await self.execute_turn(trigger)

    def stop(self) -> None:
        self._running = False

    async def trigger(self, agent_id: str, correlation_id: str, context: dict | None = None) -> None:
        chain = await self.server.db.get_activation_chain(correlation_id)

        if len(chain) >= MAX_CHAIN_DEPTH:
            await self.emit_error(agent_id, "Max activation depth exceeded", correlation_id)
            return

        if agent_id in chain:
            await self.emit_error(agent_id, "Cycle detected in activation chain", correlation_id)
            return

        await self.queue.put(Trigger(agent_id=agent_id, correlation_id=correlation_id, context=context or {}))

    async def emit_error(self, agent_id: str, error: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        await emit_event(AgentErrorEvent(agent_id=agent_id, error=error, correlation_id=correlation_id, timestamp=0.0))

    async def execute_turn(self, trigger: Trigger) -> None:
        from remora.lsp.server import emit_event, refresh_code_lenses

        agent_id = trigger.agent_id
        correlation_id = trigger.correlation_id

        await self.server.db.set_status(agent_id, "running")
        await refresh_code_lenses()
        await self.server.db.add_to_chain(correlation_id, agent_id)

        node = await self.server.db.get_node(agent_id)
        if not node:
            await self.emit_error(agent_id, "Node not found", correlation_id)
            return

        try:
            if self.executor:
                state = await self._load_agent_state(agent_id)
                if state:
                    trigger_event = await self._build_trigger_event(trigger)
                    await self.executor.run_agent(state, trigger_event)
            else:
                agent = ASTAgentNode(**node)
                agent = self.apply_extensions(agent)

                messages = [
                    {"role": "system", "content": agent.to_system_prompt()},
                ]

                events = await self.server.db.get_events_for_correlation(correlation_id)
                for event in events:
                    if event.event_type == "HumanChatEvent" and event.payload.get("to_agent") == agent_id:
                        messages.append({"role": "user", "content": event.payload.get("message", "")})
                    elif event.event_type == "AgentMessageEvent" and event.payload.get("to_agent") == agent_id:
                        from_agent = event.payload.get("from_agent", "unknown")
                        messages.append(
                            {"role": "user", "content": f"[From {from_agent}]: {event.payload.get('message', '')}"}
                        )

                if trigger.context.get("rejection_feedback"):
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[Feedback on rejected proposal]: {trigger.context['rejection_feedback']}",
                        }
                    )

                tools = self.get_agent_tools(agent)

                if self.llm:
                    response = await self.llm.chat(messages, tools)
                    await self.handle_response(agent, response, correlation_id)
                else:
                    await self.emit_error(agent_id, "No LLM client configured", correlation_id)
        except Exception as e:
            await self.emit_error(agent_id, str(e), correlation_id)
        finally:
            await self.server.db.set_status(agent_id, "active")
            await refresh_code_lenses()

    async def _load_agent_state(self, agent_id: str) -> Any:
        return None

    async def _build_trigger_event(self, trigger: Trigger) -> AgentEvent:
        return AgentEvent(
            event_type="TriggerEvent",
            timestamp=0.0,
            correlation_id=trigger.correlation_id,
            agent_id=trigger.agent_id,
            summary=f"Triggered agent {trigger.agent_id}",
            payload=trigger.context,
        )

    async def handle_response(self, agent: ASTAgentNode, response: LLMResponse, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        if not response.tool_calls:
            # Text-only response — emit as an event so the UI can show it
            if response.content:
                logger.info("Agent %s responded with text: %s", agent.remora_id, response.content[:200])
                await emit_event(
                    AgentEvent(
                        event_type="AgentTextResponse",
                        agent_id=agent.remora_id,
                        correlation_id=correlation_id,
                        summary=response.content[:200],
                        timestamp=0.0,
                        payload={"content": response.content},
                    )
                )
            return

        for tool_call in response.tool_calls:
            match tool_call.name:
                case "rewrite_self":
                    new_source = tool_call.arguments.get("new_source", "")
                    await self.create_proposal(agent, new_source, correlation_id)

                case "message_node":
                    target_id = tool_call.arguments.get("target_id", "")
                    message = tool_call.arguments.get("message", "")
                    await self.message_node(agent.remora_id, target_id, message, correlation_id)

                case "read_node":
                    target_id = tool_call.arguments.get("target_id", "")
                    target = await self.server.db.get_node(target_id)
                    if target:
                        tool_result = {
                            "name": target["name"],
                            "type": target["node_type"],
                            "source": target.get("source_code", ""),
                            "file": target.get("file_path", ""),
                        }
                        # Currently not used, but left for future integrations.

                case _:
                    await self.execute_extension_tool(agent, tool_call.name, tool_call.arguments, correlation_id)

    async def create_proposal(self, agent: ASTAgentNode, new_source: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event, publish_diagnostics, refresh_code_lenses

        proposal_id = generate_id()
        proposal = RewriteProposal(
            proposal_id=proposal_id,
            agent_id=agent.remora_id,
            file_path=agent.file_path,
            old_source=agent.source_code,
            new_source=new_source,
            start_line=agent.start_line,
            end_line=agent.end_line,
            correlation_id=correlation_id,
        )

        self.server.proposals[proposal_id] = proposal
        await self.server.db.set_pending_proposal(agent.remora_id, proposal_id)
        await self.server.db.set_status(agent.remora_id, "pending_approval")
        await self.server.db.store_proposal(proposal_id, agent.remora_id, agent.source_code, new_source, proposal.diff)

        await publish_diagnostics(agent.file_path, [proposal])
        await refresh_code_lenses()

        await emit_event(
            RewriteProposalEvent(
                agent_id=agent.remora_id,
                proposal_id=proposal_id,
                diff=proposal.diff,
                correlation_id=correlation_id,
            )
        )

    async def message_node(self, from_id: str, to_id: str, message: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        await emit_event(
            AgentMessageEvent(from_agent=from_id, to_agent=to_id, message=message, correlation_id=correlation_id)
        )
        await self.trigger(to_id, correlation_id)

    async def refresh_code_lens(self, agent_id: str) -> None:
        from remora.lsp.server import refresh_code_lenses

        node = await self.server.db.get_node(agent_id)
        if node:
            await refresh_code_lenses()

    def get_agent_tools(self, agent: ASTAgentNode) -> list[dict]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "rewrite_self",
                    "description": "Rewrite the agent's own source code with new implementation",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "new_source": {
                                "type": "string",
                                "description": "The new source code for this function/class",
                            }
                        },
                        "required": ["new_source"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "message_node",
                    "description": "Send a message to another agent to request changes",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_id": {"type": "string", "description": "The remora_id of the target agent"},
                            "message": {"type": "string", "description": "Message to send to the target agent"},
                        },
                        "required": ["target_id", "message"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "read_node",
                    "description": "Read another agent's source code",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "target_id": {"type": "string", "description": "The remora_id of the target agent"}
                        },
                        "required": ["target_id"],
                    },
                },
            },
        ]

        for tool in agent.extra_tools:
            tools.append(tool.to_llm_tool())

        return tools

    def apply_extensions(self, agent: ASTAgentNode) -> ASTAgentNode:
        extensions = load_extensions_from_disk()

        for ext_cls in extensions:
            if ext_cls.matches(agent.node_type, agent.name):
                ext = ext_cls()
                agent.custom_system_prompt = ext.system_prompt
                agent.mounted_workspaces = ext.get_workspaces()
                agent.extra_tools = ext.get_tool_schemas()
                break

        return agent

    async def execute_extension_tool(
        self, agent: ASTAgentNode, tool_name: str, params: dict, correlation_id: str
    ) -> None:
        from remora.lsp.server import emit_event

        await emit_event(
            AgentEvent(
                event_type="ToolResultEvent",
                agent_id=agent.remora_id,
                correlation_id=correlation_id,
                summary=f"Tool {tool_name} executed",
                timestamp=0.0,
                payload={"tool_name": tool_name, "params": params},
            )
        )
