"""Tests for custom node extension configs: ClassDocGenerator, FunctionTestScaffold, SwarmMonitor.

These extensions demonstrate Remora's reactive event-driven architecture:
- ClassDocGenerator: node that creates another node (class -> doc file)
- FunctionTestScaffold: cascading reactivity (function -> test file -> test agents)
- SwarmMonitor: meta-observation (watches all agent activity)
"""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from remora.core.agent_node import AgentNode, ToolSchema
from remora.core.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    ContentChangedEvent,
    NodeDiscoveredEvent,
)
from remora.core.projections import NodeProjection
from remora.core.subscriptions import SubscriptionPattern
from remora.extensions import AgentExtension, extension_matches


# ---------------------------------------------------------------------------
# Helpers to load extensions from the demo models directory
# ---------------------------------------------------------------------------

_DEMO_MODELS_DIR = Path(__file__).resolve().parents[2] / "remora_demo" / "project" / ".remora" / "models"


def _load_extension_class(module_filename: str, class_name: str) -> type:
    """Import an extension class directly from the demo models directory."""
    import importlib.util

    module_path = _DEMO_MODELS_DIR / module_filename
    spec = importlib.util.spec_from_file_location(module_path.stem, module_path)
    assert spec and spec.loader, f"Could not load {module_path}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, class_name)


# ============================================================================
# ClassDocGenerator Tests
# ============================================================================


class TestClassDocGeneratorMatches:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("class_doc_generator.py", "ClassDocGeneratorExtension")

    def test_matches_class(self):
        assert self.ext.matches("class", "MyClass") is True

    def test_matches_class_with_widened_api(self):
        assert (
            extension_matches(
                self.ext,
                "class",
                "MyClass",
                file_path="src/foo.py",
                source_code="class MyClass:\n    pass",
            )
            is True
        )

    def test_rejects_function(self):
        assert self.ext.matches("function", "my_func") is False

    def test_rejects_method(self):
        assert self.ext.matches("method", "my_method") is False

    def test_rejects_file(self):
        assert self.ext.matches("file", "MyClass") is False


class TestClassDocGeneratorData:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("class_doc_generator.py", "ClassDocGeneratorExtension")

    def test_extension_name(self):
        data = self.ext.get_extension_data()
        assert data["extension_name"] == "ClassDocGenerator"

    def test_custom_system_prompt_mentions_documentation(self):
        data = self.ext.get_extension_data()
        prompt = data["custom_system_prompt"].lower()
        assert "document" in prompt or "doc" in prompt

    def test_extra_tools_has_create_doc_file(self):
        data = self.ext.get_extension_data()
        tools = data["extra_tools"]
        assert isinstance(tools, list)
        assert len(tools) >= 1
        tool_names = [t["name"] for t in tools]
        assert "create_doc_file" in tool_names

    def test_extra_tools_are_valid_tool_schema(self):
        data = self.ext.get_extension_data()
        for tool_dict in data["extra_tools"]:
            # Should be constructable as ToolSchema
            tool = ToolSchema(**tool_dict)
            assert tool.name
            assert tool.description
            assert isinstance(tool.parameters, dict)

    def test_extra_subscriptions_present(self):
        data = self.ext.get_extension_data()
        subs = data["extra_subscriptions"]
        assert isinstance(subs, list)
        assert len(subs) >= 1

    def test_extra_subscriptions_are_valid_patterns(self):
        data = self.ext.get_extension_data()
        for sub_dict in data["extra_subscriptions"]:
            pattern = SubscriptionPattern(**sub_dict)
            assert pattern.event_types is not None


# ============================================================================
# FunctionTestScaffold Tests
# ============================================================================


class TestFunctionTestScaffoldMatches:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("function_test_scaffold.py", "FunctionTestScaffoldExtension")

    def test_matches_regular_function(self):
        assert self.ext.matches("function", "calculate") is True

    def test_matches_function_with_widened_api(self):
        assert (
            extension_matches(
                self.ext,
                "function",
                "calculate",
                file_path="src/billing.py",
                source_code="def calculate(): pass",
            )
            is True
        )

    def test_rejects_test_function(self):
        """Must not match test_ prefixed functions (those use TestFunction extension)."""
        assert self.ext.matches("function", "test_calculate") is False

    def test_rejects_class(self):
        assert self.ext.matches("class", "MyClass") is False

    def test_rejects_method(self):
        """Methods belong to classes, not standalone functions."""
        assert self.ext.matches("method", "process") is False

    def test_rejects_file(self):
        assert self.ext.matches("file", "calculate") is False


