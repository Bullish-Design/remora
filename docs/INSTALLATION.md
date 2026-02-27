# Installation

Remora ships with a lean base package plus optional dependency slices so that frontend consumers can stay on Python 3.14 while backend teams keep using the Grail + vLLM stack on ≤3.13.

## Base runtime

```bash
pip install remora
```

- Provides the core event bus, graph/runtime helpers, CLI framework, and workspace tooling.
- No `structured-agents`, `vllm`, or `openai`; backend-only workflows are disabled but the service contract and discovery utilities remain available.

## Service slice (Python 3.13+)

```bash
pip install "remora[frontend]"
```

- Installs the core runtime plus `uvicorn` and `httpx` so you can run `remora serve` or build a lightweight service adapter.
- Exposes `/subscribe`, `/events`, `/run`, `/input`, `/plan`, `/config`, and `/snapshot` for downstream dashboards.

## Backend slice (Python 3.13+)

```bash
pip install "remora[backend]"
```

- Pulls in `structured-agents`, `vllm`, `xgrammar`, and `openai` so you can validate Grail bundles, run local kernels, and drive the CLI commands that inspect vLLM models or agents.
- Backend-focused tests will skip structured-agent work and emit a warning if this extra is missing, leaving the rest of Remora functional.
- Use this extra in environments that must stay on Python 3.13 or when you need local kernel execution.

## Full install

```bash
pip install "remora[full]"
```

- A convenience meta-extra that installs both `frontend` and `backend` slices, suitable for environments that run frontends and local inference in the same Python 3.14+ interpreter.

## Notes

- Downstream libraries that only need the event stream should declare `remora[frontend]` as a dependency so they get the service helpers without pulling `structured-agents`.
- Backend developers who run Grail validation or vLLM kernels should install `remora[backend]` and keep `remora[full]` handy when combining both use cases.
