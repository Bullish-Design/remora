"""SVG element builders for server-rendered graphs.

All functions return plain strings. No Stario dependency — testable in Python 3.13.
The graph view wraps the result in SafeString when passing to w.patch().
"""

from __future__ import annotations


# ── Catppuccin Mocha palette ──

STATUS_FILL: dict[str, str] = {
    "active": "#a6e3a1",  # green
    "idle": "#6c7086",  # gray
    "running": "#89b4fa",  # blue
    "pending_approval": "#f9e2af",  # yellow
    "error": "#f38ba8",  # red
    "orphaned": "#45475a",  # dark gray
}

NODE_RADIUS: dict[str, int] = {
    "file": 14,
    "class": 11,
    "function": 8,
    "method": 8,
}

EDGE_STYLE: dict[str, dict[str, object]] = {
    "parent_of": {"stroke": "#585b70", "width": 1.5, "opacity": 0.5, "dash": ""},
    "calls": {"stroke": "#89b4fa", "width": 1.0, "opacity": 0.4, "dash": "6,4"},
}


# ── SVG primitives ──


def svg_open(width: int = 900, height: int = 600) -> str:
    return (
        f'<svg id="graph-svg" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" '
        f'class="graph-canvas" preserveAspectRatio="xMidYMid meet">'
    )


def svg_close() -> str:
    return "</svg>"


def svg_circle(
    r: int,
    fill: str,
    stroke: str | None = None,
    stroke_width: int | None = None,
    filter_id: str | None = None,
    class_name: str = "node-circle",
) -> str:
    parts = [f'<circle r="{r}" fill="{fill}" class="{class_name}"']
    if stroke:
        parts.append(f' stroke="{stroke}"')
    if stroke_width:
        parts.append(f' stroke-width="{stroke_width}"')
    if filter_id:
        parts.append(f' filter="url(#{filter_id})"')
    parts.append("/>")
    return "".join(parts)


def svg_line(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    stroke: str,
    stroke_width: float = 1.5,
    stroke_dasharray: str = "",
    opacity: float = 0.5,
    class_name: str = "edge-line",
) -> str:
    parts = [
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"',
        f' stroke="{stroke}" stroke-width="{stroke_width}"',
        f' opacity="{opacity}" class="{class_name}"',
    ]
    if stroke_dasharray:
        parts.append(f' stroke-dasharray="{stroke_dasharray}"')
    parts.append("/>")
    return "".join(parts)


def svg_text(
    content: str,
    dy: int = 22,
    font_size: str = "9px",
    class_name: str = "node-label",
) -> str:
    return f'<text dy="{dy}" text-anchor="middle" font-size="{font_size}" class="{class_name}">{content}</text>'


def svg_group_open(
    transform: str = "",
    class_name: str = "",
    data_attrs: dict[str, str] | None = None,
) -> str:
    parts = ["<g"]
    if transform:
        parts.append(f' transform="{transform}"')
    if class_name:
        parts.append(f' class="{class_name}"')
    if data_attrs:
        for k, v in data_attrs.items():
            parts.append(f' {k}="{v}"')
    parts.append(">")
    return "".join(parts)


def svg_group_close() -> str:
    return "</g>"


def svg_rect(
    x: float,
    y: float,
    width: float,
    height: float,
    rx: float = 0,
    fill: str = "none",
    class_name: str = "",
) -> str:
    parts = [f'<rect x="{x}" y="{y}" width="{width}" height="{height}"']
    if rx:
        parts.append(f' rx="{rx}"')
    parts.append(f' fill="{fill}"')
    if class_name:
        parts.append(f' class="{class_name}"')
    parts.append("/>")
    return "".join(parts)


