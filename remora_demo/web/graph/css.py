"""All graph viewer CSS — Catppuccin Mocha theme with CSS transitions."""

from __future__ import annotations


def graph_css() -> str:
    """Return the complete CSS for the graph viewer.

    Uses Catppuccin Mocha palette. CSS transitions on SVG elements provide
    smooth animation when the server pushes updated positions via SSE.
    """
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
    --lavender: #b4befe;
}

* { margin: 0; padding: 0; box-sizing: border-box; }

body {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
    height: 100vh;
}

.app { display: flex; flex-direction: column; height: 100vh; }

/* ---- Header ---- */
.header {
    background: var(--surface);
    padding: 10px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--surface2);
    flex-shrink: 0;
}
.header-title { font-size: 14px; font-weight: 600; letter-spacing: 0.5px; }
.header-controls { display: flex; align-items: center; gap: 10px; }
.header-status {
    font-size: 11px; color: var(--gray);
    padding: 2px 8px; border-radius: 4px; background: var(--surface2);
}

/* ---- Layout ---- */
.main { display: flex; flex: 1; overflow: hidden; }
.graph-pane { flex: 1; position: relative; overflow: hidden; }
.graph-svg { width: 100%; height: 100%; }

/* ---- SVG Node transitions ---- */
.node-group {
    transition: transform 0.5s ease-out;
    cursor: pointer;
}

.node-circle {
    transition: fill 0.3s ease, stroke 0.2s ease, stroke-width 0.2s ease;
}
.node-circle:hover {
    stroke-width: 3px;
    stroke: var(--lavender);
}

.node-label {
    font-family: 'JetBrains Mono', monospace;
    fill: var(--text);
    pointer-events: none;
    text-anchor: middle;
    transition: fill 0.3s ease;
}

.edge-line {
    transition: opacity 0.3s ease, stroke-width 0.3s ease;
    pointer-events: none;
}

/* ---- Running pulse animation ---- */
@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.6; }
}

.node-circle[fill='#89b4fa'] {
    animation: pulse 1.5s ease-in-out infinite;
}

/* ---- Sidebar ---- */
.sidebar {
    width: 350px; background: var(--surface);
    border-left: 1px solid var(--surface2);
    overflow-y: auto; flex-shrink: 0;
}
.sidebar-empty {
    padding: 40px 20px; text-align: center;
    color: var(--gray); font-size: 13px;
}

/* ---- Sidebar content ---- */
.node-info-header {
    padding: 12px 16px;
    display: flex; align-items: center; gap: 8px;
    border-bottom: 1px solid var(--surface2);
}
.node-info-name { font-size: 14px; font-weight: 600; }
.node-info-type {
    font-size: 10px; color: var(--subtext);
    padding: 1px 6px; border-radius: 3px; background: var(--surface2);
}
.node-info-status {
    font-size: 10px; padding: 1px 6px; border-radius: 3px;
    margin-left: auto;
}

.meta-line {
    font-size: 11px; color: var(--subtext);
    padding: 2px 16px;
}
.meta-label { font-weight: 600; margin-right: 4px; }

/* ---- Tabs ---- */
.sidebar-tabs {
    display: flex; border-bottom: 1px solid var(--surface2);
    padding: 0 8px;
}
.sidebar-tab {
    background: none; border: none; color: var(--subtext);
    font-family: inherit; font-size: 11px; padding: 8px 10px;
    cursor: pointer; border-bottom: 2px solid transparent;
    transition: color 0.2s, border-color 0.2s;
}
.sidebar-tab:hover { color: var(--text); }
.sidebar-tab[aria-selected="true"] {
    color: var(--blue); border-bottom-color: var(--blue);
}

.tab-content { padding: 8px 16px; }

/* ---- Event items (per-agent log) ---- */
.event-item {
    padding: 4px 0;
    border-bottom: 1px solid var(--surface2);
    display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
}
.event-badge {
    font-size: 9px; padding: 1px 5px; border-radius: 3px;
    background: var(--surface2); color: var(--text);
    font-weight: 600; white-space: nowrap;
}
.event-time {
    font-size: 10px; color: var(--overlay); margin-left: auto;
}
.event-summary {
    font-size: 10px; color: var(--subtext);
    width: 100%; padding-left: 2px;
}

/* ---- Connections ---- */
.connections-label {
    font-size: 11px; color: var(--subtext); font-weight: 600;
    margin: 8px 0 4px;
}
.connection-item {
    font-size: 12px; padding: 3px 8px; border-radius: 4px;
    cursor: pointer; transition: background 0.2s;
}
.connection-item:hover { background: var(--surface2); }

/* ---- Actions ---- */
.actions-group { margin-bottom: 16px; }
.actions-label {
    font-size: 11px; color: var(--subtext); font-weight: 600;
    margin-bottom: 6px;
}
.chat-input {
    width: 100%; background: var(--bg); border: 1px solid var(--surface2);
    border-radius: 4px; color: var(--text); font-family: inherit;
    font-size: 12px; padding: 8px; resize: vertical;
}
.chat-input:focus { border-color: var(--blue); outline: none; }

.action-btn {
    background: var(--surface2); border: none; color: var(--text);
    font-family: inherit; font-size: 11px; padding: 6px 12px;
    border-radius: 4px; cursor: pointer; transition: background 0.2s;
}
.action-btn:hover { background: var(--overlay); }
.action-btn.primary { background: var(--blue); color: #1e1e2e; }
.action-btn.primary:hover { opacity: 0.9; }
.action-btn.approve { background: var(--green); color: #1e1e2e; }
.action-btn.danger { background: var(--red); color: #1e1e2e; }

/* ---- Proposals ---- */
.proposal-card {
    background: var(--bg); border: 1px solid var(--surface2);
    border-radius: 6px; padding: 8px; margin-bottom: 8px;
}
.proposal-id { font-size: 10px; color: var(--subtext); margin-bottom: 4px; }
.proposal-diff {
    font-size: 10px; background: var(--surface2); padding: 6px;
    border-radius: 3px; overflow-x: auto; max-height: 200px;
    overflow-y: auto; margin: 4px 0;
}
.proposal-actions { display: flex; gap: 4px; margin-top: 6px; }
.proposal-actions .action-btn { flex: 1; text-align: center; }

/* ---- Source block ---- */
.source-block {
    font-size: 11px; background: var(--bg); padding: 8px;
    border-radius: 4px; overflow-x: auto; overflow-y: auto;
    max-height: 400px; border: 1px solid var(--surface2);
}

/* ---- Global event stream ---- */
.event-stream {
    max-height: 300px; overflow-y: auto;
    border-top: 1px solid var(--surface2);
}
.event-stream-item {
    padding: 6px 12px;
    border-bottom: 1px solid var(--surface2);
}
.event-stream-header {
    display: flex; align-items: center; gap: 6px;
}
.event-stream-body {
    font-size: 10px; color: var(--subtext); padding: 2px 0 0 2px;
    white-space: pre-wrap; word-break: break-word;
}
.event-agent {
    font-size: 10px; color: var(--lavender);
}
"""
