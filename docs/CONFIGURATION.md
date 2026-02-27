# Configuration Schema

This document describes the `remora.yaml` schema for Remora v0.4.3 and how to configure core components.

## File Resolution

- Default filename: `remora.yaml` in the current working directory.
- CLI commands accept `--config` where supported.

## Example

```yaml
bundles:
  path: agents
  mapping:
    function: lint/bundle.yaml
    class: docstring/bundle.yaml
    method: docstring/bundle.yaml
    file: lint/bundle.yaml

discovery:
  paths: ["src/"]
  languages: ["python"]
  max_workers: 4

model:
  base_url: "http://remora-server:8000/v1"
  api_key: "EMPTY"
  default_model: "Qwen/Qwen3-4B"

execution:
  max_concurrency: 4
  error_policy: skip_downstream
  timeout: 300
  max_turns: 8
  truncation_limit: 1024

indexer:
  watch_paths: ["src/"]
  store_path: ".remora/index"

dashboard:
  host: "0.0.0.0"
  port: 8420

workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"
```

## Top-Level Keys

### `bundles`
Mapping from node type to bundle path (single bundle per node type).

- `path`: base directory for bundles (default: `agents/`).
- `mapping`: map node type string (e.g., `function`, `class`, `file`) to a bundle path relative to `path`.

### `discovery`
Tree-sitter discovery settings.

- `paths`: list of paths (files or directories) to scan.
- `languages`: list of languages (by name, e.g., `python`). If omitted, uses extension mapping.
- `max_workers`: thread pool size for parsing.

### `model`
Default model server configuration.

- `base_url`: OpenAI-compatible API base URL.
- `api_key`: API token (use `EMPTY` for local servers).
- `default_model`: model identifier passed to structured-agents.

### `execution`
Graph execution behavior.

- `max_concurrency`: maximum concurrent agents.
- `error_policy`: `stop_graph`, `skip_downstream`, or `continue`.
- `timeout`: per-agent timeout in seconds.
- `max_turns`: max turns for structured-agents kernel.
- `truncation_limit`: output truncation for summaries.

### `indexer`
Indexer daemon configuration.

- `watch_paths`: list of paths to monitor for changes.
- `store_path`: path to the indexer storage.

### `dashboard`
Dashboard server configuration.

- `host`: bind host.
- `port`: bind port.

### `workspace`
Workspace settings.

- `base_path`: directory for workspace storage.
- `cleanup_after`: duration string used by cleanup routines.

## Environment Overrides

Environment variables override config values on load:

- `REMORA_MODEL_BASE_URL`
- `REMORA_MODEL_API_KEY`
- `REMORA_MODEL_DEFAULT`
- `REMORA_EXECUTION_MAX_CONCURRENCY`
- `REMORA_EXECUTION_TIMEOUT`
- `REMORA_DASHBOARD_PORT`
- `REMORA_WORKSPACE_BASE_PATH`
