"""HTML shell for the force-directed graph viewer.

Renders the complete HTML page with:
- Catppuccin dark theme CSS
- Datastar for SSE data binding
- d3-force for simulation
- SVG rendering for nodes and edges
- Sidebar panel (populated via patch_elements)
"""

from __future__ import annotations


def render_shell() -> str:
    """Render the full HTML shell (initial page load)."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remora Graph</title>
    <script type="module" src="https://cdn.jsdelivr.net/gh/starfederation/datastar@v1.0.0-RC.7/bundles/datastar.js"></script>
    <style>{_css()}</style>
</head>
<body data-signals='{_initial_signals()}' data-on-load="@get('/subscribe')">
    <div class="app">
        <header class="header">
            <div class="header-title">Remora Graph</div>
            <div class="header-controls">
                <button class="header-btn" data-on-click="$viewMode = $viewMode === 'full' ? 'follow' : 'full'"
                        data-class-active="$viewMode === 'follow'">
                    Follow Cursor
                </button>
                <div class="header-status" id="connection-status">connecting...</div>
            </div>
        </header>
        <div class="main">
            <div class="graph-pane">
                <svg id="graph-svg" width="100%" height="100%"></svg>
            </div>
            <div class="sidebar" id="sidebar">
                <div id="sidebar-content">
                    <div class="sidebar-empty">Click a node to view details</div>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/d3-dispatch@3/dist/d3-dispatch.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-quadtree@3/dist/d3-quadtree.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-timer@3/dist/d3-timer.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-force@3/dist/d3-force.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-zoom@3/dist/d3-zoom.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-selection@3/dist/d3-selection.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/d3-transition@3/dist/d3-transition.min.js"></script>
    <script>{_js()}</script>
</body>
</html>"""


def _initial_signals() -> str:
    """JSON for the initial Datastar signals."""
    import json

    return json.dumps(
        {
            "graph": {"nodes": [], "edges": [], "focus": None},
            "viewMode": "full",
            "selectedNode": None,
        }
    )


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

.header-btn {
    font-family: inherit; font-size: 11px; padding: 4px 12px;
    border: 1px solid var(--surface2); border-radius: 4px;
    background: var(--surface2); color: var(--text);
    cursor: pointer; transition: all 0.15s;
}

.header-btn:hover { background: var(--overlay); }
.header-btn.active { background: var(--blue); color: var(--bg); border-color: var(--blue); }

.header-status, #connection-status {
    font-size: 11px; color: var(--gray);
    padding: 2px 8px; border-radius: 4px; background: var(--surface2);
}

.status-connected { color: var(--green) !important; }

.main { display: flex; flex: 1; overflow: hidden; }

.graph-pane {
    flex: 1; position: relative; overflow: hidden;
    background: var(--bg);
}

#graph-svg { width: 100%; height: 100%; }

/* SVG node styles */
.node-circle { cursor: pointer; transition: stroke-width 0.15s; }
.node-circle:hover { stroke-width: 3px; }
.node-label {
    font-family: 'JetBrains Mono', monospace;
    fill: var(--text); pointer-events: none; text-anchor: middle;
}
.node-label-bg {
    fill: var(--bg); opacity: 0.7; pointer-events: none;
}

.edge-line { pointer-events: none; }

/* Sidebar */
.sidebar {
    width: 350px; background: var(--surface);
    border-left: 1px solid var(--surface2);
    overflow-y: auto; flex-shrink: 0;
}

.sidebar-empty {
    padding: 40px 20px; text-align: center;
    color: var(--gray); font-size: 13px;
}

/* Sidebar tab bar */
.sidebar-tabs {
    display: flex; border-bottom: 1px solid var(--surface2);
}

.sidebar-tab {
    flex: 1; padding: 8px 4px; text-align: center;
    font-family: inherit; font-size: 11px;
    background: none; border: none; border-bottom: 2px solid transparent;
    color: var(--subtext); cursor: pointer; transition: all 0.15s;
}

