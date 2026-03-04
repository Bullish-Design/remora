"""Graph SVG view — render the graph SVG fragment for w.patch().

Thin wrapper around svg.render_graph_svg that the handlers call.
"""

from __future__ import annotations

from remora_demo.web.graph.state import GraphSnapshot
from remora_demo.web.graph.svg import render_graph_svg


def render_graph(
    snapshot: GraphSnapshot,
    positions: dict[str, tuple[float, float]],
    cursor_focus: str | None = None,
    selected_node: str | None = None,
) -> str:
    """Render the graph SVG from a snapshot and layout positions.

    Returns an HTML string with id="graph-svg" for Datastar morphing.
    """
    return render_graph_svg(
        nodes=snapshot.nodes,
        edges=[dict(e) if not isinstance(e, dict) else e for e in snapshot.edges],
        positions=positions,
        cursor_focus=cursor_focus,
        selected_node=selected_node,
    )
