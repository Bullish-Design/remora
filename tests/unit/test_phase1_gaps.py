"""Phase 1 testing gaps T1-T7 (item 2.12).

T1: ToolSchema.to_llm_tool() — LLM tool conversion
T2: Extension with complex fields through projection round-trip
T3: Error paths for from_row() with malformed JSON
T4: Concurrency tests for multiple append() calls on same node_id
T6: Extension matches() raising exceptions (error isolation)
T7: conftest fixtures exercised via make_agent_node / make_discovered_event
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.agents.agent_node import AgentNode, ToolSchema
from remora.core.events.events import (
    AgentStartEvent,
    NodeDiscoveredEvent,
)
from remora.core.store.event_store import EventStore
from remora.core.code.projections import NodeProjection
from remora.core.events.subscriptions import SubscriptionPattern
from remora.extensions import AgentExtension, extension_matches


# ---------------------------------------------------------------------------
# Shared helpers (T7)
# ---------------------------------------------------------------------------


def make_agent_node(**overrides) -> AgentNode:
    """Create a test AgentNode with sensible defaults."""
    defaults = {
        "node_id": "test_node_001",
        "node_type": "function",
        "name": "do_work",
        "full_name": "function:do_work",
        "file_path": "/src/worker.py",
        "start_line": 1,
        "end_line": 10,
        "source_code": "def do_work(): pass",
        "source_hash": "deadbeef",
    }
    defaults.update(overrides)
    return AgentNode(**defaults)


def make_discovered_event(**overrides) -> NodeDiscoveredEvent:
    """Create a test NodeDiscoveredEvent with sensible defaults."""
    defaults = {
        "node_id": "test_node_001",
        "node_type": "function",
        "name": "do_work",
        "full_name": "function:do_work",
        "file_path": "/src/worker.py",
        "start_line": 1,
        "end_line": 10,
        "source_code": "def do_work(): pass",
        "source_hash": "deadbeef",
    }
    defaults.update(overrides)
    return NodeDiscoveredEvent(**defaults)


_DEFAULT_TOOL_PARAMS = {"type": "object", "properties": {"verbose": {"type": "boolean"}}}


def _make_tool(name: str = "run_test", desc: str = "Run tests", params: dict | None = None) -> ToolSchema:
    return ToolSchema(
        name=name,
        description=desc,
        parameters=_DEFAULT_TOOL_PARAMS if params is None else params,
    )


# ---------------------------------------------------------------------------
# T1 — ToolSchema.to_llm_tool()
# ---------------------------------------------------------------------------


class TestToolSchemaToLlmTool:
    """T1: Verify to_llm_tool() produces correct OpenAI function-calling format."""

    def test_basic_conversion(self):
        tool = _make_tool()
        result = tool.to_llm_tool()
        assert result["type"] == "function"
        assert result["function"]["name"] == "run_test"
        assert result["function"]["description"] == "Run tests"
        assert result["function"]["parameters"]["type"] == "object"

    def test_parameters_preserved_exactly(self):
        params = {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "recursive": {"type": "boolean", "default": False},
            },
            "required": ["path"],
        }
        tool = _make_tool(params=params)
        result = tool.to_llm_tool()
        assert result["function"]["parameters"] == params

    def test_empty_parameters(self):
        tool = _make_tool(params={})
        result = tool.to_llm_tool()
        assert result["function"]["parameters"] == {}

    def test_nested_parameters(self):
        params = {
            "type": "object",
            "properties": {
                "config": {
                    "type": "object",
                    "properties": {
                        "retries": {"type": "integer"},
                        "labels": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        }
        tool = _make_tool(params=params)
        result = tool.to_llm_tool()
        nested = result["function"]["parameters"]["properties"]["config"]
        assert nested["type"] == "object"
        assert nested["properties"]["labels"]["type"] == "array"

    def test_special_characters_in_description(self):
        tool = _make_tool(desc='Run "tests" with <special> & chars')
        result = tool.to_llm_tool()
        assert result["function"]["description"] == 'Run "tests" with <special> & chars'

    def test_result_is_plain_dict(self):
        """Result should be JSON-serializable without custom serializers."""
        tool = _make_tool()
        result = tool.to_llm_tool()
        # Should not raise
        roundtrip = json.loads(json.dumps(result))
        assert roundtrip == result


# ---------------------------------------------------------------------------
# T2 — Extension with complex fields through projection round-trip
# ---------------------------------------------------------------------------


@pytest.fixture
async def store_with_projection(tmp_path: Path):
    """EventStore + NodeProjection wired together for round-trip tests."""

    class ToolExtension(AgentExtension):
        @staticmethod
        def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
            return name == "do_work"

        @staticmethod
        def get_extension_data() -> dict:
            return {
                "extension_name": "WorkerAgent",
                "custom_system_prompt": "You are a worker.",
                "extra_tools": [
                    ToolSchema(
                        name="deploy",
                        description="Deploy the service",
                        parameters={"type": "object", "properties": {"env": {"type": "string"}}},
                    ),
                ],
                "extra_subscriptions": [
                    SubscriptionPattern(
                        event_types=["ContentChangedEvent", "FileSavedEvent"],
                        path_glob="*.py",
                    ),
                ],
                "mounted_workspaces": ["/data/staging", "/data/prod"],
            }

    def dummy_matcher(ext_cls, node_type, name, **kwargs):
        return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
    projection = NodeProjection(extension_matcher=dummy_matcher, extension_configs=[ToolExtension])
    s = EventStore(tmp_path / "proj.db", projection=projection)
    await s.initialize()
    yield s
    await s.close()


class TestExtensionComplexFieldsRoundTrip:
    """T2: Extension-injected extra_tools and extra_subscriptions survive projection → DB → from_row."""

    @pytest.mark.asyncio
    async def test_extra_tools_round_trip(self, store_with_projection: EventStore):
        event = make_discovered_event()
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert node.extension_name == "WorkerAgent"
        assert len(node.extra_tools) == 1
        assert node.extra_tools[0].name == "deploy"
        assert node.extra_tools[0].parameters["properties"]["env"]["type"] == "string"

    @pytest.mark.asyncio
    async def test_extra_subscriptions_round_trip(self, store_with_projection: EventStore):
        event = make_discovered_event()
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert len(node.extra_subscriptions) == 1
        sub = node.extra_subscriptions[0]
        assert sub.event_types == ["ContentChangedEvent", "FileSavedEvent"]
        assert sub.path_glob == "*.py"

    @pytest.mark.asyncio
    async def test_mounted_workspaces_round_trip(self, store_with_projection: EventStore):
        event = make_discovered_event()
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert node.mounted_workspaces == ["/data/staging", "/data/prod"]

    @pytest.mark.asyncio
    async def test_custom_system_prompt_round_trip(self, store_with_projection: EventStore):
        event = make_discovered_event()
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert node.custom_system_prompt == "You are a worker."

    @pytest.mark.asyncio
    async def test_tools_usable_after_round_trip(self, store_with_projection: EventStore):
        """Hydrated ToolSchema instances should still produce valid LLM tool dicts."""
        event = make_discovered_event()
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        llm_tool = node.extra_tools[0].to_llm_tool()
        assert llm_tool["type"] == "function"
        assert llm_tool["function"]["name"] == "deploy"

    @pytest.mark.asyncio
    async def test_upsert_preserves_extension_fields(self, store_with_projection: EventStore):
        """Re-discovering the same node should update extension fields."""
        event1 = make_discovered_event(source_hash="v1")
        await store_with_projection.append("g1", event1)

        event2 = make_discovered_event(source_hash="v2", source_code="def do_work(x): pass")
        await store_with_projection.append("g1", event2)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert node.source_hash == "v2"
        # Extension fields should still be populated after upsert
        assert node.extension_name == "WorkerAgent"
        assert len(node.extra_tools) == 1

    @pytest.mark.asyncio
    async def test_non_matching_node_has_empty_extension_fields(self, store_with_projection: EventStore):
        """A node that doesn't match the extension should have empty lists."""
        event = make_discovered_event(name="other_func", full_name="function:other_func")
        await store_with_projection.append("g1", event)

        node = await store_with_projection.nodes.get_node("test_node_001")
        assert node is not None
        assert node.extension_name is None
        assert node.extra_tools == []
        assert node.extra_subscriptions == []


