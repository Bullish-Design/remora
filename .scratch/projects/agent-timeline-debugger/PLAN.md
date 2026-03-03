# Plan — Agent Timeline Debugger (Web UI)

**CRITICAL: NO SUBAGENTS. Do all work directly. No Task tool. No delegation.**

## Overview

Implement the Agent Timeline Debugger as a web-based swimlane visualization in the remora-demo/frontend project, alongside the existing graph viewer. Leverages the existing Stario + Datastar + SSE infrastructure.

## Architecture

The timeline is a **new page/view** in the graph viewer app:
- **Data layer**: `GraphState.read_timeline_data()` — reads events grouped by agent from the shared SQLite DB
- **SVG renderer**: `graph/views/timeline.py` — server-rendered SVG swimlane view
- **CSS**: additions to `graph/css.py` for timeline-specific styles
- **Routes**: `/timeline` page, `/timeline/subscribe` SSE endpoint
- **JS**: client-side interaction (zoom, hover tooltips, correlation highlighting, click-to-inspect)
- **Bridge**: DBBridge publishes `timeline.events` subject on new events

## Steps

### Phase 1: Data Layer (TDD)

**Step 1: GraphState.read_timeline_data()**
- Write tests for the query: events grouped by agent, correlation groups, time range
- Implement in state.py
- Returns: agents (ordered by first event), flat event list, correlation map, time range

### Phase 2: SVG Renderer (TDD)

**Step 2: Timeline SVG view**
- Write tests for `render_timeline_svg()` 
- Swimlane layout: agents as rows (Y), time as X axis
- Event markers (circles with color by event type)
- Correlation lines (SVG paths between related events)
- Agent labels column
- Time axis with formatted timestamps

### Phase 3: Page & Routing

**Step 3: Timeline shell page**
- Write tests for the HTML shell
- Full HTML page with timeline SVG, inspector panel, controls
- Navigation between graph view and timeline view

**Step 4: App routes**
- GET `/timeline` — serve the timeline page
- GET `/timeline/subscribe` — SSE endpoint for live updates
- GET `/timeline/event/<id>` — event detail for inspector

### Phase 4: Interaction (JS)

**Step 5: Client-side interaction**
- Hover: show tooltip with event summary
- Click: open inspector panel with full event details
- Correlation highlight: click event shows all related events
- Zoom/pan: scroll to zoom, drag to pan
- Time range controls: narrow/widen visible window

### Phase 5: Integration

**Step 6: Bridge updates**
- DBBridge publishes timeline.events on new events
- SSE handler pushes updated SVG to client

### Phase 6: Verification

**Step 7: Run full test suite**
- All existing frontend tests must pass
- New timeline tests must pass

**CRITICAL: NO SUBAGENTS. Do all work directly. No Task tool. No delegation.**
