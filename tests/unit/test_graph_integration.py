# tests/unit/test_graph_integration.py
"""Integration tests for the graph viewer full stack."""

import json
import sqlite3
import tempfile
import time
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from remora_demo.graph.app import create_app


def _init_test_db(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS nodes (
            id TEXT PRIMARY KEY, node_type TEXT, name TEXT, file_path TEXT,
            start_line INTEGER, end_line INTEGER, start_col INTEGER DEFAULT 0,
            end_col INTEGER DEFAULT 0, source_code TEXT, source_hash TEXT,
            status TEXT DEFAULT 'active', pending_proposal_id TEXT, parent_id TEXT
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
            new_source TEXT, diff TEXT, status TEXT DEFAULT 'pending', created_at REAL
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
    # Insert test data
    conn.execute(
        "INSERT INTO nodes VALUES ('f1','file','app.py','/src/app.py',1,50,0,0,'# app','hash1','active',NULL,NULL)"
    )
    conn.execute(
        "INSERT INTO nodes VALUES ('fn1','function','main','/src/app.py',10,30,0,0,'def main(): pass','hash2','active',NULL,'f1')"
    )
    conn.execute("INSERT INTO edges VALUES ('f1','fn1','parent_of')")
    conn.commit()
    conn.close()


@pytest.fixture
def client():
    tmpdir = tempfile.mkdtemp()
    db_path = str(Path(tmpdir) / "test.db")
    _init_test_db(db_path)
    app = create_app(db_path=db_path)
    return TestClient(app)


class TestIntegration:
    def test_index_serves_shell(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "d3-force" in resp.text or "d3.forceSimulation" in resp.text

    def test_agent_detail(self, client):
        resp = client.get("/agent/fn1")
        assert resp.status_code == 200
        assert "main" in resp.text
        assert "function" in resp.text

    def test_agent_not_found(self, client):
        resp = client.get("/agent/nonexistent")
        assert resp.status_code == 200
        assert "not found" in resp.text.lower() or "Not found" in resp.text

    def test_command_queues_chat(self, client):
        resp = client.post(
            "/command",
            json={
                "command_type": "chat",
                "agent_id": "fn1",
                "payload": {"message": "optimize this"},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_command_rejects_empty_type(self, client):
        resp = client.post(
            "/command",
            json={
                "command_type": "",
                "payload": {},
            },
        )
        assert resp.status_code == 400
