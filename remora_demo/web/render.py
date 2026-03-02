"""HTML rendering for the web graph view.

All rendering is server-side. The browser receives complete HTML fragments
that are morphed into the DOM via datastar SSE patches.
"""

from __future__ import annotations

import html
import os
from pathlib import Path

from datastar_py import attribute_generator as data

from remora_demo.web.layout import (
    CollapsedDir,
    DirGroupBox,
    FocusBBox,
    GroupBox,
    LayoutResult,
    NodePosition,
    compute_edge_paths,
    compute_layout,
)
from remora_demo.web.state import GraphSnapshot

# Status -> CSS color mapping (matches neovim highlights)
STATUS_COLORS = {
    "active": "#a6e3a1",  # green
    "running": "#89b4fa",  # blue
    "pending_approval": "#f9e2af",  # yellow
    "orphaned": "#6c7086",  # gray
}

NODE_TYPE_ICONS = {
    "file": "&#128196;",  # page
    "class": "&#9670;",  # diamond
    "function": "&#9654;",  # triangle
    "method": "&#9655;",  # triangle outline
}


def render_shell() -> str:
    """Render the full HTML shell (initial page load)."""
    body_attrs = data.init("@get('/subscribe')")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Graph View</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <style>{_css()}</style>
</head>
<body {body_attrs}>
    <div class="app">
        <header class="header">
            <div class="header-title">Remora Graph View</div>
            <div class="header-controls">
                <button class="header-btn" id="fit-all-btn" title="Fit all nodes in view">Fit All</button>
                <button class="header-btn follow-btn" id="follow-btn" title="Toggle follow cursor mode">Follow Cursor</button>
                <div class="header-status" id="connection-status">connecting...</div>
            </div>
        </header>
        <div class="main">
            <div class="graph-viewport" id="graph-viewport">
                <div class="graph-container" id="graph-container">
                    <div id="graph-content">
                        <div class="empty-state">Waiting for data...</div>
                    </div>
                </div>
            </div>
            <div class="sidebar" id="sidebar">
                <div id="agent-detail">
                    <div class="sidebar-empty">Click a node to view details</div>
                </div>
            </div>
        </div>
    </div>
    <script>{_js()}</script>
