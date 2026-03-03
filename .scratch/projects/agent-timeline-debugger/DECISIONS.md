# Decisions — Agent Timeline Debugger

## D1: Web UI instead of Neovim UI
**Rationale**: Swimlane timeline is fundamentally a 2D visualization. Browser handles this natively — SVG/canvas, zooming, panning, hover tooltips, clickable elements. Terminal character grids would be fighting constraints. remora-demo/frontend already has all the infrastructure (GraphState, DBBridge, SSE, SVG rendering, Catppuccin CSS).
**Assumptions loaded**: ASSUMPTIONS.md — audience needs rich debugging visualization.

## D2: Server-rendered SVG (same pattern as graph view)
**Rationale**: Consistent with existing architecture. Views return plain HTML strings, testable without Stario. SSE pushes DOM patches via Datastar. No need for a client-side rendering library.
**Assumptions loaded**: Existing frontend architecture in app.py, svg.py, views/.

## D3: Separate page rather than tab in existing graph view
**Rationale**: Timeline needs full width for the time axis. Sharing space with the graph SVG would compress both. A separate `/timeline` page with its own layout is cleaner. Navigation link between the two views.
