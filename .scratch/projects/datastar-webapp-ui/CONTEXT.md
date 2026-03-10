# CONTEXT — datastar-webapp-ui

## What just happened
Completed full investigation + IMPLEMENTATION_GUIDE.md (detailed step-by-step guide for a
junior developer to build the remora web UI as a standalone Python 3.14 repository).

## Deliverables
- `REPORT.md` — 735-line investigation report (architectural options, pros/cons)
- `IMPLEMENTATION_GUIDE.md` — Complete build guide covering:
  - 5 remora server-side changes (CORS, companion_registry, /graph/data, /companion/sidebar,
    /companion/chat, /companion/workspace)
  - New `remora-ui` repo setup (pyproject.toml, devenv.nix, Starlette app)
  - Full HTML/CSS/JS for both modes (Cytoscape.js + Datastar + marked.js)
  - Phase-by-phase implementation plan (P0 static graph → P5 replay scrubber)
  - Testing checklist + pitfalls FAQ

## Key technical decisions
1. Standalone library serves only static HTML; browser makes CORS requests directly to remora
2. CORS middleware added to remora's Starlette app (allow_origins for localhost:8766)
3. Graph edges derived from AgentNode.callee_ids (no need for RemoraDB)
4. Cytoscape compound nodes via AgentNode.parent_id (not separate parent_of edges)
5. Datastar manages sidebar signals; vanilla JS EventSource for SSE pings; marked.js for markdown
6. `window.__datastar_store` used for JS→Datastar signal interop
7. companion_registry added to RemoraService as optional field + set_companion_registry() method

## Files to modify in remora repo (not yet done — awaiting implementation)
- src/remora/adapters/starlette.py — CORS + 4 new routes
- src/remora/service/api.py — companion_registry field + property

## Status
Documentation phase complete. Implementation not started.

## Next step (if user wants to proceed)
Start P0: add CORS + /graph/data to remora, create the remora-ui repo, get the static graph
rendering in the browser.
