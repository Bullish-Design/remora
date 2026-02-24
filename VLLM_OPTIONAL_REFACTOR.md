# VLLM Optional Dependency Refactoring Guide

## Overview

The Stario dashboard has been extracted into its own reusable library, which now needs to install just enough of Remora to playback the event stream, stream question/response state, and drive the interactive coordinator without pulling the heavy `vllm`/`structured-agents` stack on Python 3.14. Today, any import of `remora` immediately drags `structured-agents` (and transitively `vllm` + `xgrammar`) because the package exposes the Grail bundle helpers and the CLI already imports `structured_agents`. That tight coupling prevents the new Stario frontend library from installing Remora as a dependency without also installing Python 3.13-only packages.

The goal of this guide is to outline how to refactor Remora so the standalone Stario library can

- install a `remora[frontend]` slice that provides `EventBus`, `WorkspaceInboxCoordinator`, and the lightweight dashboard helpers, while remaining Python 3.14 compatible;
- keep the backend workflow (`structured-agents`, `vllm`, `openai`, etc.) behind a separate `remora[backend]` (or `remora[full]`) extra so users who need local inference can still run it on Python ≤ 3.13;
- update the CLI, docs, and tests so they work with optional backend deps and gracefully notify users when those extras are missing.

## Current architecture recap

1. **Remora core** – `src/remora/event_bus.py`, `remora.interactive`, and the workspace/KV abstractions provide the event stream and question/answer plumbing that every consumer relies on.
2. **CLI** – `src/remora/cli.py` currently imports `structured_agents` to validate Grail bundles in `list-agents` and uses `openai` to query remote models even though it only communicates over HTTP (`remora.client`).
3. **Structured-agents** – this dependency is required when CLI commands load bundles, when tests exercise Grail kernels, or when scripts like `scripts/validate_agents.py` run.
4. **Stario dashboard library** – lives outside this repo but depends on Remora for `EventBus` + `WorkspaceInboxCoordinator`. It now needs Remora to expose a minimal frontend surface that does not import `structured-agents`.

## Key constraint: structured-agents bundles vLLM

`structured_agents/__init__.py` (see `.context/structured-agents/src/structured_agents/__init__.py`) unconditionally invokes:

```python
from structured_agents.deps import require_xgrammar_and_vllm

require_xgrammar_and_vllm()
```

`require_xgrammar_and_vllm()` tries to import `vllm` and `xgrammar`, raising a `RuntimeError` if either is missing. Because `remora` currently lists `structured-agents` under `[project].dependencies`, any import of `structured_agents` (even inside commands that are unrelated to the new Stario library) forces `pip` to install `vllm`, binding `remora` to Python ≤ 3.13. To allow the Stario frontend library to install Remora on Python 3.14, we must keep `structured-agents` behind an optional backend extra and expose only the interfaces the frontend needs.

## Goals

1. **Split the dependency graph** – the base `remora` package should remain Python 3.13+ and include only things the frontend, CLI, and headless orchestrator require. `structured-agents`, `vllm`, `openai`, and other Python ≤ 3.13 packages live behind `[project.optional-dependencies.backend]` or `full`.
2. **Publish `remora[frontend]`** – this extra exposes `EventBus`, `WorkspaceInboxCoordinator`, and the dashboard helpers that the Stario library consumes, along with the runtime dependencies they require (e.g., `stario`, `uvicorn`, `httpx`).
3. **Keep CLI/scripts functional** – commands like `list-agents`, `validate-agents`, and any backend tooling should lazily import optional dependencies and show friendly guidance when `remora[backend]` is missing.
4. **Document installation paths** – README, `docs/INSTALLATION.md`, and this guide must explain how the Stario library uses `remora[frontend]`, when to install `remora[backend]`, and how to combine both when needed.

## Required modifications

### 1. `pyproject.toml` – split frontend/back dependencies

```toml
[project]
name = "remora"
version = "0.1.0"
requires-python = ">=3.13"

[project.dependencies]
# Keep only the core runtime dependencies the backend and frontend both share.
```

```toml
[project.optional-dependencies]
frontend = [
  # Stario (Python 3.14+) and lightweight HTTP tooling for the dashboard library.
  "stario>=0.1.0",
  "uvicorn>=0.23",
  "httpx>=0.27",
]
backend = [
  # vLLM stack for when cron/CLI wants to validate/run kernels locally.
  "structured-agents>=0.2",
  "vllm>=0.6",
  "xgrammar>=0.1",
  "openai>=1.0",
]
full = [
  # Convenience extra that installs both slices.
  "frontend",
  "backend",
]
```

The `frontend` extra targets Python 3.14 because `stario` currently does. Installing `remora[frontend]` on Python 3.13 will naturally fail with a clear pip error from `stario`. Consumers who need both the frontend library and backend inference should install `remora[full]` or request the extras explicitly.

### 2. Expose a minimal frontend module for downstream libraries

Create `src/remora/frontend/__init__.py` (or similar) that re-exports the interfaces the Stario library needs:

- `EventBus`, `Event`, and `get_event_bus()` so the dashboard can stream the global event log.
- `WorkspaceInboxCoordinator` (plus any workspace registry helpers) so the dashboard can write answers back to blocking agents.
- A `DashboardState`/`EventAggregator` class and `dashboard_view()` helpers (ported from `demo/stario_dashboard`) that compute recent events, blocked questions, progress counters, and results without importing `structured-agents`.
- A `register_routes(app: Stario, event_bus: EventBus)` helper that wires up `/`, `/events`, and `/agent/{agent_id}/respond` to the shared state + coordinator. This helper should live entirely in the frontend module so downstream libraries can plug it in without duplicating logic.

