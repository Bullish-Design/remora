from __future__ import annotations

import asyncio
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


MAX_CHAIN_DEPTH = 10


class Trigger(BaseModel):
    model_config = ConfigDict(frozen=False)

    agent_id: str
    correlation_id: str
    context: dict = Field(default_factory=dict)


class MockLLMClient:
    async def chat(self, messages, tools=None):
        class MockResponse:
            tool_calls = []

        return MockResponse()


class AgentRunner:
    """Asynchronous agent execution coordinator for the Remora LSP server."""

    def __init__(self, server: "RemoraLanguageServer") -> None:
        self.server = server
        self.llm = MockLLMClient()
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

        await emit_event(
            AgentErrorEvent(agent_id=agent_id, error=error, correlation_id=correlation_id, timestamp=0.0)
        )

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
                    if isinstance(event, HumanChatEvent) and event.to_agent == agent_id:
                        messages.append({"role": "user", "content": event.message})
                    elif isinstance(event, AgentMessageEvent) and event.to_agent == agent_id:
                        messages.append({"role": "user", "content": f"[From {event.from_agent}]: {event.message}"})

                if trigger.context.get("rejection_feedback"):
                    messages.append(
                        {
                            "role": "user",
                            "content": f"[Feedback on rejected proposal]: {trigger.context['rejection_feedback']}",
                        }
                    )

                tools = self.get_agent_tools(agent)

                response = await self.llm.chat(messages, tools)
                await self.handle_response(agent, response, correlation_id)
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

    async def handle_response(self, agent: ASTAgentNode, response, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        for tool_call in response.tool_calls:
            tool_name = getattr(tool_call, "name", None) or getattr(tool_call, "function", {}).get("name", "")
            args = getattr(tool_call, "arguments", {}) or getattr(tool_call, "function", {}).get("arguments", {})
            tool_call_id = getattr(tool_call, "id", "")

            match tool_name:
                case "rewrite_self":
                    new_source = args.get("new_source", "")
                    await self.create_proposal(agent, new_source, correlation_id)

                case "message_node":
                    target_id = args.get("target_id", "")
                    message = args.get("message", "")
                    await self.message_node(agent.remora_id, target_id, message, correlation_id)

                case "read_node":
                    target_id = args.get("target_id", "")
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
                    await self.execute_extension_tool(agent, tool_name, args, correlation_id)

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

        await emit_event(AgentMessageEvent(from_agent=from_id, to_agent=to_id, message=message, correlation_id=correlation_id))
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
