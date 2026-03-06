"""Tests for the graph viewer HTML shell."""

from remora_demo.web.graph.state import GraphSnapshot
from remora_demo.web.graph.views.shell import render_shell


class TestShell:
    def test_returns_html(self):
        html = render_shell(GraphSnapshot(nodes=[], edges=[], cursor_focus=None), positions={})
        assert "<!DOCTYPE html>" in html
        assert "<title>" in html

    def test_includes_datastar(self):
        html = render_shell(GraphSnapshot(nodes=[], edges=[], cursor_focus=None), positions={})
        assert "datastar" in html.lower()

    def test_includes_graph_svg(self):
        html = render_shell(GraphSnapshot(nodes=[], edges=[], cursor_focus=None), positions={})
        assert 'id="graph-svg"' in html

    def test_includes_sidebar(self):
        html = render_shell(GraphSnapshot(nodes=[], edges=[], cursor_focus=None), positions={})
        assert 'id="sidebar"' in html

    def test_includes_catppuccin_colors(self):
        html = render_shell(GraphSnapshot(nodes=[], edges=[], cursor_focus=None), positions={})
        assert "#1e1e2e" in html  # base bg
        assert "#a6e3a1" in html  # green