def svg_defs_glow_filter() -> str:
    return (
        "<defs>"
        '<filter id="glow">'
        '<feGaussianBlur stdDeviation="3" result="blur"/>'
        '<feColorMatrix type="matrix" '
        'values="0 0 0 0 0.54  0 0 0 0 0.71  0 0 0 0 0.98  0 0 0 0.6 0" '
        'in="blur" result="color"/>'
        "<feMerge>"
        '<feMergeNode in="color"/>'
        '<feMergeNode in="SourceGraphic"/>'
        "</feMerge>"
        "</filter>"
        "</defs>"
    )


# ── Composite builders ──


def render_edge(
    edge: dict,
    positions: dict[str, tuple[float, float]],
    cursor_focus: str | None = None,
    selected_node: str | None = None,
) -> str:
    """Render a single edge as an SVG <line>."""
    from_id = edge.get("from_id", "")
    to_id = edge.get("to_id", "")
    if from_id not in positions or to_id not in positions:
        return ""

    x1, y1 = positions[from_id]
    x2, y2 = positions[to_id]
    edge_type = edge.get("edge_type", "parent_of")
    style = EDGE_STYLE.get(edge_type, EDGE_STYLE["parent_of"])

    is_active = (cursor_focus and (from_id == cursor_focus or to_id == cursor_focus)) or (
        selected_node and (from_id == selected_node or to_id == selected_node)
    )
    width = float(style["width"]) + (1.0 if is_active else 0.0)  # type: ignore[arg-type]
    opacity = 0.9 if is_active else float(style["opacity"])  # type: ignore[arg-type]
    dash = str(style["dash"])

    return svg_line(
        x1=x1,
        y1=y1,
        x2=x2,
        y2=y2,
        stroke=str(style["stroke"]),
        stroke_width=width,
        stroke_dasharray=dash,
        opacity=opacity,
    )


def render_node(
    node_id: str,
    x: float,
    y: float,
    node: dict,
    cursor_focus: str | None = None,
    selected_node: str | None = None,
) -> str:
    """Render a single node as an SVG <g> group."""
    name = node.get("name", node_id)
    node_type = node.get("node_type", "function")
    status = node.get("status", "idle")
    r = NODE_RADIUS.get(node_type, 8)
    fill = STATUS_FILL.get(status, "#6c7086")

    # Truncate long names
    display_name = name if len(name) <= 16 else name[:16] + ".."

    # Focus / selection styling
    is_focused = node_id == cursor_focus
    is_selected = node_id == selected_node
    stroke = "#89b4fa" if is_focused else "#b4befe" if is_selected else None
    stroke_width = 3 if (is_focused or is_selected) else None
    filter_id = "glow" if is_focused else None

    font_size = "10px" if node_type == "file" else "9px"

    parts = [
        svg_group_open(
            transform=f"translate({x},{y})",
            class_name="node-group",
            data_attrs={"data-on-click": f"@get('/agent/{node_id}')"},
        ),
        svg_circle(r=r, fill=fill, stroke=stroke, stroke_width=stroke_width, filter_id=filter_id),
        svg_text(display_name, dy=r + 14, font_size=font_size),
        svg_group_close(),
    ]
    return "".join(parts)


def render_graph_svg(
    nodes: list[dict],
    edges: list[dict],
    positions: dict[str, tuple[float, float]],
    cursor_focus: str | None = None,
    selected_node: str | None = None,
    width: int = 900,
    height: int = 600,
) -> str:
    """Render the complete SVG graph element.

    Returns an SVG string with id="graph-svg" for Datastar morphing.
    """
    # Build node lookup
    node_map: dict[str, dict] = {}
    for n in nodes:
        nid = n.get("remora_id") or n.get("id", "")
        node_map[nid] = n

    parts = [svg_open(width, height), svg_defs_glow_filter()]

    # Edges first (drawn behind nodes)
    for e in edges:
        parts.append(render_edge(e, positions, cursor_focus, selected_node))

    # Nodes on top
    for nid, (x, y) in positions.items():
        n = node_map.get(nid, {})
        parts.append(render_node(nid, x, y, n, cursor_focus, selected_node))

    parts.append(svg_close())
    return "".join(parts)
