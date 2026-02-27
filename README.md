# Remora V2 — Event-Driven Agent Graph Workflows

Remora V2 is a simple, elegant framework for composing and running structured-agent workloads on your code. Every action flows through a **Pydantic-first event bus**, agents are described via metadata-driven graphs, work happens inside isolated Cairn workspaces, and every UI (CLI, dashboard, mobile) just consumes the same events.

## Quick Start

1. Start a vLLM-compatible server (default: `http://remora-server:8000/v1`).
2. Copy `remora.yaml.example` → `remora.yaml` and configure bundles, `model_base_url`, and credentials.
3. Discover and execute a graph using the new API:

```python
from pathlib import Path

from remora.config import load_config
from remora.discovery import discover
from remora.event_bus import get_event_bus
from remora.graph import build_graph
from remora.executor import ExecutionConfig, GraphExecutor

config = load_config()
nodes = await discover(Path("src"))
agent_nodes = build_graph(nodes, config.bundle_metadata, config=config)
executor = GraphExecutor(
    config=ExecutionConfig(max_concurrency=2),
    event_bus=get_event_bus(),
    remora_config=config,
)
results = await executor.run(agent_nodes, config.workspace)
```

4. Stream events via the dashboard demo or mount `DashboardApp`:

```bash
uvicorn demo.dashboard.app:app --reload
```

The dashboard, projector view (`/projector`), and mobile remote (`/mobile`) all subscribe to the same SSE/WebSocket feed driven by `remora.event_bus.EventBus`.

## Installation Options

Remora ships with a lightweight core plus backend-focused extras so you can mix dashboards and structured-agent tooling across interpreter versions.

- `pip install remora` – installs the base runtime with the event bus, CLI framework, Cairn workspace helpers, and the `DashboardApp` demo that exposes SSE/HTTP endpoints for downstream dashboards.
- `pip install "remora[backend]"` – pulls in `structured-agents`, `vllm`, `xgrammar`, and `openai` so CLI commands like `list-agents` or `scripts/validate_agents.py` can validate Grail bundles and drive vLLM kernels.
- `pip install "remora[full]"` – convenience meta extra that installs both slices for environments that run dashboards and local inference in the same interpreter.

See `docs/INSTALLATION.md` for more detail and the recommended deployment patterns for dashboards versus backend tooling.


## Public API Highlights

- `GraphExecutor`, `ExecutionConfig`, `ErrorPolicy`: run declarative graphs with bounded concurrency, structured-agents observers, and configurable error handling.
- `EventBus`, `Event`, `get_event_bus()`: central nervous system for logging, dashboards, and integrations.
- `ContextBuilder`, `RecentAction`: two-track memory for prompt sections, knowledge aggregation, and human-in-the-loop responses.
- `WorkspaceConfig`, `CairnWorkspace`, `CairnDataProvider`: supply isolated Cairn workspaces, file data, and snapshots for each agent run.
- `DashboardApp`, `create_app()`: lightweight Starlette application that streams SSE updates, handles `/events`, `/run`, and `/input`, and can be mounted in any ASGI host.
- `discover()`, `TreeSitterDiscoverer`, `CSTNode`: AST discovery remains tree-sitter based but now feeds structured graphs directly.

## Event-Driven UI

Every UI consumer subscribes to the same event stream. Use the dashboard at `/events` (SSE) or `/ws/events` (WebSocket), and resolve blocked agents via `/agent/{agent_id}/respond`. The FastAPI demo app under `demo/dashboard/` ships with a modern Vue-inspired layout and lightweight projector/mobile remotes.

## Workspaces & Checkpoints

`CairnWorkspace` and `WorkspaceConfig` create isolated SQLite-backed workspaces per agent plus optional shared areas. `CheckpointManager` materializes those snapshots so you can version them with `jj`, `git`, or any storage backend. The KV store inside each workspace keeps the event history, tool outputs, and metadata for auditability.

## Testing Strategy

- `tests/unit/test_event_bus.py`: validates pub/sub, wildcard patterns, SSE streaming, and JSON serialization.
- `tests/test_context_manager.py`: exercises `ContextBuilder` short/long track behavior and summary ingestion.
- `tests/unit/test_workspace.py`: covers Cairn workspace creation, snapshots, and shared databases.

Run the unit suite with `pytest tests/unit/ -v` (see `TESTING_GUIDELINES.md` for Phase-focused expectations).

## Documentation

- `BLUE_SKY_V2_REWRITE_GUIDE.md` — detailed phase-by-phase roadmap
- `V2_IMPLEMENTATION_STATUS.md` — what is shipped so far
- `docs/ARCHITECTURE.md` — updated architecture diagram and data flow
- `docs/TESTING_GUIDELINES.md` — new Phase 1-6/7 test coverage plan
- `demo/dashboard/` — SSE/WebSocket dashboard + projector/mobile remotes
