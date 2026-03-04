"""Tests for CSS theme output."""

from __future__ import annotations

from remora_demo.web.graph.css import graph_css


class TestGraphCss:
    def test_returns_string(self) -> None:
        result = graph_css()
        assert isinstance(result, str)

    def test_contains_css_variables(self) -> None:
        css = graph_css()
        for var in ("--bg", "--surface", "--text", "--green", "--blue", "--red", "--yellow"):
            assert var in css, f"Missing CSS variable {var}"

    def test_contains_catppuccin_colors(self) -> None:
        css = graph_css()
        assert "#1e1e2e" in css  # bg
        assert "#cdd6f4" in css  # text

    def test_has_node_group_transition(self) -> None:
        css = graph_css()
        assert ".node-group" in css
        assert "transition: transform" in css

    def test_has_node_circle_transition(self) -> None:
        css = graph_css()
        assert ".node-circle" in css
        assert "transition: fill" in css

    def test_has_edge_transition(self) -> None:
        css = graph_css()
        assert ".edge-line" in css

    def test_has_pulse_animation(self) -> None:
        css = graph_css()
        assert "@keyframes pulse" in css

    def test_has_sidebar_styles(self) -> None:
        css = graph_css()
        assert ".sidebar" in css
        assert ".sidebar-tab" in css

    def test_has_event_stream_styles(self) -> None:
        css = graph_css()
        assert ".event-stream" in css

    def test_has_action_buttons(self) -> None:
        css = graph_css()
        assert ".action-btn" in css

    def test_has_proposal_card(self) -> None:
        css = graph_css()
        assert ".proposal-card" in css

    def test_has_header_styles(self) -> None:
        css = graph_css()
        assert ".header" in css

    def test_has_graph_pane_layout(self) -> None:
        css = graph_css()
        assert ".graph-pane" in css
        assert ".main" in css
