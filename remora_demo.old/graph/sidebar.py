"""Server-rendered sidebar HTML fragments for the graph viewer."""

from __future__ import annotations

import datetime
import html


STATUS_COLORS = {
    "active": "#a6e3a1",
    "running": "#89b4fa",
    "pending_approval": "#f9e2af",
    "orphaned": "#6c7086",
}


def render_sidebar(
    node: dict | None,
    events: list[dict],
    proposals: list[dict],
    connections: dict,
) -> str:
    """Render the full sidebar HTML for a selected node."""
    if not node:
        return '<div id="sidebar-content"><div class="sidebar-empty">Node not found</div></div>'

    nid = html.escape(node.get("remora_id", ""))
    name = html.escape(node.get("name", "unknown"))
    node_type = node.get("node_type", "unknown")
    status = node.get("status", "active")
    file_path = html.escape(node.get("file_path", ""))
    start_line = node.get("start_line", "?")
    end_line = node.get("end_line", "?")
    source = node.get("source_code", "")
    color = STATUS_COLORS.get(status, "#6c7086")

    parts = ['<div id="sidebar-content">']

    # Header
    parts.append('<div class="node-info-header">')
    parts.append(f'<span class="node-info-name">{name}</span>')
    parts.append(f'<span class="node-info-type">{node_type}</span>')
    parts.append(f'<span class="node-info-status" style="background:{color};color:#1e1e2e">{status}</span>')
    parts.append("</div>")

    # Meta
    parts.append('<div class="sidebar-section">')
    parts.append(
        f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px"><strong>ID:</strong> <code>{nid}</code></div>'
    )
    parts.append(
        f'<div style="font-size:11px;color:#a6adc8;margin-bottom:4px"><strong>File:</strong> {file_path}</div>'
    )
    parts.append(f'<div style="font-size:11px;color:#a6adc8"><strong>Lines:</strong> {start_line}-{end_line}</div>')
    parts.append("</div>")

    # Tabs: Log | Source | Connections | Actions
    parts.append('<div class="sidebar-tabs">')
    for tab in ["Log", "Source", "Connections", "Actions"]:
        parts.append(f'<button class="sidebar-tab" onclick="switchTab(this, \'{tab.lower()}\')">{tab}</button>')
    parts.append("</div>")

    # Log tab
    parts.append('<div class="sidebar-section tab-content" data-tab="log">')
    if events:
        for ev in events[:15]:
            et = html.escape(str(ev.get("event_type", "")))
            ts = ev.get("timestamp", 0)
            parts.append('<div class="event-item">')
            parts.append(f'<span class="event-badge">{et}</span>')
            parts.append(f'<span class="event-time">{_format_time(ts)}</span>')
            parts.append("</div>")
    else:
        parts.append('<div class="sidebar-empty" style="padding:12px">No events yet</div>')
    parts.append("</div>")

    # Source tab
    parts.append('<div class="sidebar-section tab-content" data-tab="source" style="display:none">')
    if source:
        parts.append(f'<pre class="source-block"><code>{html.escape(source)}</code></pre>')
    else:
        parts.append('<div class="sidebar-empty" style="padding:12px">No source code</div>')
    parts.append("</div>")

    # Connections tab
    parts.append('<div class="sidebar-section tab-content" data-tab="connections" style="display:none">')
    if connections:
        for label, key in [
            ("Parents", "parents"),
            ("Children", "children"),
            ("Callers", "callers"),
            ("Callees", "callees"),
        ]:
            items = connections.get(key, [])
            if items:
                parts.append(
                    f'<div style="font-size:11px;color:#a6adc8;margin:6px 0 2px;font-weight:600">{label}</div>'
                )
                for item_id in items:
                    escaped_id = html.escape(item_id)
                    parts.append(
                        f'<div class="connection-item" onclick="selectNode(\'{escaped_id}\')">{escaped_id}</div>'
                    )
        if not any(connections.get(k) for k in ("parents", "children", "callers", "callees")):
            parts.append('<div class="sidebar-empty" style="padding:12px">No connections</div>')
    else:
        parts.append('<div class="sidebar-empty" style="padding:12px">No connections</div>')
    parts.append("</div>")

    # Actions tab
    parts.append('<div class="sidebar-section tab-content" data-tab="actions" style="display:none">')

    # Chat
    parts.append('<div style="margin-bottom:12px">')
    parts.append('<div style="font-size:11px;color:#a6adc8;margin-bottom:4px;font-weight:600">Send Message</div>')
    parts.append('<textarea class="chat-input" id="chat-input" placeholder="Message to agent..."></textarea>')
    parts.append(
        f'<button class="action-btn primary" style="margin-top:4px" onclick="sendChat(\'{nid}\')">Send</button>'
    )
    parts.append("</div>")

    # Proposals
    if proposals:
        parts.append(
            '<div style="font-size:11px;color:#a6adc8;margin-bottom:4px;font-weight:600">Pending Proposals</div>'
        )
        for p in proposals:
            pid = html.escape(str(p.get("proposal_id", "")))
            diff = html.escape(str(p.get("diff", "")))
            parts.append('<div class="proposal-card">')
            parts.append(f'<div style="font-size:10px;color:#a6adc8;margin-bottom:4px">ID: {pid}</div>')
            parts.append(f'<pre class="proposal-diff">{diff}</pre>')
            parts.append('<div style="display:flex;gap:4px;margin-top:6px">')
            parts.append(
                f'<button class="action-btn" style="flex:1" onclick="approveProposal(\'{pid}\')">Approve</button>'
            )
            parts.append(
                f'<button class="action-btn danger" style="flex:1" onclick="rejectProposal(\'{pid}\')">Reject</button>'
            )
            parts.append("</div>")
            parts.append("</div>")

    parts.append("</div>")

    parts.append("</div>")
    return "\n".join(parts)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")
