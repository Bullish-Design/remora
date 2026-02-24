# VLLM Optional Dependency Refactoring Guide

## Overview

We want Remora to keep delivering the same agent orchestration and CLI features while enabling a pure `python3.14` frontend process (the Stario dashboard) that only needs the event stream, the interactive bridge, and the basic workspace state. Today Remora pulls in `structured-agents` (and transitively `vllm` + `xgrammar`) at import time even when the UI/dashboard is the only component running: every package that touches `structured_agents` hits `structured_agents/__init__.py`, which invokes `require_xgrammar_and_vllm()` and immediately raises unless both dependencies are installed.

The goal of this guide is to outline a refactor that:

- makes the vLLM dependency chain optional so frontend-only installs never touch `structured-agents`/`vllm`,
- introduces a `remora[frontend]` installation slice that bundles the Stario dashboard and its runtime dependencies (Python 3.14 only), and
- keeps the `remora[backend]` slice (or `remora[full]`) available for users who want to run the full agent graph + vLLM server locally.

## Current architecture recap

1. **Remora core** – `src/remora/event_bus.py`, `remora.interactive`, and the workspace/KV abstractions provide the event stream and question/answer plumbing that every UI (dashboard, CLI, remote) relies on.
2. **CLI** – `src/remora/cli.py` still imports `structured_agents` to validate Grail bundles in `list-agents` and uses `openai` to check the remote vLLM model list, but it talks to the vLLM server via HTTP only (`remora.client`).
3. **Structured-agents** – this dependency plugs into Remora when the CLI or any tests try to load agent bundles or run a kernel (see `scripts/validate_agents.py`, `tests/acceptance`, and `demo/dashboard`).
4. **Stario dashboard** – `scripts/remora_dashboard.py` and `demo/stario_dashboard` connect to `remora.event_bus.EventBus` and `remora.interactive.WorkspaceInboxCoordinator` to stream events and post user answers. They never need `structured-agents` by themselves but cannot run today because `remora` (the package) presently installs the heavy `structured-agents` tree that drags in `vllm`/`xgrammar`.

## Key constraint: structured-agents bundles vLLM

`structured_agents/__init__.py` (see `.context/structured-agents/src/structured_agents/__init__.py`) immediately calls:

```python
from structured_agents.deps import require_xgrammar_and_vllm

require_xgrammar_and_vllm()
```

That helper attempts to import `vllm` and `xgrammar` and raises a `RuntimeError` if either is missing. Because `remora` currently lists `structured-agents` under `[project].dependencies`, any import of `structured_agents` (even in CLI commands that are unused by the frontend) forces `pip` to install `vllm` and binds `remora` to Python <= 3.13. To let frontend-only consumers install `remora[frontend]` under Python 3.14, we must stop importing `structured_agents` from modules that the frontend touches and move the package into an optional `backend` extra.

## Goals

1. **Split dependency graph** – base Remora (without extras) should be Python 3.13+ and include only the pieces the frontend, CLI, and headless orchestrator truly need. `structured-agents`, `vllm`, `openai`, and any other packages that only support Python ≤ 3.13 live behind a `[project.optional-dependencies.backend]` (or `full`) extra.
2. **Publish `remora[frontend]`** – this extra pulls in Stario, its HTTP server, and any UI-specific helpers so the Stario dashboard can run on Python 3.14 without dragging in the backend stack.
3. **Keep CLI/scripts functional** – commands like `list-agents`, `validate-agents`, and `remora-dashboard` should import optional dependencies lazily and emit clear guidance when those extras are missing.
4. **Document installation paths** – README and a new `docs/INSTALLATION.md` guide should spell out when to install `[frontend]`, `[backend]`, or both, covering both CLI-based agent runs and the Stario UI.

## Required modifications

### 1. `pyproject.toml` – split frontend/back dependencies

```toml
[project]
name = "remora"
version = "0.1.0"
requires-python = ">=3.13"

[project.dependencies]
# core runtime remains but drops `structured-agents` and `openai`
# (openai moves to backend so CLI model probing stays optional)
```