</body>
</html>"""


def render_graph(snapshot: GraphSnapshot) -> str:
    """Render the full graph as HTML, suitable for SSE.patch_elements."""
    if not snapshot.nodes:
        return '<div id="graph-content"><div class="empty-state">No nodes indexed yet</div></div>'

    layout = compute_layout(snapshot.nodes, snapshot.edges, snapshot.cursor_focus)
    edge_paths = compute_edge_paths(layout.positions, snapshot.edges)

    focused_id = snapshot.cursor_focus.get("agent_id") if snapshot.cursor_focus else None

    # Build data attributes for focus bbox (used by client zoom-to-cursor)
    focus_attrs = ""
    if layout.focus_bbox:
        fb = layout.focus_bbox
        focus_attrs = (
            f' data-focus-x="{fb.x:.1f}" data-focus-y="{fb.y:.1f}" data-focus-w="{fb.w:.1f}" data-focus-h="{fb.h:.1f}"'
        )

    parts = [
        f'<div id="graph-content" style="position:relative;'
        f'width:{layout.total_width + 100}px;height:{layout.total_height + 100}px;"{focus_attrs}>'
    ]

    # Render directory group boxes (outermost first for z-order)
    for dir_group in sorted(layout.dir_groups, key=lambda g: g.depth):
        parts.append(_render_dir_group_box(dir_group))

    # Render group boxes (class backgrounds)
    for group in layout.groups:
        parts.append(_render_group_box(group))

    # Render edges as SVG overlay
    parts.append(_render_edges_svg(edge_paths, layout))

    # Render nodes
    for node in snapshot.nodes:
        nid = node.get("remora_id") or node.get("id", "")
        pos = layout.positions.get(nid)
        if pos:
            is_focused = nid == focused_id
            parts.append(_render_node(node, pos, is_focused))

    # Render collapsed directory summaries
    for collapsed in layout.collapsed_dirs:
        parts.append(_render_collapsed_dir(collapsed))

    parts.append("</div>")

    # Connection status update
    parts.append('<div id="connection-status" class="status-connected">live</div>')

    return "\n".join(parts)


def render_agent_detail(node: dict, events: list[dict]) -> str:
    """Render the agent detail sidebar content."""
    nid = node.get("remora_id") or node.get("id", "")
    name = html.escape(node.get("name", "unknown"))
    node_type = node.get("node_type", "unknown")
    status = node.get("status", "active")
    file_path = html.escape(node.get("file_path", ""))
    start_line = node.get("start_line", "?")
    end_line = node.get("end_line", "?")
    parent_id = node.get("parent_id", "")
    color = STATUS_COLORS.get(status, "#888")

    parts = [f'<div id="agent-detail" class="agent-detail-content">']
    parts.append(f'<div class="detail-header">')
    parts.append(f'<span class="detail-icon">{NODE_TYPE_ICONS.get(node_type, "")}</span>')
    parts.append(f'<span class="detail-name">{name}</span>')
    parts.append(f'<span class="detail-status" style="color:{color}">{status}</span>')
    parts.append(f"</div>")

    parts.append(f'<div class="detail-meta">')
    parts.append(f"<div><strong>ID:</strong> <code>{html.escape(nid)}</code></div>")
    parts.append(f"<div><strong>Type:</strong> {node_type}</div>")
    parts.append(f"<div><strong>File:</strong> {_short_path(file_path)}</div>")
    parts.append(f"<div><strong>Lines:</strong> {start_line}-{end_line}</div>")
    if parent_id:
        parts.append(f"<div><strong>Parent:</strong> <code>{html.escape(parent_id)}</code></div>")
    parts.append(f"</div>")

    # Recent events
    parts.append(f'<div class="detail-events">')
    parts.append(f"<h3>Recent Events</h3>")
    if events:
        for ev in events[:10]:
            et = html.escape(str(ev.get("event_type", "")))
            ts = ev.get("timestamp", 0)
            parts.append(f'<div class="detail-event">')
            parts.append(f'<span class="event-type-badge">{et}</span>')
            parts.append(f'<span class="event-time">{_format_time(ts)}</span>')
            parts.append(f"</div>")
    else:
        parts.append('<div class="empty-state small">No events yet</div>')
    parts.append(f"</div>")
    parts.append(f"</div>")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _render_node(node: dict, pos: NodePosition, is_focused: bool) -> str:
    nid = node.get("remora_id") or node.get("id", "")
    name = html.escape(node.get("name", "?"))
    node_type = node.get("node_type", "function")
    status = node.get("status", "active")
    color = STATUS_COLORS.get(status, "#888")
    icon = NODE_TYPE_ICONS.get(node_type, "")

    classes = f"graph-node node-{node_type} status-{status}"
    if is_focused:
        classes += " focused"

    click_attr = data.on("click", f"@get('/agent/{nid}')")

    return (
        f'<div id="node-{html.escape(nid)}" class="{classes}" '
        f'style="left:{pos.x}px;top:{pos.y}px;width:{pos.w}px;height:{pos.h}px;'
        f'border-left:3px solid {color};" {click_attr}>'
        f'<span class="node-icon">{icon}</span>'
        f'<span class="node-name">{name}</span>'
        f'<span class="node-status-dot" style="background:{color};"></span>'
        f"</div>"
    )


def _render_group_box(group: GroupBox) -> str:
    return (
        f'<div class="class-group" '
        f'style="left:{group.x}px;top:{group.y}px;'
        f'width:{group.w}px;height:{group.h}px;">'
        f"</div>"
    )


def _render_dir_group_box(group: DirGroupBox) -> str:
    label = html.escape(group.label)
    return (
        f'<div class="dir-group dir-depth-{group.depth}" '
        f'style="left:{group.x}px;top:{group.y}px;'
        f'width:{group.w}px;height:{group.h}px;">'
        f'<div class="dir-group-label">{label}</div>'
        f"</div>"
    )


def _render_collapsed_dir(collapsed: CollapsedDir) -> str:
    label = html.escape(collapsed.label)
    file_s = "file" if collapsed.file_count == 1 else "files"
    node_s = "node" if collapsed.node_count == 1 else "nodes"
    subtitle = f"{collapsed.file_count} {file_s}, {collapsed.node_count} {node_s}"
    return (
        f'<div class="collapsed-dir" '
        f'style="left:{collapsed.x}px;top:{collapsed.y}px;'
        f'width:{collapsed.w}px;height:{collapsed.h}px;">'
        f'<span class="collapsed-dir-icon">&#128193;</span>'
        f'<div class="collapsed-dir-text">'
        f'<span class="collapsed-dir-name">{label}</span>'
        f'<span class="collapsed-dir-count">{subtitle}</span>'
        f"</div>"
        f"</div>"
    )


def _render_edges_svg(paths: list[dict], layout: LayoutResult) -> str:
    if not paths:
        return ""
    parts = [
        f'<svg class="edge-layer" width="{layout.total_width + 100}" '
        f'height="{layout.total_height + 100}" '
        f'style="position:absolute;top:0;left:0;pointer-events:none;">'
    ]
    for p in paths:
        edge_type = p["edge_type"]
        dash = 'stroke-dasharray="6,4"' if edge_type == "calls" else ""
        opacity = "0.3" if edge_type == "calls" else "0.5"
        parts.append(
            f'<path d="{p["path_d"]}" fill="none" stroke="#888" stroke-width="1.5" opacity="{opacity}" {dash}/>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _short_path(fp: str) -> str:
    """Shorten a file path for display."""
    try:
        return str(Path(fp).relative_to(Path.cwd()))
    except ValueError:
        parts = fp.split(os.sep)
        if len(parts) > 3:
            return os.sep.join(["...", *parts[-3:]])
        return fp


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    import datetime

    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")


def _css() -> str:
    return """
