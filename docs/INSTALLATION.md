# Installation

Remora now ships with a lean base package plus optional dependency slices so that frontend consumers (like the new Stario dashboard library) can stay on Python 3.14 while backend teams keep using the Grail + vLLM stack on ≤3.13.

## Base runtime

```bash
pip install remora
```

- Provides the core event bus, workspace helpers, CLI framework, and analyzer/orchestrator plumbing that every consumer needs.
- No `structured-agents`, `vllm`, or `openai`; backend-only workflows are disabled but the CLI still works for discovery, watch, and analysis commands.

## Dashboard slice (Python 3.13+)

```bash
pip install remora
```

- Installs the core runtime plus `uvicorn` so you can run `demo/dashboard/app.py`, mount `DashboardApp`, or expose the SSE `/events` feed in your own ASGI host.
- No additional event helpers are needed; `DashboardApp` exposes `/subscribe`, `/events`, `/run`, and `/input` along with the shared `EventBus` so every UI consumer reuses the same stream.

## Backend slice (Python 3.13+)

```bash
pip install "remora[backend]"
```

- Pulls in `structured-agents`, `vllm`, `xgrammar`, and `openai` so you can validate Grail bundles, run local kernels, and drive the CLI commands that inspect vLLM models or agents.
- CLI commands such as `list-agents`, `scripts/validate_agents.py`, and any backend-focused tests will skip structured-agent work and emit a warning if this extra is missing, leaving the rest of Remora functional.
- Use this extra in environments that must stay on Python 3.13 or when you need local kernel execution.

## Full install

```bash
pip install "remora[full]"
```

- A convenience meta-extra that installs both `frontend` and `backend` slices, suitable for environments that run dashboards and local inference in the same Python 3.14+ interpreter.

## Notes

- Downstream libraries that only need the event stream should declare `remora[frontend]` as a dependency so they get the lightweight dashboard helpers without pulling `structured-agents`.
- Backend developers who run Grail validation, acceptance scripts, or vLLM kernels should install `remora[backend]` and keep `remora[full]` handy when combining both use cases.
- The CLI and `scripts/validate_agents.py` now use `remora.backend.require_backend_extra()` to raise a friendly error when `structured-agents` is missing; install the backend extra to re-enable Grail tooling.
