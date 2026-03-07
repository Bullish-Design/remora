"""Tests for DB->Relay bridge."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from remora_demo.web.graph.bridge import DBBridge
from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphState


class FakeRelay:
    """Test double for the Relay — records published subjects."""

    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, subject: str, data: str) -> None:
        self.published.append((subject, data))


def _create_test_db(path: str) -> sqlite3.Connection:
    """Create a minimal DB with the expected schema."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY,
            name TEXT,
            node_type TEXT DEFAULT 'function',
            status TEXT DEFAULT 'idle',
            file_path TEXT,
            line INTEGER,
            source TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT,
            to_id TEXT,
            edge_type TEXT DEFAULT 'parent_of'
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            file_path TEXT,
            line INTEGER,
            timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT,
            event_type TEXT,
            timestamp REAL,
            correlation_id TEXT,
            agent_id TEXT,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS proposals (
            id INTEGER PRIMARY KEY,
            agent_id TEXT,
            status TEXT DEFAULT 'pending',
            diff TEXT,
            payload TEXT
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_type TEXT,
            agent_id TEXT,
            payload TEXT,
            status TEXT DEFAULT 'pending',
            created_at REAL
        );
    """)
    conn.commit()
    return conn


class TestGraphState:
    def test_read_empty_snapshot(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.close()
        state = GraphState(db_path=db_path)
        snapshot = state.read_snapshot()
        assert snapshot.nodes == []
        assert snapshot.edges == []
        assert snapshot.cursor_focus is None
        state.close()

    def test_read_snapshot_with_nodes(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.execute("INSERT INTO nodes (id, name, node_type, status) VALUES ('a', 'func_a', 'function', 'idle')")
        conn.execute("INSERT INTO nodes (id, name, node_type, status) VALUES ('b', 'func_b', 'function', 'running')")
        conn.commit()

        state = GraphState(db_path=db_path)
        snapshot = state.read_snapshot()
        assert len(snapshot.nodes) == 2
        # id should be renamed to remora_id
        assert snapshot.nodes[0]["remora_id"] == "a"
        state.close()
        conn.close()

    def test_read_node(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.execute("INSERT INTO nodes (id, name, node_type, status) VALUES ('x', 'func_x', 'function', 'active')")
        conn.commit()

        state = GraphState(db_path=db_path)
        node = state.read_node("x")
        assert node is not None
        assert node["remora_id"] == "x"
        assert node["status"] == "active"
        assert state.read_node("nonexistent") is None
        state.close()
        conn.close()

    def test_read_edges_for_node(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.execute("INSERT INTO nodes (id, name) VALUES ('a', 'a')")
        conn.execute("INSERT INTO nodes (id, name) VALUES ('b', 'b')")
        conn.execute("INSERT INTO edges (from_id, to_id, edge_type) VALUES ('a', 'b', 'parent_of')")
        conn.execute("INSERT INTO edges (from_id, to_id, edge_type) VALUES ('b', 'a', 'calls')")
        conn.commit()

        state = GraphState(db_path=db_path)
        connections = state.read_edges_for_node("a")
        assert connections["children"] == ["b"]
        assert connections["callers"] == ["b"]
        state.close()
        conn.close()

    def test_push_command(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.close()
        state = GraphState(db_path=db_path)
        cmd_id = state.push_command("chat", "agent1", {"message": "hello"})
        assert cmd_id is not None
        assert cmd_id > 0

        # Verify the command was written
        verify_conn = sqlite3.connect(db_path)
        verify_conn.row_factory = sqlite3.Row
        row = verify_conn.execute("SELECT * FROM command_queue WHERE id = ?", (cmd_id,)).fetchone()
        assert row is not None
        assert row["command_type"] == "chat"
        assert row["agent_id"] == "agent1"
        verify_conn.close()
        state.close()

    def test_read_recent_events(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        conn.execute(
            "INSERT INTO events (event_id, event_type, timestamp, agent_id, payload) "
            "VALUES ('e1', 'StatusChanged', ?, 'a', '{\"message\": \"hello\"}')",
            (time.time(),),
        )
        conn.commit()

        state = GraphState(db_path=db_path)
        events = state.read_recent_events(limit=10)
        assert len(events) == 1
        assert events[0]["event_type"] == "StatusChanged"
        state.close()
        conn.close()


class TestDBBridge:
    @pytest.fixture
    def setup(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        conn = _create_test_db(db_path)
        state = GraphState(db_path=db_path)
        layout = ForceLayout()
        relay = FakeRelay()
        bridge = DBBridge(state=state, layout=layout, relay=relay, poll_interval=0.1)
        try:
            yield conn, state, layout, relay, bridge
        finally:
            state.close()
            conn.close()

    @pytest.mark.asyncio
    async def test_first_poll_detects_all_as_changed(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute("INSERT INTO nodes (id, name, status) VALUES ('a', 'a', 'idle')")
        conn.execute(
            "INSERT INTO events (event_id, event_type, timestamp, agent_id, payload) VALUES ('e1', 'Test', 1.0, 'a', '{}')"
        )
        conn.commit()

        subjects = await bridge._poll_once()
        # First poll: everything is "new" relative to empty last_fp
        assert "graph.topology" in subjects
        assert "graph.events" in subjects
        assert len(relay.published) > 0

    @pytest.mark.asyncio
    async def test_second_poll_no_change_no_publish(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute("INSERT INTO nodes (id, name, status) VALUES ('a', 'a', 'idle')")
        conn.commit()

        await bridge._poll_once()
        relay.published.clear()

        # Second poll with no changes
        subjects = await bridge._poll_once()
        assert subjects == []
        assert relay.published == []

    @pytest.mark.asyncio
    async def test_node_added_triggers_topology(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute("INSERT INTO nodes (id, name, status) VALUES ('a', 'a', 'idle')")
        conn.commit()
        await bridge._poll_once()
        relay.published.clear()

        # Add a new node
        conn.execute("INSERT INTO nodes (id, name, status) VALUES ('b', 'b', 'idle')")
        conn.commit()
        subjects = await bridge._poll_once()
        assert "graph.topology" in subjects

    @pytest.mark.asyncio
    async def test_status_change_triggers_status(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute("INSERT INTO nodes (id, name, status) VALUES ('a', 'a', 'idle')")
        conn.commit()
        await bridge._poll_once()
        relay.published.clear()

        # Change status
        conn.execute("UPDATE nodes SET status = 'running' WHERE id = 'a'")
        conn.commit()
        subjects = await bridge._poll_once()
        assert "graph.status" in subjects

    @pytest.mark.asyncio
    async def test_cursor_change_triggers_cursor(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute(
            "INSERT INTO cursor_focus (id, agent_id, file_path, line, timestamp) VALUES (1, 'a', 'f.py', 1, 0.0)"
        )
        conn.commit()
        await bridge._poll_once()
        relay.published.clear()

        conn.execute("UPDATE cursor_focus SET timestamp = 1.0, agent_id = 'b' WHERE id = 1")
        conn.commit()
        subjects = await bridge._poll_once()
        assert "graph.cursor" in subjects

    @pytest.mark.asyncio
    async def test_new_event_triggers_events(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        await bridge._poll_once()
        relay.published.clear()

        conn.execute(
            "INSERT INTO events (event_id, event_type, timestamp, agent_id, payload) "
            "VALUES ('e1', 'Test', 1.0, 'a', '{}')"
        )
        conn.commit()
        subjects = await bridge._poll_once()
        assert "graph.events" in subjects

    @pytest.mark.asyncio
    async def test_layout_updated_on_topology_change(self, setup) -> None:
        conn, state, layout, relay, bridge = setup
        conn.execute("INSERT INTO nodes (id, name, status, node_type) VALUES ('a', 'a', 'idle', 'function')")
        conn.execute("INSERT INTO nodes (id, name, status, node_type) VALUES ('b', 'b', 'idle', 'function')")
        conn.execute("INSERT INTO edges (from_id, to_id, edge_type) VALUES ('a', 'b', 'calls')")
        conn.commit()

        await bridge._poll_once()
        positions = layout.get_positions()
        assert "a" in positions
        assert "b" in positions
