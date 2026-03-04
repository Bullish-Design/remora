"""Integration tests for the scaffold node lifecycle.

Verifies the full reactive chain for scaffold nodes:
  Stub discovered -> projection sets scaffold status -> extension matched ->
  ScaffoldRequestEvent triggers subscribed agent -> prompt includes scaffold context

Uses EventStore's append() -> projection -> subscription -> trigger_queue
pipeline directly, without an LLM.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from remora.core.agent_node import AgentNode, ToolSchema
from remora.core.event_store import EventStore
from remora.core.events import (
    NodeDiscoveredEvent,
    ScaffoldRequestEvent,
)
from remora.core.projections import NodeProjection, _is_stub
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEMO_MODELS_DIR = Path(__file__).resolve().parents[2] / "remora_demo" / "project" / ".remora" / "models"


def _load_extension_class(module_filename: str, class_name: str) -> type:
    import importlib.util

    module_path = _DEMO_MODELS_DIR / module_filename
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def _all_extensions() -> list[type]:
    """Load all 6 extensions in alphabetical filename order (first match wins)."""
    return [
        _load_extension_class("00_scaffold_initializer.py", "ScaffoldInitializerExtension"),
        _load_extension_class("class_doc_generator.py", "ClassDocGeneratorExtension"),
        _load_extension_class("function_test_scaffold.py", "FunctionTestScaffoldExtension"),
        _load_extension_class("package_init.py", "PackageInitExtension"),
        _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension"),
        _load_extension_class("test_function.py", "TestFunctionExtension"),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def scaffold_env(tmp_path: Path):
    """Set up EventStore + SubscriptionRegistry + NodeProjection with all extensions."""
    extensions = _all_extensions()
    projection = NodeProjection(extension_configs=extensions)

    subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
    await subscriptions.initialize()

    event_store = EventStore(
        tmp_path / "events.db",
        subscriptions=subscriptions,
        projection=projection,
    )
    await event_store.initialize()
    event_store.set_subscriptions(subscriptions)

    try:
        yield event_store, subscriptions
    finally:
        with contextlib.suppress(Exception):
            await event_store.close()
        with contextlib.suppress(Exception):
            await subscriptions.close()


def _drain_trigger_queue(event_store: EventStore) -> list[tuple[str, int]]:
    """Drain the trigger queue and return list of (agent_id, event_id)."""
    triggers = []
    while event_store._trigger_queue and not event_store._trigger_queue.empty():
        try:
            agent_id, event_id, _event = event_store._trigger_queue.get_nowait()
            triggers.append((agent_id, event_id))
        except asyncio.QueueEmpty:
            break
    return triggers


async def _register_extra_subscriptions(
    event_store: EventStore,
    subscriptions: SubscriptionRegistry,
    node_id: str,
) -> None:
    """Register the extra_subscriptions from a node's extension data."""
    node = await event_store.get_node(node_id)
    assert node is not None
    for sub_pattern in node.extra_subscriptions:
        await subscriptions.register(node_id, sub_pattern)


# ============================================================================
# Scaffold Status Assignment
# ============================================================================


