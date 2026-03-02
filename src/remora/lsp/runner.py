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
MAX_TOOL_ROUNDS = 5  # max LLM↔tool round-trips per turn


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
        logger.info("LLMClient.chat: sending %d messages, %d tools to %s", len(messages), len(tools), self.model)
        try:
            response = await self._client.chat_completion(
                messages=messages,
                tools=tools or None,
                tool_choice="auto" if tools else "none",
            )
            logger.info(
                "LLMClient.chat: got response content=%r tool_calls=%d",
                (response.content or "")[:100],
                len(response.tool_calls or []),
            )
        except Exception:
            logger.exception("LLMClient.chat: FAILED to call LLM")
            raise

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
        logger.info("AgentRunner.run_forever: started, waiting for triggers")
        while self._running:
            trigger = await self.queue.get()
            logger.info(
                "AgentRunner.run_forever: dequeued trigger agent=%s corr=%s", trigger.agent_id, trigger.correlation_id
            )
            await self.execute_turn(trigger)

    def stop(self) -> None:
        self._running = False

    async def trigger(self, agent_id: str, correlation_id: str, context: dict | None = None) -> None:
        logger.info("AgentRunner.trigger: agent=%s corr=%s context=%r", agent_id, correlation_id, context)
        chain = await self.server.db.get_activation_chain(correlation_id)

        if len(chain) >= MAX_CHAIN_DEPTH:
            logger.error("AgentRunner.trigger: max chain depth exceeded for %s", agent_id)
            await self.emit_error(agent_id, "Max activation depth exceeded", correlation_id)
            return

        if agent_id in chain:
            logger.error("AgentRunner.trigger: cycle detected for %s in chain %r", agent_id, chain)
            await self.emit_error(agent_id, "Cycle detected in activation chain", correlation_id)
            return

        logger.info("AgentRunner.trigger: enqueuing trigger for %s", agent_id)
        await self.queue.put(Trigger(agent_id=agent_id, correlation_id=correlation_id, context=context or {}))

    async def emit_error(self, agent_id: str, error: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        await emit_event(AgentErrorEvent(agent_id=agent_id, error=error, correlation_id=correlation_id, timestamp=0.0))

    async def execute_turn(self, trigger: Trigger) -> None:
        from remora.lsp.server import emit_event, refresh_code_lenses

        agent_id = trigger.agent_id
        correlation_id = trigger.correlation_id
        logger.info("execute_turn: START agent=%s corr=%s", agent_id, correlation_id)

        await self.server.db.set_status(agent_id, "running")
        await refresh_code_lenses()
        await self.server.db.add_to_chain(correlation_id, agent_id)

        node = await self.server.db.get_node(agent_id)
        if not node:
            logger.error("execute_turn: node %s not found in DB!", agent_id)
            await self.emit_error(agent_id, "Node not found", correlation_id)
            return

        logger.info(
            "execute_turn: node found: %s (%s) file=%s", node["name"], node["node_type"], node.get("file_path", "?")
        )

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
                logger.info("execute_turn: %d events for correlation %s", len(events), correlation_id)
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
                logger.info("execute_turn: %d messages, %d tools — calling LLM", len(messages), len(tools))
                logger.debug("execute_turn: messages=%r", [(m["role"], m["content"][:100]) for m in messages])

                if not self.llm:
                    await self.emit_error(agent_id, "No LLM client configured", correlation_id)
                else:
                    # Tool call loop: LLM → tool calls → results → LLM → ... → text response
                    for round_num in range(MAX_TOOL_ROUNDS):
                        logger.info("execute_turn: round %d/%d", round_num + 1, MAX_TOOL_ROUNDS)
                        response = await self.llm.chat(messages, tools)
                        logger.info(
                            "execute_turn: LLM response: content=%r tool_calls=%d",
                            (response.content or "")[:200],
                            len(response.tool_calls),
                        )

                        tool_results = await self.handle_response(agent, response, correlation_id)
                        if not tool_results:
                            # No tool calls or only side-effect tools — turn is done
                            break

                        # Append assistant message + tool results for next round
                        assistant_msg: dict[str, Any] = {"role": "assistant", "content": response.content or ""}
                        messages.append(assistant_msg)

                        for tr in tool_results:
                            messages.append(
                                {
                                    "role": "user",
                                    "content": f"[Tool result for {tr['tool']}]:\n{tr['result']}",
                                }
                            )
                        logger.info("execute_turn: appended %d tool results, continuing loop", len(tool_results))
                    else:
                        logger.warning(
                            "execute_turn: max tool rounds (%d) reached for agent %s", MAX_TOOL_ROUNDS, agent_id
                        )
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

    @staticmethod
    def _extract_text_tool_calls(content: str) -> list[ToolCall]:
        """Extract tool calls from <tool_call> XML tags in text content.

        Some models (e.g. Qwen) emit tool calls as text rather than using the
        structured tool_calls field in the response.
        """
        import re

        calls: list[ToolCall] = []
        for m in re.finditer(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL):
            try:
                parsed = json.loads(m.group(1))
                name = parsed.get("name", "")
                arguments = parsed.get("arguments", {})
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if name:
                    calls.append(ToolCall(name=name, arguments=arguments))
            except (json.JSONDecodeError, KeyError):
                logger.warning("_extract_text_tool_calls: failed to parse: %s", m.group(1)[:200])
        return calls

    async def handle_response(self, agent: ASTAgentNode, response: LLMResponse, correlation_id: str) -> list[dict]:
        """Process an LLM response, executing any tool calls.

        Returns a list of tool result dicts ``[{"tool": name, "result": text}, ...]``
        that should be fed back to the LLM in the next round.  An empty list means the
        turn is complete (text-only response or only side-effect tools).
        """
        from remora.lsp.server import emit_event

        tool_calls = response.tool_calls

        # Some models (e.g. Qwen) emit tool calls as <tool_call> XML in text
        # content rather than using the structured tool_calls field.
        if not tool_calls and response.content:
            tool_calls = self._extract_text_tool_calls(response.content)
            if tool_calls:
                logger.info(
                    "handle_response: extracted %d tool call(s) from text content for agent %s",
                    len(tool_calls),
                    agent.remora_id,
                )

        if not tool_calls:
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
            return []

        tool_results: list[dict] = []
        for tool_call in tool_calls:
            match tool_call.name:
                case "rewrite_self":
                    new_source = tool_call.arguments.get("new_source", "")
                    await self.create_proposal(agent, new_source, correlation_id)
                    # Emit event so the panel can show the tool call
                    await emit_event(
                        AgentEvent(
                            event_type="ToolResultEvent",
                            agent_id=agent.remora_id,
                            correlation_id=correlation_id,
                            summary="rewrite_self",
                            timestamp=0.0,
                            payload={
                                "tool_name": "rewrite_self",
                                "target_id": agent.remora_id,
                                "result_summary": f"proposal created — {len(new_source)} chars",
                            },
                        )
                    )
                    # Side-effect only — no result to feed back

                case "message_node":
                    target_id = tool_call.arguments.get("target_id", "")
                    # Resolve symbolic target names
                    if target_id == "parent" and agent.parent_id:
                        logger.info(
                            "message_node: resolved 'parent' -> %s for agent %s", agent.parent_id, agent.remora_id
                        )
                        target_id = agent.parent_id
                    message = tool_call.arguments.get("message", "")
                    if not target_id or target_id == "parent":
                        logger.warning(
                            "message_node: unresolved target_id=%r for agent %s (no parent?)",
                            target_id,
                            agent.remora_id,
                        )
                        await self.emit_error(
                            agent.remora_id, f"Cannot resolve message target: {target_id!r}", correlation_id
                        )
                    else:
                        await self.message_node(agent.remora_id, target_id, message, correlation_id)
                        # Emit event so the panel can show the tool call
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.remora_id,
                                correlation_id=correlation_id,
                                summary=f"message_node({target_id})",
                                timestamp=0.0,
                                payload={
                                    "tool_name": "message_node",
                                    "target_id": target_id,
                                    "result_summary": f"sent — {len(message)} chars",
                                },
                            )
                        )
                    # Side-effect only — no result to feed back

                case "read_node":
                    target_id = tool_call.arguments.get("target_id", "")
                    if target_id == "parent" and agent.parent_id:
                        logger.info("read_node: resolved 'parent' -> %s for agent %s", agent.parent_id, agent.remora_id)
                        target_id = agent.parent_id
                    target = await self.server.db.get_node(target_id)
                    if target:
                        result_text = json.dumps(
                            {
                                "name": target["name"],
                                "type": target["node_type"],
                                "source": target.get("source_code", ""),
                                "file": target.get("file_path", ""),
                            },
                            indent=2,
                        )
                        logger.info("read_node: returning %d chars for node %s", len(result_text), target_id)
                        tool_results.append({"tool": "read_node", "result": result_text})
                        # Emit event so the panel can show tool usage
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.remora_id,
                                correlation_id=correlation_id,
                                summary=f"read_node({target_id})",
                                timestamp=0.0,
                                payload={
                                    "tool_name": "read_node",
                                    "target_id": target_id,
                                    "result_summary": f"{target['name']} ({target['node_type']}) — {len(target.get('source_code', ''))} chars",
                                },
                            )
                        )
                    else:
                        logger.warning("read_node: node %s not found", target_id)
                        tool_results.append({"tool": "read_node", "result": f"Error: node {target_id!r} not found"})
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.remora_id,
                                correlation_id=correlation_id,
                                summary=f"read_node({target_id}) — not found",
                                timestamp=0.0,
                                payload={
                                    "tool_name": "read_node",
                                    "target_id": target_id,
                                    "result_summary": "not found",
                                },
                            )
                        )

                case _:
                    await self.execute_extension_tool(agent, tool_call.name, tool_call.arguments, correlation_id)

        return tool_results

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
            AgentMessageEvent(
                agent_id=from_id, from_agent=from_id, to_agent=to_id, message=message, correlation_id=correlation_id
            )
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
