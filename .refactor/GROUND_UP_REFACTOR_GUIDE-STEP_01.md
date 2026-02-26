# Implementation Guide: Step 1 - Foundation Systems

## Target
Align Remora's configuration, event taxonomy, and discovery surface with the v0.4.0 architecture so every component consumes a single source of truth and observes the unified EventBus.

## Overview
- Load `remora.yaml` once into a frozen `RemoraConfig`, serve slices to discovery, workspace, executor, and services, and record each bundle's Remora-only metadata (`node_types`, `priority`, `requires_context`).
- Define all graph-, agent-, and human-IO events plus structured-agents kernel events inside `events.py` and re-export them through the bus.
- Collapse discovery into `discovery.py` that emits deterministic `CSTNode` dataclasses from the `.scm` query set, then feed those nodes downstream.

## Contract Touchpoints
- `EventBus` implements `structured_agents.events.observer.Observer` and is the only observer wired into executor, context builder, and dashboard.
- `events.py` exports structured-agents kernel events alongside Remora events for downstream subscribers.
- `discovery.discover()` returns frozen `CSTNode` records consumed by graph building.

## Done Criteria
- `RemoraConfig` loads once and all components receive slices by reference.
- EventBus supports typed `subscribe`/`stream`/`wait_for` and emits declared events.
- Discovery returns deterministic `CSTNode` records from `.scm` queries.

## Steps
1. Implement `remora.config.RemoraConfig` with dataclasses for discovery, bundles, execution, indexer, dashboard, workspace, and model sections; validate once and pass references explicitly.
2. Write `events.py` to declare `GraphStartEvent`, `AgentCompleteEvent`, `HumanInputRequestEvent`, the structured-agents kernel events, and the `RemoraEvent` union.
3. Build `event_bus.EventBus` that implements `structured_agents.events.observer.Observer`, supports type-based `subscribe`/`stream`/`wait_for`, and is the only bus used by the executor, context builder, and dashboard.
4. Rewrite discovery into `discovery.py` with a simple `discover(paths, languages, node_types, max_workers)` function that returns frozen `CSTNode` records built from tree-sitter queries in `queries/`.
