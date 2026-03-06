"""Tests for the graph viewer sidebar renderer."""

from remora_demo.web.graph.views.sidebar import render_sidebar_content


class TestSidebar:
    def test_renders_node_header(self):
        node = {
            "remora_id": "n1",
            "name": "my_func",
            "node_type": "function",
            "status": "active",
            "file_path": "/a/b.py",
            "start_line": 10,
            "end_line": 20,
            "source_code": "def my_func(): pass",
        }
        html = render_sidebar_content(node, events=[], proposals=[], connections={})
        assert "my_func" in html
        assert "function" in html

    def test_renders_events(self):
        node = {
            "remora_id": "n1",
            "name": "f",
            "node_type": "function",
            "status": "active",
            "file_path": "/a.py",
            "start_line": 1,
            "end_line": 5,
            "source_code": "",
        }
        events = [
            {
                "event_type": "HumanChatEvent",
                "timestamp": 1000000,
                "event_id": "e1",
                "agent_id": "n1",
                "payload": "{}",
            }
        ]
        html = render_sidebar_content(node, events=events, proposals=[], connections={})
        assert "HumanChatEvent" in html

    def test_renders_source_code(self):
        node = {
            "remora_id": "n1",
            "name": "f",
            "node_type": "function",
            "status": "active",
            "file_path": "/a.py",
            "start_line": 1,
            "end_line": 5,
            "source_code": "def f():\n    return 42",
        }
        html = render_sidebar_content(node, events=[], proposals=[], connections={})
        assert "return 42" in html

    def test_renders_connections(self):
        node = {
            "remora_id": "n1",
            "name": "f",
            "node_type": "function",
            "status": "active",
            "file_path": "/a.py",
            "start_line": 1,
            "end_line": 5,
            "source_code": "",
        }
        connections = {"parents": ["p1"], "children": [], "callers": ["c1"], "callees": []}
        html = render_sidebar_content(node, events=[], proposals=[], connections=connections)
        assert "p1" in html
        assert "c1" in html

    def test_renders_pending_proposals(self):
        node = {
            "remora_id": "n1",
            "name": "f",
            "node_type": "function",
            "status": "pending_approval",
            "file_path": "/a.py",
            "start_line": 1,
            "end_line": 5,
            "source_code": "",
        }
        proposals = [{"proposal_id": "pr1", "diff": "-old\n+new", "status": "pending"}]
        html = render_sidebar_content(node, events=[], proposals=proposals, connections={})
        assert "pr1" in html

    def test_not_found(self):
        html = render_sidebar_content(None, events=[], proposals=[], connections={})
        assert "not found" in html.lower() or "Not found" in html
