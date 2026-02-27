# Remora × Datastar Alignment Report (Stario frontend external)

This report evaluates how well Remora currently aligns with the Datastar philosophy and proposes changes to make Remora easier to use as a backend service controlled via an external Stario frontend. Because Remora must stay on Python 3.13 for vLLM, Stario (Python 3.14+) cannot be installed or shipped inside the Remora runtime. Remora must rely on `datastar_py` only, while Stario runs in a separate service if used.

## Executive summary

Remora already aligns well with Datastar on core ideas: a single event stream, server-driven state, and a minimal UI that reacts to events. The current Starlette + Datastar dashboard proves the concept. The biggest gaps are not conceptual but structural: Remora exposes a Starlette app rather than a framework-agnostic “event + command” service surface, the event stream is UI-agnostic but not “UI-ready,” and there is no canonical external Stario integration kit or reference app. This makes it slightly harder to hold the system in one’s head when building a Stario frontend in a separate service.

The most impactful improvements are:

1. Introduce a framework-agnostic `RemoraService` wrapper that exposes explicit handlers and bridges `EventBus` to Datastar SSE primitives (via `datastar_py`), without any Stario dependency.
2. Publish a stable “Backend API contract” (SSE event schema, `/run` input shape, `/input` shape, error payloads).
3. Provide a Stario dashboard reference implementation as a separate project (or example), mirroring the existing Starlette dashboard.
4. Simplify the conceptual model by separating “core runtime” from “UI service” into well named, composable layers.

---

## Alignment strengths

### 1) Event-driven architecture maps cleanly to Datastar

- Remora uses a single `EventBus` to emit everything (`src/remora/event_bus.py`).
- Datastar is designed for streaming updates via SSE and patching the DOM.
- The current dashboard already streams view patches based on event changes (`src/remora/dashboard/views.py`).

Why it aligns:
- Datastar expects a continuous server-driven stream, and Remora already models state changes as events.
- The UI doesn’t need to query for state; it can render from streamed events or from a derived state object (like `DashboardState`).

### 2) “Storyboard” UI fits Remora’s graph execution

- Remora naturally moves through discrete stages (graph start, agent start, tool calls, agent completion).
- Datastar’s storyboard-style snapshot rendering (as used by Stario) can map each stage to a new DOM snapshot.

Why it aligns:
- Each event is a storyboard frame. Datastar `patch-elements` is a direct match, and external Stario frontends can use `w.patch()` to emit those patches.

### 3) Explicit inputs/outputs are already present

- Remora’s core API uses explicit parameters (`GraphExecutor.run`, `build_graph`).
- Stario handlers are explicit (`Context` in, `Writer` out) in the external frontend.

Why it aligns:
- Both systems avoid hidden global state. This makes integration conceptually clean.

### 4) Datastar already used in the shipped dashboard

- Remora uses `datastar_py` to generate patches in the existing Starlette UI.
- This provides a proven flow that an external Stario frontend can mirror.

---

## Alignment gaps and friction points

### 1) No canonical external frontend integration kit

Current state:
- Remora ships a Starlette dashboard (`src/remora/dashboard/`).
- Remora cannot ship Stario because of the Python 3.14 requirement.
- There is no canonical external Stario reference app or integration kit.

Impact:
- Users have to mentally translate Starlette + datastar_py patterns into Stario handlers (in a separate service).
- That translation adds cognitive load and can lead to inconsistent UI patterns.

### 2) Backend API contract is implicit, not explicit

Current state:
- `/subscribe`, `/events`, `/run`, `/input` exist in the Starlette dashboard.
- These routes and payload shapes aren’t formalized in one place.

Impact:
- It is harder to build an external Stario frontend without “reading the code.”
- Harder to build alternative clients or test harnesses.

### 3) Event stream is raw but not UI-typed

Current state:
- `EventBus.stream()` yields events of multiple types (Remora + structured agents).
- The Starlette dashboard derives state in `DashboardState` and patches view.

Impact:
- UI implementers must re-derive state or copy `DashboardState` logic.
- The event stream is powerful, but it’s not immediately UI-ready.

### 4) Two configurations, one UX gap

Current state:
- `remora.yaml` config (execution, bundles, model, workspace).
- UI endpoints reference config for discovery and runs.

Impact:
- Frontend can’t easily fetch “resolved config” without an explicit endpoint.
- Developers need to understand config + bundle mapping to build UI controls.

### 5) “Human input” flow exists, but lacks a typed protocol

Current state:
- `HumanInputRequestEvent` and `HumanInputResponseEvent` exist.
- `/input` accepts JSON, but shape is defined in dashboard code.