:root {
    --bg: #1e1e2e;
    --surface: #313244;
    --surface2: #45475a;
    --overlay: #585b70;
    --text: #cdd6f4;
    --subtext: #a6adc8;
    --green: #a6e3a1;
    --blue: #89b4fa;
    --yellow: #f9e2af;
    --red: #f38ba8;
    --gray: #6c7086;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
    height: 100vh;
}

.app {
    display: flex;
    flex-direction: column;
    height: 100vh;
}

.header {
    background: var(--surface);
    padding: 12px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--surface2);
    flex-shrink: 0;
}

.header-title {
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.5px;
}

.header-controls {
    display: flex;
    align-items: center;
    gap: 10px;
}

.header-btn {
    font-family: inherit;
    font-size: 11px;
    padding: 3px 10px;
    border: 1px solid var(--surface2);
    border-radius: 4px;
    background: var(--surface2);
    color: var(--text);
    cursor: pointer;
    letter-spacing: 0.3px;
    transition: background 0.15s, border-color 0.15s, color 0.15s;
}

.header-btn:hover {
    background: var(--overlay);
}

.follow-btn.active {
    background: var(--blue);
    color: var(--bg);
    border-color: var(--blue);
}

.follow-btn.active:hover {
    background: #7ba4e8;
}

.header-status, #connection-status {
    font-size: 11px;
    color: var(--gray);
    padding: 2px 8px;
    border-radius: 4px;
    background: var(--surface2);
}

.status-connected {
    color: var(--green) !important;
}

.main {
    display: flex;
    flex: 1;
    overflow: hidden;
}

.graph-viewport {
    flex: 1;
    overflow: auto;
    position: relative;
    cursor: grab;
}

.graph-viewport:active { cursor: grabbing; }

.graph-container {
    position: relative;
    min-width: 100%;
    min-height: 100%;
    transform-origin: 0 0;
}

