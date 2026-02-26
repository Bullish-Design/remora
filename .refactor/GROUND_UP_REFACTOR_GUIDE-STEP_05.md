# Implementation Guide: Step 5 - Graph Executor and Agent Runner

## Target
Implement `GraphExecutor` that runs the immutable graph in dependency order, creates Cairn workspaces, wires the unified EventBus, and respects execution policies (`stop_graph`, `skip_downstream`, `continue`).

## Overview
- The executor owns concurrency (bounded semaphore), dependency scheduling, error routing, and human-in-the-loop handoffs.
- Each node run gets a workspace from the manager, a `CairnDataProvider` for the virtual FS, and a `CairnResultHandler` for mutations.
- `execute_agent()` delegates to `structured_agents.agent.Agent.from_bundle()` but injects Remora metadata: config-based env overrides and the event bus observer.

## Contract Touchpoints
- `execute_agent()` calls `Agent.from_bundle(..., observer=event_bus, data_provider=CairnDataProvider(workspace), result_handler=CairnResultHandler())`.
- `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` are set from `RemoraConfig.model` before `Agent.from_bundle()` runs.
- Event emission uses the unified EventBus (`GraphStartEvent`, `AgentStartEvent`, `AgentCompleteEvent`, `AgentErrorEvent`).

## Done Criteria
- Ready nodes execute with bounded concurrency and dependency ordering.
- Agent runs use Cairn workspace overlays plus data provider/result handler wiring.
- Error policies (`stop_graph`, `skip_downstream`, `continue`) behave as configured.

## Steps
1. Implement `executor.GraphExecutor` with `run(graph, observer, config, bundle_metadata)`, tracking `ExecutorState` (completed nodes, results, pending nodes). Emit `GraphStartEvent`/`AgentStartEvent`/`AgentCompleteEvent` via the bus.
2. Within `run`, use a bounded semaphore to limit concurrency, call `get_ready_nodes()` from `graph.py`, create Cairn workspaces per agent, and call `execute_agent()` for each ready node.
3. Implement `execute_agent(node, workspace, config, observer)` that sets `STRUCTURED_AGENTS_BASE_URL/API_KEY` from `RemoraConfig.model`, constructs a `Agent` via `Agent.from_bundle(bundle_path, observer=event_bus, data_provider=CairnDataProvider(workspace), result_handler=CairnResultHandler())`, and returns the `RunResult`.
4. Handle error policies by inspecting `Agent.run()` results: propagate errors, skip downstream nodes or abort the graph as configured, and emit `AgentErrorEvent` when necessary.