Impact:
- Frontend implementers need to know request/response structure.
- The flow is conceptually simple but not standardized for UI builders.

---

## Recommendations (high impact)

### 1) Add a framework-agnostic Datastar service layer

Create a new module (example: `src/remora/service/`) with:

- A `RemoraService` wrapper that exposes explicit handlers for `/`, `/subscribe`, `/events`, `/run`, `/input`
- Datastar SSE generation via `datastar_py` (no Stario dependency)
- `DashboardState` reuse to minimize duplicate logic
- Explicit dataclasses for request payloads (run config, input response)

Benefits:
- Reduces mental translation between Starlette + datastar_py and external frontends.
- Makes the backend service surface explicit and framework-agnostic.

### 2) Publish a backend contract document

Add a doc like `docs/REMORA_UI_API.md` with:

- SSE event schema (for `/events`)
- Request/response shapes for `/run`, `/input`
- Error payload conventions
- Example payloads and sequence diagrams

Benefits:
- Frontend implementers can build without reading server code.
- Easier to test and extend.

### 3) Provide an external Stario reference app

Create a separate Stario frontend project (or an `examples/` template that is not installed with Remora):

- Mirrors the Starlette dashboard behavior.
- Consumes Remora’s `/subscribe`, `/events`, `/run`, `/input` endpoints.
- Targets Python 3.14+ and runs as a separate service.

Benefits:
- Gives teams a ready-made Stario starting point without adding a runtime dependency.
- Keeps Remora compatible with Python 3.13 for vLLM.

### 4) Define UI-ready “derived state” helpers

Provide a helper that projects event streams into UI state:

- `DashboardState` is already doing this (`src/remora/dashboard/state.py`).
- Extract this into a reusable `EventProjector` or `StateReducer`.
- Provide snapshots as serializable dicts.

Benefits:
- External frontends can render from a clean state object.
- Fewer duplicated UI logic paths.

### 5) Offer a “RemoraService” abstraction

Conceptual simplification:

- `RemoraCore` = discovery + graph execution + event bus
- `RemoraService` = web endpoints + SSE + human input handling

Expose a stable interface:

```python
service = RemoraService(config, event_bus)
app = service.starlette_app()
```

Benefits:
- Makes Remora feel like a backend service instead of a library with a demo UI.
- Clarifies boundaries (core vs UI).

---

## Recommendations (medium impact)

### 6) Add a “resolved config” endpoint

Expose `GET /config` to return a sanitized version of `remora.yaml`:

- `bundles` mapping
- `model` defaults
- `execution` limits
- `discovery` paths

Benefits:
- External frontends can build UI controls without accessing the filesystem.

### 7) Provide “run plan preview” endpoint

Expose `POST /plan` that:

- Runs discovery and graph build only
- Returns the node list and bundle mapping

Benefits:
- Frontends can preview what will run before executing.

### 8) Formalize event stream categories

Add a top-level event “kind” to SSE JSON events:

- `graph`, `agent`, `tool`, `human`, `kernel`

Benefits:
- UI filtering and grouping becomes simpler.

---

## Recommendations (low impact)

### 9) Align naming with Datastar conventions

- Rename `/subscribe` to `/stream` or `/events/patches` for clarity.
- Keep `/events` for raw JSON, `/stream` for Datastar patches.

### 10) Bundle-level metadata for UI

Add optional fields to bundle.yaml:

- `ui_name`, `ui_description`, `ui_tags`

Benefits:
- Frontends can show bundle cards without parsing prompts.

---

## Proposed refactor map

### Phase 1 (low risk)

- Add `docs/REMORA_UI_API.md` with explicit contract.
- Extract `DashboardState` into `remora.ui.state` or `remora.ui.projector`.
- Add helper to serialize a `DashboardState` snapshot.

### Phase 2 (integration)

- Implement the framework-agnostic service layer (Datastar SSE + JSON endpoints).
- Keep the Starlette adapter as a thin shell over the service layer.
- Provide an external Stario reference app (separate project or template).

### Phase 3 (service abstraction)

- Introduce `RemoraService` as a service layer.
- Keep Starlette app as a reference adapter over the service layer.

---

## Concrete alignment improvements (code level)

### A) Datastar-first service layer + Starlette adapter

Split the UI logic into a framework-agnostic service layer:

- `src/remora/service/` with handlers that return Datastar SSE events (via `datastar_py`)
- A thin Starlette adapter that wires HTTP requests to those handlers

Reuse logic:

