# tests/unit/test_graph_state.py
"""Tests for the graph viewer state reader."""

import sqlite3
import time
import json
import tempfile
from pathlib import Path

from remora_demo.web.graph.state import GraphState


def _init_test_db(db_path: str) -> sqlite3.Connection:
    """Create a test DB with the remora schema."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT NOT NULL, name TEXT NOT NULL,
            file_path TEXT NOT NULL, start_line INTEGER, end_line INTEGER,
            start_col INTEGER DEFAULT 0, end_col INTEGER DEFAULT 0,
            source_code TEXT, source_hash TEXT, status TEXT DEFAULT 'active',
            pending_proposal_id TEXT, parent_id TEXT REFERENCES nodes(id)
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT NOT NULL, to_id TEXT NOT NULL, edge_type TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, event_type TEXT NOT NULL,
            timestamp REAL NOT NULL, correlation_id TEXT,
            agent_id TEXT, payload JSON NOT NULL
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL,
            old_source TEXT NOT NULL, new_source TEXT NOT NULL,
            diff TEXT NOT NULL, status TEXT DEFAULT 'pending', created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT NOT NULL,
            agent_id TEXT, payload JSON NOT NULL, status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL, processed_at REAL
        );
    """)
    conn.commit()
    return conn


class TestGraphState:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test.db")
        self.conn = _init_test_db(self.db_path)
        self.state = GraphState(db_path=self.db_path)

    def teardown_method(self):
        self.state.close()
        self.conn.close()

    def test_read_snapshot_empty(self):
        snap = self.state.read_snapshot()
        assert snap.nodes == []
        assert snap.edges == []
        assert snap.cursor_focus is None

    def test_read_snapshot_with_nodes(self):
        self.conn.execute(
            "INSERT INTO nodes (id, node_type, name, file_path, start_line, end_line, source_code, source_hash) "
            "VALUES ('n1', 'file', 'test.py', '/a/test.py', 1, 10, 'code', 'hash')"
        )
        self.conn.commit()
        snap = self.state.read_snapshot()
        assert len(snap.nodes) == 1
        assert snap.nodes[0]["remora_id"] == "n1"

    def test_read_events_for_agent(self):
        self.conn.execute(
            "INSERT INTO events (event_id, event_type, timestamp, correlation_id, agent_id, payload) "
            "VALUES ('e1', 'HumanChatEvent', ?, 'c1', 'a1', ?)",
            (time.time(), json.dumps({"message": "hello"})),
        )
        self.conn.commit()
        events = self.state.read_events_for_agent("a1")
        assert len(events) == 1
        assert events[0]["event_type"] == "HumanChatEvent"

    def test_push_command_writes_to_command_queue(self):
        cmd_id = self.state.push_command("chat", "a1", {"message": "hello"})
        assert isinstance(cmd_id, int)
        row = self.conn.execute(
            "SELECT command_type, agent_id, payload, status FROM command_queue WHERE id = ?",
            (cmd_id,),
        ).fetchone()
        assert row is not None
        assert row["command_type"] == "chat"
        assert row["agent_id"] == "a1"
        assert row["status"] == "pending"

    def test_read_proposals_for_agent(self):
        self.conn.execute(
            "INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at) "
            "VALUES ('p1', 'a1', 'old', 'new', 'diff text', 'pending', ?)",
            (time.time(),),
        )
        self.conn.commit()
        proposals = self.state.read_proposals_for_agent("a1")
        assert len(proposals) == 1
        assert proposals[0]["proposal_id"] == "p1"
