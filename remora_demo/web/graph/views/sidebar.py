"""Sidebar detail panel for selected node.

Returns HTML strings — no Stario dependency. Wrapped in SafeString by handlers.
"""

from __future__ import annotations

import datetime
import html as html_mod


STATUS_COLORS: dict[str, str] = {
    "active": "#a6e3a1",
    "idle": "#6c7086",
    "running": "#89b4fa",
    "pending_approval": "#f9e2af",
    "error": "#f38ba8",
    "orphaned": "#45475a",
}


def render_sidebar_content(
    node: dict | None,
    events: list[dict],
    proposals: list[dict],
    connections: dict,
) -> str:
    """Render the sidebar content for a selected node.

    Replaces the entire #sidebar-content div via Datastar morph.
    """
    if not node:
        return '<div id="sidebar-content"><div class="sidebar-empty">Node not found</div></div>'

    nid = html_mod.escape(node.get("remora_id", ""))
    name = html_mod.escape(node.get("name", "unknown"))
    node_type = html_mod.escape(node.get("node_type", "unknown"))
    status = node.get("status", "idle")
    file_path = html_mod.escape(node.get("file_path", "") or "")
    start_line = node.get("start_line", "?")
    end_line = node.get("end_line", "?")
    source = node.get("source_code", "") or ""
    color = STATUS_COLORS.get(status, "#6c7086")

    parts = [
        '<div id="sidebar-content">',
        _render_header(name, node_type, status, color),
        _render_meta(nid, file_path, start_line, end_line),
        _render_tabs(),
        _render_log_tab(events),
        _render_source_tab(source),
        _render_connections_tab(connections, nid),
        _render_actions_tab(nid, proposals),
        "</div>",
    ]
    return "".join(parts)


def _render_header(name: str, node_type: str, status: str, color: str) -> str:
    return (
        '<div class="node-info-header">'
        f'<span class="node-info-name">{name}</span>'
        f'<span class="node-info-type">{node_type}</span>'
        f'<span class="node-info-status" style="background:{color};color:#1e1e2e">{status}</span>'
        "</div>"
    )


def _render_meta(nid: str, file_path: str, start_line: object, end_line: object) -> str:
    return (
        '<div class="sidebar-section">'
        '<div class="meta-line">'
        f'<span class="meta-label">ID:</span><code>{nid}</code>'
        "</div>"
        '<div class="meta-line">'
        f'<span class="meta-label">File:</span><span>{file_path}</span>'
        "</div>"
        '<div class="meta-line">'
        f'<span class="meta-label">Lines:</span><span>{start_line}-{end_line}</span>'
        "</div>"
        "</div>"
    )


def _render_tabs() -> str:
    return (
        '<div class="sidebar-tabs">'
        '<button class="sidebar-tab" data-on-click="$activeTab = \'log\'">Log</button>'
        '<button class="sidebar-tab" data-on-click="$activeTab = \'source\'">Source</button>'
        '<button class="sidebar-tab" data-on-click="$activeTab = \'connections\'">Connections</button>'
        '<button class="sidebar-tab" data-on-click="$activeTab = \'actions\'">Actions</button>'
        "</div>"
    )


def _render_log_tab(events: list[dict]) -> str:
    parts = ['<div class="sidebar-section tab-content" data-show="$activeTab == \'log\'">']
    if not events:
        parts.append('<div class="sidebar-empty" style="padding:12px">No events yet</div>')
    else:
        for ev in events[:15]:
            et = html_mod.escape(str(ev.get("event_type", "")))
            ts = ev.get("timestamp", 0)
            message = ev.get("message") or ev.get("content") or ""
            if message and len(message) > 80:
                message = message[:77] + "..."

            parts.append('<div class="event-item">')
            parts.append(f'<span class="event-badge">{et}</span>')
            parts.append(f'<span class="event-time">{_format_time(ts)}</span>')
            if message:
                parts.append(f'<span class="event-summary">{html_mod.escape(message)}</span>')
            parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def _render_source_tab(source: str) -> str:
    parts = ['<div class="sidebar-section tab-content" data-show="$activeTab == \'source\'">']
    if source:
        parts.append(f'<pre class="source-block"><code>{html_mod.escape(source)}</code></pre>')
    else:
        parts.append('<div class="sidebar-empty" style="padding:12px">No source code</div>')
    parts.append("</div>")
    return "".join(parts)


def _render_connections_tab(connections: dict, current_nid: str) -> str:
    parts = ['<div class="sidebar-section tab-content" data-show="$activeTab == \'connections\'">']
    has_items = False
    for label, key in [
        ("Parents", "parents"),
        ("Children", "children"),
        ("Callers", "callers"),
        ("Callees", "callees"),
    ]:
        items = connections.get(key, [])
        if items:
            has_items = True
            parts.append(f'<div class="connections-label">{label}</div>')
            for item_id in items:
                escaped = html_mod.escape(item_id)
                parts.append(f'<div class="connection-item" data-on-click="@get(\'/agent/{escaped}\')">{escaped}</div>')
    if not has_items:
        parts.append('<div class="sidebar-empty" style="padding:12px">No connections</div>')
    parts.append("</div>")
    return "".join(parts)


def _render_actions_tab(nid: str, proposals: list[dict]) -> str:
    parts = ['<div class="sidebar-section tab-content" data-show="$activeTab == \'actions\'">']

    # Chat input
    parts.append(
        '<div class="actions-group">'
        '<div class="actions-label">Send Message</div>'
        '<textarea class="chat-input" placeholder="Message to agent..." '
        'data-model="chatMessage" rows="3"></textarea>'
        f'<button class="action-btn primary" '
        f"data-on-click=\"@post('/command', "
        f"{{signals: {{command_type: 'chat', agent_id: '{nid}', "
        f'payload: JSON.stringify({{message: $chatMessage}})}}}})">Send</button>'
        "</div>"
    )

    # Pending proposals
    if proposals:
        parts.append('<div class="actions-label">Pending Proposals</div>')
        for p in proposals:
            pid = html_mod.escape(str(p.get("proposal_id", "")))
            diff = html_mod.escape(str(p.get("diff", "")))
            parts.append(
                f'<div class="proposal-card">'
                f'<div class="proposal-id">ID: {pid}</div>'
                f'<pre class="proposal-diff">{diff}</pre>'
                f'<div class="proposal-actions">'
                f'<button class="action-btn approve" '
                f"data-on-click=\"@post('/command', "
                f"{{signals: {{command_type: 'approve', agent_id: '{nid}', "
                f"payload: JSON.stringify({{proposal_id: '{pid}'}})}}}})\">Approve</button>"
                f'<button class="action-btn danger" '
                f"data-on-click=\"@post('/command', "
                f"{{signals: {{command_type: 'reject', agent_id: '{nid}', "
                f"payload: JSON.stringify({{proposal_id: '{pid}'}})}}}})\">Reject</button>"
                f"</div></div>"
            )

    parts.append("</div>")
    return "".join(parts)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S")
