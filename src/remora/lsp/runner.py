from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field, ConfigDict

from remora.core.agent_node import AgentNode
from remora.extensions import extension_matches, load_extensions
from remora.lsp.models import (
    AgentErrorEvent,
    AgentEvent,
    AgentMessageEvent,
    HumanChatEvent,
    RewriteProposal,
    RewriteProposalEvent,
    generate_id,
)

if TYPE_CHECKING:
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


class _HeadlessDB:
    """Minimal DB stub for headless (CLI) mode — no real persistence."""

    async def get_activation_chain(self, correlation_id: str) -> list[str]:
        return []

    async def add_to_chain(self, correlation_id: str, agent_id: str) -> None:
        pass

    async def store_proposal(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def poll_commands(self, limit: int) -> list[dict]:
        return []

    async def mark_command_done(self, cmd_id: str) -> None:
        pass


class _HeadlessServer:
    """Lightweight adapter that satisfies ``AgentRunner``'s ``server`` duck-type
    without requiring a full LSP ``RemoraLanguageServer``.

    Used by ``AgentRunner.create_headless()`` for CLI / headless operation.
    """

    def __init__(self, event_store: Any) -> None:
        self.event_store = event_store
        self.db = _HeadlessDB()
        self.proposals: dict[str, Any] = {}

    def generate_correlation_id(self) -> str:
        return uuid.uuid4().hex[:12]


class AgentRunner:
    """Unified asynchronous agent execution coordinator.

    Merges LSP runner (tool loop, AgentNode, proposals) with core runner
    cascade-safety features (depth tracking, cooldown, concurrency semaphore).
    Usable from both the LSP server and the CLI swarm entrypoint.
    """

    def __init__(
        self,
        server: "RemoraLanguageServer",
        llm: LLMClient | None = None,
        *,
        max_trigger_depth: int | None = None,
        trigger_cooldown_ms: int | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.server = server
        self.llm = llm
        self.queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._running = False

        # Cascade prevention — ported from core/agent_runner.py
        self._max_trigger_depth = max_trigger_depth if max_trigger_depth is not None else MAX_CHAIN_DEPTH
        self._trigger_cooldown_ms = trigger_cooldown_ms if trigger_cooldown_ms is not None else 1000
        self._max_concurrency = max_concurrency

        self._correlation_depth: dict[str, tuple[int, float]] = {}
        self._last_trigger_time: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(self._max_concurrency)

    @classmethod
    def create_headless(
        cls,
        event_store: Any,
        llm: LLMClient | None = None,
        *,
        max_trigger_depth: int | None = None,
        trigger_cooldown_ms: int | None = None,
        max_concurrency: int = 4,
    ) -> "AgentRunner":
        """Create a runner for CLI / headless mode without a full LSP server.

        Constructs a lightweight ``_HeadlessServer`` adapter around the given
        *event_store* so the runner can operate identically to the LSP-backed
        variant but without requiring Neovim or any editor connection.
        """
        server = _HeadlessServer(event_store)
        return cls(
            server,  # type: ignore[arg-type]
            llm=llm,
            max_trigger_depth=max_trigger_depth,
            trigger_cooldown_ms=trigger_cooldown_ms,
            max_concurrency=max_concurrency,
        )

    async def run_forever(self) -> None:
        self._running = True
        logger.info("AgentRunner.run_forever: started, waiting for triggers")
        # Start command queue polling as a background task
        poll_task = asyncio.create_task(self.poll_command_queue())
        try:
            while self._running:
                trigger = await self.queue.get()
                logger.info(
                    "AgentRunner.run_forever: dequeued trigger agent=%s corr=%s",
                    trigger.agent_id,
                    trigger.correlation_id,
                )
                await self.execute_turn(trigger)
        finally:
            poll_task.cancel()

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Cascade prevention — ported from core/agent_runner.py
    # ------------------------------------------------------------------

    def _check_depth_limit(self, agent_id: str, correlation_id: str) -> bool:
        """Return True if the cascade depth limit has NOT been reached."""
        key = f"{agent_id}:{correlation_id}"
        depth, _ = self._correlation_depth.get(key, (0, 0.0))
        return depth < self._max_trigger_depth

    def _check_cooldown(self, agent_id: str) -> bool:
        """Return True if the agent is NOT within cooldown period."""
        now = time.time() * 1000  # milliseconds
        last_time = self._last_trigger_time.get(agent_id, 0)
        if now - last_time < self._trigger_cooldown_ms:
            return False
        self._last_trigger_time[agent_id] = now
        return True

    def _cleanup_stale_depths(self, ttl: float = 300.0) -> None:
        """Remove correlation depth entries older than *ttl* seconds."""
        now = time.time()
        stale = [k for k, (_, ts) in self._correlation_depth.items() if now - ts > ttl]
        for k in stale:
            self._correlation_depth.pop(k, None)

    # ------------------------------------------------------------------
    # EventStore trigger bridge — for CLI / headless mode
    # ------------------------------------------------------------------

    async def run_from_event_store(self, event_store: Any) -> None:
        """Bridge EventStore.get_triggers() into the runner queue.

        This allows the CLI ``swarm run`` command to feed subscription-matched
        triggers into the same unified runner without the LSP server.
        """
        async for agent_id, event_id, event in event_store.get_triggers():
            if not self._running:
                break
            correlation_id = getattr(event, "correlation_id", None) or self.server.generate_correlation_id()
            await self.trigger(agent_id, correlation_id)

    async def poll_command_queue(self) -> None:
        """Poll the command_queue table and dispatch commands."""
        while self._running:
            try:
                commands = await asyncio.to_thread(self.server.db.poll_commands, 10)
                for cmd in commands:
                    await self._dispatch_command(cmd)
                    await asyncio.to_thread(self.server.db.mark_command_done, cmd["id"])
            except Exception:
                logger.debug("Command queue poll error", exc_info=True)
            await asyncio.sleep(1.0)

    async def _dispatch_command(self, cmd: dict) -> None:
        """Dispatch a single command from the queue."""
        from remora.lsp.server import emit_event

        cmd_type = cmd["command_type"]
        agent_id = cmd.get("agent_id")
        payload = json.loads(cmd["payload"]) if isinstance(cmd["payload"], str) else cmd["payload"]

        logger.info("Dispatching command: type=%s agent=%s", cmd_type, agent_id)

        if cmd_type == "chat" and agent_id:
            correlation_id = self.server.generate_correlation_id()
            from remora.lsp.models import HumanChatEvent

            await emit_event(
                HumanChatEvent(
                    agent_id=agent_id,
                    to_agent=agent_id,
                    message=payload.get("message", ""),
                    correlation_id=correlation_id,
                    timestamp=0.0,
                )
            )
            await self.trigger(agent_id, correlation_id)

        elif cmd_type == "approve_proposal":
            proposal_id = payload.get("proposal_id", "")
            if proposal_id and proposal_id in self.server.proposals:
                from remora.lsp.handlers.commands import cmd_accept_proposal

                await cmd_accept_proposal(self.server, proposal_id)

        elif cmd_type == "reject_proposal":
            proposal_id = payload.get("proposal_id", "")
            feedback = payload.get("feedback", "")
            proposal = self.server.proposals.get(proposal_id)
            if proposal:
                from remora.lsp.models import RewriteRejectedEvent

                await emit_event(
                    RewriteRejectedEvent(
                        agent_id=proposal.agent_id,
                        proposal_id=proposal_id,
                        feedback=feedback,
                        correlation_id=proposal.correlation_id or "",
                        timestamp=0.0,
                    )
                )
                await self.trigger(
                    proposal.agent_id,
                    proposal.correlation_id,
                    context={"rejection_feedback": feedback},
                )

        elif cmd_type == "execute_tool" and agent_id:
            tool_name = payload.get("tool_name", "")
            tool_params = payload.get("params", {})
            agent = await self.server.event_store.get_node(agent_id)
            if agent and tool_name:
                await self.execute_extension_tool(agent, tool_name, tool_params, self.server.generate_correlation_id())
        else:
            logger.warning("Unknown command type: %s", cmd_type)

    async def trigger(self, agent_id: str, correlation_id: str, context: dict | None = None) -> None:
        logger.info("AgentRunner.trigger: agent=%s corr=%s context=%r", agent_id, correlation_id, context)

        # In-memory cooldown check (ported from core runner)
        if not self._check_cooldown(agent_id):
            logger.debug("AgentRunner.trigger: cooldown active for %s — skipping", agent_id)
            return

        # In-memory depth check (ported from core runner)
        if not self._check_depth_limit(agent_id, correlation_id):
            logger.warning("AgentRunner.trigger: in-memory depth limit for %s — skipping", agent_id)
            await self.emit_error(agent_id, "Cascade depth limit exceeded", correlation_id)
            return

        # DB-backed chain depth check (existing LSP runner logic)
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

        # Track cascade depth (ported from core runner)
        depth_key = f"{agent_id}:{correlation_id}"
        current_depth, _ = self._correlation_depth.get(depth_key, (0, 0.0))
        self._correlation_depth[depth_key] = (current_depth + 1, time.time())

        async with self._semaphore:
            await self.server.event_store.set_node_status(agent_id, "running")
            await refresh_code_lenses()
            await self.server.db.add_to_chain(correlation_id, agent_id)

            agent = await self.server.event_store.get_node(agent_id)
            if not agent:
                logger.error("execute_turn: node %s not found in EventStore!", agent_id)
                await self.emit_error(agent_id, "Node not found", correlation_id)
                return

            logger.info("execute_turn: node found: %s (%s) file=%s", agent.name, agent.node_type, agent.file_path)

            try:
                agent = self.apply_extensions(agent)

                messages = [
                    {"role": "system", "content": agent.to_system_prompt()},
                ]

                events = await self.server.event_store.get_events_for_correlation(correlation_id)
                logger.info("execute_turn: %d events for correlation %s", len(events), correlation_id)
                for event in events:
                    event_type = event["event_type"]
                    payload = event.get("payload", {})
                    if event_type == "HumanChatEvent" and payload.get("to_agent") == agent_id:
                        messages.append({"role": "user", "content": payload.get("message", "")})
                    elif event_type == "AgentMessageEvent" and payload.get("to_agent") == agent_id:
                        from_agent = payload.get("from_agent", "unknown")
                        messages.append(
                            {"role": "user", "content": f"[From {from_agent}]: {payload.get('message', '')}"}
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
                # Decrement depth tracking
                depth, ts = self._correlation_depth.get(depth_key, (1, time.time()))
                remaining = depth - 1
                if remaining <= 0:
                    self._correlation_depth.pop(depth_key, None)
                else:
                    self._correlation_depth[depth_key] = (remaining, ts)

                await self.server.event_store.set_node_status(agent_id, "idle")
                await refresh_code_lenses()

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

    async def handle_response(self, agent: AgentNode, response: LLMResponse, correlation_id: str) -> list[dict]:
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
                    agent.node_id,
                )

        if not tool_calls:
            # Text-only response — emit as an event so the UI can show it
            if response.content:
                logger.info("Agent %s responded with text: %s", agent.node_id, response.content[:200])
                await emit_event(
                    AgentEvent(
                        event_type="AgentTextResponse",
                        agent_id=agent.node_id,
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
                            agent_id=agent.node_id,
                            correlation_id=correlation_id,
                            summary="rewrite_self",
                            timestamp=0.0,
                            payload={
                                "tool_name": "rewrite_self",
                                "target_id": agent.node_id,
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
                            "message_node: resolved 'parent' -> %s for agent %s", agent.parent_id, agent.node_id
                        )
                        target_id = agent.parent_id
                    message = tool_call.arguments.get("message", "")
                    if not target_id or target_id == "parent":
                        logger.warning(
                            "message_node: unresolved target_id=%r for agent %s (no parent?)",
                            target_id,
                            agent.node_id,
                        )
                        await self.emit_error(
                            agent.node_id, f"Cannot resolve message target: {target_id!r}", correlation_id
                        )
                    else:
                        await self.message_node(agent.node_id, target_id, message, correlation_id)
                        # Emit event so the panel can show the tool call
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.node_id,
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
                        logger.info("read_node: resolved 'parent' -> %s for agent %s", agent.parent_id, agent.node_id)
                        target_id = agent.parent_id
                    target = await self.server.event_store.get_node(target_id)
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
                        tool_results.append({"tool": "read_node", "result": result_text})
                        # Emit event so the panel can show tool usage
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.node_id,
                                correlation_id=correlation_id,
                                summary=f"read_node({target_id})",
                                timestamp=0.0,
                                payload={
                                    "tool_name": "read_node",
                                    "target_id": target_id,
                                    "result_summary": f"{target.name} ({target.node_type}) — {len(target.source_code)} chars",
                                },
                            )
                        )
                    else:
                        logger.warning("read_node: node %s not found", target_id)
                        tool_results.append({"tool": "read_node", "result": f"Error: node {target_id!r} not found"})
                        await emit_event(
                            AgentEvent(
                                event_type="ToolResultEvent",
                                agent_id=agent.node_id,
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

    async def create_proposal(self, agent: AgentNode, new_source: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event, publish_diagnostics, refresh_code_lenses

        proposal_id = generate_id()
        proposal = RewriteProposal(
            proposal_id=proposal_id,
            agent_id=agent.node_id,
            file_path=agent.file_path,
            old_source=agent.source_code,
            new_source=new_source,
            start_line=agent.start_line,
            end_line=agent.end_line,
            correlation_id=correlation_id,
        )

        self.server.proposals[proposal_id] = proposal
        await self.server.event_store.set_node_status(agent.node_id, "pending_approval")
        await self.server.db.store_proposal(
            proposal_id, agent.node_id, agent.source_code, new_source, proposal.diff, file_path=agent.file_path
        )

        await publish_diagnostics(agent.file_path, [proposal])
        await refresh_code_lenses()

        await emit_event(
            RewriteProposalEvent(
                agent_id=agent.node_id,
                proposal_id=proposal_id,
                diff=proposal.diff,
                correlation_id=correlation_id,
                timestamp=0.0,
            )
        )

    async def message_node(self, from_id: str, to_id: str, message: str, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        await emit_event(
            AgentMessageEvent(
                agent_id=from_id,
                from_agent=from_id,
                to_agent=to_id,
                message=message,
                correlation_id=correlation_id,
                timestamp=0.0,
            )
        )
        await self.trigger(to_id, correlation_id)

    async def refresh_code_lens(self, agent_id: str) -> None:
        from remora.lsp.server import refresh_code_lenses

        node = await self.server.event_store.get_node(agent_id)
        if node:
            await refresh_code_lenses()

    def get_agent_tools(self, agent: AgentNode) -> list[dict]:
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
                            "target_id": {"type": "string", "description": "The node_id of the target agent"},
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
                            "target_id": {"type": "string", "description": "The node_id of the target agent"}
                        },
                        "required": ["target_id"],
                    },
                },
            },
        ]

        for tool in agent.extra_tools:
            tools.append(tool.to_llm_tool())

        return tools

    def apply_extensions(self, agent: AgentNode) -> AgentNode:
        extensions = load_extensions(Path(".remora/models"))

        for ext_cls in extensions:
            if extension_matches(
                ext_cls,
                agent.node_type,
                agent.name,
                file_path=agent.file_path,
                source_code=agent.source_code,
            ):
                data = ext_cls.get_extension_data()
                for key, value in data.items():
                    if hasattr(agent, key):
                        setattr(agent, key, value)
                break

        return agent

    async def execute_extension_tool(self, agent: AgentNode, tool_name: str, params: dict, correlation_id: str) -> None:
        from remora.lsp.server import emit_event

        await emit_event(
            AgentEvent(
                event_type="ToolResultEvent",
                agent_id=agent.node_id,
                correlation_id=correlation_id,
                summary=f"Tool {tool_name} executed",
                timestamp=0.0,
                payload={"tool_name": tool_name, "params": params},
            )
        )
