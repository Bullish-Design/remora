# Remora V2 — Event-Driven Agent Graph Workflows

Remora V2 is a simple, elegant framework for composing and running structured-agent workloads on your code. Every action flows through a **Pydantic-first event bus**, agents are expressed declaratively via an `AgentGraph`, work happens inside isolated Cairn workspaces, and every UI (CLI, dashboard, mobile) just consumes the same events.

## Quick Start

1. Start a vLLM-compatible server (default: `http://remora-server:8000/v1`).
2. Copy `remora.yaml.example` → `remora.yaml` and point `agents_dir`, `server`, and any bundle overrides.
3. Run discovery + execution with the new API:

```python
from remora import AgentGraph, GraphConfig
from remora.discovery import discover

nodes = await discover(Path("src"))
graph = AgentGraph().agent("lint", bundle="lint", target="def foo(): pass")
results = await graph.execute(GraphConfig(max_concurrency=2))
```

4. Stream events via the dashboard:

```bash
uvicorn demo.dashboard.app:app --reload
```

The dashboard, projector view (`/projector`), and mobile remote (`/mobile`) all subscribe to the same SSE/WebSocket feed driven by `remora.event_bus.EventBus`.

## Installation Options

Remora ships with a lightweight core plus two optional extras so the standalone Stario dashboard library can stay on Python 3.14 while backend tooling keeps using the Grail + vLLM stack on ≤3.13.

- `pip install remora` – installs the base runtime with the event bus, CLI framework, and analyzer/orchestrator plumbing that every consumer needs.
- `pip install "remora[frontend]"` – adds `stario`, `uvicorn`, and the `remora.frontend` helpers (dashboard view, SSE routes, `WorkspaceInboxCoordinator`, `register_routes`) required by the Stario library. This extra targets Python 3.14 because `stario` requires it; a 3.13 install will fail with a clear pip error from `stario`.
- `pip install "remora[backend]"` – pulls in `structured-agents`, `vllm`, `xgrammar`, and `openai` so CLI commands like `list-agents` or `scripts/validate_agents.py` can validate Grail bundles and query a vLLM server.
- `pip install "remora[full]"` – convenience meta extra that installs both slices for environments that run dashboards and local inference together.

See `docs/INSTALLATION.md` for more detail, including guidance on when to install each extra and how the new Stario dashboard integration uses the shared event bus.

## Public API Highlights

- `AgentGraph`, `GraphConfig`: declaratively compose agents, dependencies, parallel groups, and execute with interactive handlers.
- `EventBus`, `Event`, `get_event_bus()`: central nervous system for logging, dashboards, and integrations.
- `GraphWorkspace`, `WorkspaceManager`: manage per-graph workspaces, snapshots, and merges.
- `discover()`, `TreeSitterDiscoverer`, `CSTNode`: AST discovery remains tree-sitter based but now feeds `AgentGraph` directly.

## Event-Driven UI

Every UI consumer subscribes to the same event stream. Use the dashboard at `/events` (SSE) or `/ws/events` (WebSocket), and resolve blocked agents via `/agent/{agent_id}/respond`. The FastAPI demo app under `demo/dashboard/` ships with a modern Vue-inspired layout and lightweight projector/mobile remotes.

## Workspaces & Checkpoints

`GraphWorkspace` creates isolated folders for each agent plus shared/original sources. `CheckpointManager` materializes the filesystem + KV store for versioning via `jj`/`git`. The KV store (`AgentKVStore`) keeps conversation history, tool results, and metadata.

## Testing Strategy

- `tests/unit/test_event_bus.py`: validates pub/sub, wildcard patterns, SSE streaming, and JSON serialization.
- `tests/unit/test_agent_graph.py`: ensures declarative graph building, inbox handling, and execution events.
- `tests/unit/test_workspace.py`: covers workspace creation, snapshot, and shared directories.
- `tests/unit/test_workspace_ipc.py`: ensures the coordinator emits blocked/resumed events.
- `tests/unit/test_agent_state.py`: verifies KV-based persistence helpers.

Run the unit suite with `pytest tests/unit/ -v` (see `TESTING_GUIDELINES.md` for Phase-focused expectations).

## Documentation

- `BLUE_SKY_V2_REWRITE_GUIDE.md` — detailed phase-by-phase roadmap
- `V2_IMPLEMENTATION_STATUS.md` — what is shipped so far
- `docs/ARCHITECTURE.md` — updated architecture diagram and data flow
- `docs/TESTING_GUIDELINES.md` — new Phase 1-6/7 test coverage plan
- `demo/dashboard/` — SSE/WebSocket dashboard + projector/mobile remotes
