from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from remora.core.store.event_store import EventStore
from remora.core.code.projections import NodeProjection
from remora.core.code.reconciler import reconcile_on_startup
from remora.core.events.subscriptions import SubscriptionRegistry


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

    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        swarm_root / "events.db",
        subscriptions=subscriptions,
        projection=NodeProjection(),
    )
    await event_store.initialize()

    try:
        summary = await reconcile_on_startup(
            project_root,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="test-graph",
        )

        assert summary["created"] >= 1
        nodes = await event_store.list_nodes()
        assert nodes

        for node in nodes:
            node_id = node.node_id
            registered = await subscriptions.get_subscriptions(node_id)
            assert any(sub.pattern.to_agent == node_id for sub in registered)
            assert any(
                sub.pattern.event_types and "ContentChangedEvent" in sub.pattern.event_types for sub in registered
            )
    finally:
        await subscriptions.close()
        await event_store.close()


@pytest.mark.asyncio
async def test_reconcile_emits_content_changed_event_on_file_update(tmp_path: Path) -> None:
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        swarm_root / "events.db",
        subscriptions=subscriptions,
        projection=NodeProjection(),
    )
    await event_store.initialize()

    try:
        await reconcile_on_startup(
            project_root,
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
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        events = [event async for event in event_store.replay("swarm")]
        assert any(event["event_type"] == "ContentChangedEvent" for event in events)
    finally:
        await subscriptions.close()
        await event_store.close()


@pytest.mark.asyncio
async def test_reconcile_refreshes_source_hash_for_common_agents(tmp_path: Path) -> None:
    """When a file is modified but the function stays at the same position,
    the reconciler must re-emit NodeDiscoveredEvent to update the source_hash
    in the EventStore nodes table.
    """
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        swarm_root / "events.db",
        subscriptions=subscriptions,
        projection=NodeProjection(),
    )
    await event_store.initialize()

    try:
        # First reconcile — registers agents with original content
        await reconcile_on_startup(
            project_root,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        nodes_before = await event_store.list_nodes()
        func_node = next(
            (n for n in nodes_before if n.node_type == "function"),
            None,
        )
        assert func_node is not None, "Expected a function node"
        original_hash = func_node.source_hash

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
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        assert summary["updated"] >= 1, "Expected at least 1 updated agent"

        nodes_after = await event_store.list_nodes()
        updated_func = next(
            (n for n in nodes_after if n.node_id == func_node.node_id),
            None,
        )
        assert updated_func is not None, f"Function node {func_node.node_id} should still exist"
        assert updated_func.source_hash != original_hash, (
            f"Expected source_hash to change after file modification, "
            f"but got {updated_func.source_hash} (original: {original_hash})"
        )
        # Verify the source code was updated
        assert "world" in updated_func.source_code
    finally:
        await subscriptions.close()
        await event_store.close()


@pytest.mark.asyncio
async def test_reconcile_preserves_identity_when_function_moves(
    tmp_path: Path,
) -> None:
    """When a function moves lines, semantic node_id stays stable and metadata updates."""
    project_root, target_file = _create_sample_project(tmp_path)
    swarm_root = project_root / ".remora"

    subscriptions = SubscriptionRegistry(swarm_root / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        swarm_root / "events.db",
        subscriptions=subscriptions,
        projection=NodeProjection(),
    )
    await event_store.initialize()

    try:
        await reconcile_on_startup(
            project_root,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        nodes_before = await event_store.list_nodes()
        func_before = next(
            (n for n in nodes_before if n.node_type == "function"),
            None,
        )
        assert func_before is not None
        old_id = func_before.node_id

        # Move the function down by adding blank lines
        await asyncio.sleep(0.02)
        target_file.write_text(
            "\n\n\n\n\ndef main():\n    return 'hello'\n",
            encoding="utf-8",
        )
        await asyncio.sleep(0.02)

        summary = await reconcile_on_startup(
            project_root,
            subscriptions,
            discovery_paths=["src"],
            languages=["python"],
            event_store=event_store,
            swarm_id="swarm",
        )

        # Line movement should not churn identity.
        assert summary["created"] == 0
        assert summary["orphaned"] == 0
        assert summary["updated"] >= 1

        active_nodes = await event_store.list_nodes()
        moved_func = next(
            (n for n in active_nodes if n.node_type == "function"),
            None,
        )
        assert moved_func is not None
        assert moved_func.node_id == old_id
        assert moved_func.start_line == 6  # After 5 blank lines

        preserved_node = await event_store.get_node(old_id)
        assert preserved_node is not None
    finally:
        await subscriptions.close()
        await event_store.close()
