"""Full HTML shell — the initial page served on GET /.

Returns a complete HTML document as a string. Includes:
- Datastar CDN script
- Graph CSS
- Initial graph SVG
- Layout structure (header, graph pane, sidebar)
- Zoom/pan JS snippet
"""

from __future__ import annotations

import html as html_mod

from remora_demo.web.graph.css import graph_css
from remora_demo.web.graph.state import GraphSnapshot
from remora_demo.web.graph.views.graph import render_graph

DATASTAR_CDN = "https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"

ZOOM_PAN_JS = """\
(function() {
    let scale = 1, tx = 0, ty = 0;
    const pane = document.getElementById('graph-pane');
    const svg = document.getElementById('graph-svg');
    if (!pane || !svg) return;

    pane.addEventListener('wheel', function(e) {
        e.preventDefault();
        const factor = e.deltaY > 0 ? 0.9 : 1.1;
        scale = Math.max(0.2, Math.min(4, scale * factor));
        svg.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
    }, { passive: false });

    let dragging = false, startX = 0, startY = 0;
    pane.addEventListener('mousedown', function(e) {
        if (e.target.closest('.node-group')) return;
        dragging = true; startX = e.clientX - tx; startY = e.clientY - ty;
    });
    pane.addEventListener('mousemove', function(e) {
        if (!dragging) return;
        tx = e.clientX - startX; ty = e.clientY - startY;
        svg.style.transform = 'translate(' + tx + 'px,' + ty + 'px) scale(' + scale + ')';
    });
    window.addEventListener('mouseup', function() { dragging = false; });
})();
"""


def render_shell(
    snapshot: GraphSnapshot,
    positions: dict[str, tuple[float, float]],
) -> str:
    """Render the complete HTML page.

    The page structure:
    - Header bar with title and controls
    - Main area split into graph pane (left) and sidebar (right)
    - Datastar auto-connects to /subscribe for SSE updates
    """
    css = html_mod.escape(graph_css(), quote=False)
    graph_svg = render_graph(snapshot, positions)
    node_count = len(snapshot.nodes)
    edge_count = len(snapshot.edges)

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Remora Graph</title>
<script type="module" src="{DATASTAR_CDN}"></script>
<style>{css}</style>
</head>
<body data-on-load="@get('/subscribe')">
<div class="app" data-signals='{{"activeTab": "log", "chatMessage": ""}}'>
  <header class="header">
    <div class="header-title">Remora Graph</div>
    <div class="header-controls">
      <div class="header-status" id="connection-status">{node_count} nodes, {edge_count} edges</div>
    </div>
  </header>
  <div class="main">
    <div class="graph-pane" id="graph-pane">
      {graph_svg}
    </div>
    <div class="sidebar" id="sidebar">
      <div id="sidebar-content">
        <div class="sidebar-empty">Click a node to view details</div>
      </div>
      <div id="event-stream" class="event-stream">
        <div class="sidebar-empty">No events yet</div>
      </div>
    </div>
  </div>
</div>
<script>{ZOOM_PAN_JS}</script>
</body>
</html>"""