```toml
[project.optional-dependencies]
frontend = [
  # Stario (Python 3.14+) + lightweight web server for the dashboard
  "stario>=0.1.0",
  "uvicorn>=0.23",
]
backend = [
  # vLLM stack used whenever Remora orchestrates kernels locally
  "structured-agents>=0.2",
  "vllm>=0.6",
  "xgrammar>=0.1",
  "openai>=1.0",
]
full = [
  # For convenience: installs both slices
  "frontend", 
  "backend",
]
```

The `frontend` extra requires Python 3.14 because `stario` currently targets that runtime. Any attempt to install `remora[frontend]` on 3.13 will fail with a clear error from pip/`stario`, which is expected behavior. Consumers who need to run both the dashboard and the backend should install `remora[full]` or explicitly request multiple extras.

### 2. Guard optional imports in CLI, scripts, and tests

- **`src/remora/cli.py`**
  - Move `from structured_agents import load_bundle` and any `import openai` calls inside the `list-agents` command or `_fetch_models` helper.
  - Catch `ImportError`/`RuntimeError` and print a warning like: _“Grail validation skipped: install `remora[backend]` to enable `structured-agents`”_.
  - `_fetch_models` should gracefully handle `openai` missing (no backend extra) by returning an empty set.
- **`scripts/remora_dashboard.py`**
  - Delay `from stario import Stario` until inside `main()` and raise a descriptive `RuntimeError` if `stario` is unavailable: _“Run `pip install 'remora[frontend]'` or add Stario to your environment before starting the dashboard.”_
- **`scripts/validate_agents.py`** + **deprecated event bridge** + **tests**
  - Wrap `from structured_agents import ...` with `import importlib`/`pytest.importorskip` so the script can still be imported even when the backend extras are missing.
  - Add generic helper (e.g., `remora.backend import require_structured_agents`) that raises a friendly error when the backend stack is required but missing.

### 3. Frontend module and Stario integration

We already ship `demo/stario_dashboard`, which only touches:

- `remora.event_bus.EventBus` for streaming the global event log,
- `remora.interactive.WorkspaceInboxCoordinator` to write answers back to blocking agents,
- helper state collectors (e.g., `dashboard_state`, `workspace_registry`).

Refactor this “Stario glue” into an explicit `remora.frontend` subpackage (or at least expose its functionality through `remora.frontend.dashboard`) so the scripts/entrypoints can reuse it without duplicating logic. The frontend module should:

1. Provide a `DashboardState`/`EventAggregator` that keeps the last ~200 `Event` objects, the blocked map, results, and progress counters, just like `demo/stario_dashboard/state.py`.
2. Expose `dashboard_view(state)` helpers that render the HTML view using `stario.html`, `data.signals`, and `data.init(at.get('/events'))` so the SSE client gets patched fragments instead of raw DOM replacements.
3. Export a `register_routes(app: Stario, event_bus: EventBus)` helper that wires up:
   - `GET /` → `Writer.html(dashboard_view(state))`
   - `GET /events` → `async with Writer.alive(event_bus.stream()) as stream: ...` to patch the view + sync signal updates after every event.
   - `POST /agent/{agent_id}/respond` → `WorkspaceInboxCoordinator.respond(...)` with the workspace looked up via a registry that the backend updates as agents start.
4. Keep a lightweight workspace registry (`workspace_registry`) that stores `{agent_id → workspace}` for the duration of a run so `respond` can resolve the correct KV handle.

This module will be part of the `frontend` extra and will never import `structured_agents`, so it can operate in Python 3.14.

### 4. Documentation & user guidance

- Create `docs/INSTALLATION.md` (or expand `README.md`) to describe three workflows:
  1. `pip install remora[frontend]` runs the Stario dashboard against an externally hosted vLLM server.
  2. `pip install remora[backend]` unlocks bundle validation, CLI Grail checks, and local kernels (requires `vllm`).
  3. `pip install remora[full]` for developers who need both.
- Explain how the frontend communicates with the backend via the shared `EventBus` and `WorkspaceInboxCoordinator` (link to `STARIO_INTEGRATION_REVIEW.md`).
- Document that `remora-dashboard` and `remora[frontend]` are Python 3.14-only because of `stario`, while the backend extras stay on 3.13.
- Clarify in the VLLM guide (this document) that `remora` now talks to a running vLLM server over HTTP; no embedded dependency is required for frontend scenarios.

### 5. Testing updates