.graph-node {
    position: absolute;
    background: var(--surface);
    border-radius: 5px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 10px;
    font-size: 11px;
    cursor: pointer;
    transition: box-shadow 0.15s, background 0.15s;
    user-select: none;
}

.graph-node:hover {
    background: var(--surface2);
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
}

.graph-node.focused {
    box-shadow: 0 0 0 2px var(--blue), 0 4px 12px rgba(137,180,250,0.3);
    background: var(--surface2);
}

.node-icon { font-size: 14px; flex-shrink: 0; }
.node-name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
}
.node-status-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
}

.node-file { opacity: 0.85; }
.node-file .node-name { font-weight: 600; }

.class-group {
    position: absolute;
    background: rgba(69, 71, 90, 0.3);
    border: 1px solid var(--surface2);
    border-radius: 8px;
}

.dir-group {
    position: absolute;
    border: 1px solid var(--surface2);
    border-radius: 10px;
    pointer-events: none;
}

.dir-depth-1 { background: rgba(49, 50, 68, 0.4); }
.dir-depth-2 { background: rgba(49, 50, 68, 0.25); }
.dir-depth-3 { background: rgba(49, 50, 68, 0.15); }

.dir-group-label {
    position: absolute;
    top: 4px;
    left: 10px;
    font-size: 10px;
    color: var(--subtext);
    letter-spacing: 0.3px;
    text-transform: none;
    opacity: 0.8;
    pointer-events: none;
    white-space: nowrap;
}

.sidebar {
    width: 320px;
    background: var(--surface);
    border-left: 1px solid var(--surface2);
    overflow-y: auto;
    flex-shrink: 0;
}

.sidebar-empty {
    padding: 40px 20px;
    text-align: center;
    color: var(--gray);
    font-size: 13px;
}

.agent-detail-content { padding: 16px; }

.detail-header {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--surface2);
    margin-bottom: 12px;
}

.detail-icon { font-size: 18px; }
.detail-name { font-weight: 600; font-size: 14px; flex: 1; }
.detail-status { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }

.detail-meta {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 12px;
    margin-bottom: 16px;
}

.detail-meta code {
    background: var(--surface2);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 11px;
}

.detail-events h3 {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--subtext);
    margin-bottom: 8px;
}

.detail-event {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 6px 0;
    border-bottom: 1px solid var(--surface2);
    font-size: 11px;
}

.event-type-badge {
    background: var(--surface2);
    padding: 2px 6px;
    border-radius: 3px;
    font-size: 10px;
}

.event-time { color: var(--gray); }

.empty-state {
    padding: 40px 20px;
    text-align: center;
    color: var(--gray);
    font-size: 13px;
}

.empty-state.small {
    padding: 12px;
    font-size: 11px;
}

.edge-layer { position: absolute; top: 0; left: 0; pointer-events: none; }

.collapsed-dir {
    position: absolute;
    background: var(--surface);
    border: 1px dashed var(--surface2);
    border-radius: 8px;
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 0 12px;
    cursor: default;
    opacity: 0.6;
    transition: opacity 0.15s;
}

.collapsed-dir:hover { opacity: 0.85; }

.collapsed-dir-icon { font-size: 16px; flex-shrink: 0; }

.collapsed-dir-text {
    display: flex;
    flex-direction: column;
    gap: 1px;
    overflow: hidden;
}

