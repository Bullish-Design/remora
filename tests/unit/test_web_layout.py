"""Tests for the web graph layout focus bounding box and render integration."""

from remora_demo.web.layout import FocusBBox, compute_layout
from remora_demo.web.render import render_graph
from remora_demo.web.state import GraphSnapshot


def _make_node(nid, node_type, file_path, parent_id=None, start_line=1, end_line=10):
    return {
        "remora_id": nid,
        "node_type": node_type,
        "file_path": file_path,
        "name": nid,
        "parent_id": parent_id,
        "start_line": start_line,
        "end_line": end_line,
    }


def _make_edge(from_id, to_id, edge_type="calls"):
    return {"from_id": from_id, "to_id": to_id, "edge_type": edge_type}


# ---------------------------------------------------------------------------
# FocusBBox computation
# ---------------------------------------------------------------------------


class TestFocusBBox:
    def test_no_focus_returns_none(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        result = compute_layout(nodes, [], None)
        assert result.focus_bbox is None

    def test_focus_includes_focused_node(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        focus = {"file_path": "/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, [], focus)
        assert result.focus_bbox is not None
        pos = result.positions["fn1"]
        assert result.focus_bbox.x <= pos.x
        assert result.focus_bbox.y <= pos.y
        assert result.focus_bbox.x + result.focus_bbox.w >= pos.x + pos.w
        assert result.focus_bbox.y + result.focus_bbox.h >= pos.y + pos.h

    def test_focus_includes_edge_neighbors(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
            _make_node("f2", "file", "/a/c.py"),
            _make_node("fn2", "function", "/a/c.py", parent_id="f2"),
        ]
        edges = [_make_edge("fn1", "fn2", "calls")]
        focus = {"file_path": "/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, edges, focus)
        bbox = result.focus_bbox
        assert bbox is not None
        # f2 is a sibling file (file-only), positioned; fn2 is hidden (not positioned)
        # At minimum, f1, fn1, f2 should be positioned
        assert "f1" in result.positions
        assert "fn1" in result.positions
        assert "f2" in result.positions

    def test_focus_bbox_positive_dimensions(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        focus = {"file_path": "/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, [], focus)
        bbox = result.focus_bbox
        assert bbox is not None
        assert bbox.w > 0
        assert bbox.h > 0

    def test_focus_with_unknown_agent_falls_back_to_file(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        focus = {"file_path": "/a/b.py", "agent_id": "nonexistent"}
        result = compute_layout(nodes, [], focus)
        assert result.focus_bbox is not None

    def test_focus_normalizes_file_uris(self):
        nodes = [
            _make_node("f1", "file", "file:///home/user/a/b.py"),
            _make_node("fn1", "function", "file:///home/user/a/b.py", parent_id="f1"),
        ]
        focus = {"file_path": "file:///home/user/a/b.py", "agent_id": "fn1"}
        result = compute_layout(nodes, [], focus)
        assert result.focus_bbox is not None

    def test_focus_mixed_uri_and_path(self):
        """cursor_focus plain path matches nodes stored as file:// URIs."""
        nodes = [
            _make_node("f1", "file", "file:///home/user/a/b.py"),
            _make_node("fn1", "function", "file:///home/user/a/b.py", parent_id="f1"),
        ]
        focus = {"file_path": "/home/user/a/b.py", "agent_id": None}
        result = compute_layout(nodes, [], focus)
        assert result.focus_bbox is not None

    def test_no_focus_shows_all_nodes(self):
        """Backward compat: no cursor_focus -> everything expanded, no bbox."""
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
            _make_node("f2", "file", "/c/d.py"),
        ]
        result = compute_layout(nodes, [], None)
        assert result.focus_bbox is None
        assert len(result.positions) == 3
        assert len(result.collapsed_dirs) == 0


# ---------------------------------------------------------------------------
# Render integration: data attributes
# ---------------------------------------------------------------------------


class TestRenderFocusBBox:
    def test_render_includes_focus_data_attrs(self):
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        snapshot = GraphSnapshot(
            nodes=nodes,
            edges=[],
            cursor_focus={"file_path": "/a/b.py", "agent_id": "fn1"},
        )
        html = render_graph(snapshot)
        assert 'data-focus-x="' in html
        assert 'data-focus-y="' in html
        assert 'data-focus-w="' in html
        assert 'data-focus-h="' in html

    def test_render_no_focus_no_data_attrs(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        snapshot = GraphSnapshot(nodes=nodes, edges=[], cursor_focus=None)
        html = render_graph(snapshot)
        assert "data-focus-x" not in html

    def test_render_shell_has_follow_button(self):
        from remora_demo.web.render import render_shell

        html = render_shell()
        assert 'id="follow-btn"' in html
        assert "Follow Cursor" in html

    def test_render_shell_has_fit_all_button(self):
        from remora_demo.web.render import render_shell

        html = render_shell()
        assert 'id="fit-all-btn"' in html
