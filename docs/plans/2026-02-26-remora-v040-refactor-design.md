# Remora v0.4.0 Refactor Design

Note: The current refactor replaced `src/remora/dashboard/` with `src/remora/service/` and `src/remora/ui/`. Treat dashboard references below as historical.

## Goal
Establish a clean, minimal core for Remora that aligns with structured-agents 0.3.4 and Grail 3.0.0, with Cairn as the workspace layer, a single EventBus for observability, and isolated services for indexing and dashboards.

## Architecture
- Core stays in `src/remora/` with explicit modules: `config.py`, `events.py`, `event_bus.py`, `discovery.py`, `graph.py`, `executor.py`, `context.py`, `workspace.py`, `checkpoint.py`.
- Services live under `src/remora/indexer/` and `src/remora/dashboard/`, consuming core APIs only.
- `V040_GROUND_UP_REFACTOR_PLAN.md` is the canonical architecture reference; `.refactor` steps become implementation guides aligned to the same contracts.

## Core Contracts
### EventBus
- Methods: `async emit(event)`, `subscribe(event_type, handler)`, `stream(event_type=None)`, `wait_for(event_type, predicate=None, timeout=None)`
- Must implement `structured_agents.events.observer.Observer`.
- Single multicast for kernel, graph, and human I/O events.

### CairnDataProvider
- Methods: `load_files(node) -> dict[str, str | bytes]`, optional `load_environ(node) -> dict[str, str]`.
- Reads only from Cairn overlays, no side effects.

### CairnResultHandler
- Methods: `handle(result, workspace) -> ResultSummary`.
- Writes mutations to the workspace overlay and returns a structured summary.

### GraphExecutor
- Methods: `run(graph, event_bus, config, bundle_metadata) -> GraphResult`.
- Handles concurrency, scheduling, workspace lifecycle, error policies, and event emission.

### ContextBuilder
- Methods: `on_event(event)`, `build_context_for(node) -> str`, `get_recent_actions()`.
- Maintains short-track memory from Tool/Agent events and optional long-track store data.

### CheckpointManager
- Methods: `save(state, workspaces)`, `restore(checkpoint_id) -> ExecutorState`, `list_checkpoints()`, `delete(checkpoint_id)`.
- Snapshots Cairn workspaces and executor state for resume.

## Data Flow
- `.pym` tools are pure: inputs arrive via `Input()` declarations and Grail `files` dicts; outputs are structured dicts describing mutations.
- `ask_user` is the only built-in external; it emits `HumanInputRequestEvent` and awaits `HumanInputResponseEvent` through `EventBus.wait_for()`.
- `CairnResultHandler` persists changes to overlays and supplies `ResultSummary` for context and dashboard rendering.

## Error Handling
- Executor policies: `stop_graph`, `skip_downstream`, `continue` with consistent `AgentErrorEvent` emission.
- Tool errors (`ToolResultEvent.is_error=True`) still feed short-track memory.
- Grail errors (Input/External/Execution/Limit) are captured in `ResultSummary` for UI and tests.

## Verification
- Each `.refactor` step includes explicit “done” checks: unit tests for new modules, integration smoke tests for Grail DataProvider/ResultHandler flow, and CLI sanity checks.
- Tests map directly to the module introduced in each step guide.

## Non-Goals
- No backwards-compatibility with legacy hub/workspace APIs.
- No new agent bundle semantics beyond pure Grail tools and structured-agents bundles.