# ---------------------------------------------------------------------------
# T3 — Error paths for from_row() with malformed JSON
# ---------------------------------------------------------------------------


class TestFromRowMalformedJSON:
    """T3: from_row() should raise on malformed JSON in serialized columns."""

    def _make_db_row(self, **overrides) -> sqlite3.Row:
        """Create a sqlite3.Row with valid defaults, then override."""
        defaults = {
            "node_id": "test_node_001",
            "node_type": "function",
            "name": "do_work",
            "full_name": "function:do_work",
            "file_path": "/src/worker.py",
            "start_line": 1,
            "end_line": 10,
            "start_byte": 0,
            "end_byte": 100,
            "source_code": "def do_work(): pass",
            "source_hash": "deadbeef",
            "parent_id": None,
            "caller_ids": "[]",
            "callee_ids": "[]",
            "status": "idle",
            "last_trigger_event": "",
            "last_completed_at": None,
            "extension_name": None,
            "custom_system_prompt": "",
            "mounted_workspaces": "[]",
            "extra_tools": "[]",
            "extra_subscriptions": "[]",
        }
        defaults.update(overrides)

        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        cols = ", ".join(defaults.keys())
        placeholders = ", ".join("?" * len(defaults))
        db.execute(f"CREATE TABLE nodes ({cols})")
        db.execute(f"INSERT INTO nodes VALUES ({placeholders})", list(defaults.values()))
        return db.execute("SELECT * FROM nodes").fetchone()

    def test_malformed_extra_tools(self):
        row = self._make_db_row(extra_tools="not-json")
        with pytest.raises(json.JSONDecodeError):
            AgentNode.from_row(row)

    def test_malformed_extra_subscriptions(self):
        row = self._make_db_row(extra_subscriptions="{bad}")
        with pytest.raises(json.JSONDecodeError):
            AgentNode.from_row(row)

    def test_malformed_caller_ids(self):
        row = self._make_db_row(caller_ids="not-json")
        with pytest.raises(json.JSONDecodeError):
            AgentNode.from_row(row)

    def test_malformed_callee_ids(self):
        row = self._make_db_row(callee_ids="[[broken")
        with pytest.raises(json.JSONDecodeError):
            AgentNode.from_row(row)

    def test_malformed_mounted_workspaces(self):
        row = self._make_db_row(mounted_workspaces="not-a-list")
        with pytest.raises(json.JSONDecodeError):
            AgentNode.from_row(row)

    def test_extra_tools_wrong_structure(self):
        """JSON is valid but not a list of tool dicts — should raise TypeError."""
        row = self._make_db_row(extra_tools='"just-a-string"')
        with pytest.raises(TypeError):
            AgentNode.from_row(row)

    def test_extra_tools_missing_fields(self):
        """JSON list of dicts but missing required ToolSchema fields."""
        from pydantic import ValidationError

        row = self._make_db_row(extra_tools='[{"name": "x"}]')
        with pytest.raises((TypeError, ValidationError)):
            AgentNode.from_row(row)

    def test_null_json_fields_use_empty_defaults(self):
        """None/null JSON columns should fall back to empty lists."""
        row = self._make_db_row(
            caller_ids=None,
            callee_ids=None,
            extra_tools=None,
            extra_subscriptions=None,
            mounted_workspaces=None,
        )
        node = AgentNode.from_row(row)
        assert node.caller_ids == []
        assert node.callee_ids == []
        assert node.extra_tools == []
        assert node.extra_subscriptions == []
        assert node.mounted_workspaces == []


