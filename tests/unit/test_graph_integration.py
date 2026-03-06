"""Integration tests for refactored graph app/state/bridge pieces."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from tests.stario_stub import install_stario_stub

install_stario_stub()

from remora_demo.web.graph.app import agent_detail, event_stream
from remora_demo.web.graph.bridge import DBBridge
from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphState


def _init_test_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
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
        """
    )

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
    conn.execute(
        "INSERT INTO nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            "fn1",
            "function",
            "main",
            "/src/app.py",
            10,
            30,
            0,
            0,
            "def main(): pass",
            "hash2",
            "active",
            None,
            "f1",
        ),
    )
    conn.execute("INSERT INTO edges VALUES ('f1','fn1','parent_of')")
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        (
            "e1",
            "HumanChatEvent",
            time.time(),
            "c1",
            "fn1",
            json.dumps({"message": "optimize this"}),
        ),
    )
    conn.execute(
        "INSERT INTO proposals VALUES (?,?,?,?,?,?,?)",
        (
            "p1",
            "fn1",
            "old",
            "new",
            "-old\\n+new",
            "pending",
            time.time(),
        ),
    )
    conn.execute(
        "INSERT INTO cursor_focus VALUES (1,?,?,?,?)",
        ("fn1", "/src/app.py", 12, time.time()),
    )
    conn.commit()
    conn.close()


class _FakeReq:
    def __init__(self, tail: str = "") -> None:
        self.tail = tail


class _FakeContext:
    def __init__(self, *, tail: str = "") -> None:
        self.req = _FakeReq(tail)

    def __call__(self, _subject: str, _payload: dict | None = None) -> None:
        return None


class _FakeWriter:
    def __init__(self) -> None:
        self.html_body = ""

    def html(self, body) -> None:
        self.html_body = str(body)


class _FakeRelay:
    def __init__(self) -> None:
        self.published: list[tuple[str, str]] = []

    def publish(self, subject: str, data: str) -> None:
        self.published.append((subject, data))


@pytest.fixture
def state_layout(tmp_path: Path) -> tuple[str, GraphState, ForceLayout]:
    db_path = str(tmp_path / "test.db")
    _init_test_db(db_path)
    state = GraphState(db_path=db_path)
    layout = ForceLayout()
    yield db_path, state, layout
    state.close()


@pytest.mark.asyncio
async def test_agent_detail_renders_sidebar_content(state_layout) -> None:
    _db_path, state, _layout = state_layout
    handler = agent_detail(state)

    c = _FakeContext(tail="fn1")
    w = _FakeWriter()
    await handler(c, w)

    assert "main" in w.html_body
    assert "function" in w.html_body
    assert "HumanChatEvent" in w.html_body
    assert "p1" in w.html_body


@pytest.mark.asyncio
async def test_agent_detail_not_found(state_layout) -> None:
    _db_path, state, _layout = state_layout
    handler = agent_detail(state)

    c = _FakeContext(tail="does-not-exist")
    w = _FakeWriter()
    await handler(c, w)

    assert "not found" in w.html_body.lower()


@pytest.mark.asyncio
async def test_event_stream_renders_recent_events(state_layout) -> None:
    _db_path, state, _layout = state_layout
    handler = event_stream(state)

    c = _FakeContext()
    w = _FakeWriter()
    await handler(c, w)

    assert "HumanChatEvent" in w.html_body
    assert 'id="event-stream"' in w.html_body


@pytest.mark.asyncio
async def test_bridge_poll_updates_layout_and_publishes_subjects(state_layout) -> None:
    db_path, state, layout = state_layout
    relay = _FakeRelay()
    bridge = DBBridge(state=state, layout=layout, relay=relay, poll_interval=0.01)

    subjects = await bridge._poll_once()
    assert "graph.topology" in subjects
    assert "graph.events" in subjects
    assert layout.get_positions()
    assert relay.published

    # No DB change -> no published subjects
    relay.published.clear()
    subjects_unchanged = await bridge._poll_once()
    assert subjects_unchanged == []
    assert relay.published == []

    # Insert one event -> events subject should fire
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO events VALUES (?,?,?,?,?,?)",
        (
            "e2",
            "AgentMessageEvent",
            time.time(),
            "c2",
            "fn1",
            json.dumps({"content": "done"}),
        ),
    )
    conn.commit()
    conn.close()

    subjects_after_event = await bridge._poll_once()
    assert "graph.events" in subjects_after_event
