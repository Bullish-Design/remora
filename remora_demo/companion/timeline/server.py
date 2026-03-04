"""Timeline visualization server for Companion agent activations.

Provides a debug interface showing:
- Real-time agent activation cascade
- Workspace state changes
- Input/output tracking per agent

Usage:
    from remora_demo.companion.timeline import TimelineServer

    server = TimelineServer(runtime)
    await server.start(port=8765)
"""

import asyncio
import json
import logging
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from remora_demo.companion.runtime import CompanionRuntime

logger = logging.getLogger("companion.timeline")


class TimelineHandler(SimpleHTTPRequestHandler):
    """HTTP handler for timeline visualization."""

    runtime: "CompanionRuntime | None" = None
    static_dir: Path = Path(__file__).parent / "web" / "static"

    def __init__(self, *args, **kwargs):
        # Set directory to serve static files from
        super().__init__(*args, directory=str(self.static_dir), **kwargs)

    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/api/activations":
            self._serve_activations()
        elif self.path == "/api/workspace":
            self._serve_workspace()
        elif self.path == "/" or self.path == "/index.html":
            self._serve_index()
        else:
            super().do_GET()

    def _serve_json(self, data):
        """Serve JSON response."""
        content = json.dumps(data, indent=2, default=str)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(content.encode())

    def _serve_activations(self):
        """Serve agent activations as JSON."""
        if self.runtime:
            activations = self.runtime.get_activations()
        else:
            activations = []
        self._serve_json(activations)

    def _serve_workspace(self):
        """Serve workspace state as JSON."""
        if self.runtime and hasattr(self.runtime, "_workspace"):
            workspace = self.runtime._workspace
            if workspace and hasattr(workspace, "_data"):
                data = {k: _serialize(v) for k, v in workspace._data.items()}
            else:
                data = {}
        else:
            data = {}
        self._serve_json(data)

    def _serve_index(self):
        """Serve the main HTML page."""
        html = _generate_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.debug("%s - %s", self.address_string(), format % args)


def _serialize(value):
    """Serialize a value to JSON-compatible format."""
    if hasattr(value, "__dataclass_fields__"):
        return {k: _serialize(v) for k, v in value.__dict__.items()}
    elif isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    elif isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    elif isinstance(value, datetime):
        return value.isoformat()
    elif isinstance(value, Path):
        return str(value)
    return value


