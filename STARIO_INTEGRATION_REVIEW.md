# Stario Integration Review

## Summary
- This memo catalogs how Stario already solves the real-time hypermedia problem and then aligns those pieces with the Remora dashboard/event bus stack that currently lives inside `demo/dashboard`.
- Stario’s Python-native SSE + DOM patching pipeline (`stario/README.md:17-33`) mirrors the live event stream Remora already emits, so it can plausibly replace the existing custom WebSocket + JS implementation with a datastar-driven UI backed by the same `EventBus` instance.

## Stario Capabilities
- **Real-time-first stack**: Stario treats every connection as an ongoing conversation and streams DOM patches (`patch`, `signals`, `script`, `redirect`, `remove`) so the client only receives the minimal updates it needs (`stario/datastar/__init__.py:1-49`, `stario/datastar/sse.py:21-154`).
- **Declarative reactivity**: `data.signals`, `data.on`, `data.bind`, and `data.init` produce the `data-*` attributes datastar understands, while action builders like `at.get`/`at.post` encode structured fetches for backend routes (`stario/datastar/attributes.py:56-114`, `stario/datastar/actions.py:20-137`).
- **Stream helpers**: `Writer.alive`, `Writer.patch`, and `Writer.sync` coordinate the SSE handshake, long-lived loop, and compressed payloads so you never worry about buffering or chunking (`stario/http/writer.py:80-160`).
- **Minimal server scaffold**: The `Stario` router already offers host-based routing, tracing, and graceful shutdown, meaning the only code you need to write is the dashboard view/handlers that touch the shared `EventBus` (`stario/http/app.py:32-198`).
- **Practical reference app**: `examples/chat` demonstrates the pattern: render a datastar view, open `/subscribe`, patch on relay events, and parse signals with dataclasses (`stario/examples/chat/app/views.py:67-296`, `stario/examples/chat/app/handlers.py:61-182`).

## Remora Snapshot
- **Event Bus core**: `EventBus` publishes typed `Event` objects with category/action/payload metadata and exposes `stream()` for SSE/WebSocket consumption (`src/remora/event_bus.py:1-288`).
- **Dashboard today**: `demo/dashboard/app.py` servers `/events`, `/ws/events`, and the blocked-agent API, while `demo/dashboard/static/dashboard.js` replays each event by mutating the DOM, tracking blocked agents, and POSTing responses (`demo/dashboard/app.py:88-205`, `demo/dashboard/static/dashboard.js:1-288`).
- **Interactive coordinator**: `WorkspaceInboxCoordinator` polls each workspace for `outbox:question:*` entries, emits `agent:blocked`, and writes answers back before emitting `agent:resumed` (`src/remora/interactive/coordinator.py:27-115`).
- **Architecture context**: The entire product already leans on event-driven SSE dashboards and shared workspaces, so replacing the frontend framework is primarily a UI-level change (`docs/ARCHITECTURE.md:1-86`).

## Integration Opportunities
- **Stream the EventBus with Stario**: A Stario handler can `async for event in event_bus.stream()` inside `Writer.alive()` and re-render the dashboard view, calling `w.patch`/`w.sync` whenever the event log, blocked list, or progress status mutates (`stario/http/writer.py:80-160`, `stario/examples/chat/app/handlers.py:61-182`).
- **Render the dashboard as a datastar view**: Store events, blocked agents, agent status, and results inside `data.signals`, and patch the appropriate containers instead of manually touching DOM nodes. The datastar runtime keeps client state synchronized so each SSE patch only replaces the fragments that changed (`stario/examples/chat/app/views.py:67-296`).
- **Signal-driven actions**: Buttons/forms can use `data.on` plus `at.post`/`at.get` to send structured answers, and `Context.signals` with a dataclass lets the handler validate the answer before forwarding it to `WorkspaceInboxCoordinator.respond` (`stario/datastar/actions.py:20-137`, `stario/examples/chat/app/handlers.py:38-117`, `src/remora/interactive/coordinator.py:27-115`).
- **Reactive metrics**: Use `w.sync` to update signal values such as agent counts, result summaries, and blocked-question counts so the client can use `$signal` expressions for progress bars, badges, or filters without touching raw JavaScript.
- **Optional aux systems**: If you need finer-grained diffusion, `Relay` (used in the chat example) can distribute domain-specific notifications inside the Stario app, but the shared `EventBus` already provides the worldwide stream.

## Proposed Dashboard Architecture
1. **Views**: Build a `dashboard_view(events, blocked, statuses, results)` that renders the event log, blocked-agent cards, agent status list, results, and a progress bar. The view can include `data.signals(...)` (with `ifmissing=True`) to seed client state and `data.init(at.get("/events"))` to open the SSE stream on load.
2. **Routes**: 
   - `/` delivers the HTML view. 
   - `/events` runs a Stario handler that loops over `EventBus.stream()`, updates in-memory aggregates (recent events, blocked questions, last progress tick), and calls `w.patch(dashboard_view(...))`/`w.sync(...)` for incremental updates.
   - `/agent/{agent_id}/respond` accepts signals/JSON from the datastar form, looks up the pending question/msg_id, and calls `WorkspaceInboxCoordinator.respond(agent_id, msg_id, answer, workspace)` to unblock the agent and emit `agent:resumed`.
3. **Client wiring**: Use `data.on("click", at.post(...))` for buttons, `data.bind` for input fields, and `data.on("load", ...)` to auto-scroll the event log or results panel. `data.attr` helpers allow reactive classes, disabled states, and indicator badges.
4. **State management**: Keep a bounded deque of events (e.g., last 200) plus a map of blocked questions to display; these aggregates feed the view and are entirely computed server-side before each patch. Use `data.signals`/`Writer.sync` to push signal updates for counts/progress.
5. **Concurrency**: Each SSE client re-renders the same view, but all clients share the same `EventBus`. Stario’s `Writer.alive` ensures the loop breaks cleanly when the client disconnects.

## Risks & Considerations
- **Python version**: Stario requires Python 3.14+ while Remora currently targets `>=3.13` (`pyproject.toml:6`), so the runtime has to upgrade before we can deploy the new UI stack.
- **Workspace context for responses**: `WorkspaceInboxCoordinator.respond` needs the workspace/KV handle for the agent that asked the question. The dashboard must either receive that reference in the event payload or look it up via some coordinator map before writing the answer.
- **Deployment model**: Stario runs its own `httptools` server. We can either replace the FastAPI dashboard server with Stario entirely (shutting down `/events`, `/ws/events`, `/static`) or run it as a sidecar and proxy the assets/events from the existing Uvicorn process.
- **Data volume**: Streaming noisy `tool` or `model` events will increase SSE traffic. Consider filtering the `EventBus` stream inside the handler (e.g., only `agent:*` and `graph:*`) before re-rendering.

## Next Steps
1. Sketch the datastar-driven dashboard view (event log, blocked cards, agent list, results, progress) and identify the signals it needs.
2. Implement Stario routes (`/`, `/events`, `/agent/{agent_id}/respond`) that use `EventBus`, `Writer`, and `WorkspaceInboxCoordinator` as outlined above.
3. Wire the client-side hooks with `data.on`, `at.post`, `data.bind`, and background `data.init` for the SSE subscribe path.
4. Update the build/deploy flow to pin Python to 3.14+ and ensure the UI process shares the same event bus instance or IPC channel.
5. Add smoke tests that connect to `/events`, verify event patches arrive, and post responses to confirm `agent:resumed` is emitted.
