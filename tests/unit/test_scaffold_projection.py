"""Tests for scaffold status detection in NodeProjection.

Verifies:
- NodeDiscoveredEvent with empty source_code -> status = "scaffold"
- NodeDiscoveredEvent with stub patterns -> status = "scaffold"
- NodeDiscoveredEvent with real source_code -> status = "idle" (unchanged)
- Upsert preserves existing scaffold/idle status appropriately
- _is_stub() helper function behavior
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection, _is_stub

pytestmark = pytest.mark.skip(reason="Scaffold projection disabled until AST-based detection lands")


@pytest.fixture
async def store(tmp_path: Path):
    s = EventStore(tmp_path / "test.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.fixture
def projection():
    return NodeProjection(extension_configs=[])


def _discovered_event(**overrides) -> NodeDiscoveredEvent:
    defaults = {
        "node_id": "abc123",
        "node_type": "function",
        "name": "my_func",
        "full_name": "function:my_func",
        "file_path": "/src/app.py",
        "start_line": 1,
        "end_line": 5,
        "source_code": "def my_func(): pass",
        "source_hash": "aabb",
    }
    defaults.update(overrides)
    return NodeDiscoveredEvent(**defaults)


# ============================================================================
# _is_stub() unit tests
# ============================================================================


class TestIsStub:
    """Direct tests for the _is_stub() helper function."""

    def test_empty_string_is_stub(self):
        assert _is_stub("") is True

    def test_whitespace_only_is_stub(self):
        assert _is_stub("   \n\n  ") is True

    def test_class_pass_is_stub(self):
        assert _is_stub("class Foo: pass") is True

    def test_class_pass_with_newline_is_stub(self):
        assert _is_stub("class Foo: pass\n") is True

    def test_class_ellipsis_is_stub(self):
        assert _is_stub("class Foo: ...") is True

    def test_class_with_pass_body_is_stub(self):
        assert _is_stub("class Foo:\n    pass") is True

    def test_class_with_ellipsis_body_is_stub(self):
        assert _is_stub("class Foo:\n    ...") is True

    def test_def_pass_is_stub(self):
        assert _is_stub("def foo(): pass") is True

    def test_def_ellipsis_is_stub(self):
        assert _is_stub("def foo(): ...") is True

    def test_def_with_pass_body_is_stub(self):
        assert _is_stub("def foo():\n    pass") is True

    def test_def_with_ellipsis_body_is_stub(self):
        assert _is_stub("def foo():\n    ...") is True

    def test_def_with_params_pass_is_stub(self):
        assert _is_stub("def foo(x, y): pass") is True

    def test_def_with_type_hints_pass_is_stub(self):
        assert _is_stub("def foo(x: int, y: str) -> bool: pass") is True

    def test_real_function_not_stub(self):
        assert _is_stub("def foo():\n    return 42") is False

    def test_real_class_not_stub(self):
        assert _is_stub("class Foo:\n    def __init__(self):\n        self.x = 1") is False

    def test_comment_only_is_stub(self):
        assert _is_stub("# just a comment\n") is True

    def test_docstring_only_is_stub(self):
        assert _is_stub('"""Module docstring."""\n') is True

    def test_real_code_not_stub(self):
        assert _is_stub("import os\nprint(os.getcwd())") is False

    def test_class_with_docstring_and_pass_is_stub(self):
        assert _is_stub('class Foo:\n    """A class."""\n    pass') is True

    def test_def_with_docstring_and_pass_is_stub(self):
        assert _is_stub('def foo():\n    """A function."""\n    pass') is True


# ============================================================================
# Projection integration tests — scaffold status
# ============================================================================


class TestScaffoldStatusProjection:
    """NodeProjection assigns status='scaffold' for stub source_code."""

    @pytest.mark.asyncio
    async def test_empty_source_gets_scaffold_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(source_code="", source_hash="empty")
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

    @pytest.mark.asyncio
    async def test_class_pass_gets_scaffold_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(
            node_type="class",
            name="Foo",
            source_code="class Foo: pass",
        )
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

    @pytest.mark.asyncio
    async def test_def_ellipsis_gets_scaffold_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(
            source_code="def my_func(): ...",
        )
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

    @pytest.mark.asyncio
    async def test_def_pass_body_gets_scaffold_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(
            source_code="def my_func():\n    pass",
        )
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

    @pytest.mark.asyncio
    async def test_real_source_gets_idle_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(
            source_code="def my_func():\n    return 42\n",
        )
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "idle"

    @pytest.mark.asyncio
    async def test_real_class_gets_idle_status(self, store: EventStore, projection: NodeProjection):
        event = _discovered_event(
            node_type="class",
            name="Foo",
            source_code="class Foo:\n    def __init__(self):\n        self.x = 1",
        )
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "idle"

    @pytest.mark.asyncio
    async def test_upsert_does_not_overwrite_scaffold_to_idle(self, store: EventStore, projection: NodeProjection):
        """Re-discovering a scaffold node (still stub) should keep scaffold status."""
        event1 = _discovered_event(source_code="class Foo: pass", source_hash="v1")
        projection.apply(store._conn, event1)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

        # Re-discover with same stub content
        event2 = _discovered_event(source_code="class Foo: pass", source_hash="v1")
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

    @pytest.mark.asyncio
    async def test_scaffold_transitions_to_idle_on_real_content(self, store: EventStore, projection: NodeProjection):
        """When a scaffold node gets real content via rewrite, it transitions to idle."""
        # First: create as scaffold
        event1 = _discovered_event(source_code="class Foo: pass", source_hash="v1")
        projection.apply(store._conn, event1)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "scaffold"

        # Then: re-discover with real content (after rewrite_self)
        event2 = _discovered_event(
            source_code="class Foo:\n    def __init__(self):\n        self.x = 1",
            source_hash="v2",
        )
        projection.apply(store._conn, event2)

        row = store._conn.execute("SELECT status FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        assert row["status"] == "idle"

    @pytest.mark.asyncio
    async def test_hydrate_scaffold_node(self, store: EventStore, projection: NodeProjection):
        """AgentNode.from_row should preserve scaffold status."""
        event = _discovered_event(source_code="", source_hash="empty")
        projection.apply(store._conn, event)

        row = store._conn.execute("SELECT * FROM nodes WHERE node_id = ?", ("abc123",)).fetchone()
        node = AgentNode.from_row(row)
        assert node.status == "scaffold"
