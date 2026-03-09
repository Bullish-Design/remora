"""Bootstrap runtime loop for module-to-agent assignment."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

from remora.bootstrap.activation import handle_agent_needed
from remora.bootstrap.bedrock import BootstrapEvent
from remora.bootstrap.coordinator import emit_agent_needed_events, find_unassigned_modules
from remora.bootstrap.seed_graph import seed_coordinator_node, seed_modules_if_empty
from remora.core.agents.cairn_bridge import CairnWorkspaceService
from remora.core.code.projections import NodeProjection
from remora.core.config import Config
from remora.core.events.subscriptions import SubscriptionRegistry
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
    ) -> None:
        self.config = config
        self.project_root = (project_root or Path(config.project_path)).resolve()
        self.bootstrap_root = bootstrap_root or (self.project_root / "bootstrap")
        self.coordinator_id = coordinator_id
        self.swarm_id = config.swarm_id

        swarm_root = Path(config.swarm_root)
        if not swarm_root.is_absolute():
            swarm_root = self.project_root / swarm_root
        events_root = swarm_root / "events"

        self.event_store_path = event_store_path or (events_root / "events.db")
        self.subscriptions_path = subscriptions_path or (events_root / "subscriptions.db")

        self._subscriptions: SubscriptionRegistry | None = None
        self._event_store: EventStore | None = None
        self._workspace_service: CairnWorkspaceService | None = None
        self._initialized = False
        self._running = False

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

        subscriptions = SubscriptionRegistry(self.subscriptions_path)
        await subscriptions.initialize()

        event_store = EventStore(
            self.event_store_path,
            subscriptions=subscriptions,
            projection=NodeProjection(),
        )
        await event_store.initialize()

        workspace_service = CairnWorkspaceService(
            self.config,
            graph_id=self.swarm_id,
            project_root=self.project_root,
        )

        await seed_coordinator_node(event_store, coordinator_id=self.coordinator_id)
        await seed_modules_if_empty(event_store, self.project_root, swarm_id=self.swarm_id)

        self._subscriptions = subscriptions
        self._event_store = event_store
        self._workspace_service = workspace_service
        self._initialized = True

    def _build_agent_needed_event(self, *, node_id: str, agent_id: str) -> BootstrapEvent:
        return BootstrapEvent(
            event_type="AgentNeededEvent",
            node_id=node_id,
            payload={"node_id": node_id, "agent_id": agent_id},
            from_agent=self.coordinator_id,
            tags=("bootstrap", "agent-needed"),
        )

    async def run_once(self) -> int:
        """Run one coordinator pass and activate newly needed agents."""
        await self.initialize()

        plans = await find_unassigned_modules(self.event_store)
        if not plans:
            return 0

        await emit_agent_needed_events(
            self.event_store,
            swarm_id=self.swarm_id,
            coordinator_id=self.coordinator_id,
        )

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

    async def run_forever(self, *, poll_interval_s: float = 0.5) -> None:
        """Continuously assign and activate agents for unassigned modules."""
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

        if self._workspace_service is not None:
            with contextlib.suppress(Exception):
                await self._workspace_service.close()
            self._workspace_service = None

        if self._event_store is not None:
            with contextlib.suppress(Exception):
                await self._event_store.close()
            self._event_store = None

        if self._subscriptions is not None:
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
