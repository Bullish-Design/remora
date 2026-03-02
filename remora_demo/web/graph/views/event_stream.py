"""Global event stream rendering — firehose view of all events."""

from __future__ import annotations

import datetime
import html as html_mod


EVENT_TYPE_COLORS: dict[str, str] = {
    "NodeDiscovered": "#a6e3a1",
    "NodeRemoved": "#6c7086",
    "AgentStart": "#89b4fa",
    "AgentComplete": "#a6e3a1",
    "AgentError": "#f38ba8",
    "ContentChanged": "#f9e2af",
    "ModelRequest": "#cba6f7",
    "ModelResponse": "#cba6f7",
    "AgentMessage": "#89dceb",
    "HumanChat": "#fab387",
    "RewriteProposal": "#f9e2af",
    "RewriteApplied": "#a6e3a1",
    "RewriteRejected": "#f38ba8",
}


def render_event_list(events: list[dict]) -> str:
    """Render the global event stream as a scrollable list.

    Target element: #event-stream. Updated by w.patch() on graph.events.
    """
    if not events:
        return '<div id="event-stream" class="event-stream"><div class="sidebar-empty">No events yet</div></div>'

    parts = ['<div id="event-stream" class="event-stream">']
    for ev in events:
        et = ev.get("event_type", "Unknown")
        agent_id = ev.get("agent_id", "")
        ts = ev.get("timestamp", 0)

        message = ev.get("message") or ev.get("content") or ""
        if isinstance(message, str) and len(message) > 100:
            message = message[:97] + "..."

        color = EVENT_TYPE_COLORS.get(et, "#6c7086")

        parts.append('<div class="event-stream-item">')
        parts.append('<div class="event-stream-header">')
        parts.append(f'<span class="event-badge" style="background:{color};color:#1e1e2e">{html_mod.escape(et)}</span>')
        if agent_id:
            parts.append(f'<span class="event-agent">{html_mod.escape(agent_id)}</span>')
        parts.append(f'<span class="event-time">{_format_time(ts)}</span>')
        parts.append("</div>")  # event-stream-header

        if message:
            parts.append(f'<div class="event-stream-body">{html_mod.escape(message)}</div>')

        parts.append("</div>")  # event-stream-item

    parts.append("</div>")
    return "".join(parts)


def _format_time(ts: float) -> str:
    if not ts:
        return ""
    dt = datetime.datetime.fromtimestamp(ts)
    return dt.strftime("%H:%M:%S.") + f"{int(dt.microsecond / 1000):03d}"