.sidebar-tab:hover { color: var(--text); }
.sidebar-tab.active { color: var(--blue); border-bottom-color: var(--blue); }

/* Sidebar content sections */
.sidebar-section { padding: 12px 16px; }

.node-info-header {
    display: flex; align-items: center; gap: 8px;
    padding: 12px 16px; border-bottom: 1px solid var(--surface2);
}

.node-info-name { font-weight: 600; font-size: 14px; flex: 1; }
.node-info-type { font-size: 11px; color: var(--subtext); text-transform: uppercase; }
.node-info-status { font-size: 10px; padding: 2px 6px; border-radius: 3px; }

.event-item {
    padding: 6px 0; border-bottom: 1px solid var(--surface2);
    font-size: 11px; display: flex; justify-content: space-between;
}

.event-badge {
    background: var(--surface2); padding: 1px 5px;
    border-radius: 3px; font-size: 10px;
}

.event-time { color: var(--gray); font-size: 10px; }

.source-block {
    background: var(--bg); border-radius: 4px;
    padding: 8px; font-size: 11px; overflow-x: auto;
    max-height: 300px; overflow-y: auto; white-space: pre;
}

.connection-item {
    padding: 4px 0; font-size: 11px; cursor: pointer;
    color: var(--blue); transition: color 0.15s;
}
.connection-item:hover { color: var(--lavender); }

.action-btn {
    display: block; width: 100%; padding: 6px 10px;
    margin-bottom: 6px; font-family: inherit; font-size: 11px;
    background: var(--surface2); border: 1px solid var(--overlay);
    border-radius: 4px; color: var(--text); cursor: pointer;
    transition: all 0.15s; text-align: left;
}
.action-btn:hover { background: var(--overlay); }
.action-btn.primary { background: var(--blue); color: var(--bg); border-color: var(--blue); }
.action-btn.danger { border-color: var(--red); color: var(--red); }
.action-btn.danger:hover { background: var(--red); color: var(--bg); }

.chat-input {
    width: 100%; padding: 6px 8px; font-family: inherit; font-size: 11px;
    background: var(--bg); border: 1px solid var(--surface2); border-radius: 4px;
    color: var(--text); resize: vertical; min-height: 60px;
}
.chat-input:focus { outline: none; border-color: var(--blue); }

.proposal-card {
    background: var(--bg); border: 1px solid var(--yellow);
    border-radius: 4px; padding: 8px; margin-bottom: 8px;
}
.proposal-diff { font-size: 10px; white-space: pre; overflow-x: auto; max-height: 200px; }
"""


def _js() -> str:
    """Client-side JS: d3-force simulation, SVG rendering, Datastar signal watch."""
    return """
