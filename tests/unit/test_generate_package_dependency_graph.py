from __future__ import annotations

from scripts.generate_package_dependency_graph import parse_cross_package_edges, render_dot


def test_parse_cross_package_edges_aggregates_to_top_level_packages() -> None:
    dot = """
strict digraph {
"remora.lsp.server" -> "remora.core.events";
"remora.lsp.graph" -> "remora.core.store.event_store";
"remora.lsp.server" -> "remora.runner.models";
"remora.__main__" -> "remora.cli.main";
"remora.core.events" -> "remora.core.events.agent_events";
}
"""
    edges = parse_cross_package_edges(dot)
    assert edges[("lsp", "core")] == 2
    assert edges[("lsp", "runner")] == 1
    assert edges[("__main__", "cli")] == 1
    assert ("core", "core") not in edges


def test_render_dot_emits_expected_nodes_and_edge_labels() -> None:
    dot = render_dot(
        {
            ("lsp", "core"): 3,
            ("service", "core"): 2,
            ("__main__", "cli"): 1,
        }
    )
    assert 'label="remora.core"' in dot
    assert 'fillcolor="#e2e8f0"' in dot
    assert 'label="3"' in dot
    assert 'label="2"' in dot
    assert "style=dashed" in dot
