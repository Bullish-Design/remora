"""Integration test — golden-path smoke test for the graph viewer pipeline.

Tests the full flow: DB -> GraphState -> ForceLayout -> Views
without requiring Stario (runs in Python 3.13).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

import pytest

from remora_demo.web.graph.bridge import DBBridge
from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphSnapshot, GraphState
from remora_demo.web.graph.views.event_stream import render_event_list
from remora_demo.web.graph.views.graph import render_graph
from remora_demo.web.graph.views.shell import render_shell
from remora_demo.web.graph.views.sidebar import render_sidebar_content


@pytest.fixture()
def demo_db(tmp_path: Path) -> str:
    """Create a demo SQLite DB with realistic data."""
    db_path = tmp_path / "indexer.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # Create tables matching the combined schema
    conn.executescript("""
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL,
            name TEXT NOT NULL,
            file_path TEXT NOT NULL DEFAULT '',
            start_line INTEGER NOT NULL DEFAULT 0,
            end_line INTEGER NOT NULL DEFAULT 0,
            source_code TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'idle'
        );

        CREATE TABLE edges (
            from_id TEXT NOT NULL,
            to_id TEXT NOT NULL,
            edge_type TEXT NOT NULL,
            PRIMARY KEY (from_id, to_id, edge_type)
        );

        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            timestamp REAL NOT NULL,
            correlation_id TEXT,
            agent_id TEXT,
            payload JSON NOT NULL DEFAULT '{}'
        );

        CREATE TABLE cursor_focus (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            agent_id TEXT,
            file_path TEXT,
            line INTEGER,
            timestamp REAL
        );

        CREATE TABLE proposals (
            proposal_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            old_source TEXT NOT NULL DEFAULT '',
            new_source TEXT NOT NULL DEFAULT '',
            diff TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            file_path TEXT
        );

        CREATE TABLE command_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            command_type TEXT NOT NULL,
            agent_id TEXT,
            payload JSON NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at REAL NOT NULL,
            processed_at REAL
        );
    """)

    now = time.time()

    # Insert demo nodes
    nodes = [
        ("configlib", "file", "configlib/__init__.py", "__init__.py", 1, 5, "# configlib package", "idle"),
        (
            "load_config",
            "function",
            "configlib/loader.py",
            "load_config",
            10,
            25,
            "def load_config(path):\n    ...",
            "active",
        ),
        ("validate", "function", "configlib/schema.py", "validate", 5, 20, "def validate(data):\n    ...", "running"),
        (
            "merge_configs",
            "function",
            "configlib/merge.py",
            "merge_configs",
            8,
            30,
            "def merge_configs(*cfgs):\n    ...",
            "idle",
        ),
    ]
    for nid, ntype, fpath, name, sl, el, src, status in nodes:
        conn.execute(
            "INSERT INTO nodes (id, node_type, file_path, name, start_line, end_line, source_code, status) VALUES (?,?,?,?,?,?,?,?)",
            (nid, ntype, fpath, name, sl, el, src, status),
        )

    # Insert edges
    edges = [
        ("configlib", "load_config", "parent_of"),
        ("configlib", "validate", "parent_of"),
        ("configlib", "merge_configs", "parent_of"),
        ("load_config", "validate", "calls"),
        ("merge_configs", "load_config", "calls"),
    ]
    for fid, tid, etype in edges:
        conn.execute("INSERT INTO edges VALUES (?,?,?)", (fid, tid, etype))

    # Insert events
    events = [
        ("e1", "NodeDiscovered", now - 10, "c1", "configlib", json.dumps({"message": "Discovered configlib"})),
        ("e2", "AgentStart", now - 8, "c1", "load_config", json.dumps({"message": "Agent started processing"})),
        (
            "e3",
            "ModelResponse",
            now - 5,
            "c1",
            "load_config",
            json.dumps({"content": "Here is my analysis of load_config"}),
        ),
        ("e4", "AgentStart", now - 3, "c2", "validate", json.dumps({"message": "Validation agent started"})),
        ("e5", "AgentError", now - 1, "c2", "validate", json.dumps({"message": "Schema validation failed"})),
    ]
    for eid, etype, ts, cid, aid, payload in events:
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?,?)", (eid, etype, ts, cid, aid, payload))

    # Insert cursor focus
    conn.execute(
        "INSERT INTO cursor_focus (id, agent_id, file_path, line, timestamp) VALUES (1, 'load_config', 'configlib/loader.py', 15, ?)",
        (now,),
    )

    # Insert a pending proposal
    conn.execute(
        "INSERT INTO proposals (proposal_id, agent_id, old_source, new_source, diff, status, created_at) VALUES (?,?,?,?,?,?,?)",
        ("p1", "load_config", "old code", "new code", "- old\n+ new", "pending", now),
    )

    conn.commit()
    conn.close()
    return str(db_path)


class TestFullPipeline:
    """End-to-end: DB -> GraphState -> Layout -> Views."""

    def test_read_snapshot(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        snapshot = gs.read_snapshot()
        assert len(snapshot.nodes) >= 3  # All non-orphaned
        assert len(snapshot.edges) == 5
        assert snapshot.cursor_focus is not None
        assert snapshot.cursor_focus["agent_id"] == "load_config"
        gs.close()

    def test_read_node(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        node = gs.read_node("load_config")
        assert node is not None
        assert node["name"] == "load_config"
        assert node["status"] == "active"
        assert node["remora_id"] == "load_config"
        gs.close()

    def test_read_events_for_agent(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        events = gs.read_events_for_agent("load_config")
        assert len(events) >= 2
        gs.close()

    def test_read_proposals(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        proposals = gs.read_proposals_for_agent("load_config")
        assert len(proposals) == 1
        assert proposals[0]["proposal_id"] == "p1"
        gs.close()

    def test_read_connections(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        connections = gs.read_edges_for_node("load_config")
        assert "configlib" in connections["parents"]
        assert "validate" in connections["callees"]
        gs.close()

    def test_read_recent_events(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        events = gs.read_recent_events(limit=10)
        assert len(events) == 5
        gs.close()

    def test_push_command(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        cmd_id = gs.push_command("chat", "load_config", {"message": "hello"})
        assert cmd_id is not None
        assert cmd_id > 0
        gs.close()

    def test_layout_with_real_data(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        snapshot = gs.read_snapshot()
        layout = ForceLayout(width=900, height=600)
        layout.set_graph(
            [
                {"id": n.get("remora_id", n.get("id", "")), "node_type": n.get("node_type", "function")}
                for n in snapshot.nodes
            ],
            snapshot.edges,
        )
        layout.step(100)
        positions = layout.get_positions()
        assert len(positions) == len(snapshot.nodes)
        # All positions should be within the viewport (roughly)
        for _nid, (x, y) in positions.items():
            assert -100 < x < 1000
            assert -100 < y < 700
        gs.close()

    def test_render_shell_with_real_data(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        snapshot = gs.read_snapshot()
        layout = ForceLayout(width=900, height=600)
        layout.set_graph(
            [
                {"id": n.get("remora_id", n.get("id", "")), "node_type": n.get("node_type", "function")}
                for n in snapshot.nodes
            ],
            snapshot.edges,
        )
        layout.step(100)
        positions = layout.get_positions()
        html = render_shell(snapshot, positions)
        assert "<!DOCTYPE html>" in html
        assert "Remora Graph" in html
        assert "<svg" in html
        assert "load_config" in html
        assert "4 nodes" in html
        assert "5 edges" in html
        gs.close()

    def test_render_sidebar_with_real_data(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        node = gs.read_node("load_config")
        events = gs.read_events_for_agent("load_config")
        proposals = gs.read_proposals_for_agent("load_config")
        connections = gs.read_edges_for_node("load_config")
        html = render_sidebar_content(node, events, proposals, connections)
        assert "load_config" in html
        assert "active" in html
        assert "Approve" in html
        assert "Reject" in html
        assert "configlib" in html  # parent connection
        assert "validate" in html  # callee connection
        gs.close()

    def test_render_event_stream_with_real_data(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        events = gs.read_recent_events(limit=30)
        html = render_event_list(events)
        assert 'id="event-stream"' in html
        assert "AgentStart" in html
        assert "AgentError" in html
        assert "#f38ba8" in html  # red color for errors
        gs.close()


class TestBridgeIntegration:
    """Test the DB->Bridge fingerprinting with a real DB."""

    def test_bridge_detects_initial_state(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        layout = ForceLayout(width=900, height=600)

        published: list[tuple[str, str]] = []

        class FakeRelay:
            def publish(self, subject: str, data: str) -> None:
                published.append((subject, data))

        bridge = DBBridge(state=gs, layout=layout, relay=FakeRelay())

        import asyncio

        subjects = asyncio.run(bridge._poll_once())

        # First poll should detect everything as new
        assert "graph.topology" in subjects
        assert "graph.events" in subjects
        assert len(published) > 0
        gs.close()

    def test_bridge_detects_no_change_on_second_poll(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        layout = ForceLayout(width=900, height=600)

        class FakeRelay:
            def publish(self, subject: str, data: str) -> None:
                pass

        bridge = DBBridge(state=gs, layout=layout, relay=FakeRelay())

        import asyncio

        asyncio.run(bridge._poll_once())
        # Second poll: nothing changed
        subjects2 = asyncio.run(bridge._poll_once())
        assert len(subjects2) == 0
        gs.close()

    def test_bridge_detects_new_node(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        layout = ForceLayout(width=900, height=600)

        published: list[str] = []

        class FakeRelay:
            def publish(self, subject: str, data: str) -> None:
                published.append(subject)

        bridge = DBBridge(state=gs, layout=layout, relay=FakeRelay())

        import asyncio

        asyncio.run(bridge._poll_once())
        published.clear()

        # Insert a new node
        conn = sqlite3.connect(demo_db)
        conn.execute(
            "INSERT INTO nodes (id, node_type, file_path, name, start_line, end_line, source_code, status) VALUES (?,?,?,?,?,?,?,?)",
            ("new_func", "function", "new.py", "new_func", 1, 5, "def new_func(): ...", "idle"),
        )
        conn.commit()
        conn.close()

        subjects = asyncio.run(bridge._poll_once())
        assert "graph.topology" in subjects
        gs.close()

    def test_bridge_detects_status_change(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        layout = ForceLayout(width=900, height=600)

        published: list[str] = []

        class FakeRelay:
            def publish(self, subject: str, data: str) -> None:
                published.append(subject)

        bridge = DBBridge(state=gs, layout=layout, relay=FakeRelay())

        import asyncio

        asyncio.run(bridge._poll_once())
        published.clear()

        # Change a node's status
        conn = sqlite3.connect(demo_db)
        conn.execute("UPDATE nodes SET status = 'error' WHERE id = 'load_config'")
        conn.commit()
        conn.close()

        subjects = asyncio.run(bridge._poll_once())
        assert "graph.status" in subjects
        gs.close()

    def test_bridge_detects_new_event(self, demo_db: str) -> None:
        gs = GraphState(db_path=demo_db)
        layout = ForceLayout(width=900, height=600)

        published: list[str] = []

        class FakeRelay:
            def publish(self, subject: str, data: str) -> None:
                published.append(subject)

        bridge = DBBridge(state=gs, layout=layout, relay=FakeRelay())

        import asyncio

        asyncio.run(bridge._poll_once())
        published.clear()

        # Insert a new event
        conn = sqlite3.connect(demo_db)
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            ("e99", "AgentComplete", time.time(), "c3", "load_config", json.dumps({"message": "done"})),
        )
        conn.commit()
        conn.close()

        subjects = asyncio.run(bridge._poll_once())
        assert "graph.events" in subjects
        gs.close()
