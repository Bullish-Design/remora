Remora V2 is built around three nouns: **events**, **agents**, and **workspaces**. Every state change, tool call, and UI update flows through the same `EventBus`. Agents are defined through declarative graph builders, execution happens in deterministic batches, and dashboards simply replay the event stream.

```
                 ┌────────────┐         ┌────────────┐
                 │   User     │◀────▶│ Dashboard  │
                 │ Interface  │      │  / CLI     │
                 └────────────┘      └────────────┘
                        │                  ▲
                        ▼                  │
                  ┌────────────────────Event Bus────────────────────┐
                  │  Publishes kernel events, tool results, and logs │
                  └─────────────┬──────────────┬────────────▲────────┘
                                │              │            │
                        ┌───────▼───────┐ ┌────▼────┐ ┌─────▼─────┐
                        │ Graph Builder │ │ Context │ │ Dashboard │
                        │ (remora.graph)│ │ Builder │ │ App / SSE │
                        └───────────────┘ └─────────┘ └────────────┘
```

## Core Components

### Event Bus (`remora.event_bus.EventBus`)

- Centralized observer that implements the structured-agents `Observer` protocol.
- Type-based subscriptions and `stream()` support SSE/WebSocket consumers.
- Every tool call, human input request, and agent completion emits through the bus.

### Graph Builder & Executor (`remora.graph`, `remora.executor.GraphExecutor`)

- `build_graph()` maps `CSTNode` objects to bundles via metadata, respecting priorities and dependencies.
- `GraphExecutor` runs those nodes, provisions per-agent Cairn workspaces, injects the EventBus as the structured-agents observer, and emits `AgentStart/Complete/Error` events.
- Execution is governed by `ExecutionConfig`, `ErrorPolicy`, and the shared `ContextBuilder` for prompt context and knowledge.

### Context & Knowledge (`remora.context.ContextBuilder`)

- Subscribes to `ToolResultEvent` and `AgentCompleteEvent` to maintain rolling recent actions and persistent knowledge summaries.
- Supplies prompt sections (`build_context_for`) that `execute_agent()` uses when calling `Agent.run()`.
- `ingest_summary()` captures every `ResultSummary` so downstream UIs know what changed.

### Workspaces (`remora.workspace`, `remora.checkpoint`)

- `WorkspaceConfig` describes base path + cleanup cadence for `CairnWorkspace` instances.
- `CairnDataProvider` feeds file contents (source + related files) into prompts and results.
- `CairnResultHandler` persists tool outputs + file writes and returns `ResultSummary` objects.
- `CheckpointManager` snapshots both SQLite state and metadata for versioned replay.

### Dashboard App (`remora.dashboard.app`)

- Starlette application exposing `/subscribe`, `/events`, `/run`, and `/input`.
- Streams SSE patches and raw JSON events; posting to `/input` emits `HumanInputResponseEvent` on the EventBus.
- Intended entry point for any ASGI dashboard or projector.

### Public API (`src/remora/__init__.py`)

- `build_graph()`, `AgentNode`, `BundleMetadata`, `GraphExecutor`
- `EventBus`, `Event`, `get_event_bus()`
- `ContextBuilder`, `ResultSummary`
- `WorkspaceConfig`, `CairnWorkspace`, `CairnDataProvider`, `CairnResultHandler`
- `DashboardApp`, `create_app()`

## Data Flow

1. `discover()` parses the target paths via Tree-sitter and yields `CSTNode` objects.
2. `build_graph()` selects bundles using metadata supplied via `remora.yaml`.
3. `GraphExecutor` provisions `CairnWorkspace`, builds context, sets `STRUCTURED_AGENTS_*` env vars, and runs each agent via `Agent.from_bundle()`.
4. Tool results are persisted through `CairnResultHandler`, producing `ResultSummary` objects that feed `ContextBuilder` and `DashboardApp`.
5. The dashboard or CLI consumes `EventBus.stream()` for SSE/WS updates and posts human responses via `/input`.
6. `CheckpointManager` snapshots the SQLite files + metadata so workflows can resume or version control entire graphs.

## Testing Strategy

- `tests/unit/test_event_bus.py`: validates pub/sub, filtering, streaming, `wait_for()`, and human-in-the-loop patterns.
- `tests/test_context_manager.py`: exercises `ContextBuilder` short/long tracks and summary ingestion.
- `tests/unit/test_workspace.py`: verifies Cairn workspace creation, snapshots, and shared areas.

Run the suite with `pytest tests/unit/ -v` (see `docs/TESTING_GUIDELINES.md` for extra expectations).
