"""Tests for refactored web graph layout and SVG rendering."""

from remora_demo.web.graph.layout import ForceLayout
from remora_demo.web.graph.state import GraphSnapshot
from remora_demo.web.graph.views.graph import render_graph


def _make_node(nid: str, node_type: str, file_path: str, parent_id: str | None = None) -> dict:
    return {
        "remora_id": nid,
        "node_type": node_type,
        "file_path": file_path,
        "name": nid,
        "parent_id": parent_id,
        "start_line": 1,
        "end_line": 10,
        "status": "active",
    }


def _make_edge(from_id: str, to_id: str, edge_type: str = "calls") -> dict:
    return {"from_id": from_id, "to_id": to_id, "edge_type": edge_type}


class TestForceLayout:
    def test_set_graph_creates_positions(self):
        layout = ForceLayout(width=900, height=600)
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        edges = [_make_edge("f1", "fn1", "parent_of")]

        layout.set_graph(nodes, edges)
        positions = layout.get_positions()

        assert set(positions.keys()) == {"f1", "fn1"}

    def test_set_graph_preserves_existing_node_positions(self):
        layout = ForceLayout(width=900, height=600)
        layout.set_graph([_make_node("f1", "file", "/a/b.py")], [])
        original = layout.get_positions()["f1"]

        layout.set_graph(
            [
                _make_node("f1", "file", "/a/b.py"),
                _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
            ],
            [_make_edge("f1", "fn1", "parent_of")],
        )
        updated = layout.get_positions()["f1"]

        assert original == updated

    def test_step_keeps_nodes_within_bounds(self):
        layout = ForceLayout(width=900, height=600)
        nodes = [_make_node(f"n{i}", "function", f"/a/{i}.py") for i in range(20)]
        layout.set_graph(nodes, [])

        layout.step(100)
        positions = layout.get_positions()

        for x, y in positions.values():
            assert 40 <= x <= 860
            assert 40 <= y <= 560


class TestRenderGraph:
    def test_render_graph_outputs_svg_and_nodes(self):
        layout = ForceLayout(width=900, height=600)
        nodes = [
            _make_node("f1", "file", "/a/b.py"),
            _make_node("fn1", "function", "/a/b.py", parent_id="f1"),
        ]
        edges = [_make_edge("f1", "fn1", "parent_of")]

        layout.set_graph(nodes, edges)
        layout.step(10)
        snapshot = GraphSnapshot(nodes=nodes, edges=edges, cursor_focus=None)

        html = render_graph(snapshot, layout.get_positions(), cursor_focus="fn1")

        assert 'id="graph-svg"' in html
        assert "/agent/fn1" in html
        assert "<line" in html

    def test_render_graph_without_positions_renders_empty_svg(self):
        nodes = [_make_node("f1", "file", "/a/b.py")]
        snapshot = GraphSnapshot(nodes=nodes, edges=[], cursor_focus=None)

        html = render_graph(snapshot, positions={})

        assert 'id="graph-svg"' in html
        assert 'class="node-group"' not in html
