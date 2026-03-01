"""Agent Runner for reactive execution.

The AgentRunner consumes triggers from EventStore and executes agent turns.
It implements cascade prevention via depth limits and cooldowns.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from remora.core.config import Config
from remora.core.event_store import EventStore
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    AgentStartEvent,
    RemoraEvent,
)
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import SwarmState
from remora.core.agent_state import AgentState, load as load_agent_state, save as save_agent_state
from remora.core.reconciler import get_agent_state_path
from remora.core.swarm_executor import SwarmExecutor

if TYPE_CHECKING:
    from remora.core.event_bus import EventBus

logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Context for a single agent turn."""

    agent_id: str
    trigger_event: RemoraEvent
    state: AgentState


class AgentRunner:
    """Reactive agent runner that processes EventStore triggers."""

    def __init__(
        self,
        event_store: EventStore,
        subscriptions: SubscriptionRegistry,
        swarm_state: SwarmState,
        config: Config,
        event_bus: "EventBus | None" = None,
        project_root: Path | None = None,
    ):
        self._event_store = event_store
        self._subscriptions = subscriptions
        self._swarm_state = swarm_state
        self._config = config
        self._event_bus = event_bus
        self._project_root = project_root or Path.cwd()

        self._max_concurrency = config.max_concurrency
        self._max_trigger_depth = config.max_trigger_depth
        self._trigger_cooldown_ms = config.trigger_cooldown_ms

        self._swarm_id = getattr(config, "swarm_id", "swarm")

        self._executor = SwarmExecutor(
            config=config,
            event_bus=event_bus,
            event_store=event_store,
            subscriptions=subscriptions,
            swarm_state=swarm_state,
            swarm_id=self._swarm_id,
            project_root=self._project_root,
        )

        # depth, timestamp mapping
        self._correlation_depth: dict[str, tuple[int, float]] = {}
        self._last_trigger_time: dict[str, float] = {}

        self._semaphore = asyncio.Semaphore(self._max_concurrency)
        self._running = False
        self._tasks: set[asyncio.Task] = set()

    async def run_forever(self) -> None:
        """Main loop - process triggers from EventStore."""
        self._running = True
        logger.info("AgentRunner started")
        
        cleanup_task = asyncio.create_task(self._cleanup_loop())

        try:
            async for agent_id, event_id, event in self._event_store.get_triggers():
                logger.info(f"AgentRunner: Received trigger for {agent_id} (event_id={event_id})")
                if not self._running:
                    break

                if not self._check_cooldown(agent_id):
                    logger.debug(f"Skipping trigger for {agent_id} due to cooldown")
                    continue

                correlation_id = self._normalize_correlation_id(event)
                if not self._check_depth_limit(agent_id, correlation_id):
                    logger.warning(f"Skipping trigger for {agent_id} due to depth limit")
                    continue

                logger.info(f"AgentRunner: Processing trigger for {agent_id}")
                task = asyncio.create_task(self._process_trigger(agent_id, event_id, event, correlation_id))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        except asyncio.CancelledError:
            logger.info("AgentRunner cancelled")
        finally:
            cleanup_task.cancel()
            await self._cancel_pending()

    async def _cleanup_loop(self) -> None:
        """Periodically clean up stale correlation depth entries."""
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            # TTL of 300 seconds (5 minutes)
            stale_keys = [
                k for k, v in self._correlation_depth.items()
                if now - v[1] > 300
            ]
            for k in stale_keys:
                self._correlation_depth.pop(k, None)

    def _check_cooldown(self, agent_id: str) -> bool:
        """Check if the agent is within cooldown period."""
        now = time.time() * 1000
        last_time = self._last_trigger_time.get(agent_id, 0)
        if now - last_time < self._trigger_cooldown_ms:
            return False
        self._last_trigger_time[agent_id] = now
        return True

    def _check_depth_limit(self, agent_id: str, correlation_id: str) -> bool:
        """Check if the cascade depth limit is reached."""
        key = f"{agent_id}:{correlation_id}"
        depth, _ = self._correlation_depth.get(key, (0, 0.0))
        return depth < self._max_trigger_depth

    def _normalize_correlation_id(self, event: RemoraEvent) -> str:
        """Ensure every event has a correlation identifier."""
        return (
            getattr(event, "correlation_id", None)
            or getattr(event, "id", None)
            or "base"
        )

    async def _process_trigger(
        self,
        agent_id: str,
        event_id: int,
        event: RemoraEvent,
        correlation_id: str,
    ) -> None:
        """Process a single trigger."""
        async with self._semaphore:
            key = f"{agent_id}:{correlation_id}"
            current_depth, _ = self._correlation_depth.get(key, (0, 0.0))

            if current_depth >= self._max_trigger_depth:
                logger.warning(f"Cascade limit reached for {key}")
                return

            now = time.time()
            self._correlation_depth[key] = (current_depth + 1, now)

            try:
                await self._execute_turn(agent_id, event)
            except Exception as e:
                logger.exception(f"Error processing trigger for {agent_id}: {e}")
                await self._emit_error(agent_id, str(e))
            finally:
                key = f"{agent_id}:{correlation_id}"
                depth, ts = self._correlation_depth.get(key, (1, time.time()))
                remaining = depth - 1
                if remaining <= 0:
                    self._correlation_depth.pop(key, None)
                else:
                    self._correlation_depth[key] = (remaining, ts)

    async def _execute_turn(self, agent_id: str, trigger_event: RemoraEvent) -> None:
        """Execute a single agent turn."""
        state_path = get_agent_state_path(
            self._project_root / ".remora",
            agent_id,
        )
        logger.info("Looking for state at %s", state_path)
        state = load_agent_state(state_path)
        if state is None:
            logger.error("No state file found for agent %s at %s", agent_id, state_path)
            if self._event_bus:
                await self._event_bus.emit(
                    AgentErrorEvent(
                        graph_id=self._swarm_id,
                        agent_id=agent_id,
                        error=f"Agent state not found at {state_path}",
                    )
                )
            return

        context = ExecutionContext(
            agent_id=agent_id,
            trigger_event=trigger_event,
            state=state,
        )

        if self._event_bus:
            await self._event_bus.emit(
                AgentStartEvent(
                    graph_id=self._swarm_id,
                    agent_id=agent_id,
                    node_name=state.node_type,
                )
            )

        try:
            result = await self._run_agent(context)

            save_agent_state(state_path, state)

            if self._event_bus:
                complete_event = AgentCompleteEvent(
                    graph_id=self._swarm_id,
                    agent_id=agent_id,
                    result_summary=str(result)[:200] if result else "",
                )
                logger.info(f"Emitting AgentCompleteEvent for {agent_id}")
                await self._event_bus.emit(complete_event)

        except Exception as e:
            logger.exception(f"Error executing agent {agent_id}: {e}")
            save_agent_state(state_path, state)

            if self._event_bus:
                await self._event_bus.emit(
                    AgentErrorEvent(
                        graph_id=self._swarm_id,
                        agent_id=agent_id,
                        error=str(e),
                    )
                )

    async def _run_agent(self, context: ExecutionContext) -> Any:
        """Run the actual agent logic using SwarmExecutor."""
        logger.info(f"Running agent {context.agent_id} with trigger {type(context.trigger_event).__name__}")
        result = await self._executor.run_agent(context.state, context.trigger_event)
        return result

    async def _emit_error(self, agent_id: str, error: str) -> None:
        """Emit an error event."""
        if self._event_bus:
            await self._event_bus.emit(
                AgentErrorEvent(
                    graph_id="",
                    agent_id=agent_id,
                    error=error,
                )
            )

    async def _cancel_pending(self) -> None:
        """Cancel all pending tasks."""
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def stop(self) -> None:
        """Stop the runner gracefully."""
        self._running = False
        await self._cancel_pending()
        await self._event_store.close()
        await self._subscriptions.close()


__all__ = ["AgentRunner", "ExecutionContext"]
