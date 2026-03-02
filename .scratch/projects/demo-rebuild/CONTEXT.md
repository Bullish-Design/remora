# CONTEXT — Demo Rebuild

## Current State

**PROJECT COMPLETE.** All tasks T1-T22 are implemented and tested. 130 tests pass, 2 skipped (Stario-dependent, Python 3.14 only).

## What Was Done

### Previous sessions
- T1: configlib demo project files
- T2: Extension configs + remora.yaml
- T14: Enhanced MockLLMClient

### This session (all complete with passing tests)

**Foundations (T15-T18):**
- T15: ForceLayout — server-side force-directed graph layout (`layout.py`, 17 tests)
- T16: SVG builders — f-string-based SVG rendering (`svg.py`, 28 tests)
- T17: CSS theme — Catppuccin Mocha dark theme with transitions (`css.py`, 13 tests)
- T18: DB Bridge + GraphState — polls SQLite, publishes to Relay (`bridge.py`, `state.py`, 13 tests)

**Views (T20):**
- `views/graph.py` — render_graph() wrapper around SVG builders
- `views/shell.py` — Full HTML document with Datastar CDN, CSS, graph, sidebar, zoom/pan JS
- `views/sidebar.py` — Sidebar detail panel with tabs (Log/Source/Connections/Actions)
- `views/event_stream.py` — Global event stream with colored badges
- 24 tests passing

**App factory (T19):**
- `app.py` — Stario app with closure-based DI handlers
- Routes: GET /, GET /subscribe (SSE), GET /agent/* (sidebar), GET /events, POST /command
- Views return plain strings; wrapped in SafeString for w.patch()
- DB reads offloaded via asyncio.to_thread()
- 8 structural tests pass, 2 Stario-dependent tests skipped

**Entry points (T21):**
- `__main__.py` — argparse CLI with --port/--host/--db/--poll-interval/--verbose
- `launch.sh` — convenience launcher script
- Stario import deferred to async _serve() to keep module importable in Python 3.13
- 11 tests passing

**Integration test (T22):**
- Full pipeline test: creates SQLite DB with demo data, verifies entire chain
- Tests DB reads, layout, rendering, bridge fingerprinting, change detection
- 16 tests passing

## Key Design Decisions

1. **All views return plain strings** — no Stario dependency in views/SVG/CSS
2. **SVG as f-strings** wrapped in SafeString — Stario has no SVG elements
3. **RelayProtocol** — Protocol class for testability without Stario
4. **Catch-all routes** — `/agent/*` with `c.req.tail` (Stario has no `{param}` syntax)
5. **create_app returns (app, bridge)** — caller starts bridge task before app.serve()
6. **Deferred Stario import** — __main__.py importable in Python 3.13

## File Inventory

```
remora_demo/web/graph/
  __init__.py        (stub)
  __main__.py        Entry point with argparse CLI
  app.py             Stario app factory + handlers
  bridge.py          DB->Relay polling bridge
  layout.py          Server-side force-directed layout
  svg.py             SVG element builders
  css.py             Catppuccin Mocha CSS theme
  state.py           GraphState + GraphSnapshot
  views/
    __init__.py      (stub)
    graph.py         render_graph()
    shell.py         render_shell()
    sidebar.py       render_sidebar_content()
    event_stream.py  render_event_list()

remora_demo/launch.sh  Convenience launcher

tests/
  test_layout.py           17 passed
  test_svg.py              28 passed
  test_css.py              13 passed
  test_bridge.py           13 passed
  test_views.py            24 passed
  test_app.py              8 passed, 2 skipped
  test_entry_points.py     11 passed
  test_integration_graph.py 16 passed
  TOTAL: 130 passed, 2 skipped
```
