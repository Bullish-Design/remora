# API Reference

This document summarizes the public CLI commands and Python APIs available in Remora.

## CLI

### `remora analyze`

Run analysis on files or directories.

Key flags:
- `--operations`: Comma-separated operations (default: `lint,test,docstring`).
- `--format`: `table`, `json`, or `interactive`.
- `--config`: Path to `remora.yaml`.
- `--auto-accept`: Auto-accept successful results.
- `--max-turns`, `--max-tokens`, `--temperature`, `--tool-choice`: Runner overrides.
- `--query-pack`, `--agents-dir`: Discovery and agent overrides.
- `--max-concurrent-agents`, `--cairn-timeout`, `--cairn-home`: Cairn overrides.
- `--event-stream`, `--event-stream-file`: Event stream overrides.

### `remora watch`

Watch paths for changes and re-run analysis. Uses the `watch` configuration block.

Additional flag:
- `--debounce`: Debounce delay in milliseconds.

### `remora config`

Print the resolved configuration after merging defaults, file values, and CLI overrides.
Includes the `hub_mode` execution context setting (`in-process`, `daemon`, or `disabled`).

### `remora list-agents`

List available bundle definitions, Grail validation status, and model adapter availability.

### `remora-hub`

Manage the optional Hub daemon.

- `remora-hub start [--project-root PATH] [--db-path PATH] [--foreground/--background]`
- `remora-hub status [--project-root PATH]`
- `remora-hub stop [--project-root PATH]`

## Python Modules

### `remora.config`

Configuration models and helpers.

- `RemoraConfig`
- `DiscoveryConfig`, `ServerConfig`, `RunnerConfig`, `OperationConfig`
- `CairnConfig`, `EventStreamConfig`, `LlmLogConfig`, `WatchConfig`
- `load_config(config_path=None, overrides=None) -> RemoraConfig`
- `resolve_grail_limits(config: CairnConfig) -> dict[str, Any]`
- `serialize_config(config: RemoraConfig) -> dict[str, Any]`

### `remora.analyzer`

Programmatic API for running analysis.

- `RemoraAnalyzer(config, event_emitter=None)`
  - `analyze(paths: list[Path], operations: list[str] | None = None) -> AnalysisResults`
  - `accept(node_id: str | None = None, operation: str | None = None) -> None`
  - `reject(node_id: str | None = None, operation: str | None = None) -> None`
  - `retry(node_id: str, operation: str, config_override: dict | None = None) -> AgentResult`
  - `bulk_accept(...)`, `bulk_reject(...)`

### `remora.presenter`

Formatting and presenting analysis results.

- `ResultPresenter(format_type="table")`
  - `present(results: AnalysisResults) -> None`

### `remora.workspace_bridge`

Bridge for Cairn workspace merging and discarding operations.

- `CairnWorkspaceBridge(workspace_manager, project_root, cache_root)`
  - `merge(workspace_id: str) -> None`
  - `discard(workspace_id: str) -> None`

### `remora.constants`

Centralized configuration constants.

### `remora.orchestrator`

- `Coordinator(config, event_stream_enabled=None, event_stream_output=None)`
  - `process_node(node: CSTNode, operations: list[str]) -> NodeResult`
  - Async context manager for cleanup
- `RemoraAgentContext` and `RemoraAgentState`

### `remora.kernel_runner`

- `KernelRunner(node, ctx, config, bundle_path, event_emitter, workspace_path=None, stable_path=None)`
  - `run() -> AgentResult`

### `remora.discovery`

- `TreeSitterDiscoverer(root_dirs, query_pack, query_dir=None, languages=None)`
  - `discover() -> list[CSTNode]`
- `CSTNode` (node_type is now a string: "file", "class", "function", "method", etc.)

### `remora.events`

- `EventEmitter` protocol
- `JsonlEventEmitter`, `NullEventEmitter`, `CompositeEventEmitter`
- `EventName`, `EventStatus`

### `remora.watcher`

- `RemoraFileWatcher(watch_paths, on_changes, ...)`
  - `start()` / `stop()`
- `FileChange`

### `remora.context`

- `ContextManager`
- `DecisionPacket` models

### `remora.context.hub_client`

- `HubClient`
- `get_hub_client()`
