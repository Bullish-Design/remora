# Stario MVP Demo Concept

## Objective
- Build a lightweight Stario-powered dashboard that mirrors the existing Remora event-first UI but uses datastar patches instead of bespoke JavaScript. The goal is to prove out the SSE + reactive signal model while keeping the same `EventBus` + `WorkspaceInboxCoordinator` plumbing we already rely on.

## Core Components
1. **Event stream source** – Reuse `remora.event_bus.EventBus.stream()` as the single source of truth for agent, graph, and tool events (`src/remora/event_bus.py:1-288`).
2. **Interactive bridge** – Keep `WorkspaceInboxCoordinator` handling `outbox:question:*` polling and use its `respond` helper to write answers when users post from the Stario form (`src/remora/interactive/coordinator.py:27-115`).
3. **Stario handlers** – Build a Stario application similar to `examples/chat` that renders the dashboard view and streams patches via SSE (`stario/examples/chat/app/views.py:67-296`, `stario/examples/chat/app/handlers.py:61-182`).
4. **Signals + actions** – Use `data.signals`, `data.on`, and `at.post` to keep client state in sync and trigger backend routes without custom frontend JS (`stario/datastar/attributes.py:56-114`, `stario/datastar/actions.py:20-137`).

## Demo Flow
1. **Initial load (`GET /`)**
   - Render `dashboard_view(...)` (HTML shell + datastar runtime asset) with `data.signals` seeding the client with:
     - `events` (bounded list of recent `Event` models)
     - `blocked` map keyed by `agent_id:msg_id`
     - `agentStates` map of `agent_id → {state, label}`
     - `results` list of completed agent summaries
     - `progress` metrics (`total`, `completed` counts)
   - Include `data.init(at.get("/events"))` so the client immediately opens the SSE stream.
2. **Event stream (`GET /events`)**
   - Handler accepts shared `EventBus`, enters `async for event in event_bus.stream()` inside `w.alive()` (`stario/http/writer.py:80-160`).
   - Maintain server-side aggregates (simulate `dashboard.js` state) and `w.patch(dashboard_view(...))` whenever the aggregates change. Use `w.sync` to update `data.signals` for counts so the client can easily reference `$progress.completed`.
   - Filter events to focus on `agent:*` and `graph:*` to keep payload size manageable, but expose configuration to include `tool:*` or `model:*` if desired.
3. **Respond endpoint (`POST /agent/{agent_id}/respond`)**
   - Expect datastar signal payload (client uses `data.on("submit", at.post(...))` from the response card).
   - Parse signals via `Context.signals` into a dataclass containing `answer`, `msg_id`, `agent_id`, maybe `question`, and forward to `WorkspaceInboxCoordinator.respond(...)`.
   - After writing to KV, emit `agent:resumed` so the SSE patch loop naturally updates the blocked list.

## Dashboard View Sketch
- **Layout**: event stream column, blocked question cards, agent status list, results feed, and summary progress bar.
- **Event log** renders `events` signal with DOM patching that keeps newest events on top (similar to how `dashboard.js` accumulates events). Use `data.on("load", ...)` to auto-scroll if needed.
- **Blocked cards** show question text, optional dropdown for `options`, and a `Submit` button wired via `data.on("click", at.post(...))`. Each card includes hidden signals for `msg_id`/`agent_id` so the handler knows what to respond to.
- **Agent status list** uses `$agentStates` to render badges with reactive classes via `data.class_(...)`. Each state update comes from `w.sync`.
- **Results feed** shows latest completions with timestamps—rendered from `results` signal.
- **Progress bar** binds `width` and text to `$progress.completed / $progress.total`, all updated via `Writer.sync`.

## Signal Definitions
| Signal | Description |
| --- | --- |
| `events` | Bounded array of JSON-ready event dicts (id, timestamp, category, action, payload). Used to re-render the log. |
| `blocked` | List of {agent_id, question, options, msg_id} representing current `WorkspaceInboxCoordinator` questions. |
| `agentStates` | Dict keyed by agent_id with `{state, displayName}` to keep the status column reactive. |
| `progress` | `{total: int, completed: int}` to drive the progress bar and summary text. |
| `results` | Recent completion payloads (result text, agent_id, timestamp) fed into the results card. |
| `responseDraft` | Per-card memo storing the typed answer for a blocked agent; the inputs bind to this via `data.bind`. |

## API Contracts
- `/` (GET): returns `Html` view with datastar assets loaded (use `asset(...)` for fingerprints). Similar to `stario/examples/chat/app/views.py:45-96`. 
- `/events` (GET): SSE stream patching the view. Template: 
  ```python
  async def events(c: Context, w: Writer):
      event_bus = get_event_bus()
      async with w.alive(event_bus.stream()) as stream:
          async for event in stream:
              aggregates.record(event)
              w.patch(dashboard_view(...))
              w.sync(aggregate_signals)
  ```
- `/agent/{agent_id}/respond` (POST): handles responses. Use dataclass like `RespondSignals` (fields: `agent_id`, `msg_id`, `answer`, `question`) and validate via `await c.signals(RespondSignals)` before calling the coordinator.

## Implementation Steps
1. **Port HTML view to datastar** – Rebuild the dashboard layout inside `stario/html` helpers, exposing the same sections from `demo/dashboard/static/dashboard.js:1-288`.
2. **Build aggregator service** – Server-side singleton that tracks the last 200 events, active blocked questions, agent state map, and results history; share it between `/` and `/events` handlers. Consider an async lock if multiple SSE clients open simultaneously.
3. **Connect to Remora core** – Pass `get_event_bus()` and a `WorkspaceInboxCoordinator` (or a facade) into the Stario app so the handlers can publish/log into the shared bus and respond to blocked agents.
4. **Signal wiring** – Use `data.bind` for response inputs, `data.on("click", at.post(...))` for send buttons, and `data.init(at.get("/events"))` or `data.init(at.get("/subscribe"))` to open the SSE pipeline.
5. **Testing** – Add a smoke test hitting `/events`, verifying SSE frames contain `datastar-patch-elements`, and posting a response triggers `agent:resumed` via the event bus.

## Risks & Mitigations
- **Python requirement**: Stario needs 3.14+; we must bump Remora’s runtime target (`pyproject.toml:6-34`). Lock the new requirement before shipping the demo.
- **Event duplication**: `EventBus.stream()` is global; ensure aggregates avoid re-sending older events for a single client (maybe track the last event ID processed per stream).
- **Workspace references**: The dashboard needs to know which workspace to write to when responding. Either embed `workspace_id`/`msg_id` into the blocked events or maintain an in-memory map from agent_id to workspace reference via the coordinator.
- **Server concurrency**: Stario’s `w.alive()` loops must handle multiple simultaneous clients; ensure aggregator updates are thread-safe (use `asyncio.Lock` or copy-On-write data structures).

## Success Criteria
- SSE stream updates the view without custom JS DOM logic (patch-only updates). 
- Blocked agent questions appear and can be answered via the datastar form, leading to `agent:resumed` events. 
- Event log, status list, and progress bar remain accurate even with multiple SSE clients. 
- Demo runs on the updated Python runtime and reuses the existing `EventBus`/`WorkspaceInboxCoordinator` without duplicating state sources.
