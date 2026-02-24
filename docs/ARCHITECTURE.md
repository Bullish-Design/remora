# Remora V2 Architecture

Remora V2 is built around three nouns: **events**, **agents**, and **workspaces**. Every state change, user interaction, tool call, and dashboard update flows through the same `EventBus`. Agent logic is expressed declaratively via `AgentGraph`, and every run executes inside a `GraphWorkspace` backed by Cairn + Fsdantic file/KV stores. The dashboard and any other UI simply listen to that event stream.

## System Overview

```
            ┌────────────┐         ┌────────────┐
            │   User     │◀────▶│    UI /    │
            │ Interface  │      │  Dashboard │
            └────────────┘      └────────────┘
                   │                  ▲
                   ▼                  │
                ┌────────────────────Event Bus────────────────────┐
                │  Publishes agent events, tool calls, checkpoints │
                └────────────────────┬────────────────────────────┘
                                     │
         ┌──────────────┬────────────┴─────────────┬──────────────┐
         │ AgentGraph   │ GraphWorkspace / KV Store │ Coordinator  │
         │ (nodes + DSL)│ (per-agent files + KV)    │ (optional)   │
         └──────────────┴────────────┬─────────────┴──────────────┘
                                     │
                          AgentKernel + Tool Execution
```

## Core Components

### Event Bus (`remora.event_bus.EventBus`)

- Pydantic-first events (`Event`, `EventCategory`, convenience constructors)
- Backpressure queue plus `asyncio.gather` for concurrent subscribers
- `stream()` exposes SSE/WebSocket-ready iterators used by the dashboard, CLI, and mobile remotes.
- Every agent lifecycle change (`agent_started`, `agent_blocked`, `agent_completed`, `workspace_checkpointed`, etc.) is emitted here.

### Agent Graph (`remora.agent_graph`)

- `AgentNode` unifies identity, bundle, target, inbox, kernel, KV state, and result tracking.
- `AgentGraph` exposes `.agent()`, `.after().run()`, `.run_parallel()`, `.discover()`, and `.on_blocked()` for building declarative workflows.
- `GraphExecutor` handles concurrency, emits each agent event, and integrates blocked/resumed handling via injected handlers.

### Workspaces & State (`remora.workspace`, `remora.agent_state`, `remora.checkpoint`)

- `GraphWorkspace` creates agent directories, shared space, and a snapshot of the original source under `remora_workspaces/`.
- `AgentKVStore` (Phase 5) stores conversation history, tool results, metadata, and snapshots entirely inside the KV store.
- `CheckpointManager` materializes files + KV entries, exports them to disk, and restores new workspaces for checkpoint playback or versioning.

### Interactive Layer (`remora.interactive`)

- `WorkspaceInboxCoordinator` polls Cairn KV for `outbox:question:*`, emits `agent:blocked`, and writes answers to `inbox:response:*`.
- `ask_user()` writes a question, polls the KV inbox, and resumes once the coordinator responds.
- `get_user_messages()` flushes async user messages sent via KV and integrates them into agent turns.

### UI & Dashboard (`demo/dashboard`)

- FastAPI app streams events via `/events` (SSE) and `/ws/events` (WebSocket).
- User responses are posted to `/agent/{agent_id}/respond` and reflected back through `EventBus` (`Event.agent_resumed`).
- `/projector` and `/mobile` endpoints render simplified views for presentation or touch interactions.
- Static assets live under `demo/dashboard/static/` and talk to `/static/dashboard.js`.

### Public API (`src/remora/__init__.py`)

Exports are intentionally minimal:

- `AgentGraph`, `GraphConfig`
- `EventBus`, `Event`, `get_event_bus`
- `discover`, `CSTNode`, `TreeSitterDiscoverer`
- `GraphWorkspace`, `WorkspaceManager`

This keeps the dependency surface clean while allowing consumers to compose graphs, subscribe to events, and orchestrate UI/CLI workflows.

## Data Flow

1. `discover()` parses the target paths via Tree-sitter and yields `CSTNode` objects.
2. `AgentGraph` adds agents, wires dependencies, and optionally sets `.on_blocked()`.
3. `GraphExecutor` runs each agent:
   - publishes `agent_started`
   - executes structured-agents kernel (bundles + tools)
   - writes conversation + tool results via `AgentKVStore`
   - publishes `agent_completed` / `agent_failed`
4. The dashboard or CLI consumes `EventBus.stream()` to display progress and resolve questions.
5. Workspaces can be checkpointed via `CheckpointManager`, materializing both files and KV entries for versioning.

## Testing Strategy

Each phase ships with dedicated unit tests (`tests/unit/test_event_bus.py`, `test_agent_graph.py`, etc.) and an integration suite under `tests/integration/` that uses the new graph API plus interactive handlers. The event bus tests guarantee wildcard matching, SSE clients, and telemetry; agent_graph tests cover dependency wiring and agent inbox interactions; workspace tests verify directories, snapshots, and cleanup.
