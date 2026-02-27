# Remora — Event-Driven Agent Graph Workflows

Remora V2 is a simple, elegant framework for composing and running structured-agent workloads on your code. Every action flows through a **Pydantic-first event bus**, agents are described via metadata-driven graphs, work happens inside isolated Cairn workspaces, and every UI just consumes the same events.

## Quick Start

1. Start a vLLM-compatible server (default: `http://remora-server:8000/v1`).
2. Copy `remora.yaml.example` → `remora.yaml` and configure bundles, `model.base_url`, and credentials.
3. Discover and execute a graph using the new API:

```python
import asyncio
from pathlib import Path

from remora.core.config import load_config
from remora.core.discovery import discover
from remora.core.event_bus import EventBus
from remora.core.graph import build_graph
from remora.core.executor import GraphExecutor

def main() -> None:
    config = load_config()
    nodes = discover(
        list(config.discovery.paths),
        languages=list(config.discovery.languages) if config.discovery.languages else None,
        max_workers=config.discovery.max_workers,
    )
    bundle_root = Path(config.bundles.path)
    bundle_mapping = {
        node_type: bundle_root / bundle
        for node_type, bundle in config.bundles.mapping.items()
    }
    graph = build_graph(nodes, bundle_mapping)
    event_bus = EventBus()
    executor = GraphExecutor(config=config, event_bus=event_bus)
    results = asyncio.run(executor.run(graph, "quickstart"))
    print(f"Completed {len(results)} agents")

if __name__ == "__main__":
    main()
```

4. Start the Remora service (Starlette adapter):

```bash
remora serve
```

UIs subscribe to the same SSE feed driven by the event bus.

## How to run the service

```bash
remora serve --host 0.0.0.0 --port 8420
```

Then open `http://localhost:8420/` or connect to `/subscribe` and `/events` from an external frontend.

## Installation Options

Remora ships with a lightweight core plus backend-focused extras so you can mix dashboards and structured-agent tooling across interpreter versions.

- `pip install remora` – installs the base runtime with the event bus, CLI framework, Cairn workspace helpers, and the Remora service adapter (SSE/HTTP endpoints for downstream dashboards).
- `pip install "remora[backend]"` – pulls in `structured-agents`, `vllm`, `xgrammar`, and `openai` so Grail bundles and vLLM kernels can execute in-process.
- `pip install "remora[full]"` – convenience meta extra that installs both slices for environments that run dashboards and local inference in the same interpreter.

See `docs/INSTALLATION.md` for more detail and the recommended deployment patterns for dashboards versus backend tooling.

## Tool Calling Modes

Remora supports two tool-calling modes, controlled per bundle with `grammar.send_tools_to_api`.

- `send_tools_to_api: true` (default): tool schemas are sent to vLLM and the model calls tools via the native OpenAI-style tool API. This yields the most reliable tool selection and argument formatting.
- `send_tools_to_api: false`: tool schemas are not sent to vLLM. The model must emit XML tool calls (Qwen XML parser) in the response content, which Remora parses and executes. Use this for legacy XML tool-call formats or when you need to test model misbehavior (unknown tools, malformed args).
- When `send_tools_to_api` is `false`, Remora does not attach structured-output constraints because constraints are only applied when tool schemas are sent to the kernel.

Example bundle snippet:

```yaml
grammar:
  strategy: ebnf
  allow_parallel_calls: false
  send_tools_to_api: true
```


## Public API Highlights

- `GraphExecutor`, `ExecutionConfig`, `ErrorPolicy`: run declarative graphs with bounded concurrency, structured-agents observers, and configurable error handling.
- `EventBus`, `RemoraEvent`: central nervous system for logging, dashboards, and integrations (explicit injection recommended).
- `ContextBuilder`, `RecentAction`: two-track memory for prompt sections, knowledge aggregation, and human-in-the-loop responses.
- `WorkspaceConfig`, `AgentWorkspace`, `WorkspaceManager`: supply isolated workspaces and file data for each agent run.
- `remora.service.RemoraService`, `remora.service.RemoraService.create_default()`, `remora.adapters.starlette.create_app()`: service surface plus Starlette adapter that exposes `/`, `/subscribe`, `/events`, `/run`, `/input`, `/plan`, `/config`, and `/snapshot`.
- `discover()`, `TreeSitterDiscoverer`, `CSTNode`: AST discovery remains tree-sitter based but now feeds structured graphs directly.

## Event-Driven UI

Every UI consumer subscribes to the same event stream. Use `/subscribe` for Datastar patches or `/events` for raw SSE JSON, and resolve blocked agents via `/input`.

## Workspaces & Checkpoints

`AgentWorkspace` and `WorkspaceConfig` create isolated workspaces per agent. `CheckpointManager` materializes snapshots so you can version them with `jj`, `git`, or any storage backend.

## Testing Strategy

- `tests/unit/test_event_bus.py`: validates pub/sub and streaming helpers.
- `tests/unit/test_agent_graph.py`: covers graph construction and ordering.
- `tests/test_context_manager.py`: exercises `ContextBuilder` short/long track behavior.
- `tests/utils/test_fs.py`: covers filesystem utility helpers.

Run the unit suite with `pytest tests/unit/ -v` (see `docs/TESTING_GUIDELINES.md` for Phase-focused expectations).

## Documentation

- `BLUE_SKY_V2_REWRITE_GUIDE.md` — detailed phase-by-phase roadmap
- `V2_IMPLEMENTATION_STATUS.md` — what is shipped so far
- `docs/ARCHITECTURE.md` — updated architecture diagram and data flow
- `docs/REMORA_UI_API.md` — service contract for UI/frontends
- `docs/TESTING_GUIDELINES.md` — new Phase 1-6/7 test coverage plan
- `examples/stario_reference/` — external Stario reference frontend template
