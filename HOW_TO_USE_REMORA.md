# How to Use Remora (Current)

This guide reflects the current Remora runtime and APIs. It focuses on the DI container, event sourcing, and streaming sync, along with the CLI and service endpoints.

If you are new, start with:
1. Quick start
2. Configuration
3. Core concepts
4. Service endpoints
5. Programmatic usage

---

## 1. Quick start

### 1.1 Requirements

- Python 3.13+ (see `pyproject.toml` `requires-python`)
- An OpenAI-compatible model server (vLLM or similar)
- Cairn AgentFS available for workspace operations

### 1.2 Minimal config

Create `remora.yaml` (or start from `remora.yaml.example`):

```yaml
bundles:
  path: agents
  mapping:
    function: lint/bundle.yaml
    class: docstring/bundle.yaml
    file: lint/bundle.yaml

discovery:
  paths: ["src/"]
  languages: ["python"]
  max_workers: 4

model:
  base_url: "http://remora-server:8000/v1"
  api_key: "EMPTY"
  default_model: "Qwen/Qwen3-4B"

execution:
  max_concurrency: 4
  error_policy: skip_downstream
  timeout: 300
  max_turns: 8
  truncation_limit: 1024

workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"
  ignore_patterns:
    - ".git"
    - ".venv"
    - "node_modules"
    - "__pycache__"
    - ".mypy_cache"
    - ".pytest_cache"
  ignore_dotfiles: true
```

### 1.3 CLI

Run a graph over a target path:

```bash
remora run src/
```

Start the service UI:

```bash
remora serve --host 0.0.0.0 --port 8420
```

---

## 2. Core concepts

### 2.1 Discovery and graph

- `discover()` parses source files via tree-sitter and returns `CSTNode` objects.
- `build_graph()` maps nodes to bundles and computes dependencies.
- The graph is sorted topologically with priority ordering.

Key types:
- `CSTNode`: immutable code element metadata (id, file, range, text)
- `AgentNode`: immutable graph node with upstream/downstream edges

### 2.2 Execution

`GraphExecutor` runs nodes in dependency order with bounded concurrency. It emits lifecycle events to the `EventBus` and uses `ContextBuilder` to assemble prompts.

Error policies:
- `stop_graph`
- `skip_downstream`
- `continue`

### 2.3 Workspaces and sync modes

Remora uses Cairn to isolate agent changes:
- One stable workspace per graph
- One copy-on-write workspace per agent
- Reads fall through to stable when a file is unchanged

Sync modes (runtime choice):
- `SyncMode.FULL`: sync all project files into the stable workspace (default)
- `SyncMode.LAZY`: sync on first access via streaming sync
- `SyncMode.NONE`: no automatic sync

Streaming sync:
- Implemented by `StreamingSyncManager`
- `AgentWorkspace.read()` triggers lazy sync when in LAZY mode
- Optional file watching via `FileWatcher` if `watchfiles` is installed

### 2.4 Event system

Remora emits structured events to the `EventBus`, including:
- Graph lifecycle (`GraphStartEvent`, `GraphCompleteEvent`, `GraphErrorEvent`)
- Agent lifecycle (`AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`)
- Tool and model events (re-exported from structured-agents)
- Human-in-the-loop events

`EventKind` is used in the UI projector to classify events.

### 2.5 Event sourcing

Remora can persist every event to SQLite via `EventStore`:
- Stores events in `.remora/events/events.db` by default
- Supports replay and graph metadata queries
- Service endpoints can stream historical events

Event sourcing is wired into the service handler: when a graph is started via the service API, an `EventSourcedBus` wraps the event bus and persists every emitted event.

---

## 3. Service endpoints

The Starlette adapter exposes these endpoints:

- `GET /` – HTML dashboard
- `GET /subscribe` – Datastar patch stream
- `GET /events` – raw event SSE stream
- `GET /replay?graph_id=...` – event replay SSE stream (requires event store)
- `POST /run` – start a graph
- `POST /input` – submit human input
- `POST /plan` – preview graph
- `GET /config` – config snapshot
- `GET /snapshot` – UI state snapshot

The `/replay` endpoint streams persisted event records as SSE; it returns an error if the event store is disabled.

