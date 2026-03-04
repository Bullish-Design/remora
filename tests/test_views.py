"""Tests for view functions (shell, graph, sidebar, event_stream)."""

from __future__ import annotations

import time

from remora_demo.web.graph.state import GraphSnapshot
from remora_demo.web.graph.views.graph import render_graph
from remora_demo.web.graph.views.shell import render_shell
from remora_demo.web.graph.views.sidebar import render_sidebar_content
from remora_demo.web.graph.views.event_stream import render_event_list


# ── render_graph ──


class TestRenderGraph:
    def test_empty_snapshot(self) -> None:
        snapshot = GraphSnapshot()
        result = render_graph(snapshot, {})
        assert "<svg" in result
        assert "</svg>" in result

    def test_with_nodes(self) -> None:
        snapshot = GraphSnapshot(
            nodes=[
                {"remora_id": "a", "name": "a", "node_type": "file", "status": "idle"},
                {"remora_id": "b", "name": "b", "node_type": "function", "status": "running"},
            ],
            edges=[{"from_id": "a", "to_id": "b", "edge_type": "parent_of"}],
        )
        positions = {"a": (100.0, 100.0), "b": (200.0, 300.0)}
        result = render_graph(snapshot, positions)
        assert "translate(100.0,100.0)" in result
        assert "translate(200.0,300.0)" in result
        assert "<line" in result


# ── render_shell ──


class TestRenderShell:
    def test_returns_full_html(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert "<!DOCTYPE html>" in result
        assert "<html" in result
        assert "</html>" in result

    def test_includes_datastar_script(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert "datastar" in result

    def test_includes_css(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert "<style>" in result
        assert "--bg" in result

    def test_includes_graph_svg(self) -> None:
        snapshot = GraphSnapshot(
            nodes=[{"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}],
        )
        positions = {"x": (50.0, 50.0)}
        result = render_shell(snapshot, positions)
        assert 'id="graph-svg"' in result

    def test_includes_sidebar(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert 'id="sidebar"' in result
        assert 'id="sidebar-content"' in result

    def test_includes_sse_connection(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert "data-on-load" in result
        assert "/subscribe" in result

    def test_includes_zoom_pan_js(self) -> None:
        snapshot = GraphSnapshot()
        result = render_shell(snapshot, {})
        assert "graph-pane" in result
        assert "wheel" in result

    def test_node_count_in_status(self) -> None:
        snapshot = GraphSnapshot(
            nodes=[{"remora_id": "a"}, {"remora_id": "b"}],
            edges=[{"from_id": "a", "to_id": "b"}],
        )
        result = render_shell(snapshot, {"a": (0, 0), "b": (1, 1)})
        assert "2 nodes" in result
        assert "1 edges" in result


# ── render_sidebar_content ──


class TestRenderSidebarContent:
    def test_no_node(self) -> None:
        result = render_sidebar_content(None, [], [], {})
        assert "Node not found" in result
        assert 'id="sidebar-content"' in result

    def test_with_node(self) -> None:
        node = {
            "remora_id": "load_config",
            "name": "load_config",
            "node_type": "function",
            "status": "active",
            "file_path": "loader.py",
            "start_line": 10,
            "end_line": 25,
        }
        result = render_sidebar_content(node, [], [], {})
        assert 'id="sidebar-content"' in result
        assert "load_config" in result
        assert "function" in result
        assert "active" in result
        assert "loader.py" in result

    def test_tabs_present(self) -> None:
        node = {"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}
        result = render_sidebar_content(node, [], [], {})
        assert "Log" in result
        assert "Source" in result
        assert "Connections" in result
        assert "Actions" in result

    def test_events_rendered(self) -> None:
        node = {"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}
        events = [
            {"event_type": "AgentStart", "timestamp": time.time(), "message": "started"},
        ]
        result = render_sidebar_content(node, events, [], {})
        assert "AgentStart" in result
        assert "started" in result

    def test_source_code_rendered(self) -> None:
        node = {
            "remora_id": "x",
            "name": "x",
            "node_type": "function",
            "status": "idle",
            "source_code": "def foo():\n    pass",
        }
        result = render_sidebar_content(node, [], [], {})
        assert "def foo():" in result

    def test_connections_rendered(self) -> None:
        node = {"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}
        connections = {"parents": ["parent_a"], "children": [], "callers": [], "callees": ["callee_b"]}
        result = render_sidebar_content(node, [], [], connections)
        assert "parent_a" in result
        assert "callee_b" in result
        assert "Parents" in result
        assert "Callees" in result

    def test_proposals_rendered(self) -> None:
        node = {"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}
        proposals = [{"proposal_id": "p1", "diff": "- old\n+ new"}]
        result = render_sidebar_content(node, [], proposals, {})
        assert "p1" in result
        assert "Approve" in result
        assert "Reject" in result

    def test_chat_input_present(self) -> None:
        node = {"remora_id": "x", "name": "x", "node_type": "function", "status": "idle"}
        result = render_sidebar_content(node, [], [], {})
        assert "chat-input" in result
        assert "Send" in result

    def test_xss_escaping(self) -> None:
        node = {
            "remora_id": "<script>alert(1)</script>",
            "name": "<b>evil</b>",
            "node_type": "function",
            "status": "idle",
        }
        result = render_sidebar_content(node, [], [], {})
        assert "<script>" not in result
        assert "&lt;script&gt;" in result


# ── render_event_list ──


class TestRenderEventList:
    def test_empty_events(self) -> None:
        result = render_event_list([])
        assert 'id="event-stream"' in result
        assert "No events yet" in result

    def test_with_events(self) -> None:
        events = [
            {
                "event_type": "AgentStart",
                "agent_id": "load_config",
                "timestamp": time.time(),
                "message": "Agent started processing",
            },
            {
                "event_type": "ModelResponse",
                "agent_id": "merge",
                "timestamp": time.time(),
                "content": "Here is my response",
            },
        ]
        result = render_event_list(events)
        assert 'id="event-stream"' in result
        assert "AgentStart" in result
        assert "load_config" in result
        assert "Agent started processing" in result
        assert "ModelResponse" in result

    def test_long_message_truncated(self) -> None:
        events = [
            {
                "event_type": "Test",
                "timestamp": time.time(),
                "message": "x" * 200,
            },
        ]
        result = render_event_list(events)
        assert "..." in result
        # Should not contain 200 x's
        assert "x" * 200 not in result

    def test_event_type_color(self) -> None:
        events = [
            {"event_type": "AgentError", "timestamp": time.time()},
        ]
        result = render_event_list(events)
        assert "#f38ba8" in result  # Red for errors

    def test_xss_in_agent_id(self) -> None:
        events = [
            {"event_type": "Test", "agent_id": "<script>bad</script>", "timestamp": 0},
        ]
        result = render_event_list(events)
        assert "<script>" not in result