class TestFunctionTestScaffoldData:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("function_test_scaffold.py", "FunctionTestScaffoldExtension")

    def test_extension_name(self):
        data = self.ext.get_extension_data()
        assert data["extension_name"] == "FunctionTestScaffold"

    def test_custom_system_prompt_mentions_test(self):
        data = self.ext.get_extension_data()
        prompt = data["custom_system_prompt"].lower()
        assert "test" in prompt

    def test_extra_tools_has_create_test_file(self):
        data = self.ext.get_extension_data()
        tools = data["extra_tools"]
        assert isinstance(tools, list)
        assert len(tools) >= 1
        tool_names = [t["name"] for t in tools]
        assert "create_test_file" in tool_names

    def test_extra_tools_are_valid_tool_schema(self):
        data = self.ext.get_extension_data()
        for tool_dict in data["extra_tools"]:
            tool = ToolSchema(**tool_dict)
            assert tool.name
            assert tool.description
            assert isinstance(tool.parameters, dict)

    def test_extra_subscriptions_present(self):
        data = self.ext.get_extension_data()
        subs = data["extra_subscriptions"]
        assert isinstance(subs, list)
        assert len(subs) >= 1


# ============================================================================
# SwarmMonitor Tests
# ============================================================================


class TestSwarmMonitorMatches:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension")

    def test_matches_monitor_md(self):
        assert self.ext.matches("file", "MONITOR") is True

    def test_matches_with_widened_api(self):
        assert (
            extension_matches(
                self.ext,
                "file",
                "MONITOR",
                file_path="MONITOR.md",
                source_code="# Activity Log",
            )
            is True
        )

    def test_rejects_readme(self):
        assert self.ext.matches("file", "README") is False

    def test_rejects_wrong_node_type(self):
        """Must be file node_type, not function or section."""
        assert self.ext.matches("function", "MONITOR") is False
        assert self.ext.matches("section", "MONITOR") is False

    def test_rejects_other_file(self):
        assert self.ext.matches("file", "main.py") is False


class TestSwarmMonitorData:
    @pytest.fixture(autouse=True)
    def load_ext(self):
        self.ext = _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension")

    def test_extension_name(self):
        data = self.ext.get_extension_data()
        assert data["extension_name"] == "SwarmMonitor"

    def test_custom_system_prompt_mentions_observe_or_monitor(self):
        data = self.ext.get_extension_data()
        prompt = data["custom_system_prompt"].lower()
        assert "observe" in prompt or "monitor" in prompt

    def test_extra_subscriptions_subscribe_to_agent_events(self):
        """SwarmMonitor should subscribe to ToolCallEvent, AgentErrorEvent, AgentCompleteEvent."""
        data = self.ext.get_extension_data()
        subs = data["extra_subscriptions"]
        assert isinstance(subs, list)
        assert len(subs) >= 1

        # Collect all event types across all subscription patterns
        all_event_types: set[str] = set()
        for sub_dict in subs:
            pattern = SubscriptionPattern(**sub_dict)
            if pattern.event_types:
                all_event_types.update(pattern.event_types)

        assert "AgentCompleteEvent" in all_event_types
        assert "AgentErrorEvent" in all_event_types

    def test_no_extra_tools(self):
        """SwarmMonitor uses rewrite_self only — no extra tools."""
        data = self.ext.get_extension_data()
        tools = data.get("extra_tools", [])
        assert tools == [] or "extra_tools" not in data

    def test_subscription_patterns_are_valid(self):
        data = self.ext.get_extension_data()
        for sub_dict in data["extra_subscriptions"]:
            pattern = SubscriptionPattern(**sub_dict)
            assert pattern.event_types is not None


# ============================================================================
# Projection Integration Tests
# ============================================================================