Because this module never imports `structured-agents`, it can be part of the `frontend` extra and remain Python 3.14 compatible.

### 3. Guard optional imports in CLI, scripts, and tests

- **`src/remora/cli.py`**
  - Move `from structured_agents import load_bundle` and any `import openai` calls inside the `list-agents` command or `_fetch_models` helper.
  - Catch `ImportError`/`RuntimeError` and print a warning like _“Grail validation skipped: install `remora[backend]` to enable `structured-agents`”_.
  - `_fetch_models` should handle missing `openai` by returning an empty set or `None` so the CLI still runs in frontend-only installs.
- **`scripts/validate_agents.py`**, any backend utilities, and backend tests
  - Wrap backend-specific imports with `import importlib` or `pytest.importorskip("structured_agents")` so the modules can be imported without installing the backend extra.
  - Consider adding a helper such as `remora.backend.require_backend_extra()` that raises a descriptive error when backend functionality is requested but not installed.

### 4. Documentation & user guidance

- Create or expand `docs/INSTALLATION.md` to outline three workflows:
  1. `pip install remora[frontend]` for downstream dashboards (like the Stario library) that only need the event stream and interactive bridge.
  2. `pip install remora[backend]` for developers running kernels locally and validating Grail bundles (requires `vllm`).
  3. `pip install remora[full]` for users who need both capabilities in the same environment.
- Mention that the Stario library should install `remora[frontend]`, that it is Python 3.14-only, and how it interacts with `EventBus` + `WorkspaceInboxCoordinator` (link to `STARIO_INTEGRATION_REVIEW.md`).
- Update README and the VLLM guide to emphasize that Remora now communicates with a running vLLM server over HTTP and that frontend-only libraries do not import `structured-agents`.
- Clarify which scripts/commands continue to need the backend extra and provide instructions on how to opt into it.

### 5. Testing updates

- Guard backend-focused acceptance/integration tests with `pytest.importorskip("structured_agents")` so frontend installs can run the remaining suites.
- Add a new smoke test that installs `remora[frontend]` and ensures the exported frontend helpers can register routes and stream events (mock `stario` if needed).
- Consider adding CI jobs for both extras: one running on Python 3.14/`remora[frontend]` and another on Python 3.13/`remora[backend]`.

## Frontend interaction plan (Stario library + Remora)

The standalone Stario dashboard library will rely on the shared `remora.frontend` helpers and the exported interfaces:

1. Import `event_bus = remora.frontend.get_event_bus()` plus the `DashboardState` aggregator.
2. Use `dashboard_view(state)` to render the HTML view that seeds `data.signals` with `events`, `blocked`, `progress`, and `results`, and that calls `data.init(at.get('/events'))` to open the SSE stream.
3. Stream updates from `/events`:

```python
from stario import Writer

async with Writer.alive(event_bus.stream()) as stream:
    async for event in stream:
        state.record(event)
        w.patch(dashboard_view(state))
        w.sync(state.get_signals())
```

4. Accept user answers through the `/agent/{agent_id}/respond` handler provided by `register_routes`, parse `signals`, look up the workspace registry, and call `WorkspaceInboxCoordinator.respond(...)`. When the workspace is missing, return `400` so clients can reload.
5. Keep the dashboard state and workspace registry in memory so every SSE client sees the same aggregated timeline.

Because none of this code touches `structured-agents`, the Stario library can stay on Python 3.14. Backend users who need local inference simply install `remora[backend]`, start a vLLM server, and keep consuming the same `EventBus` where the dashboards (Stario or otherwise) stream updates.

## Implementation order

1. **Dependency split (packaging)**
   - Move `structured-agents`, `openai`, `vllm`, and `xgrammar` to `[project.optional-dependencies.backend]`.
   - Add the `frontend` extra with `stario`, `uvicorn`, and `httpx`, plus a `full` meta extra.
   - Update documentation, CI, and lockfiles to reflect the new extras.
2. **Exposed frontend module**
   - Add `src/remora/frontend` with the shared `EventBus`, `WorkspaceInboxCoordinator`, `DashboardState`, and route helpers.
   - Make the Stario library depend on `remora[frontend]` and reuse these helpers.
3. **CLI/script guard rails**
   - Lazy-import backend dependencies, provide fallbacks, and emit helpful messages when extras are missing.
   - Keep backend scripts working by adding helper checks or optional imports.
4. **Documentation + testing**
   - Write `docs/INSTALLATION.md`, update README/VLLM guide, and reference this doc.
   - Add smoke tests/CI coverage to ensure both extras remain functional.

## Compatibility matrix

| Installation | Python | Includes `structured-agents`/`vllm` | Includes `stario` | Enables Stario library | Enables backend inference |
|--------------|--------|--------------------------------------|--------------------|------------------------|----------------------------|
| `remora` | >=3.13 | No | No | No | CLI works but backend features are disabled |
| `remora[frontend]` | >=3.14 | No | Yes | ✅ (exports Styled helpers + SSE routes) | Backend disabled (no `structured-agents`) |
| `remora[backend]` | >=3.13 | Yes | No | Dashboard library can still use exported frontend helpers | ✅ (local kernels + validation) |
| `remora[full]` | >=3.14 (frontend) + >=3.13 (backend) | Yes | Yes | ✅ | ✅ |

## Summary

By splitting the dependency surface into frontend and backend extras, exposing a dedicated `remora.frontend` API, and guarding backend imports, the standalone Stario library can now install `remora[frontend]` on Python 3.14 and interact with the backend through the shared event bus and coordinator. Backend developers retain access to `structured-agents`, `vllm`, and the CLI grail tooling via the `backend` extra, while documentation (see `docs/INSTALLATION.md`) and tests clearly describe the new install paths.
