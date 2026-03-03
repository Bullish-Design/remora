# Timeline Debugger Enhancements — Brainstorm

> Enhancement ideas for the Agent Timeline Debugger web UI, building on the existing swimlane visualization.

---

## Table of Contents

1. [Filter Controls UI](#1-filter-controls-ui) — Interactive filter bar for narrowing visible events by type, agent, time range, and correlation chain.
2. [Follow Mode (Auto-Scroll)](#2-follow-mode-auto-scroll) — Live tail that auto-scrolls to show the most recent events as they arrive.
3. [Event Type Legend](#3-event-type-legend) — Color-coded legend panel showing all event types and their colors, with click-to-filter.
4. [Keyboard Navigation](#4-keyboard-navigation) — Vim-style keys for navigating lanes, events, and inspector without mouse.
5. [Correlation Chain Highlighting](#5-correlation-chain-highlighting) — Click an event to highlight all events in the same correlation chain, dim everything else.
6. [Event Replay / Scrub Mode](#6-event-replay--scrub-mode) — Step through events one at a time in chronological order, watching the timeline build up.
7. [Agent Grouping / Collapsing](#7-agent-grouping--collapsing) — Collapse idle agents, group by file or type, auto-hide agents with no events in view.
8. [Time Range Selection / Brush](#8-time-range-selection--brush) — Minimap overview bar with a draggable range selector for zooming into a time window.
9. [Event Search / Quick Filter](#9-event-search--quick-filter) — Text search across event payloads, types, and agent names with highlight-in-place results.
10. [Performance Flame View](#10-performance-flame-view) — Show agent turn durations as flame-chart-style bars instead of point markers.
11. [Export / Share](#11-export--share) — Export visible timeline as PNG/SVG, or as a JSON event dump for sharing.
12. [Multi-Timeline Comparison](#12-multi-timeline-comparison) — Side-by-side or overlay comparison of two time ranges or two runs.
13. [Minimap / Overview Bar](#13-minimap--overview-bar) — A compressed full-timeline overview showing event density, with the current viewport highlighted.

---

## 1. Filter Controls UI

### What It Does

An interactive filter bar above the timeline SVG that lets you narrow visible events without reloading the page. Filters include:

- **Event type checkboxes**: Toggle visibility of specific event types (AgentStart, AgentComplete, ModelRequest, etc.)
- **Agent dropdown/multi-select**: Show only events from selected agents
- **Time range inputs**: Start/end time pickers (or relative: "last 5 min", "last 1 hour")
- **Correlation ID filter**: Text input to filter to a specific correlation chain
- **Limit slider**: Control how many events are displayed (50, 100, 500, all)

### Implementation Approach

**Server-side filtering** (preferred): The controls bar sends filter params as query parameters to `/timeline/subscribe`. The `read_timeline_data()` function already supports `since`, `until`, `agent_ids`, `correlation_id`, and `limit` parameters. The SSE handler re-renders the SVG with the filtered data.

**Controls bar HTML**: Extend the existing `.timeline-controls` bar in `timeline/views.py`. Use Datastar signals to bind form values and trigger SSE re-subscribe on change.

```html
<div class="timeline-controls">
  <label>Types:</label>
  <select multiple data-model="eventTypes">...</select>
  <label>Agents:</label>
  <select multiple data-model="agentFilter">...</select>
  <label>Since:</label>
  <input type="text" data-model="sinceFilter" placeholder="5m ago">
  <button class="btn" data-on-click="@get('/timeline/subscribe?since=...')">Apply</button>
</div>
```

**New data layer additions**: Add an `event_types` filter parameter to `read_timeline_data()`. The current implementation doesn't filter by event type — add a `WHERE event_type IN (...)` clause.

### Complexity: Medium

- Data layer changes: minimal (add event_type filter)
- View changes: moderate (controls bar HTML, Datastar bindings)
- Route changes: parse query params in timeline_subscribe handler
- Tests: ~10-15 new tests

---

## 2. Follow Mode (Auto-Scroll)

### What It Does

A toggle button ("Follow" / "Live") that, when active, automatically scrolls the timeline to show the most recent events as they arrive via SSE. The viewport pans right to keep the latest events visible. Disabling follow mode freezes the viewport so you can inspect historical events without being yanked to the present.

### Implementation Approach

**Client-side JS**: After each SSE update replaces the SVG, if follow mode is active:
1. Calculate the X position of the rightmost event marker
2. Set `tx` (the pan offset) to keep that position near the right edge of the viewport
3. Apply the transform

**Toggle button**: Add a "Follow" button to the controls bar. When active, it has the `.active` class (blue background). Clicking toggles a `followMode` signal.

```javascript
// In the SSE update handler (Datastar after-settle):
if (window.__timelineFollowMode) {
    const svg = document.getElementById('timeline-svg');
    const markers = svg.querySelectorAll('.event-marker');
    if (markers.length > 0) {
        const last = markers[markers.length - 1];
        const cx = parseFloat(last.getAttribute('cx'));
        // Pan so cx is at 80% of viewport width
        const pane = document.getElementById('timeline-pane');
        tx = pane.clientWidth * 0.8 - cx * scale;
        svg.style.transform = `translate(${tx}px,${ty}px) scale(${scale})`;
    }
}
```

**Auto-disable on manual pan**: If the user manually drags the timeline, follow mode automatically disables (they've indicated they want to look at something specific).

### Complexity: Low

- Pure client-side JS change
- One new button in the controls bar
- ~5 new tests (follow toggle state, auto-disable on pan)

---

## 3. Event Type Legend

### What It Does

A panel (either inline in the controls bar or as a collapsible sidebar section) showing all event types with their color dots. Acts as both a reference and a filter — clicking a type toggles its visibility.

### Implementation Approach

**Legend HTML**: Generated server-side from the `EVENT_TYPE_COLORS` dict in `timeline/svg.py`. Rendered as a horizontal strip in the controls bar or as a vertical list in the inspector panel.

```html
<div class="timeline-legend">
  <span class="legend-item" data-type="AgentStart">
    <span class="legend-dot" style="background:#89b4fa"></span> AgentStart
  </span>
  <span class="legend-item" data-type="AgentComplete">
    <span class="legend-dot" style="background:#a6e3a1"></span> AgentComplete
  </span>
  ...
</div>
```

**Interactive filtering**: Clicking a legend item toggles a CSS class on all markers of that type. Uses SVG `data-event-type` attribute (needs to be added to `render_event_marker`). CSS approach avoids server round-trips:

```javascript
legendItem.addEventListener('click', function() {
    const type = this.dataset.type;
    this.classList.toggle('legend-disabled');
    document.querySelectorAll(`.event-marker[data-event-type="${type}"]`)
        .forEach(m => m.classList.toggle('hidden'));
});
```

**Adaptive**: Only shows event types that actually appear in the current data, not all possible types.

### Complexity: Low

- Add `data-event-type` attribute to `render_event_marker` in svg.py
- New `render_legend()` function in svg.py or views.py
- Client-side JS for click-to-filter
- ~8 new tests

---

## 4. Keyboard Navigation

### What It Does

Vim-style keyboard shortcuts for navigating the timeline without a mouse:

| Key | Action |
|-----|--------|
| `j` / `k` | Move focus to next/previous agent lane |
| `h` / `l` | Move focus to previous/next event in current lane |
| `Enter` | Open inspector for focused event |
| `Escape` | Close inspector / clear selection |
| `f` | Toggle follow mode |
| `c` | Highlight correlation chain for focused event |
| `+` / `-` | Zoom in / out |
| `0` | Reset zoom to fit all events |
| `/` | Open search / quick filter |
| `?` | Show keyboard shortcuts help overlay |

### Implementation Approach

**Focus tracking**: Maintain a `currentAgentIndex` and `currentEventIndex` in JS. The "focused" event gets a visual ring (SVG stroke or CSS outline). Moving focus updates the tracking variables and applies the visual indicator.

```javascript
let focusAgent = 0, focusEvent = 0;

document.addEventListener('keydown', function(e) {
    if (e.key === 'j') {
        focusAgent = Math.min(focusAgent + 1, agents.length - 1);
        updateFocus();
    }
    // ... etc
});
```

**Event index**: Build a 2D array `agentEvents[agentIndex][eventIndex]` from the SVG markers on each SSE update. This allows O(1) navigation.

**Auto-pan on focus**: When keyboard focus moves to an event outside the current viewport, pan the timeline to center that event.

### Complexity: Medium

- Moderate JS work for focus tracking + key handlers
- Need to rebuild the event index on each SSE update
- ~10 new tests (key handler behavior, focus tracking, viewport pan)

---

## 5. Correlation Chain Highlighting

### What It Does

When you click an event (or press `c` with keyboard focus), all events sharing the same `correlation_id` are highlighted — brighter, larger markers, with the correlation lines becoming opaque. All other events dim to 30% opacity. This makes causal chains visually obvious in a dense timeline.

### Implementation Approach

**SVG attributes**: Already have `data-event-id` on markers. Need to add `data-correlation-id` to both markers and correlation lines.

**CSS-based dimming**: Apply a `.dim` class to non-chain elements and a `.highlight` class to chain elements:

```css
.event-marker.dim { opacity: 0.2; }
.event-marker.highlight { r: 9; filter: drop-shadow(0 0 3px currentColor); }
.correlation-line.highlight { opacity: 0.8; stroke-width: 2; }
```

**JS handler**: On click/keypress, read the correlation_id from the clicked marker, then toggle classes:

```javascript
function highlightCorrelation(correlationId) {
    document.querySelectorAll('.event-marker').forEach(m => {
        m.classList.toggle('dim', m.dataset.correlationId !== correlationId);
        m.classList.toggle('highlight', m.dataset.correlationId === correlationId);
    });
}
```

**Clear**: Click empty space or press Escape to remove highlighting.

### Complexity: Low-Medium

- Add `data-correlation-id` to markers in svg.py
- CSS additions in css.py
- JS handler in views.py
- ~8 new tests

---

## 6. Event Replay / Scrub Mode

### What It Does

A "Replay" mode where you step through events one at a time in chronological order. The timeline builds up progressively — start with an empty timeline, then each step adds the next event (with a brief animation). This is the "killer feature" for understanding complex event cascades.

### Implementation Approach

**Replay controls**: A bar at the bottom with Play/Pause, Step Forward, Step Back, Speed slider (0.5x, 1x, 2x, 5x), and a scrub slider showing position in the event sequence.

**Progressive rendering**: In replay mode, the SVG only shows events up to the current replay position. This requires either:

1. **Client-side masking**: Render all events but hide those beyond the replay cursor (CSS `display:none`). Simpler, no server round-trips.
2. **Server-side re-render**: Request SVG with `limit=N` for each step. More accurate but slower.

Client-side masking is better for smooth replay. Events have sequential IDs so we can use `data-event-id` to show/hide:

```javascript
function replayTo(eventIndex) {
    const events = sortedEvents; // cached sorted list
    events.forEach((eid, i) => {
        const el = document.querySelector(`[data-event-id="${eid}"]`);
        el.style.display = i <= eventIndex ? '' : 'none';
    });
    // Also show/hide correlation lines
    updateReplayCorrelationLines(eventIndex);
}
```

**Auto-play**: Play button steps through events at a configurable rate, updating the scrub position and inspector panel.

**Source code integration**: In the remora-demo context, this is less relevant (no source files). But the inspector panel updates to show each event's details as you step through, which is the equivalent.

### Complexity: High

- New replay controls UI (HTML + CSS)
- Complex JS state machine (play/pause/step/scrub)
- Event sorting and progressive visibility
- Correlation line management during replay
- ~15-20 new tests

---

## 7. Agent Grouping / Collapsing

### What It Does

When there are many agents, the timeline becomes vertically crowded. Grouping lets you:

- **Collapse idle agents**: Agents with no events in the current time window are hidden (or collapsed to a single thin row).
- **Group by type**: `function`, `module`, `test` agents grouped with collapsible headers.
- **Group by file**: Agents from the same file grouped together.
- **Manual pin/unpin**: Pin specific agents to always be visible, unpin to allow auto-hide.

### Implementation Approach

**Server-side**: Extend `read_timeline_data()` to return agent metadata (type, file_path) alongside the agent names. Group ordering logic in svg.py.

**Collapsible groups**: Render group headers as clickable SVG elements. Clicking toggles child lane visibility. Group state stored in a Datastar signal.

**Auto-hide idle**: A checkbox "Hide idle agents" that filters the agent list to only those with events in the visible time range. This is a filter on the data layer — `agent_ids` parameter already supports this.

### Complexity: Medium-High

- Data layer: need agent metadata (join with nodes table or include in events query)
- SVG renderer: group headers, collapsible sections, variable lane heights
- JS: collapse/expand interaction
- ~12-15 new tests

---

## 8. Time Range Selection / Brush

### What It Does

A "brush" control — a miniaturized overview of the entire timeline where you can drag a range selector to zoom into a specific time window. Like the overview bar in VS Code's minimap, but for the time axis.

### Implementation Approach

**Overview SVG**: A thin (40px tall) SVG below the main timeline showing the full time range with simplified event markers (just dots, no labels). A semi-transparent rectangle shows the current viewport's time range.

**Drag interaction**: Drag the edges of the rectangle to resize the time window. Drag the middle to pan. Mouse wheel on the overview to zoom the main timeline.

**Server integration**: When the brush range changes, re-request data with `since` and `until` parameters matching the brush selection.

### Complexity: Medium-High

- New SVG rendering for the overview bar
- Complex drag interaction JS
- Sync between brush, main timeline viewport, and server filters
- ~12 new tests

---

## 9. Event Search / Quick Filter

### What It Does

A search box (`/` to activate) that searches across event types, agent names, and payload content. Matching events are highlighted in-place on the timeline; non-matching events dim. The inspector shows a count of matches and lets you jump between them.

### Implementation Approach

**Server-side search**: New parameter `search` on `read_timeline_data()` that does a LIKE query across `event_type`, `from_agent`, `to_agent`, and `payload` columns. Returns matching event IDs alongside the full data.

**Client-side highlight**: Similar to correlation highlighting but driven by search results. Matching markers get a `.search-match` class with a distinctive visual (e.g., pulsing ring).

**Navigation**: Up/Down arrows in the search box jump between matches, centering each in the viewport.

### Complexity: Medium

- Data layer: add `search` parameter with SQLite LIKE queries
- Client-side: search input, highlight logic, match navigation
- ~10 new tests

---

## 10. Performance Flame View

### What It Does

An alternative visualization mode where instead of point markers, agent turns are shown as **horizontal bars** spanning from `AgentStart` to `AgentComplete` (or `AgentError`). This reveals duration and overlap — you can see which agents are running concurrently and which are sequential.

### Implementation Approach

**Data layer**: Group events into "spans" — pairs of (start, end) events for each agent turn. A span is `AgentStart` -> `AgentComplete/AgentError` for the same agent and correlation chain.

**SVG rendering**: Replace circle markers with `<rect>` elements sized to the span duration. Color by event type or by agent. Overlapping spans stack vertically within a lane.

**Toggle**: A mode selector in the controls bar: "Points" (current) | "Bars" (flame view). The SVG renderer checks the mode and calls different rendering logic.

### Complexity: High

- New data layer logic for span extraction (pairing start/end events)
- New SVG rendering path (rects instead of circles)
- Stacking logic for overlapping spans within a lane
- ~15-20 new tests

---

## 11. Export / Share

### What It Does

Export the current timeline view for sharing, debugging, or documentation:

- **SVG export**: Download the current SVG as a file
- **PNG export**: Render the SVG to a canvas and export as PNG
- **JSON export**: Export the raw event data (filtered as currently displayed) as JSON
- **Link with filters**: Generate a URL with current filter state encoded as query params

### Implementation Approach

**SVG/PNG**: Client-side JS. For SVG, serialize the `#timeline-svg` element. For PNG, use `<canvas>` with `drawImage` from the SVG.

**JSON export**: New route `GET /timeline/export?format=json&since=...&until=...` that returns raw event data.

**Share URL**: Encode filter state as URL query params. Loading `/timeline?since=...&until=...&agents=...` pre-applies filters.

### Complexity: Low-Medium

- Client-side: SVG/PNG export (well-known patterns)
- Server-side: one new route for JSON export
- ~5-8 new tests

---

## 12. Multi-Timeline Comparison

### What It Does

Compare two time ranges or two different runs side-by-side. Useful for:

- "What was different about this run vs. the last one?"
- "Compare the event pattern before and after my change"
- "Show me the last 5 minutes vs. the 5 minutes before that"

### Implementation Approach

**Split view**: Two timeline SVGs stacked vertically, each with its own time range filter. A shared time axis aligns them so you can visually compare event patterns.

**Overlay mode**: Alternatively, render both time ranges in the same SVG with different opacity/color schemes. Events from range A in blue, range B in orange.

**Diff markers**: Highlight events that appear in one range but not the other (new event types, new agents, missing agents).

### Complexity: High

- Significant UI work (split layout, synced navigation)
- Data layer: two simultaneous queries
- Complex SVG rendering with dual datasets
- ~15-20 new tests

---

## 13. Minimap / Overview Bar

### What It Does

A thin bar (either at the top or bottom of the timeline) showing a compressed view of the entire event history. Event density is shown as a heatmap — dark regions have many events, light regions are quiet. The current viewport is shown as a highlighted rectangle. Clicking the minimap jumps to that time position.

### Implementation Approach

**Server-side rendering**: A separate lightweight SVG that renders the full time range as a density histogram (bin events into N buckets, render as rects with opacity proportional to count).

**Viewport indicator**: A semi-transparent overlay rectangle showing which portion of the full timeline is currently visible.

**Click-to-jump**: Clicking a position on the minimap sets the main timeline's viewport center to that time position.

### Complexity: Medium

- New SVG rendering function for the minimap
- Viewport sync between minimap and main timeline
- ~8-10 new tests

---

## Implementation Priority

| Priority | Enhancement | Value | Complexity | Rationale |
|----------|------------|-------|------------|-----------|
| **1** | Filter Controls UI | High | Medium | Most impactful — currently no way to narrow down visible events |
| **2** | Event Type Legend | High | Low | Quick win — essential for understanding what the colors mean |
| **3** | Follow Mode | High | Low | Quick win — critical for live monitoring use case |
| **4** | Keyboard Navigation | Medium-High | Medium | Core UX — the timeline should be fully navigable without mouse |
| **5** | Correlation Chain Highlighting | High | Low-Medium | Already have correlation lines; this makes them actionable |
| **6** | Event Search | Medium | Medium | Necessary for large event sets; pairs well with filters |
| **7** | Minimap / Overview Bar | Medium | Medium | Spatial awareness of where you are in the full timeline |
| **8** | Event Replay / Scrub | Very High | High | "Killer feature" — but complex to build right |
| **9** | Agent Grouping / Collapsing | Medium | Medium-High | Important at scale but less critical for initial use |
| **10** | Performance Flame View | High | High | Reveals duration/overlap info that points can't show |
| **11** | Time Range Brush | Medium | Medium-High | Overlaps with minimap; do minimap first |
| **12** | Export / Share | Medium | Low-Medium | Nice to have; not urgent |
| **13** | Multi-Timeline Comparison | Medium | High | Advanced feature; defer until core is solid |

### Suggested Implementation Phases

**Phase A — Quick Wins (3 items, ~25 tests):**
Event Type Legend, Follow Mode, Correlation Chain Highlighting

**Phase B — Core Interactivity (3 items, ~30 tests):**
Filter Controls UI, Keyboard Navigation, Event Search

**Phase C — Spatial Awareness (2 items, ~18 tests):**
Minimap / Overview Bar, Agent Grouping / Collapsing

**Phase D — Advanced Features (4 items, ~55 tests):**
Event Replay / Scrub, Performance Flame View, Time Range Brush, Export / Share

**Phase E — Polish (1 item, ~18 tests):**
Multi-Timeline Comparison

---

## Architecture Notes

All enhancements follow the existing patterns:

- **Server-rendered SVG**: New rendering logic goes in `timeline/svg.py`
- **HTML/CSS**: New UI elements go in `timeline/views.py` and `timeline/css.py`
- **Data queries**: Filter extensions go in `timeline/state.py`
- **Routes**: New endpoints in `graph/app.py`
- **JS interaction**: Client-side behavior embedded in `timeline/views.py` (same as current zoom/pan/tooltip JS)
- **TDD**: Every enhancement starts with failing tests

The existing `read_timeline_data()` already supports most of the filter parameters needed. The SVG renderer's composable design (individual render functions for markers, labels, lines, axis) makes it straightforward to add new visual elements.
