# REMORA_DATASTAR_ALIGNMENT_REFACTOR_GUIDE

This guide is a step-by-step refactor plan for a clean-slate Remora architecture aligned with Datastar. It assumes:

- No backward compatibility is required.
- Remora runs on Python 3.13 with vLLM.
- Stario cannot be installed in Remora; Stario runs as a separate frontend service (Python 3.14+).
- No authentication or authorization is implemented in Remora (private Tailscale network).
- Remora must rely on `datastar_py` for SSE patches.

The outcome: a minimal, elegant Remora backend service with a stable SSE + JSON API and a clean core/runtime split.

---

## 0) Target architecture (what we are building)

### 0.1 Core principles

- **Single source of truth:** events in the EventBus.
- **Datastar-first UI contract:** SSE patches + JSON endpoints.
- **Framework-agnostic service layer:** UI/service logic is separate from Starlette (or any web framework).
- **Explicit data flow:** no magic global state.
- **Simplicity over compatibility:** remove legacy APIs that do not fit the new shape.

### 0.2 Layered architecture

```
remora/
  core/              # discovery, graph, execution, workspaces, event bus
  service/           # framework-agnostic handlers for API + SSE
  adapters/          # thin web adapters (starlette only)
  ui/                # event projector + state model (UI-ready)
  models/            # request/response dataclasses
  cli/               # minimal CLI wiring
```

### 0.3 Service contract (public API)

- `GET /` -> HTML shell (Datastar script + body with `data-init`)
- `GET /subscribe` -> Datastar SSE patches (patch-elements)
- `GET /events` -> raw JSON SSE events
- `POST /run` -> start a graph run (JSON)
- `POST /input` -> submit human response (JSON)
- `GET /config` -> sanitized config snapshot (JSON)
- `POST /plan` -> preview graph without executing (JSON)
- `GET /snapshot` -> UI state snapshot (JSON) (optional but recommended)

---

## 1) Create the new module layout

### Step 1.1 — Add new package structure

Create these directories:

```
src/remora/core/
src/remora/service/
src/remora/adapters/
src/remora/ui/
src/remora/models/
src/remora/cli/
```

### Step 1.2 — Move core runtime into `core/`

Move (or re-implement cleanly) into `src/remora/core/`:

- `event_bus.py`
- `events.py`
- `discovery.py`
- `graph.py`
- `executor.py`
- `context.py`
- `workspace.py`
- `cairn_bridge.py`
- `cairn_externals.py`
- `tools/grail.py`
- `checkpoint.py`
- `errors.py`
- `config.py`

Acceptance check:
- Core modules have no HTTP or framework dependencies.

### Step 1.3 — Clean imports and public API

Create `src/remora/__init__.py` as a clean public API surface:

- Export core types only.
- Do not export dashboard or web adapter details.

Acceptance check:
- `import remora` is light and framework-free.

---

## 2) Define request/response models

### Step 2.1 — Add dataclasses in `src/remora/models/`

Create:

- `RunRequest`
- `RunResponse`
- `InputResponse`
- `PlanRequest`
- `PlanResponse`
- `ConfigSnapshot`

All models should be `@dataclass(slots=True)` and JSON-serializable.

Acceptance check:
- Each model has a `.to_dict()` (or standard conversion helper).
- Models are used by service handlers (no ad hoc dicts).

---

## 3) Build the UI state projector

### Step 3.1 — Introduce `ui/projector.py`

Create a reusable projector to convert events -> UI state:

- Start with existing `DashboardState` logic.
- Rename to `UiStateProjector` or `EventProjector`.
- Provide:
  - `record(event)`
  - `snapshot()` -> dict
  - `reset()`

Acceptance check:
- The UI state is stable and JSON-serializable.
- No UI framework assumptions in the projector.

---

## 4) Implement the service layer (framework-agnostic)

### Step 4.1 — Create `service/handlers.py`

Handlers are plain async functions. They accept explicit inputs and return explicit outputs.

Example shape:

```python
async def handle_run(request: RunRequest, deps: ServiceDeps) -> RunResponse:
    ...
```

`ServiceDeps` should include:

- `event_bus`
- `config`
- `project_root`
- `projector`
- `executor_factory`

### Step 4.2 — Add Datastar SSE generator helpers

Add `service/datastar.py` with helper functions using `datastar_py`:

- `render_shell()` -> HTML shell with Datastar script
- `render_patch(state)` -> SSE patch-elements event
- `render_signals(data)` -> SSE patch-signals event