- Use `DashboardState` for event-derived UI state.
- Use the same `GraphExecutor` entry point.

### B) Event projection helper

Extract from `DashboardState`:

- `record(event)` stays, but expose a stable `to_dict()`.
- Create a `DashboardProjector` that can be re-used in any UI layer.

### C) Formal request dataclasses

Add dataclasses for:

- `RunRequest(target_path, bundle)`
- `InputResponse(request_id, response)`

Benefits:
- Explicit UI contract.
- Backend handler input parsing becomes clean and testable.

---

## Risks and tradeoffs

- Stario must run as a separate Python 3.14+ service, so you’ll need a deployment boundary (auth, CORS, and version coordination).
- Maintaining a Starlette adapter plus an external Stario reference app can drift; keep a shared API contract and versioned examples.
- The event stream is already flexible; standardizing it could reduce flexibility. Consider adding optional “UI normalized events” instead of changing base events.

---

## Integration boundary (Remora backend <-> external Stario frontend)

Because Stario cannot be installed in Remora’s Python 3.13 runtime, the boundary between the Remora backend and the Stario frontend must be treated as a real service interface. The goal is to make it safe, stable, and easy to reason about.

### 1) Transport and topology

- Run Remora as a backend service exposing HTTP + SSE endpoints (`/subscribe`, `/events`, `/run`, `/input`, etc).
- Run Stario as a separate service that connects to Remora over the network.
- Prefer a private network or service mesh boundary if the UI is internal (Tailscale, VPC, or docker network).
- For public access, put Remora behind a reverse proxy that can handle auth and rate limits.

### 2) Authentication and authorization

- Define who can trigger runs vs who can view events.
- Options: mTLS, API keys, or OAuth2 in front of Remora.
- If using API keys, treat `/run` and `/input` as privileged endpoints.
- If using cookies in the Stario app, avoid sending them to Remora unless you control both services.

### 3) CORS and CSRF

- If Stario and Remora are on different origins, configure CORS on the Remora service.
- For state changing endpoints (`/run`, `/input`), require an auth token in headers.
- Avoid relying on cookie-based CSRF for cross-origin calls (Datastar can send JSON bodies).

### 4) API versioning and compatibility

- Establish a versioned API contract (e.g., `/v1/subscribe`, `/v1/run`).
- Document payload shapes and event schemas (recommended in `docs/REMORA_UI_API.md`).
- When changing event shapes, add fields rather than removing them.

### 5) SSE behavior and durability

- SSE is best-effort and does not guarantee replay.
- If a UI needs history, it must reconstruct state from persisted data (or a backend snapshot).
- Consider adding a `/snapshot` endpoint for initial state, then stream deltas.
- Keep the event stream lean; avoid high-volume tool events unless the UI needs them.

### 6) Timeouts and connection limits

- SSE connections are long-lived; configure reverse proxy timeouts accordingly.
- Limit concurrent `/subscribe` connections if Remora is used by many clients.
- For heavy workloads, consider per-session streams or a fan-out layer.

### 7) Data exposure and security

- Remora events may include file paths and agent identifiers; treat them as sensitive.
- For shared or multi-tenant environments, filter events by project or graph id.
- If you expose `remora.yaml` via `/config`, remove secrets (model API keys).

### 8) Observability and tracing

- Correlate UI actions (`/run`, `/input`) to graph ids and agent ids.
- Propagate request ids from Stario to Remora via headers.
- Log SSE connection lifecycle (connect, disconnect, reconnect).

### 9) Backpressure and rate limits

- UI-triggered runs can overwhelm the model server if not limited.
- Enforce rate limits and queueing at the Remora service boundary.
- Consider a “max active graphs” limit in configuration.

### 10) Deployment strategy

- Keep Stario and Remora in separate deployable units.
- Version-lock the Stario reference app to a specific Remora API contract.
- Provide a lightweight “compatibility matrix” in docs (Remora version <-> UI version).

---

## Suggested next actions

1. Formalize the service boundary: commit to a stable Datastar SSE + JSON API contract.
2. Add a UI API contract doc to make frontend integration explicit.
3. Extract and publish event projection helpers for UI state.
4. Build an external Stario reference app that consumes the Remora service API.

---

## References (code)

- Event bus: `src/remora/event_bus.py`
- Events: `src/remora/events.py`
- Graph execution: `src/remora/executor.py`
- Dashboard state: `src/remora/dashboard/state.py`
- Starlette Datastar dashboard: `src/remora/dashboard/views.py`
- Config schema: `docs/CONFIGURATION.md`
- Installation: `docs/INSTALLATION.md`