- Update `tests/acceptance` and any integration suites to guard `structured_agents`/`vllm` usage with `pytest.importorskip("structured_agents")` so the default `pytest` run (without backend extras) continues to succeed.
- Add a lightweight smoke test that installs `remora[frontend]` and verifies the `remora-dashboard` entrypoint can start (mocking `Stario` if necessary).
- Consider a CI matrix job that installs `remora[frontend]` on Python 3.14 and another job that installs `remora[backend]` on Python 3.13 so both stacks remain supported.

## Frontend interaction plan (Stario + EventBus)

The Stario dashboard becomes the default UI for `remora[frontend]`. Its runtime flow is:

1. Import the shared event bus with `event_bus = remora.event_bus.get_event_bus()` in a long-lived server process.
2. Render the initial dashboard at `/` using an HTML builder that embeds `data.signals` for `events`, `blocked`, `results`, and `progress` counters.
3. Stream updates via `/events`:

```python
from stario import Writer

async with Writer.alive(event_bus.stream()) as stream:
    async for event in stream:
        state.record(event)
        w.patch(dashboard_view(state))
        w.sync(state.get_signals())
```

4. Accept user answers through the `/agent/{agent_id}/respond` handler, parse `signals` into a dataclass, look up the workspace from the registry, and call `WorkspaceInboxCoordinator.respond(...)`. When the workspace is missing, return `400` so clients know to refresh.
5. Keep the dashboard state and workspace registry in memory so every SSE client sees the same timeline and can resolve blocked agents.

Because none of the code above touches `structured_agents`, the dashboard process can stay on Python 3.14. Backend teams that want to interrogate Grail bundles or run kernels locally should install `remora[backend]`, start a vLLM server, and consume the same `EventBus` through in-process subscribers.

## Implementation order

1. **Dependency split (packaging)**
   - Move `structured-agents`/`openai`/`vllm` to `[project.optional-dependencies.backend]`.
   - Add `frontend` extra with `stario`/`uvicorn` and a convenience `full` extra.
   - Update CI/lockfiles to reflect the new extras.
2. **CLI/script guard rails**
   - Lazy-import `structured_agents` + `openai` in CLI commands and scripts.
   - Provide user-friendly errors directing people to install the required extra.
   - Keep `remora-dashboard` entrypoint but only run if `stario` is available.
3. **Frontend module refactor**
   - Publish `remora.frontend` helpers (views, registries, SSE loop) built on `EventBus` + `WorkspaceInboxCoordinator`.
   - Ensure `demo/stario_dashboard` reuses these helpers so the same logic can power `scripts/remora_dashboard.py` (and other Stario experiments).
4. **Documentation + testing**
   - Write `docs/INSTALLATION.md`, update README, and reference this guide in `STARIO_INTEGRATION_REVIEW.md`.
   - Add tests/CI jobs for both extras, guard optional imports in fixtures, and add a smoke test for the dashboard.

## Compatibility matrix

| Installation | Python | Includes `structured-agents`/`vllm` | Includes `stario` | Works with Stario dashboard | Works with backend inference |
|--------------|--------|--------------------------------------|--------------------|------------------------------|------------------------------|
| `remora` | >=3.13 | No | No | No (`remora-dashboard` errors) | CLI runs but `list-agents` and Grail validation skip optional features |
| `remora[frontend]` | >=3.14 | No | Yes | ✅ (dashboard + SSE) | Backend features disabled (no `structured-agents`) |
| `remora[backend]` | >=3.13 | Yes (requires `vllm`, `xgrammar`, `openai`) | No | Dashboard still runs if you embed it separately | ✅ (full agent graph + validation) |
| `remora[full]` | >=3.14 (frontend) + >=3.13 (backend) | Yes | Yes | ✅ | ✅ |

## Summary

By splitting the dependency surface into frontend and backend extras and guarding the optional imports in CLI scripts, we keep the event bus + interactive coordinator available on Python 3.14 while local vLLM inference remains behind `structured-agents`/`vllm`. Stario can now plug into Remora via the shared `EventBus` and `WorkspaceInboxCoordinator`, the `remora-dashboard` entrypoint stays usable when `stario` is installed, and backend tooling can continue to use `structured-agents` and `openai` by opting into the `backend` slice. This makes the frontend-only experience lightweight, keeps the backend features intact, and documents both paths for future contributors.