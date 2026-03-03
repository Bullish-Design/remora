# Context — Agent Timeline Debugger (Web UI)

## Current State
Implementation complete. All phases done, all tests passing.

## What Was Done
1. **Phase 1 — Data Layer**: Created `timeline/state.py` with `read_timeline_data()` function and `TimelineData` dataclass. Queries events from SQLite, groups by agent for swimlane rendering. Supports filtering by since/until, agent_ids, correlation_id, limit. 19 tests in `test_timeline_state.py`.

2. **Phase 2 — SVG Renderer**: Created `timeline/svg.py` with swimlane layout rendering. Event markers colored by type (Catppuccin Mocha palette), correlation lines connecting related events, agent labels column, time axis. 24 tests in `test_timeline_svg.py`.

3. **Phase 3 — Page & Routing**: Created `timeline/css.py` (timeline-specific Catppuccin CSS), `timeline/views.py` (shell page + event inspector panel). Added routes to `graph/app.py` for GET /timeline, GET /timeline/subscribe, GET /timeline/event/*. 21 tests in `test_timeline_views.py` + 3 route tests in `test_app.py`.

4. **Phase 4 — Interaction**: Client-side JS in views.py shell: zoom/pan, hover tooltips on event markers, click-to-inspect dispatching.

5. **Phase 5 — Integration**: `timeline_subscribe` handler in app.py subscribes to `graph.events` via the existing Relay. DBBridge already detects new events and publishes `graph.events`.

6. **Phase 6 — Verification**: Full test suite: 253 passed, 2 skipped, 1 pre-existing failure (unrelated scaffold/idle mismatch in test_cross_process.py).

## Files Created/Modified

### New files (in remora-demo/frontend/):
- `timeline/__init__.py` — package init
- `timeline/state.py` — data queries (read_timeline_data, TimelineData)
- `timeline/svg.py` — SVG swimlane rendering
- `timeline/css.py` — Catppuccin Mocha CSS for timeline
- `timeline/views.py` — shell page + event inspector
- `tests/test_timeline_state.py` — 19 tests
- `tests/test_timeline_svg.py` — 24 tests
- `tests/test_timeline_views.py` — 21 tests

### Modified files:
- `graph/app.py` — added 3 timeline routes + handler factories + imports
- `graph/views/shell.py` — added Timeline nav link in header
- `pyproject.toml` — added "timeline" to packages
- `tests/test_app.py` — added 3 timeline route structure tests