def _generate_html():
    """Generate the timeline visualization HTML."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Companion Timeline</title>
    <style>
        :root {
            --bg: #1e1e2e;
            --surface: #313244;
            --text: #cdd6f4;
            --subtext: #a6adc8;
            --green: #a6e3a1;
            --blue: #89b4fa;
            --yellow: #f9e2af;
            --red: #f38ba8;
            --mauve: #cba6f7;
        }
        
        * { box-sizing: border-box; }
        
        body {
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            background: var(--bg);
            color: var(--text);
            margin: 0;
            padding: 20px;
        }
        
        h1 {
            color: var(--mauve);
            margin-bottom: 20px;
        }
        
        .controls {
            margin-bottom: 20px;
        }
        
        button {
            background: var(--surface);
            color: var(--text);
            border: 1px solid var(--subtext);
            padding: 8px 16px;
            cursor: pointer;
            margin-right: 10px;
            border-radius: 4px;
        }
        
        button:hover {
            background: var(--blue);
            color: var(--bg);
        }
        
        .container {
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 20px;
        }
        
        .panel {
            background: var(--surface);
            border-radius: 8px;
            padding: 15px;
        }
        
        .panel h2 {
            color: var(--blue);
            margin-top: 0;
            font-size: 1em;
            border-bottom: 1px solid var(--subtext);
            padding-bottom: 8px;
        }
        
        /* Timeline styles */
        .timeline {
            position: relative;
            padding-left: 20px;
        }
        
        .timeline::before {
            content: '';
            position: absolute;
            left: 5px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: var(--subtext);
        }
        
        .activation {
            position: relative;
            margin-bottom: 15px;
            padding: 10px;
            background: var(--bg);
            border-radius: 4px;
            border-left: 3px solid var(--green);
        }
        
        .activation.running {
            border-left-color: var(--yellow);
        }
        
        .activation.error {
            border-left-color: var(--red);
        }
        
        .activation::before {
            content: '';
            position: absolute;
            left: -23px;
            top: 15px;
            width: 10px;
            height: 10px;
            background: var(--green);
            border-radius: 50%;
        }
        
        .activation.running::before {
            background: var(--yellow);
            animation: pulse 1s infinite;
        }
        
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .activation .agent-name {
            color: var(--mauve);
            font-weight: bold;
        }
        
        .activation .trigger {
            color: var(--subtext);
            font-size: 0.85em;
        }
        
        .activation .time {
            color: var(--subtext);
            font-size: 0.8em;
            float: right;
        }
        
        .activation .outputs {
            margin-top: 5px;
            font-size: 0.85em;
            color: var(--green);
        }
        
        /* Workspace styles */
        .workspace-path {
            margin-bottom: 10px;
            padding: 8px;
            background: var(--bg);
            border-radius: 4px;
        }
        
        .workspace-path .path {
            color: var(--blue);
            font-size: 0.9em;
            word-break: break-all;
        }
        
        .workspace-path .value {
            color: var(--text);
            font-size: 0.85em;
            margin-top: 5px;
            max-height: 100px;
            overflow: auto;
        }
        
        .status {
            margin-top: 20px;
            padding: 10px;
            background: var(--surface);
            border-radius: 4px;
            font-size: 0.9em;
            color: var(--subtext);
        }
        
        .status.connected {
            border-left: 3px solid var(--green);
        }
        
        .status.error {
            border-left: 3px solid var(--red);
        }
    </style>
</head>
<body>
    <h1>🧠 Companion Agent Timeline</h1>
    
    <div class="controls">
        <button onclick="refresh()">↻ Refresh</button>
        <button onclick="toggleAutoRefresh()">⏱ Auto-refresh: <span id="auto-status">OFF</span></button>
        <button onclick="clearTimeline()">🗑 Clear</button>
    </div>
    
    <div class="container">
        <div class="panel">
            <h2>Agent Activations</h2>
            <div id="timeline" class="timeline">
                <p style="color: var(--subtext)">Loading...</p>
            </div>
        </div>
        
        <div class="panel">
            <h2>Workspace State</h2>
            <div id="workspace">
                <p style="color: var(--subtext)">Loading...</p>
            </div>
        </div>
    </div>
    
    <div id="status" class="status">
        Connecting...
    </div>
    
    <script>
        let autoRefresh = false;
        let autoRefreshInterval = null;
        
        function formatTime(timestamp) {
            if (!timestamp) return '';
            const d = new Date(timestamp * 1000);
            return d.toLocaleTimeString();
        }
        
        function formatDuration(start, end) {
            if (!start || !end) return '';
            const ms = (end - start) * 1000;
            return `${ms.toFixed(0)}ms`;
        }
        
        async function fetchActivations() {
            try {
                const res = await fetch('/api/activations');
                return await res.json();
            } catch (e) {
                console.error('Failed to fetch activations:', e);
                return [];
            }
        }
        
        async function fetchWorkspace() {
            try {
                const res = await fetch('/api/workspace');
                return await res.json();
            } catch (e) {
                console.error('Failed to fetch workspace:', e);
                return {};
            }
        }
        
        function renderActivations(activations) {
            const container = document.getElementById('timeline');
            
            if (!activations || activations.length === 0) {
                container.innerHTML = '<p style="color: var(--subtext)">No activations yet. Move your cursor in the editor to trigger agents.</p>';
                return;
            }
            
            // Reverse to show newest first
            const sorted = [...activations].reverse();
            
            container.innerHTML = sorted.map(a => `
                <div class="activation ${a.status}">
                    <span class="time">${formatTime(a.started_at)} (${formatDuration(a.started_at, a.ended_at)})</span>
                    <div class="agent-name">${a.agent}</div>
                    <div class="trigger">← ${a.trigger}</div>
                    ${a.outputs && a.outputs.length > 0 ? 
                        `<div class="outputs">→ ${a.outputs.join(', ')}</div>` : ''}
                </div>
            `).join('');
        }
        
        function renderWorkspace(workspace) {
            const container = document.getElementById('workspace');
            
            const paths = Object.keys(workspace).sort();
            
            if (paths.length === 0) {
                container.innerHTML = '<p style="color: var(--subtext)">Workspace empty</p>';
                return;
            }
            
            container.innerHTML = paths.map(path => {
                const value = workspace[path];
                let displayValue;
                
                if (typeof value === 'string') {
                    displayValue = value.length > 200 ? value.substring(0, 200) + '...' : value;
                } else {
                    displayValue = JSON.stringify(value, null, 2);
                    if (displayValue.length > 200) {
                        displayValue = displayValue.substring(0, 200) + '...';
                    }
                }
                
                return `
                    <div class="workspace-path">
                        <div class="path">${path}</div>
                        <pre class="value">${escapeHtml(displayValue)}</pre>
                    </div>
                `;
            }).join('');
        }
        
        function escapeHtml(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        }
        
        async function refresh() {
            try {
                const [activations, workspace] = await Promise.all([
                    fetchActivations(),
                    fetchWorkspace()
                ]);
                
                renderActivations(activations);
                renderWorkspace(workspace);
                
                document.getElementById('status').className = 'status connected';
                document.getElementById('status').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
            } catch (e) {
                document.getElementById('status').className = 'status error';
                document.getElementById('status').textContent = `Error: ${e.message}`;
            }
        }
        
        function toggleAutoRefresh() {
            autoRefresh = !autoRefresh;
            document.getElementById('auto-status').textContent = autoRefresh ? 'ON' : 'OFF';
            
            if (autoRefresh) {
                autoRefreshInterval = setInterval(refresh, 1000);
            } else {
                clearInterval(autoRefreshInterval);
                autoRefreshInterval = null;
            }
        }
        
        function clearTimeline() {
            document.getElementById('timeline').innerHTML = '<p style="color: var(--subtext)">Timeline cleared</p>';
        }
        
        // Initial load
        refresh();
    </script>
</body>
</html>
"""


class TimelineServer:
    """HTTP server for timeline visualization."""

    def __init__(self, runtime: "CompanionRuntime", port: int = 8765) -> None:
        self.runtime = runtime
        self.port = port
        self._server: HTTPServer | None = None
        self._thread = None

    def start(self) -> None:
        """Start the timeline server in a background thread."""
        import threading

        TimelineHandler.runtime = self.runtime

        # Ensure static directory exists
        static_dir = Path(__file__).parent / "web" / "static"
        static_dir.mkdir(parents=True, exist_ok=True)

        self._server = HTTPServer(("localhost", self.port), TimelineHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        logger.info(f"Timeline server started at http://localhost:{self.port}")

    def stop(self) -> None:
        """Stop the timeline server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            logger.info("Timeline server stopped")


def start_timeline_server(runtime: "CompanionRuntime", port: int = 8765) -> TimelineServer:
    """Start the timeline visualization server."""
    server = TimelineServer(runtime, port)
    server.start()
    return server