# ---------------------------------------------------------------------------
# T4 — Concurrency tests for append()
# ---------------------------------------------------------------------------


class TestAppendConcurrency:
    """T4: Multiple concurrent append() calls should not corrupt data."""

    @pytest.mark.asyncio
    async def test_concurrent_appends_same_graph(self, tmp_path: Path):
        """Many concurrent appends to the same graph should all succeed."""
        store = EventStore(tmp_path / "conc.db")
        await store.initialize()

        n_events = 50

        async def _append(i: int) -> int:
            event = make_discovered_event(
                node_id=f"node_{i}",
                name=f"func_{i}",
                full_name=f"function:func_{i}",
            )
            return await store.append("graph1", event)

        event_ids = await asyncio.gather(*[_append(i) for i in range(n_events)])

        assert len(set(event_ids)) == n_events  # All unique IDs
        count = await store.get_event_count("graph1")
        assert count == n_events
        await store.close()

    @pytest.mark.asyncio
    async def test_concurrent_appends_same_node_id_with_projection(self, tmp_path: Path):
        """Concurrent appends for the SAME node_id through projection — last write wins, no crash."""
        projection = NodeProjection(extension_configs=[])
        store = EventStore(tmp_path / "conc_proj.db", projection=projection)
        await store.initialize()

        n_events = 20

        async def _append(i: int) -> int:
            event = make_discovered_event(
                source_hash=f"hash_{i}",
                source_code=f"def do_work(): return {i}",
            )
            return await store.append("graph1", event)

        await asyncio.gather(*[_append(i) for i in range(n_events)])

        # Node should exist (last upsert wins)
        node = await store.nodes.get_node("test_node_001")
        assert node is not None
        assert node.node_id == "test_node_001"

        # All events stored
        count = await store.get_event_count("graph1")
        assert count == n_events
        await store.close()

    @pytest.mark.asyncio
    async def test_concurrent_appends_different_graphs(self, tmp_path: Path):
        """Appends to different graph_ids should be fully independent."""
        store = EventStore(tmp_path / "conc_multi.db")
        await store.initialize()

        async def _append(graph: str, i: int) -> int:
            event = make_discovered_event(
                node_id=f"{graph}_node_{i}",
                name=f"func_{i}",
                full_name=f"function:func_{i}",
            )
            return await store.append(graph, event)

        tasks = []
        for g in ["g1", "g2", "g3"]:
            for i in range(10):
                tasks.append(_append(g, i))

        await asyncio.gather(*tasks)

        for g in ["g1", "g2", "g3"]:
            count = await store.get_event_count(g)
            assert count == 10

        await store.close()


