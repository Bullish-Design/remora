"""Tests for the refactored graph app handler factories."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from tests.stario_stub import install_stario_stub

install_stario_stub()

from remora_demo.web.graph.app import create_app, index, post_command
from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphState


def _init_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
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
        """
    )
    conn.commit()
    conn.close()


class _FakeReq:
    def __init__(self, tail: str = "") -> None:
        self.tail = tail


class _FakeContext:
    def __init__(self, *, tail: str = "", signals: dict[str, str] | None = None) -> None:
        self.req = _FakeReq(tail)
        self._signals = signals or {}
        self.emitted: list[tuple[str, dict | None]] = []

    async def signals(self, schema):
        return schema(**self._signals)

    def __call__(self, subject: str, payload: dict | None = None) -> None:
        self.emitted.append((subject, payload))


class _FakeWriter:
    def __init__(self) -> None:
        self.html_body = ""
        self.json_body: dict | None = None
        self.json_status = 200

    def html(self, body) -> None:
        self.html_body = str(body)

    def json(self, body: dict, status: int = 200) -> None:
        self.json_body = body
        self.json_status = status


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)
    return db_path


@pytest.mark.asyncio
async def test_index_handler_renders_shell(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "f1",
            "file",
            "app.py",
            "/src/app.py",
            1,
            50,
            0,
            0,
            "# app",
            "hash1",
            "active",
            None,
            None,
        ),
    )
    conn.commit()
    conn.close()

    state = GraphState(db_path=db_path)
    layout = ForceLayout()
    handler = index(state, layout)

    c = _FakeContext()
    w = _FakeWriter()
    await handler(c, w)

    assert "<!DOCTYPE html>" in w.html_body
    assert 'id="graph-svg"' in w.html_body
    state.close()


@pytest.mark.asyncio
async def test_post_command_queues_chat_command(db_path: str) -> None:
    state = GraphState(db_path=db_path)
    handler = post_command(state)

    c = _FakeContext(
        signals={
            "command_type": "chat",
            "agent_id": "a1",
            "payload": json.dumps({"message": "hello"}),
        }
    )
    w = _FakeWriter()

    await handler(c, w)

    assert w.json_status == 200
    assert w.json_body is not None
    assert w.json_body["status"] == "queued"
    assert "command_id" in w.json_body

    conn = sqlite3.connect(db_path)
    row = conn.execute("SELECT command_type, agent_id FROM command_queue").fetchone()
    conn.close()
    assert row == ("chat", "a1")
    state.close()


@pytest.mark.asyncio
async def test_post_command_rejects_missing_type(db_path: str) -> None:
    state = GraphState(db_path=db_path)
    handler = post_command(state)

    c = _FakeContext(signals={"command_type": "", "agent_id": "", "payload": "{}"})
    w = _FakeWriter()

    await handler(c, w)

    assert w.json_status == 400
    assert w.json_body == {"error": "command_type required"}
    state.close()


def test_create_app_returns_app_and_bridge(db_path: str) -> None:
    app, bridge = create_app(db_path=db_path, poll_interval=0.1)
    assert app is not None
    assert bridge is not None
    assert str(bridge.state.db_path) == db_path
    assert {(method, path) for method, path, _handler in app.routes} == {
        ("GET", "/"),
        ("GET", "/subscribe"),
        ("GET", "/agent/*"),
        ("GET", "/events"),
        ("POST", "/command"),
    }
    bridge.state.close()
