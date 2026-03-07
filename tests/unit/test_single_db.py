"""TDD tests for 6.3: Single SQLite database.

Verifies:
- EventStore enables WAL mode
- EventStore creates subscriptions table
- EventStore creates RemoraDB tables (edges, proposals, cursor_focus, etc.)
- SubscriptionRegistry accepts a shared connection from EventStore
- RemoraDB accepts a shared connection from EventStore
- All three components work against the same DB file
"""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from remora.core.event_store import EventStore
from remora.core.events import NodeDiscoveredEvent
from remora.core.projections import NodeProjection
from remora.core.subscriptions import SubscriptionPattern, SubscriptionRegistry


class TestEventStoreWALMode:
    """EventStore should enable WAL journal mode."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        # Check journal_mode via the internal connection
        assert store._conn is not None
        cursor = store._conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal", f"Expected WAL mode, got {mode}"

        await store.close()

    @pytest.mark.asyncio
    async def test_synchronous_normal(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("PRAGMA synchronous")
        # synchronous=NORMAL is value 1
        val = cursor.fetchone()[0]
        assert val == 1, f"Expected synchronous=1 (NORMAL), got {val}"

        await store.close()


class TestEventStoreSubscriptionsTable:
    """EventStore should create the subscriptions table."""

    @pytest.mark.asyncio
    async def test_subscriptions_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='subscriptions'")
        row = cursor.fetchone()
        assert row is not None, "subscriptions table should exist"

        await store.close()

    @pytest.mark.asyncio
    async def test_subscriptions_table_columns(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("PRAGMA table_info(subscriptions)")
        columns = {row[1] for row in cursor.fetchall()}
        expected = {"id", "agent_id", "pattern_json", "is_default", "created_at", "updated_at"}
        assert expected.issubset(columns), f"Missing columns: {expected - columns}"

        await store.close()


@pytest.mark.skip(reason="EventStore no longer creates RemoraDB tables")
class TestEventStoreRemoraDBTables:
    """EventStore should create the RemoraDB operational tables."""

    @pytest.mark.asyncio
    async def test_edges_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='edges'")
        assert cursor.fetchone() is not None

        await store.close()

    @pytest.mark.asyncio
    async def test_proposals_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='proposals'")
        assert cursor.fetchone() is not None

        await store.close()

    @pytest.mark.asyncio
    async def test_cursor_focus_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='cursor_focus'")
        assert cursor.fetchone() is not None

        await store.close()

    @pytest.mark.asyncio
    async def test_command_queue_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='command_queue'")
        assert cursor.fetchone() is not None

        await store.close()

    @pytest.mark.asyncio
    async def test_activation_chain_table_exists(self, tmp_path):
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        cursor = store._conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activation_chain'")
        assert cursor.fetchone() is not None

        await store.close()


class TestSubscriptionRegistrySharedConnection:
    """SubscriptionRegistry should accept a shared connection."""

    @pytest.mark.asyncio
    async def test_accepts_connection_kwarg(self, tmp_path):
        """SubscriptionRegistry(connection=conn, lock=lock) uses shared connection."""
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        registry = SubscriptionRegistry(
            connection=store._conn,
            lock=store._lock,
        )
        # Should not need to call initialize() — tables already exist
        sub = await registry.register("agent_1", SubscriptionPattern(event_types=["TestEvent"]))
        assert sub.agent_id == "agent_1"

        subs = await registry.get_subscriptions("agent_1")
        assert len(subs) == 1

        await store.close()

    @pytest.mark.asyncio
    async def test_shared_connection_same_db(self, tmp_path):
        """Data written via SubscriptionRegistry is visible via the shared connection."""
        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        registry = SubscriptionRegistry(
            connection=store._conn,
            lock=store._lock,
        )
        await registry.register("agent_x", SubscriptionPattern(event_types=["Foo"]))

        # Query directly via store's connection
        cursor = store._conn.execute("SELECT agent_id FROM subscriptions WHERE agent_id = 'agent_x'")
        row = cursor.fetchone()
        assert row is not None

        await store.close()

    @pytest.mark.asyncio
    async def test_backward_compat_db_path(self, tmp_path):
        """SubscriptionRegistry(db_path) still works for backward compatibility."""
        registry = SubscriptionRegistry(tmp_path / "subs.db")
        await registry.initialize()

        sub = await registry.register("agent_1", SubscriptionPattern(to_agent="agent_1"))
        assert sub.id is not None

        await registry.close()


class TestRemoraDBSharedConnection:
    """RemoraDB should accept a shared connection."""

    @pytest.mark.asyncio
    async def test_accepts_connection_kwarg(self, tmp_path):
        from remora.lsp.db import RemoraDB

        store = EventStore(tmp_path / "remora.db")
        await store.initialize()

        db = RemoraDB(connection=store._conn, lock=store._lock)

        # Should be able to use RemoraDB methods with shared connection
        db.push_command("test_cmd", "agent_1", {"key": "value"})
        cmds = db.poll_commands()
        assert len(cmds) == 1
        assert cmds[0]["command_type"] == "test_cmd"

        await store.close()

    @pytest.mark.asyncio
    async def test_backward_compat_db_path(self, tmp_path):
        from remora.lsp.db import RemoraDB

        db = RemoraDB(db_path=str(tmp_path / "indexer.db"))
        db.push_command("test_cmd", None, {})
        cmds = db.poll_commands()
        assert len(cmds) == 1
        db.close()


class TestSingleDBEndToEnd:
    """All three components share one DB file and see each other's data."""

    @pytest.mark.asyncio
    async def test_all_tables_in_one_file(self, tmp_path):
        from remora.lsp.db import RemoraDB

        db_path = tmp_path / "remora.db"
        store = EventStore(db_path, projection=NodeProjection())
        await store.initialize()

        registry = SubscriptionRegistry(
            connection=store._conn,
            lock=store._lock,
        )

        db = RemoraDB(connection=store._conn, lock=store._lock)

        # Write via EventStore
        event = NodeDiscoveredEvent(
            node_id="test::func",
            node_type="function",
            name="func",
            full_name="test::func",
            file_path="test.py",
            start_line=1,
            end_line=5,
            source_code="def func(): pass",
            source_hash="abc123",
        )
        await store.append("test", event)

        # Write via SubscriptionRegistry
        await registry.register("agent_1", SubscriptionPattern(event_types=["NodeDiscoveredEvent"]))

        # Write via RemoraDB
        db.push_command("run_agent", "agent_1", {"trigger": "test"})

        # Verify all data is in the same DB file
        verify_conn = sqlite3.connect(str(db_path))
        verify_conn.row_factory = sqlite3.Row

        events = verify_conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        nodes = verify_conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        subs = verify_conn.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        cmds = verify_conn.execute("SELECT COUNT(*) FROM command_queue").fetchone()[0]

        assert events >= 1
        assert nodes >= 1
        assert subs >= 1
        assert cmds >= 1

        verify_conn.close()
        await store.close()
