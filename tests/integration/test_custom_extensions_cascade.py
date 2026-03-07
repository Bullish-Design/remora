"""E2e cascade test for custom node extensions.

Verifies the full reactive chain:
  Node discovered -> extension matched -> projection populates fields ->
  subscriptions registered -> event emitted -> correct agents triggered

Uses the EventStore's append() -> projection -> subscription -> trigger_queue
pipeline directly, without an LLM.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import AsyncIterator

import pytest

from remora.core.agents.agent_node import AgentNode, ToolSchema
from remora.core.store.event_store import EventStore
from remora.core.events.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    ContentChangedEvent,
    NodeDiscoveredEvent,
)
from remora.core.code.projections import NodeProjection
from remora.core.events.subscriptions import SubscriptionPattern, SubscriptionRegistry


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
    """Load all 5 extensions in alphabetical filename order (first match wins)."""
    return [
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
async def cascade_env(tmp_path: Path):
    """Set up EventStore + SubscriptionRegistry + NodeProjection with all extensions."""
    extensions = _all_extensions()
    def dummy_matcher(ext_cls, node_type, name, **kwargs):
        return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)

    projection = NodeProjection(extension_matcher=dummy_matcher, extension_configs=extensions)

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
# E2e Cascade Tests
# ============================================================================


class TestCascadeClassDiscovery:
    """When a class is discovered, its agent gets ClassDocGenerator extension data."""

    @pytest.mark.asyncio
    async def test_class_discovered_populates_extension_fields(self, cascade_env):
        event_store, subscriptions = cascade_env

        event = NodeDiscoveredEvent(
            node_id="cls:MyWidget",
            node_type="class",
            name="MyWidget",
            full_name="class:MyWidget",
            file_path="src/widgets.py",
            start_line=1,
            end_line=20,
            source_code="class MyWidget:\n    def render(self): pass\n",
            source_hash="hash1",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("cls:MyWidget")
        assert node is not None
        assert node.extension_name == "ClassDocGenerator"
        assert node.custom_system_prompt != ""
        assert len(node.extra_tools) >= 1
        assert node.extra_tools[0].name == "create_doc_file"

    @pytest.mark.asyncio
    async def test_class_agent_receives_content_change_trigger(self, cascade_env):
        """After registering ClassDocGenerator subscriptions, a ContentChangedEvent triggers the agent."""
        event_store, subscriptions = cascade_env

        # Step 1: Discover the class
        discover_event = NodeDiscoveredEvent(
            node_id="cls:MyWidget",
            node_type="class",
            name="MyWidget",
            full_name="class:MyWidget",
            file_path="src/widgets.py",
            start_line=1,
            end_line=20,
            source_code="class MyWidget:\n    pass\n",
            source_hash="hash1",
        )
        await event_store.append("swarm", discover_event)

        # Step 2: Register the extension's subscriptions
        await _register_extra_subscriptions(event_store, subscriptions, "cls:MyWidget")

        # Drain any triggers from discovery
        _drain_trigger_queue(event_store)

        # Step 3: Emit a ContentChangedEvent
        change_event = ContentChangedEvent(path="src/widgets.py", diff="+ added method")
        await event_store.append("swarm", change_event)

        # Step 4: Check trigger queue — ClassDocGenerator agent should be triggered
        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "cls:MyWidget" in triggered_agents


class TestCascadeFunctionDiscovery:
    """Non-test functions get FunctionTestScaffold, test functions get TestFunction."""

    @pytest.mark.asyncio
    async def test_regular_function_gets_scaffold(self, cascade_env):
        event_store, subscriptions = cascade_env

        event = NodeDiscoveredEvent(
            node_id="fn:calculate_total",
            node_type="function",
            name="calculate_total",
            full_name="function:calculate_total",
            file_path="src/billing.py",
            start_line=5,
            end_line=15,
            source_code="def calculate_total(items): return sum(i.price for i in items)",
            source_hash="hash2",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:calculate_total")
        assert node is not None
        assert node.extension_name == "FunctionTestScaffold"

    @pytest.mark.asyncio
    async def test_test_function_gets_test_extension(self, cascade_env):
        event_store, subscriptions = cascade_env

        event = NodeDiscoveredEvent(
            node_id="fn:test_calculate",
            node_type="function",
            name="test_calculate",
            full_name="function:test_calculate",
            file_path="tests/test_billing.py",
            start_line=1,
            end_line=5,
            source_code="def test_calculate(): assert True",
            source_hash="hash3",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("fn:test_calculate")
        assert node is not None
        assert node.extension_name == "TestFunction"


class TestCascadeSwarmMonitor:
    """MONITOR.md file gets SwarmMonitor extension and observes all agent activity."""

    @pytest.mark.asyncio
    async def test_monitor_md_gets_swarm_monitor(self, cascade_env):
        event_store, subscriptions = cascade_env

        event = NodeDiscoveredEvent(
            node_id="file:MONITOR",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            start_line=1,
            end_line=3,
            source_code="# Activity Log\n",
            source_hash="hash4",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("file:MONITOR")
        assert node is not None
        assert node.extension_name == "SwarmMonitor"

    @pytest.mark.asyncio
    async def test_monitor_triggered_by_agent_complete(self, cascade_env):
        """SwarmMonitor should be triggered when any agent completes."""
        event_store, subscriptions = cascade_env

        # Step 1: Discover the MONITOR.md node
        discover_event = NodeDiscoveredEvent(
            node_id="file:MONITOR",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            start_line=1,
            end_line=3,
            source_code="# Activity Log\n",
            source_hash="hash4",
        )
        await event_store.append("swarm", discover_event)

        # Step 2: Register the monitor's subscriptions
        await _register_extra_subscriptions(event_store, subscriptions, "file:MONITOR")

        _drain_trigger_queue(event_store)

        # Step 3: Emit AgentCompleteEvent from some other agent
        complete_event = AgentCompleteEvent(
            graph_id="swarm",
            agent_id="cls:MyWidget",
            result_summary="Generated documentation",
        )
        await event_store.append("swarm", complete_event)

        # Step 4: Monitor should be triggered
        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "file:MONITOR" in triggered_agents

    @pytest.mark.asyncio
    async def test_monitor_triggered_by_agent_error(self, cascade_env):
        """SwarmMonitor should be triggered when any agent errors."""
        event_store, subscriptions = cascade_env

        # Discover and register monitor
        discover_event = NodeDiscoveredEvent(
            node_id="file:MONITOR",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            start_line=1,
            end_line=3,
            source_code="# Activity Log\n",
            source_hash="hash5",
        )
        await event_store.append("swarm", discover_event)
        await _register_extra_subscriptions(event_store, subscriptions, "file:MONITOR")

        _drain_trigger_queue(event_store)

        # Emit AgentErrorEvent
        error_event = AgentErrorEvent(
            graph_id="swarm",
            agent_id="fn:broken_func",
            error="RuntimeError: something went wrong",
        )
        await event_store.append("swarm", error_event)

        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "file:MONITOR" in triggered_agents

    @pytest.mark.asyncio
    async def test_monitor_not_triggered_by_content_change(self, cascade_env):
        """SwarmMonitor should NOT be triggered by ContentChangedEvent (not subscribed)."""
        event_store, subscriptions = cascade_env

        # Discover and register monitor
        discover_event = NodeDiscoveredEvent(
            node_id="file:MONITOR",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            start_line=1,
            end_line=3,
            source_code="# Activity Log\n",
            source_hash="hash6",
        )
        await event_store.append("swarm", discover_event)
        await _register_extra_subscriptions(event_store, subscriptions, "file:MONITOR")

        _drain_trigger_queue(event_store)

        # Emit ContentChangedEvent — monitor should NOT be triggered
        change_event = ContentChangedEvent(path="src/main.py")
        await event_store.append("swarm", change_event)

        triggers = _drain_trigger_queue(event_store)
        triggered_agents = [agent_id for agent_id, _ in triggers]
        assert "file:MONITOR" not in triggered_agents


class TestFullCascadeChain:
    """Test the full multi-agent cascade: discovery -> extension -> subscribe -> trigger chain."""

    @pytest.mark.asyncio
    async def test_full_cascade_multiple_agents(self, cascade_env):
        """
        Scenario:
        1. Discover a class (ClassDocGenerator)
        2. Discover a function (FunctionTestScaffold)
        3. Discover MONITOR.md (SwarmMonitor)
        4. Register all their subscriptions
        5. Emit AgentCompleteEvent -> monitor is triggered
        6. Emit ContentChangedEvent -> class and function agents are triggered
        """
        event_store, subscriptions = cascade_env

        # --- Step 1-3: Discover all three nodes ---
        nodes_to_discover = [
            NodeDiscoveredEvent(
                node_id="cls:Processor",
                node_type="class",
                name="Processor",
                full_name="class:Processor",
                file_path="src/processor.py",
                start_line=1,
                end_line=30,
                source_code="class Processor:\n    def run(self): pass\n",
                source_hash="h1",
            ),
            NodeDiscoveredEvent(
                node_id="fn:transform",
                node_type="function",
                name="transform",
                full_name="function:transform",
                file_path="src/utils.py",
                start_line=1,
                end_line=10,
                source_code="def transform(data): return data",
                source_hash="h2",
            ),
            NodeDiscoveredEvent(
                node_id="file:MONITOR",
                node_type="file",
                name="MONITOR",
                full_name="file:MONITOR",
                file_path="MONITOR.md",
                start_line=1,
                end_line=3,
                source_code="# Activity Log\n",
                source_hash="h3",
            ),
        ]

        for event in nodes_to_discover:
            await event_store.append("swarm", event)

        # Verify extensions were matched correctly
        cls_node = await event_store.get_node("cls:Processor")
        fn_node = await event_store.get_node("fn:transform")
        mon_node = await event_store.get_node("file:MONITOR")

        assert cls_node is not None
        assert fn_node is not None
        assert mon_node is not None
        assert cls_node.extension_name == "ClassDocGenerator"
        assert fn_node.extension_name == "FunctionTestScaffold"
        assert mon_node.extension_name == "SwarmMonitor"

        # --- Step 4: Register all extra_subscriptions ---
        for node_id in ["cls:Processor", "fn:transform", "file:MONITOR"]:
            await _register_extra_subscriptions(event_store, subscriptions, node_id)

        _drain_trigger_queue(event_store)

        # --- Step 5: AgentCompleteEvent -> only monitor is triggered ---
        complete_event = AgentCompleteEvent(
            graph_id="swarm",
            agent_id="cls:Processor",
            result_summary="Documented the class",
        )
        await event_store.append("swarm", complete_event)

        triggers = _drain_trigger_queue(event_store)
        triggered_agents = {agent_id for agent_id, _ in triggers}
        assert "file:MONITOR" in triggered_agents
        # ClassDocGenerator and FunctionTestScaffold don't subscribe to AgentCompleteEvent
        assert "cls:Processor" not in triggered_agents
        assert "fn:transform" not in triggered_agents

        # --- Step 6: ContentChangedEvent -> class and function agents triggered, not monitor ---
        change_event = ContentChangedEvent(path="src/processor.py")
        await event_store.append("swarm", change_event)

        triggers = _drain_trigger_queue(event_store)
        triggered_agents = {agent_id for agent_id, _ in triggers}
        # ClassDocGenerator subscribes to ContentChangedEvent
        assert "cls:Processor" in triggered_agents
        # FunctionTestScaffold also subscribes to ContentChangedEvent
        assert "fn:transform" in triggered_agents
        # SwarmMonitor does NOT subscribe to ContentChangedEvent
        assert "file:MONITOR" not in triggered_agents

    @pytest.mark.asyncio
    async def test_hydrated_agent_node_has_correct_tools_and_subscriptions(self, cascade_env):
        """Verify that AgentNode from get_node() is fully hydrated."""
        event_store, subscriptions = cascade_env

        event = NodeDiscoveredEvent(
            node_id="cls:Widget",
            node_type="class",
            name="Widget",
            full_name="class:Widget",
            file_path="src/widget.py",
            start_line=1,
            end_line=15,
            source_code="class Widget:\n    pass\n",
            source_hash="hw",
        )
        await event_store.append("swarm", event)

        node = await event_store.get_node("cls:Widget")
        assert node is not None

        # Extension fields populated
        assert node.extension_name == "ClassDocGenerator"
        assert "document" in node.custom_system_prompt.lower() or "doc" in node.custom_system_prompt.lower()

        # Tools are ToolSchema instances
        assert len(node.extra_tools) >= 1
        assert isinstance(node.extra_tools[0], ToolSchema)
        assert node.extra_tools[0].name == "create_doc_file"

        # Subscriptions are SubscriptionPattern instances
        assert len(node.extra_subscriptions) >= 1
        assert isinstance(node.extra_subscriptions[0], SubscriptionPattern)

        # System prompt includes extension specialization
        prompt = node.to_system_prompt()
        assert "ClassDocGenerator" in prompt