---

## 4. Recommended usage patterns

### 4.1 Use the DI container

`RemoraContainer` is the preferred entry point. It wires:
- `EventBus`
- `ContextBuilder` subscription
- `EventStore` (optional)
- project root

```python
from remora.core.container import RemoraContainer
from remora.service.api import RemoraService

container = RemoraContainer.create(
    config_path="remora.yaml",
    project_root=".",
)
service = RemoraService(container=container)
```

Disable event sourcing when needed:

```python
container = RemoraContainer.create(
    config_path="remora.yaml",
    project_root=".",
    enable_event_store=False,
)
```

### 4.2 Programmatic graph execution

```python
import asyncio
from pathlib import Path

from remora.core.config import load_config
from remora.core.discovery import discover
from remora.core.graph import build_graph
from remora.core.executor import GraphExecutor
from remora.core.event_bus import EventBus

async def main() -> None:
    config = load_config()
    nodes = discover(list(config.discovery.paths))
    bundle_root = Path(config.bundles.path)
    mapping = {k: bundle_root / v for k, v in config.bundles.mapping.items()}
    graph = build_graph(nodes, mapping)

    event_bus = EventBus()
    executor = GraphExecutor(config=config, event_bus=event_bus)
    results = await executor.run(graph, "example-run")
    print(f"Completed {len(results)} agents")

asyncio.run(main())
```

### 4.3 Access event history

```python
import asyncio
from remora.core.event_store import EventStore

async def main() -> None:
    store = EventStore(".remora/events/events.db")
    await store.initialize()
    async for record in store.replay("graph-id"):
        print(record["event_type"], record["timestamp"])

asyncio.run(main())
```

---

## 5. Bundles and tools

Bundles are structured-agent manifests. Tools are defined in `.pym` files (Grail). Remora:
- Loads tool schemas automatically
- Injects Cairn externals (`read_file`, `write_file`, `list_dir`, `submit_result`, etc)
- Parses model tool calls using either API tool schemas or XML grammar

Key bundle options:
- `max_turns`: overrides `execution.max_turns`
- `grammar.send_tools_to_api`: if false, tool schemas are not sent to the model

`submit_result` writes a submission record into the workspace; Remora reads the summary and uses it as agent output.

---

## 6. Configuration reference

Config sections (see `remora.yaml.example`):

- `bundles.path`: root folder for bundles
- `bundles.mapping`: node_type -> bundle path
- `discovery.paths`: list of paths to scan
- `discovery.languages`: restrict languages (by extension)
- `execution.*`: concurrency, error policy, timeouts
- `workspace.*`: base path, cleanup policy, ignore patterns
- `model.*`: OpenAI-compatible base_url, api_key, default_model

Environment overrides:
- `REMORA_MODEL_BASE_URL`
- `REMORA_MODEL_API_KEY`
- `REMORA_MODEL_DEFAULT`
- `REMORA_EXECUTION_MAX_CONCURRENCY`
- `REMORA_EXECUTION_TIMEOUT`
- `REMORA_WORKSPACE_BASE_PATH`

---

## 7. UI and Datastar notes

Remora’s built-in dashboard is a reference Datastar UI:
- `/subscribe` streams HTML patches
- `/events` streams raw event JSON
- `/snapshot` returns the current UI state

If you use a custom frontend, treat Remora as an event source and rebuild UI state from the event stream.

---

## 8. Troubleshooting

- **Empty outputs:** check model server connectivity and bundle tool configuration.
- **No events on /replay:** ensure event store is enabled (default is on) and that the graph was run through the service API.
- **Workspace issues:** verify AgentFS availability and `workspace.base_path` permissions.
- **Slow startup:** use `SyncMode.LAZY` in `CairnWorkspaceService.initialize()` to avoid full sync on large repos.

---

## 9. Useful entry points

- Container: `src/remora/core/container.py`
- Executor: `src/remora/core/executor.py`
- Event bus: `src/remora/core/event_bus.py`
- Event store: `src/remora/core/event_store.py`
- Streaming sync: `src/remora/core/streaming_sync.py`
- Service API: `src/remora/service/api.py`
- Starlette adapter: `src/remora/adapters/starlette.py`
