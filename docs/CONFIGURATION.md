# Configuration Schema

This document describes the `remora.yaml` schema, defaults, and how CLI overrides apply.

## File Resolution

- Default filename: `remora.yaml` in the current working directory.
- Use `remora analyze --config path/to/remora.yaml` to load a specific file.

## Example

```yaml
agents_dir: agents
hub_mode: disabled

server:
  base_url: http://remora-server:8000/v1
  api_key: EMPTY
  timeout: 120
  default_adapter: google/functiongemma-270m-it
  retry:
    max_attempts: 3
    initial_delay: 1.0
    max_delay: 30.0
    backoff_factor: 2.0

discovery:
  language: python
  query_pack: remora_core
  query_dir: null

operations:
  lint:
    enabled: true
    auto_accept: false
    subagent: lint
    priority: normal
  test:
    enabled: true
    auto_accept: false
    subagent: test
    priority: high
  docstring:
    enabled: true
    auto_accept: false
    subagent: docstring
    priority: normal
    style: google
  sample_data:
    enabled: false
    auto_accept: false
    subagent: sample_data
    priority: low

runner:
  max_turns: 20
  max_tokens: 4096
  temperature: 0.1
  tool_choice: auto
  max_history_messages: 50

cairn:
  home: null
  max_concurrent_agents: 16
  timeout: 300
  limits_preset: default
  limits_override: {}
  pool_workers: 4
  max_queue_size: 100
  workspace_cache_size: 100
  enable_snapshots: false
  max_snapshots: 50
  max_resumes_per_script: 5

event_stream:
  enabled: false
  output: null
  control_file: null
  include_payloads: true
  max_payload_chars: 4000

llm_log:
  enabled: false
  output: null
  include_full_prompts: false
  max_content_lines: 100

watch:
  extensions: [".py"]
  ignore_patterns:
    - __pycache__
    - .git
    - .jj
    - .venv
    - node_modules
    - .remora_cache
    - .agentfs
  debounce_ms: 500
```

## Top-Level Keys

### `agents_dir`

Path to the `agents/` directory containing bundle definitions. Relative paths are resolved against the config file directory.

### `hub_mode`

Hub daemon execution context setting.

- `hub_mode`: Can be `in-process`, `daemon`, or `disabled` (default). Determines how the state synchronization Hub connects. 

### `server`

Settings for the OpenAI-compatible inference server.

- `base_url`: Server base URL.
- `api_key`: API token (use `EMPTY` for local servers).
- `timeout`: Request timeout in seconds.
- `default_adapter`: Default model/adapter identifier.
- `retry`: Retry policy for transient failures (used by downstream tooling).

### `discovery`

Tree-sitter discovery settings.

- `language`: Language identifier (default `python`).
- `query_pack`: Query pack directory name.
- `query_dir`: Optional custom query directory; `null` uses built-in queries.

### `operations`

Mapping of operation name → operation config. Additional keys are allowed and forwarded to the bundle context.

Common fields:
- `enabled`: Enable/disable the operation.
- `auto_accept`: Auto-merge successful workspaces.
- `subagent`: Directory containing `bundle.yaml` (relative to `agents_dir`).
- `model_id`: Optional adapter override.
- `priority`: `low`, `normal`, or `high`.

### `runner`

Model runner settings.

- `max_turns`: Maximum turns before aborting.
- `max_tokens`: Completion token cap.
- `temperature`: Sampling temperature.
- `tool_choice`: `auto`, `required`, or `none` (passed to structured-agents).
- `max_history_messages`: Maximum conversation history retained by the kernel.

### `cairn`

Grail/Cairn execution settings.

- `home`: Cache directory (defaults to `~/.cache/remora`).
- `max_concurrent_agents`: Concurrency limit.
- `timeout`: Tool execution timeout (seconds).
- `limits_preset`: `strict`, `default`, or `permissive`.
- `limits_override`: Dict merged into preset limits.
- `pool_workers`: Process pool size for tool execution.
- `max_queue_size`: Task queue capacity.
- `workspace_cache_size`: Workspace LRU cache size.
- `enable_snapshots`: Enable pause/resume snapshots.
- `max_snapshots`: Maximum active snapshots.
- `max_resumes_per_script`: Resume attempts per snapshot.

### `event_stream`

Structured event streaming (JSONL).

- `enabled`: Enable event stream output.
- `output`: JSONL output path (defaults to `~/.cache/remora/events.jsonl`).
- `control_file`: Optional control file used by `remora-tui`.
- `include_payloads`: Include full payloads when true.
- `max_payload_chars`: Truncation limit per payload.

### `llm_log`

Human-readable conversation logs.

- `enabled`: Enable transcript logs.
- `output`: File or directory path (defaults to cache dir).
- `include_full_prompts`: Include full prompt text.
- `max_content_lines`: Output line limit per message.

### `watch`

Settings for `remora watch`.

- `extensions`: File extensions to monitor.
- `ignore_patterns`: Path components to skip.
- `debounce_ms`: Debounce window in milliseconds.

## CLI Overrides

CLI flags override configuration values at runtime. Example:

```
remora analyze --max-turns 10 --discovery-language python --query-pack remora_core
```
