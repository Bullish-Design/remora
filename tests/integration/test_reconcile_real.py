from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.core.event_store import EventStore
from remora.core.reconciler import get_agent_state_path, reconcile_on_startup
from remora.core.subscriptions import SubscriptionRegistry
from remora.core.swarm_state import SwarmState


pytestmark = pytest.mark.integration


def _create_sample_project(tmp_path: Path) -> tuple[Path, Path]:
    project_root = tmp_path / "project"
    project_root.mkdir(parents=True)
    src_dir = project_root / "src"
    src_dir.mkdir()
    target_file = src_dir / "main.py"
    target_file.write_text(
        "def main():\n"
        "    return 'hello'\n",
        encoding="utf-8",
    )
    return project_root, target_file


@pytest.mark.asyncio
async def test_reconcile_registers_agents_and_default_subscriptions(tmp_path: Path) -> None:
    project_root, _ = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    swarm_state = SwarmState(swarm_root / "swarm.db")
    await swarm_state.initialize()
    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    try:
        summary = await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            swarm_id="test-graph",
        )

        assert summary["created"] >= 1
        agents = await swarm_state.list_agents()
        assert agents

        for agent in agents:
            agent_id = agent.agent_id
            state_path = get_agent_state_path(swarm_root, agent_id)
            assert state_path.exists()

            registered = await subscriptions.get_subscriptions(agent_id)
            assert any(sub.pattern.to_agent == agent_id for sub in registered)
            assert any(
                sub.pattern.event_types
                and "ContentChangedEvent" in sub.pattern.event_types
                for sub in registered
            )
    finally:
        await swarm_state.close()
        await subscriptions.close()


@pytest.mark.asyncio
async def test_reconcile_emits_content_changed_event_on_file_update(tmp_path: Path) -> None:
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    swarm_state = SwarmState(swarm_root / "swarm.db")
    await swarm_state.initialize()
    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(swarm_root / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    try:
        await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        await asyncio.sleep(0.01)
        target_file.write_text(
            "def main():\n"
            "    return 'world'\n",
            encoding="utf-8",
        )
        await asyncio.sleep(0.01)

        await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        events = [event async for event in event_store.replay("swarm")]
        assert any(event["event_type"] == "ContentChangedEvent" for event in events)
    finally:
        await swarm_state.close()
        await subscriptions.close()
        await event_store.close()