.collapsed-dir-name {
    font-size: 11px;
    font-weight: 600;
    color: var(--subtext);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.collapsed-dir-count {
    font-size: 9px;
    color: var(--gray);
    white-space: nowrap;
}
"""


def _js() -> str:
    """JS for zoom/pan/fit/follow on the graph viewport."""
    return """
(function() {
    let scale = 1;
    let translateX = 0;
    let translateY = 0;
    let followMode = false;
    const viewport = document.getElementById('graph-viewport');
    const container = document.getElementById('graph-container');
    const followBtn = document.getElementById('follow-btn');

    if (!viewport || !container) return;

    function applyTransform(animate) {
        if (animate) {
            container.style.transition = 'transform 0.3s ease';
        } else {
            container.style.transition = 'none';
        }
        container.style.transform =
            'translate(' + translateX + 'px, ' + translateY + 'px) scale(' + scale + ')';
    }

    function fitAll() {
        const content = document.getElementById('graph-content');
        if (!content) return;
        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        const cw = content.scrollWidth || 800;
        const ch = content.scrollHeight || 600;
        if (cw === 0 || ch === 0) return;

        const pad = 40;
        const sx = (vw - pad * 2) / cw;
        const sy = (vh - pad * 2) / ch;
        scale = Math.min(sx, sy, 1.5);
        scale = Math.max(scale, 0.1);

        translateX = (vw - cw * scale) / 2;
        translateY = (vh - ch * scale) / 2;
        applyTransform(true);
    }

    function zoomToFocus() {
        if (!followMode) return;
        const content = document.getElementById('graph-content');
        if (!content) return;
        const fx = parseFloat(content.dataset.focusX);
        const fy = parseFloat(content.dataset.focusY);
        const fw = parseFloat(content.dataset.focusW);
        const fh = parseFloat(content.dataset.focusH);
        if (isNaN(fx) || isNaN(fy) || isNaN(fw) || isNaN(fh)) return;
        if (fw <= 0 || fh <= 0) return;

        const vw = viewport.clientWidth;
        const vh = viewport.clientHeight;
        const pad = 60;

        const sx = (vw - pad * 2) / fw;
        const sy = (vh - pad * 2) / fh;
        scale = Math.min(sx, sy, 2.0);
        scale = Math.max(scale, 0.2);

        // Center the focus bbox in the viewport
        var centerX = fx + fw / 2;
        var centerY = fy + fh / 2;
        translateX = vw / 2 - centerX * scale;
        translateY = vh / 2 - centerY * scale;

        applyTransform(true);
    }

    // Toggle follow mode
    if (followBtn) {
        followBtn.addEventListener('click', function() {
            followMode = !followMode;
            followBtn.classList.toggle('active', followMode);
            if (followMode) {
                zoomToFocus();
            }
        });
    }

    // Observe graph-content for SSE patches
    let fitted = false;
    const observer = new MutationObserver(function() {
        if (followMode) {
            zoomToFocus();
        } else if (!fitted) {
            fitted = true;
            setTimeout(fitAll, 50);
        }
    });
    observer.observe(container, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['data-focus-x', 'data-focus-y', 'data-focus-w', 'data-focus-h']
    });

    // Fit All button — also disables follow mode
    const fitBtn = document.getElementById('fit-all-btn');
    if (fitBtn) {
        fitBtn.addEventListener('click', function() {
            followMode = false;
            if (followBtn) followBtn.classList.remove('active');
            fitAll();
        });
    }

    // Zoom via scroll wheel
    viewport.addEventListener('wheel', function(e) {
        e.preventDefault();
        var delta = e.deltaY > 0 ? 0.9 : 1.1;
        var newScale = Math.max(0.05, Math.min(4, scale * delta));

        var rect = viewport.getBoundingClientRect();
        var mx = e.clientX - rect.left;
        var my = e.clientY - rect.top;

        translateX = mx - (mx - translateX) * (newScale / scale);
        translateY = my - (my - translateY) * (newScale / scale);
        scale = newScale;
        applyTransform(false);
    }, { passive: false });

    // Pan via left-click drag on background
    let isPanning = false;
    let startX, startY;

    viewport.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        if (e.target.closest('.graph-node')) return;
        isPanning = true;
        startX = e.clientX - translateX;
        startY = e.clientY - translateY;
        e.preventDefault();
    });

    window.addEventListener('mousemove', function(e) {
        if (!isPanning) return;
        translateX = e.clientX - startX;
        translateY = e.clientY - startY;
        applyTransform(false);
    });

    window.addEventListener('mouseup', function() {
        isPanning = false;
    });
})();
"""