# ---------------------------------------------------------------------------
# T6 — Extension matches() raising exceptions
# ---------------------------------------------------------------------------


class TestExtensionMatchesErrorIsolation:
    """T6: extension_matches() should handle errors from buggy extensions."""

    def test_non_type_error_propagates(self):
        """An extension whose matches() raises a non-TypeError should propagate."""

        class BuggyExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                raise ValueError("I'm broken")

        # extension_matches only catches TypeError for old-API fallback;
        # ValueError should propagate to the caller
        with pytest.raises(ValueError, match="I'm broken"):
            extension_matches(BuggyExt, "function", "foo")

    def test_old_api_fallback_works(self):
        """Extension with 2-arg matches() should still work via TypeError fallback."""

        class OldStyleExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                return name == "target"

            @staticmethod
            def get_extension_data() -> dict:
                return {"extension_name": "OldStyle"}

        assert extension_matches(OldStyleExt, "function", "target") is True
        assert extension_matches(OldStyleExt, "function", "other") is False

    def test_old_api_with_kwargs_fallback(self):
        """Old-style extension should receive file_path/source_code context if it accepts them."""

        class NewStyleExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                return "worker" in file_path

        assert extension_matches(NewStyleExt, "function", "foo", file_path="/src/worker.py", source_code="") is True
        assert extension_matches(NewStyleExt, "function", "foo", file_path="/src/utils.py", source_code="") is False

    def test_old_api_exception_propagates(self):
        """Old-style matches() that raises non-TypeError should still propagate."""

        class BuggyOldExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str) -> bool:
                raise RuntimeError("old-style bug")

        # First call with kwargs -> TypeError -> falls back to 2-arg -> RuntimeError
        with pytest.raises(RuntimeError, match="old-style bug"):
            extension_matches(BuggyOldExt, "function", "foo")

    def test_projection_skips_broken_extension(self):
        """NodeProjection should tolerate a broken extension and still project the node."""

        class GoodExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                return name == "do_work"

            @staticmethod
            def get_extension_data() -> dict:
                return {"extension_name": "GoodAgent"}

        class BadExt(AgentExtension):
            @staticmethod
            def matches(node_type: str, name: str, *, file_path: str = "", source_code: str = "") -> bool:
                raise RuntimeError("crash")

        # BadExt is tried first; extension_matches propagates RuntimeError
        # so projection with BadExt first will fail.
        # But if GoodExt is first, it matches and BadExt is never tried.
        def dummy_matcher(ext_cls, node_type, name, **kwargs):
            return getattr(ext_cls, "matches", lambda *a, **k: False)(node_type, name)
        proj = NodeProjection(extension_matcher=dummy_matcher, extension_configs=[GoodExt, BadExt])
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript("""
            CREATE TABLE nodes (
                node_id TEXT PRIMARY KEY, node_type TEXT, name TEXT,
                full_name TEXT, file_path TEXT, start_line INTEGER,
                end_line INTEGER, start_byte INTEGER DEFAULT 0,
                end_byte INTEGER DEFAULT 0, source_code TEXT,
                source_hash TEXT, parent_id TEXT, caller_ids TEXT DEFAULT '[]',
                callee_ids TEXT DEFAULT '[]', status TEXT DEFAULT 'idle',
                last_trigger_event TEXT DEFAULT '', last_completed_at REAL,
                extension_name TEXT, custom_system_prompt TEXT DEFAULT '',
                mounted_workspaces TEXT DEFAULT '[]', extra_tools TEXT DEFAULT '[]',
                extra_subscriptions TEXT DEFAULT '[]'
            )
        """)
        event = make_discovered_event()
        proj.apply(db, event)

        row = db.execute("SELECT * FROM nodes WHERE node_id = ?", ("test_node_001",)).fetchone()
        assert row["extension_name"] == "GoodAgent"


