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
        "def main():\n    return 'hello'\n",
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
                sub.pattern.event_types and "ContentChangedEvent" in sub.pattern.event_types for sub in registered
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
            "def main():\n    return 'world'\n",
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


@pytest.mark.asyncio
async def test_reconcile_refreshes_metadata_for_common_agents(tmp_path: Path) -> None:
    """Reconciler should upsert fresh metadata for common_ids agents (same node_id).

    When a file is modified but the function stays at the same position
    (same node_id), the reconciler must still call swarm_state.upsert()
    to refresh ``updated_at`` and keep SwarmState metadata current.
    """
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    swarm_state = SwarmState(swarm_root / "swarm.db")
    await swarm_state.initialize()
    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(swarm_root / "events.db", subscriptions=subscriptions)
    await event_store.initialize()

    try:
        # First reconcile — registers agents with original content
        await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        agents_before = await swarm_state.list_agents(status="active")
        # Find the function-level agent (not the file-level agent)
        func_agent = next(
            (a for a in agents_before if a.node_type == "function"),
            None,
        )
        assert func_agent is not None, "Expected a function agent"
        original_updated_at = func_agent.updated_at

        # Modify the file body but keep function at same position/name
        await asyncio.sleep(0.05)
        target_file.write_text(
            "def main():\n    return 'world'\n",
            encoding="utf-8",
        )
        await asyncio.sleep(0.05)

        # Second reconcile — same node_id (function didn't move), but file changed
        summary = await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        assert summary["updated"] >= 1, "Expected at least 1 updated agent"

        agents_after = await swarm_state.list_agents(status="active")
        updated_func = next(
            (a for a in agents_after if a.agent_id == func_agent.agent_id),
            None,
        )
        assert updated_func is not None, f"Function agent {func_agent.agent_id} should still exist"
        assert updated_func.updated_at is not None
        assert original_updated_at is not None
        assert updated_func.updated_at > original_updated_at, (
            f"Expected updated_at to be refreshed after reconciliation, "
            f"but got {updated_func.updated_at} (original: {original_updated_at})"
        )

        # Also verify the on-disk AgentState was updated
        state_path = get_agent_state_path(swarm_root, func_agent.agent_id)
        from remora.core.agent_state import load as load_agent_state

        disk_state = load_agent_state(state_path)
        assert disk_state is not None
        assert disk_state.name == "main"
    finally:
        await swarm_state.close()
        await subscriptions.close()
        await event_store.close()


@pytest.mark.asyncio
async def test_reconcile_orphans_old_and_creates_new_when_function_moves(
    tmp_path: Path,
) -> None:
    """When a function moves lines, node_id changes — old agent is orphaned, new one created."""
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    swarm_state = SwarmState(swarm_root / "swarm.db")
    await swarm_state.initialize()
    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    try:
        await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            swarm_id="swarm",
        )

        agents_before = await swarm_state.list_agents(status="active")
        func_before = next(
            (a for a in agents_before if a.node_type == "function"),
            None,
        )
        assert func_before is not None
        old_id = func_before.agent_id

        # Move the function down by adding blank lines
        await asyncio.sleep(0.02)
        target_file.write_text(
            "\n\n\n\n\ndef main():\n    return 'hello'\n",
            encoding="utf-8",
        )
        await asyncio.sleep(0.02)

        summary = await reconcile_on_startup(
            project_root,
            swarm_state,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            swarm_id="swarm",
        )

        # Old function agent should be orphaned, new one created
        assert summary["created"] >= 1
        assert summary["orphaned"] >= 1

        active_agents = await swarm_state.list_agents(status="active")
        new_func = next(
            (a for a in active_agents if a.node_type == "function"),
            None,
        )
        assert new_func is not None
        assert new_func.agent_id != old_id
        assert new_func.start_line == 6  # After 5 blank lines

        # Old agent should be orphaned
        old_agent = await swarm_state.get_agent(old_id)
        assert old_agent is not None
        assert old_agent.status == "orphaned"
    finally:
        await swarm_state.close()
        await subscriptions.close()
