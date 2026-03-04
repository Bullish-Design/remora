"""Tests for SVG element builders."""

from __future__ import annotations

from remora_demo.web.graph.svg import (
    STATUS_FILL,
    NODE_RADIUS,
    EDGE_STYLE,
    svg_open,
    svg_close,
    svg_circle,
    svg_line,
    svg_text,
    svg_group_open,
    svg_group_close,
    svg_rect,
    svg_defs_glow_filter,
    render_edge,
    render_node,
    render_graph_svg,
)


class TestPalette:
    def test_status_fill_has_standard_statuses(self) -> None:
        for status in ("active", "idle", "running", "pending_approval", "error", "orphaned"):
            assert status in STATUS_FILL

    def test_node_radius_has_standard_types(self) -> None:
        for ntype in ("file", "class", "function", "method"):
            assert ntype in NODE_RADIUS

    def test_edge_style_has_standard_types(self) -> None:
        for etype in ("parent_of", "calls"):
            assert etype in EDGE_STYLE


class TestSvgPrimitives:
    def test_svg_open(self) -> None:
        result = svg_open(width=900, height=600)
        assert "<svg" in result
        assert 'id="graph-svg"' in result
        assert 'viewBox="0 0 900 600"' in result

    def test_svg_close(self) -> None:
        assert svg_close() == "</svg>"

    def test_svg_circle(self) -> None:
        result = svg_circle(r=8, fill="#a6e3a1")
        assert "<circle" in result
        assert 'r="8"' in result
        assert 'fill="#a6e3a1"' in result

    def test_svg_circle_with_stroke(self) -> None:
        result = svg_circle(r=8, fill="#fff", stroke="#89b4fa", stroke_width=3)
        assert 'stroke="#89b4fa"' in result
        assert 'stroke-width="3"' in result

    def test_svg_circle_with_filter(self) -> None:
        result = svg_circle(r=8, fill="#fff", filter_id="glow")
        assert 'filter="url(#glow)"' in result

    def test_svg_line(self) -> None:
        result = svg_line(x1=10.0, y1=20.0, x2=30.0, y2=40.0, stroke="#585b70")
        assert "<line" in result
        assert 'x1="10.0"' in result
        assert 'y2="40.0"' in result

    def test_svg_line_with_dash(self) -> None:
        result = svg_line(x1=0, y1=0, x2=1, y2=1, stroke="#fff", stroke_dasharray="6,4")
        assert 'stroke-dasharray="6,4"' in result

    def test_svg_text(self) -> None:
        result = svg_text("hello", dy=22, font_size="10px")
        assert ">hello</text>" in result
        assert 'dy="22"' in result
        assert 'text-anchor="middle"' in result

    def test_svg_group_open_close(self) -> None:
        open_tag = svg_group_open(transform="translate(100.0,200.0)", class_name="node-group")
        assert "<g" in open_tag
        assert 'transform="translate(100.0,200.0)"' in open_tag
        assert 'class="node-group"' in open_tag
        assert svg_group_close() == "</g>"

    def test_svg_rect(self) -> None:
        result = svg_rect(x=-40, y=-10, width=80, height=20, rx=4, fill="#1e1e2e")
        assert "<rect" in result
        assert 'rx="4"' in result

    def test_svg_defs_glow_filter(self) -> None:
        result = svg_defs_glow_filter()
        assert "<defs>" in result
        assert '<filter id="glow">' in result
        assert "feGaussianBlur" in result
        assert "</defs>" in result


class TestRenderEdge:
    def test_basic_edge(self) -> None:
        edge = {"from_id": "a", "to_id": "b", "edge_type": "parent_of"}
        positions = {"a": (100.0, 200.0), "b": (300.0, 400.0)}
        result = render_edge(edge, positions)
        assert "<line" in result
        assert 'x1="100.0"' in result
        assert 'y2="400.0"' in result

    def test_missing_position_returns_empty(self) -> None:
        edge = {"from_id": "a", "to_id": "missing"}
        positions = {"a": (100.0, 200.0)}
        assert render_edge(edge, positions) == ""

    def test_calls_edge_has_dash(self) -> None:
        edge = {"from_id": "a", "to_id": "b", "edge_type": "calls"}
        positions = {"a": (0.0, 0.0), "b": (1.0, 1.0)}
        result = render_edge(edge, positions)
        assert 'stroke-dasharray="6,4"' in result

    def test_active_edge_highlighted(self) -> None:
        edge = {"from_id": "a", "to_id": "b", "edge_type": "parent_of"}
        positions = {"a": (0.0, 0.0), "b": (1.0, 1.0)}
        result = render_edge(edge, positions, cursor_focus="a")
        assert 'opacity="0.9"' in result


class TestRenderNode:
    def test_basic_node(self) -> None:
        node = {"name": "load_config", "node_type": "function", "status": "idle"}
        result = render_node("load_config", 100.0, 200.0, node)
        assert "<g" in result
        assert "translate(100.0,200.0)" in result
        assert "<circle" in result
        assert ">load_config</text>" in result
        assert "</g>" in result

    def test_long_name_truncated(self) -> None:
        node = {"name": "very_long_function_name_here", "node_type": "function", "status": "idle"}
        result = render_node("x", 0.0, 0.0, node)
        assert "very_long_functi.." in result

    def test_focused_node_has_stroke(self) -> None:
        node = {"name": "f", "node_type": "function", "status": "active"}
        result = render_node("f", 0.0, 0.0, node, cursor_focus="f")
        assert 'stroke="#89b4fa"' in result
        assert 'stroke-width="3"' in result

    def test_selected_node_has_different_stroke(self) -> None:
        node = {"name": "f", "node_type": "function", "status": "idle"}
        result = render_node("f", 0.0, 0.0, node, selected_node="f")
        assert 'stroke="#b4befe"' in result

    def test_file_node_uses_larger_radius(self) -> None:
        node = {"name": "loader.py", "node_type": "file", "status": "idle"}
        result = render_node("loader", 0.0, 0.0, node)
        assert 'r="14"' in result

    def test_status_determines_fill_color(self) -> None:
        node = {"name": "f", "node_type": "function", "status": "running"}
        result = render_node("f", 0.0, 0.0, node)
        assert f'fill="{STATUS_FILL["running"]}"' in result

    def test_click_action(self) -> None:
        node = {"name": "f", "node_type": "function", "status": "idle"}
        result = render_node("my_func", 0.0, 0.0, node)
        assert "data-on-click" in result
        assert "/agent/my_func" in result


class TestRenderGraphSvg:
    def test_empty_graph(self) -> None:
        result = render_graph_svg([], [], {})
        assert "<svg" in result
        assert "</svg>" in result

    def test_full_graph(self) -> None:
        nodes = [
            {"id": "a", "name": "a", "node_type": "file", "status": "idle"},
            {"id": "b", "name": "b", "node_type": "function", "status": "running"},
        ]
        edges = [{"from_id": "a", "to_id": "b", "edge_type": "parent_of"}]
        positions = {"a": (100.0, 100.0), "b": (200.0, 300.0)}
        result = render_graph_svg(nodes, edges, positions)
        assert "<svg" in result
        assert "</svg>" in result
        assert "<line" in result
        assert "translate(100.0,100.0)" in result
        assert "translate(200.0,300.0)" in result

    def test_graph_has_glow_filter(self) -> None:
        result = render_graph_svg([], [], {})
        assert '<filter id="glow">' in result
