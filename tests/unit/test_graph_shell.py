# tests/unit/test_graph_shell.py
"""Tests for the graph viewer HTML shell."""

from remora_demo.graph.shell import render_shell


class TestShell:
    def test_returns_html(self):
        html = render_shell()
        assert "<!DOCTYPE html>" in html
        assert "<title>" in html

    def test_includes_datastar(self):
        html = render_shell()
        assert "datastar" in html.lower()

    def test_includes_d3_force(self):
        html = render_shell()
        assert "d3-force" in html or "d3.forceSimulation" in html

    def test_includes_svg_container(self):
        html = render_shell()
        assert "graph-svg" in html

    def test_includes_sidebar(self):
        html = render_shell()
        assert "sidebar" in html

    def test_includes_catppuccin_colors(self):
        html = render_shell()
        assert "#1e1e2e" in html  # base bg
        assert "#a6e3a1" in html  # green
