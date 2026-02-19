# API Reference

This document summarizes the public CLI commands and Python APIs available in Remora. It is hand-written and does not rely on Sphinx/MkDocs.

## CLI

### `remora analyze`
Run analysis on files or directories.

Key flags:
- `--operations`: Comma-separated operations (default: `lint,test,docstring`).
- `--format`: `table`, `json`, or `interactive`.
- `--config`: Path to `remora.yaml`.
- `--auto-accept`: Auto-accept successful results.
- `--max-turns`, `--max-tokens`, `--temperature`, `--tool-choice`: Runner overrides.
- `--discovery-language`, `--query-pack`, `--agents-dir`: Discovery and agent overrides.
- `--cairn-home`, `--max-concurrent-agents`, `--cairn-timeout`: Cairn overrides.
- `--event-stream`, `--event-stream-file`: Event stream overrides.

### `remora watch`
Watch paths for changes and re-run analysis. Uses the `watch` configuration block.

### `remora config`
Print the resolved configuration after merging defaults, file values, and CLI overrides.

### `remora list-agents`
List available subagent definitions and their status.

## Python Modules

### `remora.config`
Configuration models and helpers.

- `RemoraConfig`: Root configuration model.
- `DiscoveryConfig`, `ServerConfig`, `RunnerConfig`, `OperationConfig`.
- `CairnConfig`, `EventStreamConfig`, `LlmLogConfig`, `WatchConfig`.
- `load_config(config_path=None, overrides=None) -> RemoraConfig`.
- `resolve_grail_limits(config: CairnConfig) -> dict[str, Any]`.
- `serialize_config(config: RemoraConfig) -> dict[str, Any]`.

### `remora.analyzer`
Programmatic API for running analysis.

- `RemoraAnalyzer(config, event_emitter=None)`
  - `analyze(paths: list[Path], operations: list[str] | None = None) -> AnalysisResults`
  - `accept(node_id: str | None = None, operation: str | None = None) -> None`
  - `reject(node_id: str | None = None, operation: str | None = None) -> None`
  - `get_results() -> AnalysisResults | None`

### `remora.orchestrator`
Coordinates discovery and execution.

- `Coordinator(config, event_stream_enabled=None, event_stream_output=None)`
  - `process_node(node: CSTNode, operations: list[str]) -> NodeResult`
  - Async context manager to ensure shutdown/cleanup.
- `RemoraAgentContext`: Tracks agent lifecycle state.

### `remora.runner`
Runs the model loop for a single node/operation.

- `FunctionGemmaRunner`
  - `run() -> AgentResult`
- `AgentError`: Structured error with phase and error code.

### `remora.discovery`
Tree-sitter based CST discovery.

- `TreeSitterDiscoverer(root_dirs, language, query_pack, query_dir=None)`
  - `discover() -> list[CSTNode]`
- `CSTNode`, `NodeType` data models.

### `remora.execution`
Grail execution utilities.

- `ProcessIsolatedExecutor(max_workers=4, call_timeout=300.0)`
  - `execute(pym_path, grail_dir, inputs, limits=None, ...) -> dict[str, Any]`
- `SnapshotManager` for pause/resume snapshots.

### `remora.events`
Event streaming and payloads.

- `EventStreamController`, `build_event_emitter()`.
- `EventName`, `EventStatus` constants.

### `remora.watcher`
File change watcher for `remora watch`.

- `RemoraFileWatcher(watch_paths, on_changes, ...)`
  - `start()` / `stop()`
- `FileChange` data model.
