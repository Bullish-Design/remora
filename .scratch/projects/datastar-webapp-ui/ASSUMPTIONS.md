# ASSUMPTIONS — datastar-webapp-ui

## Scope
- This is a planning/investigation project, not yet an implementation
- The webapp is a *complement* to the Neovim LSP integration, not a replacement
- Users may use either or both interfaces simultaneously

## Scale assumptions
- Current project: ~100–300 nodes, ~300–1000 edges
- Target scale: up to ~500 nodes before needing to revisit graph library choice
- For >1000 nodes, Sigma.js (WebGL) would be needed

## Tech stack assumptions
- Starlette is the HTTP framework (already in use)
- Datastar v1.0.0-RC.7 is the frontend reactivity layer (already loaded from CDN)
- Python 3.11+ (async/await throughout)
- No new Python dependencies beyond what's already in pyproject.toml
- Cytoscape.js loaded from CDN (no bundler required)

## Architecture assumptions
- The Starlette webapp and LSP server run in the same OS process (sharing EventBus in-memory)
- NodeAgentRegistry can be initialized in the Starlette adapter (same as in LSP server)
- The EventStore SQLite DB is accessible from the Starlette process

## UX assumptions
- Mode 2 (graph) is the default/home view
- Mode 1 (node panel) opens as a slide-in drawer from the right
- The webapp is used in a browser alongside the editor, not replacing the editor
- Users expect sub-500ms event-to-ping latency (SSE is sufficient, WebSocket not required)
