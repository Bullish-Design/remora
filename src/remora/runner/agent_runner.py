from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from remora.runner.event_emitter import RunnerEventEmitter
from remora.runner.headless import _HeadlessServer
from remora.runner.models import RewriteProposal, generate_id
from remora.runner.protocols import RunnerServer
from remora.runner.tools import build_lsp_tools
from remora.runner.turn_logic import (
    apply_agent_extensions,
    append_agent_complete,
    append_agent_error,
    append_agent_start,
    create_workspace_service,
    execute_agent_turn,
    load_runner_config,
)
from remora.runner.trigger import Trigger

logger = logging.getLogger("remora.runner")

MAX_CHAIN_DEPTH = 10
EXECUTE_AGENT_TURN_TIMEOUT_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class AgentRunner:
    """Unified asynchronous agent execution coordinator.

    Merges LSP runner (tool loop, AgentNode, proposals) with core runner
    cascade-safety features (depth tracking, cooldown, concurrency semaphore).
    Usable from both the LSP server and the CLI swarm entrypoint.

    Agent execution is delegated to ``execute_agent_turn()`` from
    ``remora.core.agents.execution``, with LSP-specific tools injected via
    ``build_lsp_tools()`` from ``remora.runner.tools``.
    """

    def __init__(
        self,
        server: RunnerServer,
        *,
        config: Any | None = None,
        max_trigger_depth: int | None = None,
        trigger_cooldown_ms: int | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.server = server
        self.queue: asyncio.Queue[Trigger] = asyncio.Queue()
        self._running = False

        # Config — stored on server by __main__.py, or loaded on demand
        self._config = config

        # Cascade prevention — ported from core/agent_runner.py
        self._max_trigger_depth = max_trigger_depth if max_trigger_depth is not None else MAX_CHAIN_DEPTH
        self._trigger_cooldown_ms = trigger_cooldown_ms if trigger_cooldown_ms is not None else 1000
        self._max_concurrency = max_concurrency

        self._correlation_depth: dict[str, tuple[int, float]] = {}
        self._last_trigger_time: dict[str, float] = {}
        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._workspace_service: Any | None = None
        self._workspace_service_root: Path | None = None
        self._events = RunnerEventEmitter(server)

    @property
    def config(self) -> Any:
        """Lazily resolve configuration."""
        if self._config is None:
            self._config = load_runner_config()
        return self._config

    @classmethod
    def create_headless(
        cls,
        event_store: Any,
        *,
        config: Any | None = None,
        max_trigger_depth: int | None = None,
        trigger_cooldown_ms: int | None = None,
        max_concurrency: int = 4,
    ) -> AgentRunner:
        """Create a runner for CLI / headless mode without a full LSP server.

        Constructs a lightweight ``_HeadlessServer`` adapter around the given
        *event_store* so the runner can operate identically to the LSP-backed
        variant but without requiring Neovim or any editor connection.
        """
        server = _HeadlessServer(event_store)
        return cls(
            server,  # type: ignore[arg-type]
            config=config,
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

    async def close(self) -> None:
        """Release long-lived resources owned by the runner."""
        if self._workspace_service is None:
            return
        try:
            await self._workspace_service.close()
        except Exception:
            logger.warning("AgentRunner.close: workspace service close failed", exc_info=True)
        else:
            logger.info("AgentRunner.close: workspace service closed")
        finally:
            self._workspace_service = None
            self._workspace_service_root = None

    async def _get_workspace_service(self, project_root: Path) -> Any:
        """Return a reusable workspace service for the current project root."""
        resolved_root = project_root.resolve()
        if self._workspace_service is not None and self._workspace_service_root == resolved_root:
            return self._workspace_service

        if self._workspace_service is not None:
            logger.info(
                "AgentRunner: project root changed (%s -> %s), recycling workspace service",
                self._workspace_service_root,
                resolved_root,
            )
            await self.close()

        self._workspace_service = await create_workspace_service(self.config, resolved_root)
        self._workspace_service_root = resolved_root
        return self._workspace_service

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

    async def _accept_proposal(self, proposal_id: str) -> None:
        await self.server.accept_proposal(proposal_id)

    # ------------------------------------------------------------------
    # EventStore trigger bridge — for CLI / headless mode
    # ------------------------------------------------------------------

    async def run_from_event_store(self, event_store: Any) -> None:
        """Bridge EventStore.get_triggers() into the runner queue.

        Consumes subscription-matched triggers from the EventStore trigger
        queue and feeds them into the same ``self.trigger()`` path used by
        manual LSP handler triggers.  Deduplication is handled naturally by
        ``_check_cooldown()`` — if a handler already triggered the agent
        within the cooldown window, the subscription trigger is suppressed.

        In LSP mode this runs alongside ``run_forever()`` so that the
        reactive loop is fully closed (Gap #1).
        """
        # Wait for run_forever() to set _running before consuming triggers
        while not self._running:
            await asyncio.sleep(0.05)
        async for agent_id, _event_id, event in event_store.get_triggers():
            if not self._running:
                break
            correlation_id = getattr(event, "correlation_id", None) or self.server.generate_correlation_id()
            await self.trigger(agent_id, correlation_id, trigger_event=event)

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

        cmd_type = cmd["command_type"]
        agent_id = cmd.get("agent_id")
        payload = json.loads(cmd["payload"]) if isinstance(cmd["payload"], str) else cmd["payload"]

        logger.info("Dispatching command: type=%s agent=%s", cmd_type, agent_id)

        if cmd_type == "chat" and agent_id:
            correlation_id = self.server.generate_correlation_id()
            await self._events.emit_human_chat(
                agent_id=agent_id,
                message=payload.get("message", ""),
                correlation_id=correlation_id,
            )
            await self.trigger(agent_id, correlation_id)

        elif cmd_type == "approve_proposal":
            proposal_id = payload.get("proposal_id", "")
            if proposal_id and proposal_id in self.server.proposals:
                await self._accept_proposal(proposal_id)

        elif cmd_type == "reject_proposal":
            proposal_id = payload.get("proposal_id", "")
            feedback = payload.get("feedback", "")
            proposal = self.server.proposals.get(proposal_id)
            if proposal:
                await self._events.emit_rewrite_rejected(
                    agent_id=proposal.agent_id,
                    proposal_id=proposal_id,
                    feedback=feedback,
                    correlation_id=proposal.correlation_id or "",
                )
                await self.trigger(
                    proposal.agent_id,
                    proposal.correlation_id,
                    context={"rejection_feedback": feedback},
                )

        elif cmd_type == "execute_tool" and agent_id:
            tool_name = payload.get("tool_name", "")
            tool_params = payload.get("params", {})
            agent = await self.server.event_store.nodes.get_node(agent_id)
            if agent and tool_name:
                await self.execute_extension_tool(agent, tool_name, tool_params, self.server.generate_correlation_id())
        else:
            logger.warning("Unknown command type: %s", cmd_type)

    async def trigger(
        self, agent_id: str, correlation_id: str, context: dict | None = None, trigger_event: Any = None
    ) -> None:
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
        await self.queue.put(
            Trigger(
                agent_id=agent_id, correlation_id=correlation_id, context=context or {}, trigger_event=trigger_event
            )
        )

    async def emit_error(self, agent_id: str, error: str, correlation_id: str) -> None:
        try:
            await self._events.emit_agent_error(agent_id=agent_id, error=error, correlation_id=correlation_id)
        except Exception:
            logger.debug("emit_error: failed to emit event for %s", agent_id, exc_info=True)

    async def execute_turn(self, trigger: Trigger) -> None:
        """Execute a single agent turn.

        Handles cascade tracking, status management, and code lenses,
        then delegates actual agent execution to ``execute_agent_turn()``.
        """

        agent_id = trigger.agent_id
        correlation_id = trigger.correlation_id
        logger.info("execute_turn: START agent=%s corr=%s", agent_id, correlation_id)

        # Track cascade depth (ported from core runner)
        depth_key = f"{agent_id}:{correlation_id}"
        current_depth, _ = self._correlation_depth.get(depth_key, (0, 0.0))
        self._correlation_depth[depth_key] = (current_depth + 1, time.time())

        async with self._semaphore:
            status_start = time.monotonic()
            await self.server.event_store.nodes.set_node_status(agent_id, "running")
            logger.info(
                "execute_turn: set_node_status(running) END agent=%s duration_ms=%.1f",
                agent_id,
                (time.monotonic() - status_start) * 1000,
            )
            await self.server.refresh_code_lenses()
            await self.server.db.add_to_chain(correlation_id, agent_id)

            node_read_start = time.monotonic()
            agent = await self.server.event_store.nodes.get_node(agent_id)
            node_read_ms = (time.monotonic() - node_read_start) * 1000
            logger.info(
                "execute_turn: get_node END agent=%s duration_ms=%.1f found=%s",
                agent_id,
                node_read_ms,
                bool(agent),
            )
            if not agent:
                logger.error("execute_turn: node %s not found in EventStore!", agent_id)
                await self.emit_error(agent_id, "Node not found", correlation_id)
                return

            logger.info("execute_turn: node found: %s (%s) file=%s", agent.name, agent.node_type, agent.file_path)

            # Emit domain-level AgentStartEvent so projections populate
            # last_trigger_event (Workstream E — Gap #11)
            await append_agent_start(self.server.event_store, agent_id=agent_id, node_name=agent.name)

            try:
                agent = self.apply_extensions(agent)

                # Build chat history from correlation events
                chat_history: list[dict[str, str]] = []
                events_read_start = time.monotonic()
                events = await self.server.event_store.get_events_for_correlation(correlation_id)
                logger.info(
                    "execute_turn: get_events_for_correlation END corr=%s duration_ms=%.1f count=%d",
                    correlation_id,
                    (time.monotonic() - events_read_start) * 1000,
                    len(events),
                )
                for event in events:
                    event_type = event["event_type"]
                    payload = event.get("payload", {})
                    to_agent = event.get("to_agent")
                    from_agent = event.get("from_agent", "unknown")

                    if event_type == "HumanChatEvent" and to_agent == agent_id:
                        chat_history.append({"role": "user", "content": payload.get("message", "")})
                    elif event_type == "AgentMessageEvent" and to_agent == agent_id:
                        chat_history.append(
                            {"role": "user", "content": f"[From {from_agent}]: {payload.get('content', '')}"}
                        )
                    elif event_type == "AgentTextResponse" and event.get("agent_id") == agent_id:
                        chat_history.append({"role": "assistant", "content": payload.get("content", "")})

                if trigger.context.get("rejection_feedback"):
                    chat_history.append(
                        {
                            "role": "user",
                            "content": f"[Feedback on rejected proposal]: {trigger.context['rejection_feedback']}",
                        }
                    )

                # Build LSP-specific tools via callback injection
                async def _emit_tool_event(
                    agent_id: str, summary: str, result_summary: str, payload: dict[str, Any]
                ) -> None:
                    payload["result_summary"] = result_summary
                    await self._events.emit_agent_event(
                        event_type="ToolResultEvent",
                        agent_id=agent_id,
                        correlation_id=correlation_id,
                        summary=summary,
                        payload=payload,
                    )

                lsp_tools = build_lsp_tools(
                    agent,
                    self.server.event_store,
                    create_proposal=lambda a, src, _cid: self.create_proposal(a, src, correlation_id),
                    message_node=lambda from_id, to_id, msg, _cid: self.message_node(
                        from_id, to_id, msg, correlation_id
                    ),
                    emit_tool_event=_emit_tool_event,
                )

                # Resolve project root from workspace or cwd
                project_root = Path.cwd()
                if hasattr(self.server, "workspace") and hasattr(self.server.workspace, "root_path"):
                    root_path = getattr(self.server.workspace, "root_path", None)
                    if root_path:
                        project_root = Path(root_path)
                workspace_service = await self._get_workspace_service(project_root)

                # On-kernel-event callback: forward to LSP UI
                async def _on_kernel_event(event: Any) -> None:
                    await self._events.emit_agent_event(
                        event_type="KernelEvent",
                        agent_id=agent_id,
                        correlation_id=correlation_id,
                        summary=str(type(event).__name__),
                        payload={"event": str(event)},
                    )

                exec_start = time.monotonic()
                logger.info(
                    "execute_turn: execute_agent_turn START agent=%s corr=%s timeout_s=%.1f",
                    agent_id,
                    correlation_id,
                    EXECUTE_AGENT_TURN_TIMEOUT_SECONDS,
                )
                try:
                    result = await asyncio.wait_for(
                        execute_agent_turn(
                            node=agent,
                            config=self.config,
                            event_store=self.server.event_store,
                            subscriptions=getattr(self.server, "subscriptions", None),
                            swarm_id="swarm",
                            project_root=project_root,
                            workspace_service=workspace_service,
                            extra_tools=lsp_tools,
                            on_kernel_event=_on_kernel_event,
                            chat_history=chat_history,
                            trigger_event=trigger.trigger_event,
                        ),
                        timeout=EXECUTE_AGENT_TURN_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    duration_ms = (time.monotonic() - exec_start) * 1000
                    logger.error(
                        "execute_turn: execute_agent_turn TIMEOUT agent=%s corr=%s duration_ms=%.1f timeout_s=%.1f",
                        agent_id,
                        correlation_id,
                        duration_ms,
                        EXECUTE_AGENT_TURN_TIMEOUT_SECONDS,
                    )
                    raise RuntimeError(
                        f"execute_agent_turn timed out after {EXECUTE_AGENT_TURN_TIMEOUT_SECONDS:.1f}s"
                    ) from None
                logger.info(
                    "execute_turn: execute_agent_turn END agent=%s corr=%s duration_ms=%.1f",
                    agent_id,
                    correlation_id,
                    (time.monotonic() - exec_start) * 1000,
                )

                # Emit final text response if present
                if result.response_text:
                    await self._events.emit_agent_text_response(
                        agent_id=agent_id,
                        correlation_id=correlation_id,
                        content=result.response_text,
                        summary=result.response_text[:200],
                    )

                # Emit domain-level AgentCompleteEvent so projections
                # populate last_completed_at (Workstream E — Gap #11)
                await append_agent_complete(
                    self.server.event_store,
                    agent_id=agent_id,
                    result_summary=result.response_text[:200] if result.response_text else "",
                    trigger_event=trigger.trigger_event,
                )

            except Exception as e:
                # Emit domain-level AgentErrorEvent so projections set
                # status = 'error' (Workstream E — Gap #11)
                await append_agent_error(self.server.event_store, agent_id=agent_id, error=str(e))
                await self.emit_error(agent_id, str(e), correlation_id)
            finally:
                # Decrement depth tracking
                depth, ts = self._correlation_depth.get(depth_key, (1, time.time()))
                remaining = depth - 1
                if remaining <= 0:
                    self._correlation_depth.pop(depth_key, None)
                else:
                    self._correlation_depth[depth_key] = (remaining, ts)

                await self.server.event_store.nodes.set_node_status(agent_id, "idle")
                await self.server.refresh_code_lenses()

    async def create_proposal(self, agent: Any, new_source: str, correlation_id: str) -> None:

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
        await self.server.event_store.nodes.set_node_status(agent.node_id, "pending_approval")
        await self.server.db.store_proposal(
            proposal_id, agent.node_id, agent.source_code, new_source, proposal.diff, file_path=agent.file_path
        )

        await self.server.publish_diagnostics(agent.file_path, [proposal])
        await self.server.refresh_code_lenses()

        await self._events.emit_rewrite_proposal(
            agent_id=agent.node_id,
            proposal_id=proposal_id,
            diff=proposal.diff,
            correlation_id=correlation_id,
        )

    async def message_node(self, from_id: str, to_id: str, message: str, correlation_id: str) -> None:

        await self._events.emit_agent_message(
            from_agent=from_id,
            to_agent=to_id,
            message=message,
            correlation_id=correlation_id,
        )
        await self.trigger(to_id, correlation_id)

    async def refresh_code_lens(self, agent_id: str) -> None:

        node = await self.server.event_store.nodes.get_node(agent_id)
        if node:
            await self.server.refresh_code_lenses()

    def apply_extensions(self, agent: Any) -> Any:
        return apply_agent_extensions(agent)

    def get_agent_tools(self, agent: Any) -> list[dict]:
        """Return the list of tools available to this agent."""
        async def _dummy(*args: Any, **kwargs: Any) -> None:
            pass

        lsp_tools = build_lsp_tools(
            agent,
            self.server.event_store,
            create_proposal=_dummy,
            message_node=_dummy,
            emit_tool_event=_dummy,
        )

        raw_tools = []
        for t in lsp_tools:
            # Format to dict with "function" key containing "name" and "description"
            s = t.schema
            raw_tools.append({
                "function": {
                    "name": s.name,
                    "description": s.description
                }
            })
            
        # Also include any built-in tools that unstructured agents could have
        return raw_tools

    async def execute_extension_tool(self, agent: Any, tool_name: str, params: dict, correlation_id: str) -> None:
        await self._events.emit_agent_event(
            event_type="ToolResultEvent",
            agent_id=agent.node_id,
            correlation_id=correlation_id,
            summary=f"Tool {tool_name} executed",
            payload={"tool_name": tool_name, "params": params},
        )
