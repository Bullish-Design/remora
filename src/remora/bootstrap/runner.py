"""Bootstrap runtime loop for node-to-agent assignment.

PHASE-1 SCAFFOLDING
-------------------
The coordinator currently runs as Python code in this module so bootstrap can
start itself before coordinator-agent infrastructure is fully online.

Current responsibilities:
1. Seed coordinator/module nodes.
2. Find unassigned nodes.
3. Emit AgentNeededEvent for each plan.
4. Activate each target agent directly.

Target phase:
- Replace this loop with an event-driven LLM coordinator
  (see ``bootstrap/agents/coordinator.yaml``).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from remora.bootstrap.activation import handle_agent_needed
from remora.bootstrap.bedrock import BootstrapEvent
from remora.bootstrap.coordinator import (
    AgentNeededPlan,
    find_unassigned_nodes,
)
from remora.bootstrap.seed_graph import seed_coordinator_node, seed_modules_if_empty
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.code.projections import NodeProjection
from remora.core.config import Config
from remora.core.events.subscriptions import SubscriptionRegistry
from remora.core.runtime_paths import RuntimePaths
from remora.core.store.event_store import EventStore

logger = logging.getLogger(__name__)


class BootstrapRunner:
    """Drive bootstrap agent assignment for discovered module nodes."""

    def __init__(
        self,
        config: Config,
        *,
        project_root: Path | None = None,
        bootstrap_root: Path | None = None,
        event_store_path: Path | None = None,
        subscriptions_path: Path | None = None,
        coordinator_id: str = "coordinator",
        node_types: set[str] | None = None,
        event_store: EventStore | None = None,
        subscriptions: SubscriptionRegistry | None = None,
        workspace_service: CairnWorkspaceService | None = None,
    ) -> None:
        self.config = config
        self.paths = RuntimePaths.from_config(
            config,
            project_root=project_root,
            bootstrap_root=bootstrap_root,
        )
        self.project_root = self.paths.project_root
        self.bootstrap_root = self.paths.bootstrap_root
        self.coordinator_id = coordinator_id
        self.swarm_id = config.swarm_id
        self.node_types: set[str] = set(node_types) if node_types is not None else {"file"}

        self.event_store_path = event_store_path or self.paths.event_store_path
        self.subscriptions_path = subscriptions_path or self.paths.subscriptions_path

        self._subscriptions: SubscriptionRegistry | None = subscriptions
        self._event_store: EventStore | None = event_store
        self._workspace_service: CairnWorkspaceService | None = workspace_service
        self._owns_subscriptions = subscriptions is None
        self._owns_event_store = event_store is None
        self._owns_workspace_service = workspace_service is None
        self._initialized = False
        self._running = False
        self._activation_lock = asyncio.Lock()

    @property
    def subscriptions(self) -> SubscriptionRegistry:
        if self._subscriptions is None:
            raise RuntimeError("BootstrapRunner is not initialized")
        return self._subscriptions

    @property
    def event_store(self) -> EventStore:
        if self._event_store is None:
            raise RuntimeError("BootstrapRunner is not initialized")
        return self._event_store

    @property
    def workspace_service(self) -> CairnWorkspaceService:
        if self._workspace_service is None:
            raise RuntimeError("BootstrapRunner is not initialized")
        return self._workspace_service

    async def initialize(self) -> None:
        if self._initialized:
            return

        subscriptions = self._subscriptions
        if subscriptions is None:
            subscriptions = SubscriptionRegistry(self.subscriptions_path)
            await subscriptions.initialize()
            self._subscriptions = subscriptions

        event_store = self._event_store
        if event_store is None:
            event_store = EventStore(
                self.event_store_path,
                subscriptions=subscriptions,
                projection=NodeProjection(),
            )
            await event_store.initialize()
            self._event_store = event_store

        workspace_service = self._workspace_service
        if workspace_service is None:
            workspace_service = CairnWorkspaceService(
                self.config,
                graph_id=self.swarm_id,
                project_root=self.project_root,
            )
            self._workspace_service = workspace_service

        await seed_coordinator_node(event_store, coordinator_id=self.coordinator_id)
        await seed_modules_if_empty(event_store, self.project_root, swarm_id=self.swarm_id)
        self._initialized = True

    def _build_agent_needed_event(self, *, node_id: str, agent_id: str) -> BootstrapEvent:
        return BootstrapEvent(
            event_type="AgentNeededEvent",
            node_id=node_id,
            payload={"node_id": node_id, "agent_id": agent_id},
            from_agent=self.coordinator_id,
            tags=("bootstrap", "agent-needed"),
        )

    async def _emit_events_for_plans(self, plans: list[AgentNeededPlan]) -> None:
        """Emit AgentNeededEvent for each already-resolved activation plan."""
        for plan in plans:
            await self.event_store.append(
                self.swarm_id,
                self._build_agent_needed_event(node_id=plan.node_id, agent_id=plan.agent_id),
            )

    async def run_once(self) -> int:
        """Run one coordinator pass and activate newly needed agents.

        Phase-1 note: coordinator logic is Python-driven here. The coordinator
        schema in ``bootstrap/agents/coordinator.yaml`` is aspirational and is
        not activated by this loop yet.
        """
        await self.initialize()
        async with self._activation_lock:
            plans = await find_unassigned_nodes(
                self.event_store,
                node_types=self.node_types,
            )
            if not plans:
                return 0

            await self._emit_events_for_plans(plans)
            return await self._activate_plans(plans, parallel=False)

    async def run_for_file(self, file_path: str) -> int:
        """Activate bootstrap agents for all unassigned nodes in a file."""
        await self.initialize()
        async with self._activation_lock:
            plans = await find_unassigned_nodes(
                self.event_store,
                file_path=file_path,
                node_types=self.node_types,
            )
            if not plans:
                return 0

            await self._emit_events_for_plans(plans)
            return await self._activate_plans(plans, parallel=True)

    async def handle_human_input_response(
        self,
        *,
        agent_id: str,
        node_id: str,
        request_id: str,
        response: str,
        question: str | None = None,
    ) -> bool:
        """Append a human response event and re-activate the target bootstrap agent."""
        await self.initialize()
        async with self._activation_lock:
            event_payload = {
                "node_id": node_id,
                "agent_id": agent_id,
                "request_id": request_id,
                "response": response,
                "kind": "user_question_response",
            }
            if question:
                event_payload["question"] = question

            event = BootstrapEvent(
                event_type="HumanInputResponseEvent",
                node_id=node_id,
                payload=event_payload,
                from_agent="human",
                to_agent=agent_id,
                tags=("bootstrap", "human-input"),
            )

            await self.event_store.append(self.swarm_id, event)

            try:
                await handle_agent_needed(
                    event,
                    workspace_service=self.workspace_service,
                    subscriptions=self.subscriptions,
                    event_store=self.event_store,
                    config=self.config,
                    swarm_id=self.swarm_id,
                    bootstrap_root=self.bootstrap_root,
                )
            except Exception:
                logger.exception(
                    "Bootstrap human-input activation failed for agent=%s node=%s request_id=%s",
                    agent_id,
                    node_id,
                    request_id,
                )
                return False
            return True

    async def _activate_plans(self, plans: list[AgentNeededPlan], *, parallel: bool) -> int:
        if not plans:
            return 0

        if not parallel:
            handled = 0
            for plan in plans:
                event = self._build_agent_needed_event(node_id=plan.node_id, agent_id=plan.agent_id)
                try:
                    await handle_agent_needed(
                        event,
                        workspace_service=self.workspace_service,
                        subscriptions=self.subscriptions,
                        event_store=self.event_store,
                        config=self.config,
                        swarm_id=self.swarm_id,
                        bootstrap_root=self.bootstrap_root,
                    )
                    handled += 1
                except Exception:
                    logger.exception(
                        "Bootstrap activation failed for agent=%s node=%s",
                        plan.agent_id,
                        plan.node_id,
                    )
            return handled

        events = [self._build_agent_needed_event(node_id=plan.node_id, agent_id=plan.agent_id) for plan in plans]
        results = await asyncio.gather(
            *[
                handle_agent_needed(
                    event,
                    workspace_service=self.workspace_service,
                    subscriptions=self.subscriptions,
                    event_store=self.event_store,
                    config=self.config,
                    swarm_id=self.swarm_id,
                    bootstrap_root=self.bootstrap_root,
                )
                for event in events
            ],
            return_exceptions=True,
        )

        handled = 0
        for plan, result in zip(plans, results, strict=True):
            if isinstance(result, Exception):
                logger.error(
                    "Bootstrap activation failed for agent=%s node=%s: %s",
                    plan.agent_id,
                    plan.node_id,
                    result,
                    exc_info=(type(result), result, result.__traceback__),
                )
                continue
            handled += 1

        return handled

    async def run_forever(self, *, poll_interval_s: float = 0.5) -> None:
        """Continuously assign and activate agents for unassigned nodes."""
        await self.initialize()
        self._running = True
        try:
            while self._running:
                handled = await self.run_once()
                if handled == 0:
                    await asyncio.sleep(max(0.0, poll_interval_s))
        finally:
            self._running = False

    def stop(self) -> None:
        self._running = False

    async def close(self) -> None:
        self._running = False

        if self._workspace_service is not None and self._owns_workspace_service:
            with contextlib.suppress(Exception):
                await self._workspace_service.close()
            self._workspace_service = None

        if self._event_store is not None and self._owns_event_store:
            with contextlib.suppress(Exception):
                await self._event_store.close()
            self._event_store = None

        if self._subscriptions is not None and self._owns_subscriptions:
            with contextlib.suppress(Exception):
                await self._subscriptions.close()
            self._subscriptions = None

        self._initialized = False


async def run_bootstrap(config: Config, *, project_root: Path | None = None, bootstrap_root: Path | None = None) -> None:
    """Run the bootstrap runtime loop until cancelled/stopped."""
    runner = BootstrapRunner(config, project_root=project_root, bootstrap_root=bootstrap_root)
    try:
        await runner.run_forever()
    finally:
        await runner.close()


__all__ = ["BootstrapRunner", "run_bootstrap"]