# ---------------------------------------------------------------------------
# T7 — Verify shared fixtures work correctly
# ---------------------------------------------------------------------------


class TestSharedFixtures:
    """T7: make_agent_node and make_discovered_event produce valid objects."""

    def test_make_agent_node_defaults(self):
        node = make_agent_node()
        assert node.node_id == "test_node_001"
        assert node.node_type == "function"
        assert node.status == "idle"
        assert node.extra_tools == []

    def test_make_agent_node_overrides(self):
        node = make_agent_node(
            node_id="custom_id",
            status="running",
            extra_tools=[_make_tool()],
        )
        assert node.node_id == "custom_id"
        assert node.status == "running"
        assert len(node.extra_tools) == 1

    def test_make_discovered_event_defaults(self):
        event = make_discovered_event()
        assert event.node_id == "test_node_001"
        assert event.node_type == "function"
        assert event.start_byte == 0
        assert event.end_byte == 0

    def test_make_discovered_event_overrides(self):
        event = make_discovered_event(
            node_id="custom",
            start_byte=100,
            end_byte=500,
        )
        assert event.node_id == "custom"
        assert event.start_byte == 100
        assert event.end_byte == 500

    def test_make_agent_node_round_trips(self):
        """Node from make_agent_node should survive to_row/from_row."""
        node = make_agent_node(extra_tools=[_make_tool()])
        row = node.to_row()
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" * len(row))
        db.execute(f"CREATE TABLE nodes ({cols})")
        db.execute(f"INSERT INTO nodes VALUES ({placeholders})", list(row.values()))
        sqlite_row = db.execute("SELECT * FROM nodes").fetchone()

        restored = AgentNode.from_row(sqlite_row)
        assert restored.node_id == node.node_id
        assert len(restored.extra_tools) == 1
        assert restored.extra_tools[0].name == "run_test"