Acceptance check:
- The service layer can produce Datastar events without Starlette.

### Step 4.3 — Define a stable service API surface

Create `service/api.py`:

- `RemoraService` class exposing methods:
  - `index_html()`
  - `subscribe_stream()` (async generator)
  - `events_stream()` (async generator)
  - `run(request)`
  - `input(request)`
  - `plan(request)`
  - `config_snapshot()`
  - `ui_snapshot()`

Acceptance check:
- The service layer can be unit tested without HTTP.

---

## 5) Build the Starlette adapter

### Step 5.1 — Create `adapters/starlette.py`

This module maps HTTP requests to service methods:

- Starlette routes call `RemoraService` methods.
- SSE responses are `StreamingResponse` for raw JSON or `DatastarResponse` for patch events.

Acceptance check:
- No service logic is duplicated in the adapter.

### Step 5.2 — Remove the old dashboard

- Delete or archive `src/remora/dashboard/`.
- Replace it with the new adapter + service layer.

Acceptance check:
- The only UI layer in Remora is the adapter to `RemoraService`.

---

## 6) Update CLI to use the service

### Step 6.1 — Minimal CLI

Refactor CLI to:

- Start the Starlette adapter
- Provide simple run commands (optional)

Acceptance check:
- The CLI depends on the service layer, not the old dashboard code.

---

## 7) Define the API contract doc

### Step 7.1 — Create `docs/REMORA_UI_API.md`

This should include:

- Endpoint list with payloads
- Example JSON
- SSE event format
- UI snapshot schema

Acceptance check:
- A frontend developer can build without reading server code.

---

## 8) Update configuration system

### Step 8.1 — Introduce `ConfigSnapshot`

`ConfigSnapshot` must:

- Strip secrets (API keys)
- Include only fields needed by UI

### Step 8.2 — Add endpoint in service

`GET /config` returns the sanitized snapshot.

Acceptance check:
- No secrets are exposed.

---

## 9) Run plan preview

### Step 9.1 — Add plan handler

`POST /plan` should:

- Run discovery
- Build graph
- Return node list + bundle mapping
- Never execute agents

Acceptance check:
- Safe to call in a UI for preview.

---

## 10) Human input flow

### Step 10.1 — Standardize request/response

- `HumanInputRequestEvent` includes `request_id`, `question`, `options`.
- `POST /input` accepts `{request_id, response}`.

Acceptance check:
- UI can reliably render questions and submit answers.

---

## 11) Event stream normalization

### Step 11.1 — Add UI event envelopes

Wrap events for UI consumption:

```
{
  "kind": "agent",
  "type": "AgentCompleteEvent",
  "graph_id": "...",
  "agent_id": "...",
  "timestamp": ...,
  "payload": { ... }
}
```

Acceptance check:
- UI can filter by `kind` without parsing event class names.

---

## 12) External Stario reference app (separate repo)

### Step 12.1 — Define the interface

Create a small Stario app that:

- Connects to `GET /subscribe`
- Uses `/run` and `/input`
- Renders a basic dashboard

Important:
- This app is not part of Remora runtime.
- Treat it as a separate project or template.

Acceptance check:
- Works against the Remora service API.

---

## 13) Testing strategy

### Unit tests

- `EventBus` streams
- `UiStateProjector` snapshot output
- Service handlers (run/plan/input)

### Integration tests

- Starlette adapter endpoints
- SSE streaming smoke test

Acceptance check:
- All unit tests pass without vLLM.
- Integration tests can be skipped when vLLM is absent.

---

## 14) Cleanup and final checklist

### Step 14.1 — Remove dead code

Delete any:

- Old dashboard views
- Legacy CLI commands
- Unused exports

### Step 14.2 — Documentation

- Update `README.md` with the new architecture.
- Add a short “How to run service” section.

### Step 14.3 — Final acceptance

- Remora runs on Python 3.13.
- Service endpoints work end-to-end.
- External Stario app can drive runs and display updates.
- No internal Stario dependency remains.

---

## Appendix: Minimal service flow

1. UI loads `/` and initializes `data-init` to `/subscribe`.
2. UI receives Datastar patches for state updates.
3. User triggers `/run` (graph execution starts).
4. EventBus emits events; projector updates UI state; `/subscribe` sends patches.
5. If human input is needed, UI posts `/input`.

---

## Handoff summary

If you are a junior developer, you can follow this guide in order. Do not build new features while refactoring; focus on restructuring the system to match this architecture. Ask for help only if you are unsure how to structure a layer or where to place a file.
