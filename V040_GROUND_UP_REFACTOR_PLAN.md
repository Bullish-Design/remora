# Remora v0.4.0 Ground-Up Refactor Plan

## Goal
Create a lean Remora core that treats Cairn as the workspace, structured-agents 0.3.4 as the kernel, and Grail 3.0.0 as the sandbox while exposing a single event-driven control plane and clean services on top.

> See `docs/plans/2026-02-26-remora-v040-refactor-design.md` for the approved contracts and rationale.

## Architecture Overview
- **One layer, clear dependency owner**: discovery, graph, execution, context, and checkpoint code live in `src/remora/`; each package has a clear dependency (Cairn for workspaces, structured-agents for kernels, Grail for scripts, fsdantic for indexes).
- **Explicit config surface**: `remora.yaml` holds project-wide settings while each agent bundle stays in structured-agents format; Remora metadata such as node types and priority hints sits in separate Remora metadata mappings.
- **Unified observability**: the typed event taxonomy is exposed via an EventBus that implements `structured_agents.events.observer.Observer`, re-emits kernel events, and surfaces Remora graph/human-IO events for services and context builders.

## Foundation
### Flattened Configuration
- `remora.yaml` is the single authoritative source for discovery paths, workspace cleanup, indexer storage, dashboard binding, execution concurrency, and structured-agents client details (`model_base_url`, `api_key`, defaults).
- `bundle.yaml` files stay in the public structured-agents shape (model, grammar, limits, tools) while Remora-specific metadata (node types handled, execution priority, context requirements) live in a lightweight `BundleMetadata` record keyed by bundle name within Remora metadata.
- Configuration loading occurs once at startup via a frozen `RemoraConfig` dataclass; components receive their slices explicitly rather than reading globals.

### Unified EventBus
- Implement an `EventBus` that conforms to `structured_agents.events.observer.Observer`, exposing `async def emit(self, event: Event)` so kernels, context builders, and dashboards share a single multicast.
- Re-emit kernel events (`KernelStartEvent`, `RestartEvent`, `ToolCallEvent`, etc.) and add Remora graph/human-in-the-loop events such as `GraphStartEvent`, `AgentCompleteEvent`, `HumanInputRequestEvent`, and `HumanInputResponseEvent`.
- Provide `subscribe`, `stream`, and `wait_for` primitives so the dashboard SSE stream, context builder, and the event-based IPC flow all use typed handlers.

### Core Contracts
- `EventBus` is the single event plane for kernels, graphs, and services.
- `CairnDataProvider` populates Grail files from the Cairn workspace layer.
- `CairnResultHandler` persists tool outputs back into Cairn layers and returns a `ResultSummary`.
- `GraphExecutor` schedules nodes, injects context, and emits graph events.
- `ContextBuilder` aggregates short/long-track context via EventBus.
- `CheckpointManager` snapshots Cairn state with executor progress.

### Discovery Simplification
- Collapse the five discovery modules into `discovery.py` with `discover(paths, languages, node_types, max_workers)` returning pure `CSTNode` dataclasses with deterministic IDs.
- Keep the `.scm` queries directory as-is and execute tree-sitter parsing via a worker pool; results feed the graph builder without side effects.

## Core Execution
### Cairn-First Workspace Layer
- Each agent run creates a Cairn workspace derived from the base path in `remora.yaml`; the workspace populates the Grail virtual filesystem via a `CairnDataProvider` that reads required files for the target `CSTNode` and related contexts.
- Shared state between agents is handled through Cairn's layered diffs: accepted changes land in the base layer while overlays keep writes isolated until the executor decides to merge.
- Workspaces use Cairn snapshots for checkpoints and automatic cleanup (TTL/expiration) to prevent orphaned directories.
- A `CairnResultHandler` persists structured `.pym` outputs (fixes, new files, metadata) back into the workspace so downstream agents see the accepted changes.

### Agent Execution Aligned to structured-agents 0.3.4
- `GraphExecutor` delegates to `structured_agents.agent.Agent.from_bundle()` but injects Remora context: set `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` from `RemoraConfig.model` before loading, provide the EventBus as the agent observer, and pass `CairnDataProvider`/`CairnResultHandler` for Grail IO.
- Keep node type → bundle mapping plus node priority/`requires_context` data in Remora-owned `BundleMetadata`; do not extend `bundle.yaml` with Remora-specific fields.
- Replace `structured_agents.tools.grail.discover_tools()` with a Remora-aware loader that instantiates each Grail script once per bundle with the correct `files` dict (from `CairnDataProvider`) and `externals` (human-in-the-loop `ask_user` adapter).
- The executor tracks agent state externally (`dict[str, AgentState]`), routes error policies (`stop_graph`, `skip_downstream`, `continue`), and emits graph-level events via the EventBus before handing each node to `execute_agent()`.

### Data Flow and Human-in-the-Loop
- EventBus drives `ContextBuilder`, dashboard SSE, and `ask_user` via `HumanInputRequestEvent`/`HumanInputResponseEvent` with `wait_for()`.
- Tools stay pure: inputs arrive via Grail VFS and `Input()` declarations, outputs describe mutations, and `CairnResultHandler` persists changes.
- `CairnResultHandler` returns a `ResultSummary` for context and dashboard rendering.
- `ContextBuilder` maintains short-track results and pulls long-track indexer context as needed.

### Error Handling
- Executor enforces policy per node (`stop_graph`, `skip_downstream`, `continue`) and emits failure events.
- Tool errors still feed short-track memory via `ToolResultEvent.is_error`.
- Grail errors are captured in `ResultSummary` for dashboards/tests.
- Errors surface through EventBus for dashboard and context updates.

### Graph Topology and Executor Separation
- `graph.py` builds an immutable list of `AgentNode` dataclasses (id, bundle_path, target node, upstream/downstream ids) using the metadata mapping, keeping topology separate from execution state.
- `executor.py` owns concurrency (bounded semaphore), dependency scheduling, workspace creation, and invoking `execute_agent()`. It also aggregates results for `GraphCompleteEvent` and interacts with `CheckpointManager` for Cairn snapshots.
- Checkpoints store executor state (completed nodes, results, pending nodes) plus Cairn workspace snapshots so runs can resume without re-running already finished agents.

## Services
### Indexer vs Dashboard
- Split the legacy `hub/` code into `indexer/` (daemon, store, fsdantic models, rules) and `dashboard/` (Starlette app, SSE views, dashboard state) so each package has a single responsibility.
- The indexer publishes node metadata into a shared `NodeStateStore`; the dashboard consumes the store (read-only) and subscribes to the EventBus for live graph/agent updates, including kernel events now emitted by the unified bus.
- CLI entry points become `remora` (core), `remora-index`, and `remora-dashboard`, with `cli.py` orchestrating discovery → graph → executor and the services launching their own loops.

## Verification
- Unit-test the event system (type-based subscriptions, wait_for, Observer compliance), the Discovery API, and the graph builder/executor path with mock agent bundles.
- Add integration smoke tests that run a single bundle against sample code to ensure `CairnDataProvider` wiring correctly populates the virtual filesystem and that human-IO events resolve.
- Ensure the indexer can rebuild the node store from sample repos and that the dashboard streams Remora events to SSE clients.