(function() {
    'use strict';

    // --- Config ---
    const NODE_RADIUS = { file: 14, class: 11, function: 8, method: 8 };
    const STATUS_COLOR = {
        active: '#a6e3a1', running: '#89b4fa',
        pending_approval: '#f9e2af', orphaned: '#6c7086'
    };
    const EDGE_STYLE = {
        parent_of: { stroke: '#585b70', width: 1.5, dash: '', opacity: 0.5 },
        calls:     { stroke: '#89b4fa', width: 1,   dash: '6,4', opacity: 0.4 }
    };

    // --- State ---
    let simulation = null;
    let simNodes = [];
    let simLinks = [];
    let svgGroup = null;
    let zoom = null;
    let currentFocus = null;
    let selectedNodeId = null;

    const svg = d3.select('#graph-svg');
    const width = () => svg.node().clientWidth;
    const height = () => svg.node().clientHeight;

    // Create a group for zoom/pan
    svgGroup = svg.append('g').attr('class', 'zoom-group');

    // Setup zoom
    zoom = d3.zoom()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
            svgGroup.attr('transform', event.transform);
        });
    svg.call(zoom);

    // Edge and node groups (edges behind nodes)
    const edgeGroup = svgGroup.append('g').attr('class', 'edges');
    const nodeGroup = svgGroup.append('g').attr('class', 'nodes');

    // --- d3-force simulation ---
    function initSimulation() {
        simulation = d3.forceSimulation(simNodes)
            .force('link', d3.forceLink(simLinks)
                .id(d => d.id)
                .distance(d => d.edge_type === 'parent_of' ? 60 : 120)
                .strength(d => d.edge_type === 'parent_of' ? 0.7 : 0.2))
            .force('charge', d3.forceManyBody().strength(-100))
            .force('center', d3.forceCenter(width() / 2, height() / 2))
            .force('collide', d3.forceCollide()
                .radius(d => (NODE_RADIUS[d.node_type] || 8) + 20))
            .on('tick', render);
    }

    // --- Rendering ---
    function render() {
        // Edges
        const lines = edgeGroup.selectAll('line').data(simLinks, d => d.source.id + '-' + d.target.id + '-' + d.edge_type);
        lines.enter()
            .append('line')
            .attr('class', 'edge-line')
            .merge(lines)
            .attr('x1', d => d.source.x)
            .attr('y1', d => d.source.y)
            .attr('x2', d => d.target.x)
            .attr('y2', d => d.target.y)
            .each(function(d) {
                const style = EDGE_STYLE[d.edge_type] || EDGE_STYLE.parent_of;
                const touching = (currentFocus && (d.source.id === currentFocus || d.target.id === currentFocus))
                    || (selectedNodeId && (d.source.id === selectedNodeId || d.target.id === selectedNodeId));
                d3.select(this)
                    .attr('stroke', style.stroke)
                    .attr('stroke-width', touching ? style.width + 1 : style.width)
                    .attr('stroke-dasharray', style.dash)
                    .attr('opacity', touching ? 0.9 : style.opacity);
            });
        lines.exit().remove();

        // Nodes
        const groups = nodeGroup.selectAll('g.node-group').data(simNodes, d => d.id);

        const enter = groups.enter().append('g').attr('class', 'node-group');
        enter.append('circle').attr('class', 'node-circle');
        enter.append('text').attr('class', 'node-label').attr('dy', d => (NODE_RADIUS[d.node_type] || 8) + 14);
        enter.append('title');  // tooltip

        // Click handler
        enter.on('click', function(event, d) {
            selectedNodeId = d.id;
            // Fetch sidebar content
            const sidebarEl = document.getElementById('sidebar-content');
            if (sidebarEl) {
                fetch('/agent/' + encodeURIComponent(d.id))
                    .then(r => r.text())
                    .then(html => { sidebarEl.innerHTML = html; })
                    .catch(() => {});
            }
            render();  // re-render to update highlight
        });

        const merged = enter.merge(groups);

        merged.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');

        merged.select('circle')
            .attr('r', d => NODE_RADIUS[d.node_type] || 8)
            .attr('fill', d => STATUS_COLOR[d.status] || '#6c7086')
            .attr('stroke', d => {
                if (d.id === currentFocus) return '#89b4fa';
                if (d.id === selectedNodeId) return '#b4befe';
                return 'none';
            })
            .attr('stroke-width', d => (d.id === currentFocus || d.id === selectedNodeId) ? 3 : 0)
            .style('filter', d => d.id === currentFocus ? 'drop-shadow(0 0 6px rgba(137,180,250,0.6))' : 'none');

        merged.select('text')
            .text(d => d.name.length > 16 ? d.name.slice(0, 14) + '..' : d.name)
            .attr('font-size', d => d.node_type === 'file' ? '10px' : '9px');

        merged.select('title')
            .text(d => d.name + ' (' + d.node_type + ') [' + d.status + ']');

        groups.exit().remove();
    }

    // --- Data update from Datastar signals ---
    function updateGraph(graphData) {
        if (!graphData || !graphData.nodes) return;

        const nodeMap = new Map(simNodes.map(n => [n.id, n]));

        // Update nodes — preserve positions for existing nodes
        const newNodes = graphData.nodes.map(n => {
            const existing = nodeMap.get(n.remora_id);
            return {
                id: n.remora_id,
                name: n.name,
                node_type: n.node_type,
                status: n.status || 'active',
                file_path: n.file_path,
                x: existing ? existing.x : width() / 2 + (Math.random() - 0.5) * 100,
                y: existing ? existing.y : height() / 2 + (Math.random() - 0.5) * 100,
                vx: existing ? existing.vx : 0,
                vy: existing ? existing.vy : 0,
            };
        });

        const newLinks = graphData.edges.map(e => ({
            source: e.from_id,
            target: e.to_id,
            edge_type: e.edge_type,
        }));

        simNodes = newNodes;
        simLinks = newLinks;

        // Update focus
        currentFocus = graphData.focus;

        if (simulation) {
            simulation.nodes(simNodes);
            simulation.force('link').links(simLinks);
            simulation.alpha(0.3).restart();
        } else {
            initSimulation();
        }

        // Follow mode: zoom to focused node
        const viewMode = document.body.dataset.signals
            ? JSON.parse(document.body.dataset.signals).viewMode
            : 'full';
        if (viewMode === 'follow' && currentFocus) {
            const focusNode = simNodes.find(n => n.id === currentFocus);
            if (focusNode && focusNode.x && focusNode.y) {
                const t = d3.zoomIdentity.translate(width() / 2, height() / 2).scale(1.5).translate(-focusNode.x, -focusNode.y);
                svg.transition().duration(500).call(zoom.transform, t);
            }
        }
    }

    // --- Datastar signal integration ---
    // Watch for signal changes via MutationObserver on body data-signals
    let lastGraphJSON = '';
    const observer = new MutationObserver(() => {
        try {
            const raw = document.body.dataset.signals;
            if (!raw) return;
            const signals = JSON.parse(raw);
            const graphJSON = JSON.stringify(signals.graph);
            if (graphJSON !== lastGraphJSON) {
                lastGraphJSON = graphJSON;
                updateGraph(signals.graph);
                // Update connection status
                const status = document.getElementById('connection-status');
                if (status) { status.textContent = 'live'; status.className = 'status-connected'; }
            }
        } catch(e) { console.error('Signal parse error:', e); }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['data-signals'] });

    // --- Tab switching ---
    window.switchTab = function(btn, tabName) {
        const sidebar = btn.closest('.sidebar, #sidebar-content');
        if (!sidebar) return;
        sidebar.querySelectorAll('.sidebar-tab').forEach(t => t.classList.remove('active'));
        btn.classList.add('active');
        sidebar.querySelectorAll('.tab-content').forEach(el => {
            el.style.display = el.dataset.tab === tabName ? '' : 'none';
        });
    };

    // --- Node selection from sidebar connections ---
    window.selectNode = function(nodeId) {
        selectedNodeId = nodeId;
        const sidebarEl = document.getElementById('sidebar-content');
        if (sidebarEl) {
            fetch('/agent/' + encodeURIComponent(nodeId))
                .then(r => r.text())
                .then(html => { sidebarEl.innerHTML = html; })
                .catch(() => {});
        }
        render();
    };

    // --- Command helpers ---
    window.sendChat = function(agentId) {
        const input = document.getElementById('chat-input');
        if (!input || !input.value.trim()) return;
        fetch('/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command_type: 'chat', agent_id: agentId, payload: {message: input.value.trim()}}),
        }).then(() => { input.value = ''; });
    };

    window.approveProposal = function(proposalId) {
        fetch('/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command_type: 'approve_proposal', agent_id: null, payload: {proposal_id: proposalId}}),
        });
    };

    window.rejectProposal = function(proposalId) {
        fetch('/command', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command_type: 'reject_proposal', agent_id: null, payload: {proposal_id: proposalId}}),
        });
    };

    // Initial fit
    window.addEventListener('resize', () => {
        if (simulation) {
            simulation.force('center', d3.forceCenter(width() / 2, height() / 2));
            simulation.alpha(0.1).restart();
        }
    });
})();
"""
