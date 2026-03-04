# tests/unit/test_graph_app.py
"""Tests for the graph viewer Starlette app routes."""

import tempfile
import sqlite3
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora_demo.graph.app import create_app


def _init_test_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT, name TEXT, file_path TEXT,
            start_line INTEGER, end_line INTEGER, start_col INTEGER DEFAULT 0,
            end_col INTEGER DEFAULT 0, source_code TEXT, source_hash TEXT,
            status TEXT DEFAULT 'active', pending_proposal_id TEXT,
            parent_id TEXT
        );
        CREATE TABLE IF NOT EXISTS edges (
            from_id TEXT, to_id TEXT, edge_type TEXT,
            PRIMARY KEY (from_id, to_id, edge_type)
        );
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY, event_type TEXT, timestamp REAL,
            correlation_id TEXT, agent_id TEXT, payload JSON
        );
        CREATE TABLE IF NOT EXISTS proposals (
            proposal_id TEXT PRIMARY KEY, agent_id TEXT, old_source TEXT,
            new_source TEXT, diff TEXT, status TEXT DEFAULT 'pending',
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT, file_path TEXT, line INTEGER, timestamp REAL
        );
        CREATE TABLE IF NOT EXISTS command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, command_type TEXT,
            agent_id TEXT, payload JSON, status TEXT DEFAULT 'pending',
            created_at REAL, processed_at REAL
        );
    """)
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test.db")
    _init_test_db(db_path)
    app = create_app(db_path=db_path)
    return TestClient(app)


class TestRoutes:
    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "<!DOCTYPE html>" in resp.text

    def test_command_post(self, client):
        resp = client.post(
            "/command",
            json={
                "command_type": "chat",
                "agent_id": "a1",
                "payload": {"message": "hello"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "queued"
        assert "command_id" in data
