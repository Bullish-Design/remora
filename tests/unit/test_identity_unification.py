"""Tests for Batch 4: Identity Unification.

Verifies that:
- Reconciler uses EventStore (via NodeDiscoveredEvent/NodeRemovedEvent) as sole source
- SwarmExecutor accepts AgentNode instead of AgentState
- CLI and service handlers query EventStore instead of SwarmState
- AgentState JSONL files are no longer created
- SwarmState is no longer written to by reconciler
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from remora.core.agents.agent_node import AgentNode
from remora.core.config import Config
from remora.core.store.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent
from remora.core.code.projections import NodeProjection
from remora.core.events.subscriptions import SubscriptionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent_node(**overrides: Any) -> AgentNode:
    defaults = {
        "node_id": "abc123",
        "node_type": "function",
        "name": "calculate_total",
        "full_name": "billing.calculate_total",
        "file_path": "src/billing.py",
        "start_line": 10,
        "end_line": 25,
        "start_byte": 100,
        "end_byte": 500,
        "source_code": "def calculate_total(items): return sum(items)",
        "source_hash": "deadbeef",
        "parent_id": None,
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


def _make_config(tmp_path: Path, **overrides: Any) -> Config:
    defaults = {
        "project_path": str(tmp_path),
        "bundle_root": str(tmp_path / "agents"),
        "bundle_mapping": {"function": "code", "file": "file"},
        "model_base_url": "http://localhost:8000/v1",
        "model_default": "test/model",
        "model_api_key": "test-key",
        "swarm_root": str(tmp_path / ".remora"),
        "swarm_id": "test-swarm",
        "max_concurrency": 4,
        "max_turns": 3,
        "truncation_limit": 512,
        "timeout_s": 10.0,
        "chat_history_limit": 5,
    }
    defaults.update(overrides)
    return Config(**defaults)


# =========================================================================
# 1. Reconciler emits NodeDiscoveredEvent into EventStore
# =========================================================================


class TestReconcilerUsesEventStore:
    """Reconciler should emit NodeDiscoveredEvent for new nodes,
    NodeRemovedEvent for orphaned nodes, and NOT write to SwarmState or JSONL.
    """

    @pytest.mark.asyncio
    async def test_reconcile_creates_nodes_in_event_store(self, tmp_path: Path):
        """New discovered nodes should appear in EventStore.nodes table."""
        from remora.core.code.reconciler import reconcile_on_startup

        project_root = tmp_path / "project"
        (project_root / "src").mkdir(parents=True)
        (project_root / "src" / "main.py").write_text("def hello():\n    pass\n", encoding="utf-8")

        subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
        await subscriptions.initialize()

        projection = NodeProjection()
        event_store = EventStore(
            tmp_path / "events.db",
            subscriptions=subscriptions,
            projection=projection,
        )
        await event_store.initialize()

        try:
            result = await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            assert result["created"] >= 1

            # Nodes should be in EventStore
            nodes = await event_store.nodes.list_nodes()
            assert len(nodes) >= 1

            # Find the function node
            func_nodes = [n for n in nodes if n.node_type == "function"]
            assert len(func_nodes) >= 1
            assert func_nodes[0].name == "hello"
            assert func_nodes[0].file_path.endswith("main.py")
        finally:
            await event_store.close()
            await subscriptions.close()

    @pytest.mark.asyncio
    async def test_reconcile_does_not_create_jsonl_files(self, tmp_path: Path):
        """Reconciler should NOT create agent state JSONL files."""
        from remora.core.code.reconciler import reconcile_on_startup

        project_root = tmp_path / "project"
        (project_root / "src").mkdir(parents=True)
        (project_root / "src" / "main.py").write_text("def hello():\n    pass\n", encoding="utf-8")

        subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
        await subscriptions.initialize()

        projection = NodeProjection()
        event_store = EventStore(
            tmp_path / "events.db",
            subscriptions=subscriptions,
            projection=projection,
        )
        await event_store.initialize()

        try:
            await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            # No JSONL files should exist
            swarm_root = project_root / ".remora"
            agents_dir = swarm_root / "agents"
            jsonl_files = list(agents_dir.rglob("*.jsonl")) if agents_dir.exists() else []
            assert len(jsonl_files) == 0, f"Found unexpected JSONL files: {jsonl_files}"
        finally:
            await event_store.close()
            await subscriptions.close()

    @pytest.mark.asyncio
    async def test_reconcile_orphans_removed_nodes(self, tmp_path: Path):
        """Nodes that disappear from source should be removed from EventStore."""
        from remora.core.code.reconciler import reconcile_on_startup

        project_root = tmp_path / "project"
        src_dir = project_root / "src"
        src_dir.mkdir(parents=True)
        main_py = src_dir / "main.py"
        main_py.write_text("def hello():\n    pass\n", encoding="utf-8")

        subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
        await subscriptions.initialize()

        projection = NodeProjection()
        event_store = EventStore(
            tmp_path / "events.db",
            subscriptions=subscriptions,
            projection=projection,
        )
        await event_store.initialize()

        try:
            # First reconcile — creates nodes
            await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            nodes_before = await event_store.nodes.list_nodes()
            assert len(nodes_before) >= 1

            # Remove the file
            main_py.write_text("# empty\n", encoding="utf-8")

            # Second reconcile — should remove orphaned nodes
            result = await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            assert result["orphaned"] >= 1

            # The function node should be gone
            nodes_after = await event_store.nodes.list_nodes(node_type="function")
            func_names = [n.name for n in nodes_after]
            assert "hello" not in func_names
        finally:
            await event_store.close()
            await subscriptions.close()

    @pytest.mark.asyncio
    async def test_reconcile_updates_changed_nodes(self, tmp_path: Path):
        """Nodes that change should be re-upserted in EventStore."""
        import asyncio
        from remora.core.code.reconciler import reconcile_on_startup

        project_root = tmp_path / "project"
        src_dir = project_root / "src"
        src_dir.mkdir(parents=True)
        main_py = src_dir / "main.py"
        main_py.write_text("def hello():\n    pass\n", encoding="utf-8")

        subscriptions = SubscriptionRegistry(tmp_path / "subscriptions.db")
        await subscriptions.initialize()

        projection = NodeProjection()
        event_store = EventStore(
            tmp_path / "events.db",
            subscriptions=subscriptions,
            projection=projection,
        )
        await event_store.initialize()

        try:
            await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            nodes_before = await event_store.nodes.list_nodes(node_type="function")
            assert len(nodes_before) >= 1
            old_hash = nodes_before[0].source_hash

            # Modify the file (keep function at same position for same node_id)
            await asyncio.sleep(0.02)
            main_py.write_text("def hello():\n    return 'world'\n", encoding="utf-8")
            await asyncio.sleep(0.02)

            result = await reconcile_on_startup(
                project_root,
                subscriptions,
                event_store=event_store,
                discovery_paths=["src"],
                languages=["python"],
                swarm_id="test",
            )

            # Node should have updated source_hash
            nodes_after = await event_store.nodes.list_nodes(node_type="function")
            assert len(nodes_after) >= 1
            new_hash = nodes_after[0].source_hash
            assert new_hash != old_hash, "source_hash should change after code modification"
        finally:
            await event_store.close()
            await subscriptions.close()

    @pytest.mark.asyncio
    async def test_reconcile_signature_no_swarm_state_param(self):
        """reconcile_on_startup should not require a swarm_state parameter."""
        import inspect
        from remora.core.code.reconciler import reconcile_on_startup

        sig = inspect.signature(reconcile_on_startup)
        param_names = list(sig.parameters.keys())
        assert "swarm_state" not in param_names, "reconcile_on_startup should not have a swarm_state parameter"


# =========================================================================
# 2. SwarmExecutor uses AgentNode instead of AgentState
# =========================================================================


class TestSwarmExecutorUsesAgentNode:
    """SwarmExecutor.run_agent should accept AgentNode, not AgentState."""

    def test_resolve_bundle_path_with_agent_node(self, tmp_path):
        """_resolve_bundle_path should work with AgentNode."""
        from remora.core.agents.turn_context import _resolve_bundle_path

        config = _make_config(tmp_path, bundle_mapping={"function": "code"})
        node = _make_agent_node(node_type="function")
        path = _resolve_bundle_path(node, config)
        assert path == Path(config.bundle_root) / "code"

    def test_build_prompt_with_agent_node(self, tmp_path):
        """_build_prompt should work with AgentNode."""
        from remora.core.agents.turn_context import _build_prompt, _agent_node_to_cst_node
        from remora.utils import PathResolver

        config = _make_config(tmp_path)
        resolver = PathResolver(tmp_path)
        node = _make_agent_node()
        cst_node = _agent_node_to_cst_node(node)
        prompt = _build_prompt(node, cst_node, {}, resolver, config)
        assert "billing.calculate_total" in prompt
        assert "src/billing.py" in prompt
        assert "Lines: 10-25" in prompt

    @patch("remora.core.agents.swarm_executor.build_client")
    def test_executor_constructor_no_swarm_state_param(self, mock_build_client, tmp_path):
        """SwarmExecutor should not require a swarm_state parameter."""
        import inspect
        from remora.core.agents.swarm_executor import SwarmExecutor

        sig = inspect.signature(SwarmExecutor.__init__)
        param_names = list(sig.parameters.keys())
        assert "swarm_state" not in param_names, "SwarmExecutor.__init__ should not have a swarm_state parameter"

    @patch("remora.core.agents.swarm_executor.build_client")
    def test_run_agent_accepts_agent_node(self, mock_build_client, tmp_path):
        """run_agent type annotation should accept AgentNode."""
        import inspect
        from remora.core.agents.swarm_executor import SwarmExecutor

        sig = inspect.signature(SwarmExecutor.run_agent)
        # First param after self should accept AgentNode
        params = list(sig.parameters.values())
        # params[0] is self, params[1] is the agent param
        agent_param = params[1]
        annotation = agent_param.annotation
        # Should be AgentNode (or at least not AgentState)
        assert "AgentState" not in str(annotation), f"run_agent should not use AgentState, got annotation: {annotation}"


# =========================================================================
# 3. Service handlers use EventStore instead of SwarmState
# =========================================================================


class TestServiceHandlersUseEventStore:
    """Service handler functions should query EventStore for agent data."""

    @pytest.mark.asyncio
    async def test_handle_swarm_list_agents_uses_event_store(self):
        """handle_swarm_list_agents should use EventStore.list_nodes."""
        from remora.service.handlers import handle_swarm_list_agents, ServiceDeps

        mock_event_store = AsyncMock()
        mock_event_store.nodes.list_nodes = AsyncMock(
            return_value=[
                _make_agent_node(node_id="a1", name="func_a"),
                _make_agent_node(node_id="a2", name="func_b"),
            ]
        )

        deps = ServiceDeps(
            event_bus=MagicMock(),
            config=Config(),
            project_root=Path("/tmp"),
            projector=MagicMock(),
            event_store=mock_event_store,
        )

        result = await handle_swarm_list_agents(deps)
        assert len(result) == 2
        mock_event_store.nodes.list_nodes.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_swarm_get_agent_uses_event_store(self):
        """handle_swarm_get_agent should use EventStore.get_node."""
        from remora.service.handlers import handle_swarm_get_agent, ServiceDeps

        mock_event_store = AsyncMock()
        mock_event_store.nodes.get_node = AsyncMock(return_value=_make_agent_node(node_id="agent_1", name="my_func"))

        deps = ServiceDeps(
            event_bus=MagicMock(),
            config=Config(),
            project_root=Path("/tmp"),
            projector=MagicMock(),
            event_store=mock_event_store,
        )

        result = await handle_swarm_get_agent("agent_1", deps)
        assert result["node_id"] == "agent_1"
        assert result["name"] == "my_func"
        mock_event_store.nodes.get_node.assert_awaited_once_with("agent_1")

    @pytest.mark.asyncio
    async def test_handle_swarm_list_agents_no_event_store_raises(self):
        """Should raise if no event_store is configured."""
        from remora.service.handlers import handle_swarm_list_agents, ServiceDeps

        deps = ServiceDeps(
            event_bus=MagicMock(),
            config=Config(),
            project_root=Path("/tmp"),
            projector=MagicMock(),
            event_store=None,
        )

        with pytest.raises(ValueError, match="event store"):
            await handle_swarm_list_agents(deps)

    @pytest.mark.asyncio
    async def test_handle_swarm_get_agent_not_found_raises(self):
        """Should raise if agent not found."""
        from remora.service.handlers import handle_swarm_get_agent, ServiceDeps

        mock_event_store = AsyncMock()
        mock_event_store.nodes.get_node = AsyncMock(return_value=None)

        deps = ServiceDeps(
            event_bus=MagicMock(),
            config=Config(),
            project_root=Path("/tmp"),
            projector=MagicMock(),
            event_store=mock_event_store,
        )

        with pytest.raises(ValueError, match="agent not found"):
            await handle_swarm_get_agent("nonexistent", deps)


# =========================================================================
# 4. CLI swarm list uses EventStore
# =========================================================================


class TestCliUsesEventStore:
    """CLI swarm list command should query EventStore, not SwarmState."""

    def test_swarm_list_no_swarm_state_import(self):
        """The swarm_list implementation should not import SwarmState."""
        import inspect
        from remora.cli.main import swarm_list

        # Click wraps the function; use .callback to get the real function
        func = getattr(swarm_list, "callback", swarm_list)
        source = inspect.getsource(func)
        assert "SwarmState" not in source, "swarm_list should not reference SwarmState"


# =========================================================================
# 5. AgentNode has what SwarmExecutor needs (no _state_to_cst_node needed)
# =========================================================================


class TestAgentNodeSufficiency:
    """AgentNode has all fields SwarmExecutor needs — no conversion required."""

    def test_agent_node_has_file_path(self):
        node = _make_agent_node()
        assert hasattr(node, "file_path")
        assert node.file_path == "src/billing.py"

    def test_agent_node_has_range_equivalent(self):
        """AgentNode has start_line/end_line instead of range tuple."""
        node = _make_agent_node(start_line=10, end_line=25)
        assert node.start_line == 10
        assert node.end_line == 25

    def test_agent_node_has_full_name(self):
        node = _make_agent_node()
        assert node.full_name == "billing.calculate_total"

    def test_agent_node_has_source_code(self):
        """AgentNode carries source_code — no separate load needed."""
        node = _make_agent_node(source_code="def foo(): pass")
        assert node.source_code == "def foo(): pass"

    def test_agent_node_to_cst_node(self):
        """Can create a CSTNode from AgentNode fields for data_provider."""
        from remora.core.code.discovery import CSTNode

        node = _make_agent_node()
        cst = CSTNode(
            node_id=node.node_id,
            node_type=node.node_type,
            name=node.name,
            full_name=node.full_name,
            file_path=node.file_path,
            text=node.source_code,
            start_line=node.start_line,
            end_line=node.end_line,
            start_byte=node.start_byte,
            end_byte=node.end_byte,
        )
        assert cst.node_id == node.node_id
        assert cst.text == node.source_code


# =========================================================================
# 6. Post-unification cleanup: agent_state.py deleted
# =========================================================================


class TestAgentStateModuleDeleted:
    """After identity unification, agent_state.py should not exist."""

    def test_agent_state_module_file_deleted(self):
        """The agent_state.py source file should no longer exist."""
        module_path = Path(__file__).resolve().parents[2] / "src" / "remora" / "core" / "agent_state.py"
        assert not module_path.exists(), f"agent_state.py should be deleted: {module_path}"

    def test_agent_state_not_importable(self):
        """Importing agent_state should fail — module is gone."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("remora.core.agent_state")

    def test_no_agent_state_in_core_init(self):
        """core/__init__.py should not re-export AgentState."""
        import remora.core as core

        assert not hasattr(core, "AgentState"), "AgentState should not be in core.__init__"

    def test_no_agent_state_in_remora_init(self):
        """remora/__init__.py should not re-export AgentState."""
        import remora

        assert not hasattr(remora, "AgentState"), "AgentState should not be in remora.__init__"


class TestSwarmStateModuleDeleted:
    """After post-unification cleanup, swarm_state.py should not exist."""

    def test_swarm_state_module_file_deleted(self):
        """The swarm_state.py source file should no longer exist."""
        module_path = Path(__file__).resolve().parents[2] / "src" / "remora" / "core" / "swarm_state.py"
        assert not module_path.exists(), f"swarm_state.py should be deleted: {module_path}"

    def test_swarm_state_not_importable(self):
        """Importing swarm_state should fail — module is gone."""
        import importlib

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("remora.core.swarm_state")

    def test_no_swarm_state_in_core_init(self):
        """core/__init__.py should not re-export SwarmState."""
        import remora.core as core

        assert not hasattr(core, "SwarmState"), "SwarmState should not be in core.__init__"

    def test_no_swarm_state_in_remora_init(self):
        """remora/__init__.py should not re-export SwarmState."""
        import remora

        assert not hasattr(remora, "SwarmState"), "SwarmState should not be in remora.__init__"
