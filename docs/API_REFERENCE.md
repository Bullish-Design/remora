# API Reference

This document summarizes the public CLI commands and Python APIs available in Remora.

## CLI

### `remora serve`

Start the Remora service (Starlette adapter).

Key flags:

- `--host`, `--port`: bind address for the service.
- `--project-root`: override the root directory used for relative targets.
- `--config`: path to `remora.yaml`.

### `remora run`

Run a graph execution for a target path.

Key flags:

- `--config`: path to `remora.yaml`.

### `remora-index`

Start the indexer daemon.

Key flags:

- `--watch-paths`: paths to monitor for changes.
- `--store-path`: path to the index store.

## Python Modules

### Core Runtime (`remora.core`)

Framework-agnostic runtime modules:

- `remora.core.config`: `RemoraConfig`, `ExecutionConfig`, `BundleConfig`, `load_config()`
- `remora.core.discovery`: `discover()`, `CSTNode`, `TreeSitterDiscoverer`
- `remora.core.graph`: `AgentNode`, `build_graph()`, `get_execution_batches()`
- `remora.core.executor`: `GraphExecutor`, `ExecutorState`, `AgentState`
- `remora.core.event_bus`: `EventBus` (explicit injection recommended; `get_event_bus()` remains for legacy usage)
- `remora.core.events`: Remora + structured-agent event classes
- `remora.core.workspace`: Cairn workspace helpers
- `remora.core.checkpoint`: `CheckpointManager`

### Service Layer

- `remora.service.RemoraService`: framework-agnostic API surface for `/`, `/subscribe`, `/events`, `/run`, `/input`, `/plan`, `/config`, `/snapshot`
- `remora.service.RemoraService.create_default()`: convenience constructor that creates a service with a fresh EventBus and loaded config
- `remora.adapters.starlette.create_app`: Starlette adapter for the service

### UI Helpers

- `remora.ui.projector.UiStateProjector`: event → UI state reducer
- `remora.ui.view.render_dashboard`: HTML snapshot renderer

### Models

- `remora.models.RunRequest`, `RunResponse`
- `remora.models.PlanRequest`, `PlanResponse`
- `remora.models.InputResponse`
- `remora.models.ConfigSnapshot`