class TestScaffoldStatusAssignment:
    """Stub source_code results in status='scaffold' after projection."""

    @pytest.mark.asyncio
    async def test_stub_function_gets_scaffold_status(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="fn:stub_func",
            node_type="function",
            name="stub_func",
            full_name="function:stub_func",
            file_path="src/stubs.py",
            start_line=1,
            end_line=1,
            source_code="def stub_func(): pass",
            source_hash="h1",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:stub_func")
        assert node is not None
        assert node.status == "scaffold"

    @pytest.mark.asyncio
    async def test_stub_class_gets_scaffold_status(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="cls:StubClass",
            node_type="class",
            name="StubClass",
            full_name="class:StubClass",
            file_path="src/stubs.py",
            start_line=1,
            end_line=1,
            source_code="class StubClass: pass",
            source_hash="h2",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("cls:StubClass")
        assert node is not None
        assert node.status == "scaffold"

    @pytest.mark.asyncio
    async def test_empty_file_gets_scaffold_status(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="file:empty",
            node_type="file",
            name="empty",
            full_name="file:empty",
            file_path="src/empty.py",
            start_line=1,
            end_line=1,
            source_code="",
            source_hash="h3",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("file:empty")
        assert node is not None
        assert node.status == "scaffold"

    @pytest.mark.asyncio
    async def test_real_code_gets_idle_status(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="fn:real_func",
            node_type="function",
            name="real_func",
            full_name="function:real_func",
            file_path="src/real.py",
            start_line=1,
            end_line=5,
            source_code="def real_func():\n    return 42\n",
            source_hash="h4",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:real_func")
        assert node is not None
        assert node.status == "idle"


# ============================================================================
# Scaffold Extension Matching
# ============================================================================


class TestScaffoldExtensionMatching:
    """Scaffold nodes get the ScaffoldInitializer extension."""

    @pytest.mark.asyncio
    async def test_stub_function_gets_scaffold_initializer(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="fn:placeholder",
            node_type="function",
            name="placeholder",
            full_name="function:placeholder",
            file_path="src/module.py",
            start_line=1,
            end_line=1,
            source_code="def placeholder(): pass",
            source_hash="h5",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:placeholder")
        assert node is not None
        assert node.extension_name == "ScaffoldInitializer"
        assert "rewrite_self" in node.custom_system_prompt

    @pytest.mark.asyncio
    async def test_stub_class_gets_scaffold_initializer(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="cls:EmptyClass",
            node_type="class",
            name="EmptyClass",
            full_name="class:EmptyClass",
            file_path="src/empty_cls.py",
            start_line=1,
            end_line=1,
            source_code="class EmptyClass: pass",
            source_hash="h6",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("cls:EmptyClass")
        assert node is not None
        assert node.extension_name == "ScaffoldInitializer"

    @pytest.mark.asyncio
    async def test_real_function_does_not_get_scaffold_initializer(self, scaffold_env):
        """Functions with real code should get FunctionTestScaffold, not ScaffoldInitializer."""
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="fn:calculate",
            node_type="function",
            name="calculate",
            full_name="function:calculate",
            file_path="src/billing.py",
            start_line=1,
            end_line=5,
            source_code="def calculate(items):\n    return sum(i.price for i in items)\n",
            source_hash="h7",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:calculate")
        assert node is not None
        # ScaffoldInitializer (s) comes after FunctionTestScaffold (f) alphabetically
        # but a real function shouldn't match ScaffoldInitializer at all
        assert node.extension_name != "ScaffoldInitializer"


# ============================================================================
# ScaffoldRequestEvent Subscription Triggering
# ============================================================================


class TestScaffoldRequestTrigger:
    """ScaffoldRequestEvent triggers scaffold-subscribed agents."""

    @pytest.mark.asyncio
    async def test_scaffold_agent_triggered_by_scaffold_request(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        # Step 1: Discover a stub node
        discover_event = NodeDiscoveredEvent(
            node_id="fn:new_func",
            node_type="function",
            name="new_func",
            full_name="function:new_func",
            file_path="src/new_module.py",
            start_line=1,
            end_line=1,
            source_code="def new_func(): pass",
            source_hash="h8",
        )
        await event_store.append("swarm", discover_event)

        # Step 2: Register the ScaffoldInitializer subscriptions
        await _register_extra_subscriptions(event_store, subscriptions, "fn:new_func")

        _drain_trigger_queue(event_store)

        # Step 3: Emit ScaffoldRequestEvent
        scaffold_event = ScaffoldRequestEvent(
            node_id="fn:new_func",
            to_agent="fn:new_func",
            node_type="function",
            parent_id="file:new_module",
            intent="Implement a helper function for data transformation",
        )
        await event_store.append("swarm", scaffold_event)

        # Step 4: The scaffold agent should be triggered
        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "fn:new_func" in triggered_agents

    @pytest.mark.asyncio
    async def test_non_scaffold_agent_not_triggered_by_scaffold_request(self, scaffold_env):
        """Regular agents (e.g. SwarmMonitor) should NOT be triggered by ScaffoldRequestEvent."""
        event_store, subscriptions = scaffold_env

        # Discover a MONITOR.md node (SwarmMonitor extension)
        discover_event = NodeDiscoveredEvent(
            node_id="file:MONITOR",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            start_line=1,
            end_line=3,
            source_code="# Activity Log\n",
            source_hash="h9",
        )
        await event_store.append("swarm", discover_event)
        await _register_extra_subscriptions(event_store, subscriptions, "file:MONITOR")

        _drain_trigger_queue(event_store)

        # Emit ScaffoldRequestEvent — monitor should NOT be triggered
        scaffold_event = ScaffoldRequestEvent(
            node_id="fn:some_func",
            to_agent="fn:some_func",
            node_type="function",
        )
        await event_store.append("swarm", scaffold_event)

        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "file:MONITOR" not in triggered_agents


# ============================================================================
# Full Lifecycle: Stub -> Scaffold -> Trigger -> Prompt
# ============================================================================


class TestScaffoldFullLifecycle:
    """End-to-end: discover stub -> scaffold status -> extension matched ->
    subscription registered -> ScaffoldRequestEvent -> agent triggered."""

    @pytest.mark.asyncio
    async def test_full_scaffold_lifecycle(self, scaffold_env):
        event_store, subscriptions = scaffold_env

        # 1. Discover a parent node with real code
        parent_event = NodeDiscoveredEvent(
            node_id="file:service",
            node_type="file",
            name="service",
            full_name="file:service",
            file_path="src/service.py",
            start_line=1,
            end_line=20,
            source_code="class Service:\n    def run(self):\n        return True\n",
            source_hash="hp",
        )
        await event_store.append("swarm", parent_event)

        # 2. Discover a stub child function
        stub_event = NodeDiscoveredEvent(
            node_id="fn:process_data",
            node_type="function",
            name="process_data",
            full_name="function:process_data",
            file_path="src/service.py",
            start_line=5,
            end_line=5,
            source_code="def process_data(): pass",
            source_hash="hs",
            parent_id="file:service",
        )
        await event_store.append("swarm", stub_event)

        # 3. Verify scaffold status and extension
        node = await event_store.get_node("fn:process_data")
        assert node is not None
        assert node.status == "scaffold"
        assert node.extension_name == "ScaffoldInitializer"
        assert "rewrite_self" in node.custom_system_prompt

        # 4. Register subscriptions
        await _register_extra_subscriptions(event_store, subscriptions, "fn:process_data")
        _drain_trigger_queue(event_store)

        # 5. Emit ScaffoldRequestEvent
        scaffold_event = ScaffoldRequestEvent(
            node_id="fn:process_data",
            to_agent="fn:process_data",
            node_type="function",
            parent_id="file:service",
            intent="Process incoming data from the API",
        )
        await event_store.append("swarm", scaffold_event)

        # 6. Verify the scaffold agent was triggered
        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "fn:process_data" in triggered_agents

    @pytest.mark.asyncio
    async def test_scaffold_and_real_nodes_coexist(self, scaffold_env):
        """Mix of scaffold and real nodes: each gets correct extension."""
        event_store, subscriptions = scaffold_env

        # Discover a real function
        real_event = NodeDiscoveredEvent(
            node_id="fn:real",
            node_type="function",
            name="real",
            full_name="function:real",
            file_path="src/module.py",
            start_line=1,
            end_line=5,
            source_code="def real():\n    return 42\n",
            source_hash="hr",
        )
        # Discover a stub function
        stub_event = NodeDiscoveredEvent(
            node_id="fn:stub",
            node_type="function",
            name="stub",
            full_name="function:stub",
            file_path="src/module.py",
            start_line=7,
            end_line=7,
            source_code="def stub(): pass",
            source_hash="hs2",
        )

        await event_store.append("swarm", real_event)
        await event_store.append("swarm", stub_event)

        real_node = await event_store.get_node("fn:real")
        stub_node = await event_store.get_node("fn:stub")

        assert real_node is not None
        assert stub_node is not None

        # Real function: idle status, non-scaffold extension
        assert real_node.status == "idle"
        assert real_node.extension_name != "ScaffoldInitializer"

        # Stub function: scaffold status, ScaffoldInitializer extension
        assert stub_node.status == "scaffold"
        assert stub_node.extension_name == "ScaffoldInitializer"

    @pytest.mark.asyncio
    async def test_scaffold_subscription_data_persisted(self, scaffold_env):
        """ScaffoldInitializer extra_subscriptions are correctly stored and hydrated."""
        event_store, subscriptions = scaffold_env

        event = NodeDiscoveredEvent(
            node_id="fn:pending",
            node_type="function",
            name="pending",
            full_name="function:pending",
            file_path="src/pending.py",
            start_line=1,
            end_line=1,
            source_code="def pending(): ...",
            source_hash="hpend",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:pending")
        assert node is not None
        assert len(node.extra_subscriptions) >= 1

        # Verify the subscription pattern includes ScaffoldRequestEvent
        event_types_across_subs = set()
        for sub in node.extra_subscriptions:
            assert isinstance(sub, SubscriptionPattern)
            if sub.event_types:
                event_types_across_subs.update(sub.event_types)
        assert "ScaffoldRequestEvent" in event_types_across_subs