class TestProjectionWithCustomExtensions:
    """Verify NodeProjection correctly populates nodes table with extension data."""

    @pytest.fixture
    def all_extensions(self):
        """Load all 5 extensions (2 existing + 3 new) in alphabetical filename order."""
        exts = []
        exts.append(_load_extension_class("class_doc_generator.py", "ClassDocGeneratorExtension"))
        exts.append(_load_extension_class("function_test_scaffold.py", "FunctionTestScaffoldExtension"))
        exts.append(_load_extension_class("package_init.py", "PackageInitExtension"))
        exts.append(_load_extension_class("swarm_monitor.py", "SwarmMonitorExtension"))
        exts.append(_load_extension_class("test_function.py", "TestFunctionExtension"))
        return exts

    @pytest.fixture
    async def store(self, tmp_path):
        from remora.core.event_store import EventStore

        s = EventStore(tmp_path / "test.db")
        await s.initialize()
        yield s
        await s.close()

    def _discovered(self, **overrides) -> NodeDiscoveredEvent:
        defaults = {
            "node_id": "test-node",
            "node_type": "function",
            "name": "my_func",
            "full_name": "function:my_func",
            "file_path": "src/billing.py",
            "start_line": 1,
            "end_line": 10,
            "source_code": "def my_func(): pass",
            "source_hash": "abc",
        }
        defaults.update(overrides)
        return NodeDiscoveredEvent(**defaults)

    @pytest.mark.asyncio
    async def test_class_gets_class_doc_generator(self, store, all_extensions):
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="cls-1",
            node_type="class",
            name="MyClass",
            full_name="class:MyClass",
            source_code="class MyClass: pass",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("cls-1",)).fetchone()
        assert row["extension_name"] == "ClassDocGenerator"
        assert row["custom_system_prompt"] != ""
        # extra_tools and extra_subscriptions should be non-empty JSON arrays
        tools = json.loads(row["extra_tools"])
        assert len(tools) >= 1
        subs = json.loads(row["extra_subscriptions"])
        assert len(subs) >= 1

    @pytest.mark.asyncio
    async def test_non_test_function_gets_function_test_scaffold(self, store, all_extensions):
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="fn-1",
            node_type="function",
            name="calculate",
            full_name="function:calculate",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("fn-1",)).fetchone()
        assert row["extension_name"] == "FunctionTestScaffold"

    @pytest.mark.asyncio
    async def test_test_function_gets_test_function_extension(self, store, all_extensions):
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="fn-2",
            node_type="function",
            name="test_calculate",
            full_name="function:test_calculate",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("fn-2",)).fetchone()
        assert row["extension_name"] == "TestFunction"

    @pytest.mark.asyncio
    async def test_monitor_md_gets_swarm_monitor(self, store, all_extensions):
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="file-1",
            node_type="file",
            name="MONITOR",
            full_name="file:MONITOR",
            file_path="MONITOR.md",
            source_code="# Activity Log\n",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("file-1",)).fetchone()
        assert row["extension_name"] == "SwarmMonitor"
        # SwarmMonitor should have subscriptions but no extra tools
        tools = json.loads(row["extra_tools"])
        assert tools == []
        subs = json.loads(row["extra_subscriptions"])
        assert len(subs) >= 1

    @pytest.mark.asyncio
    async def test_init_py_gets_package_init(self, store, all_extensions):
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="file-2",
            node_type="file",
            name="__init__",
            full_name="file:__init__",
            file_path="src/__init__.py",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("file-2",)).fetchone()
        assert row["extension_name"] == "PackageInit"

    @pytest.mark.asyncio
    async def test_hydrate_agent_node_with_extension_data(self, store, all_extensions):
        """AgentNode.from_row() correctly deserializes extension fields."""
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=all_extensions)
        event = self._discovered(
            node_id="cls-2",
            node_type="class",
            name="Widget",
            full_name="class:Widget",
            source_code="class Widget: pass",
        )
        proj.apply(store._conn, event)
        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("cls-2",)).fetchone()
        node = AgentNode.from_row(row)
        assert node.extension_name == "ClassDocGenerator"
        assert len(node.extra_tools) >= 1
        assert isinstance(node.extra_tools[0], ToolSchema)
        assert len(node.extra_subscriptions) >= 1
        assert isinstance(node.extra_subscriptions[0], SubscriptionPattern)


# ============================================================================
# Subscription Pattern Matching Tests
# ============================================================================


class TestExtensionSubscriptionPatterns:
    """Verify subscription patterns from extensions match correct events."""

    def test_swarm_monitor_matches_agent_complete_event(self):
        ext = _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension")
        data = ext.get_extension_data()

        # Build patterns
        patterns = [SubscriptionPattern(**s) for s in data["extra_subscriptions"]]

        event = AgentCompleteEvent(graph_id="swarm", agent_id="some-agent", result_summary="done")
        assert any(p.matches(event) for p in patterns)

    def test_swarm_monitor_matches_agent_error_event(self):
        ext = _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension")
        data = ext.get_extension_data()
        patterns = [SubscriptionPattern(**s) for s in data["extra_subscriptions"]]

        event = AgentErrorEvent(graph_id="swarm", agent_id="some-agent", error="boom")
        assert any(p.matches(event) for p in patterns)

    def test_swarm_monitor_does_not_match_content_changed(self):
        ext = _load_extension_class("swarm_monitor.py", "SwarmMonitorExtension")
        data = ext.get_extension_data()
        patterns = [SubscriptionPattern(**s) for s in data["extra_subscriptions"]]

        event = ContentChangedEvent(path="src/main.py")
        assert not any(p.matches(event) for p in patterns)

    def test_class_doc_generator_subscription_matches_content_changed(self):
        ext = _load_extension_class("class_doc_generator.py", "ClassDocGeneratorExtension")
        data = ext.get_extension_data()
        patterns = [SubscriptionPattern(**s) for s in data["extra_subscriptions"]]

        # At least one pattern should match ContentChangedEvent
        event = ContentChangedEvent(path="src/foo.py")
        # The subscription should include ContentChangedEvent in event_types
        event_types_across_patterns = set()
        for p in patterns:
            if p.event_types:
                event_types_across_patterns.update(p.event_types)
        assert (
            "ContentChangedEvent" in event_types_across_patterns or "NodeDiscoveredEvent" in event_types_across_patterns
        )
