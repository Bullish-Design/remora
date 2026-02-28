# Configuration Schema

Remora loads a single flat configuration file (`remora.yaml`) and exposes every
setting as a top-level key. CLI commands can override the path with `--config`.

## File Resolution

- Default filename: `remora.yaml` in the current working directory.
- When running inside a project directory, the CLI searches upward until it
  reaches the filesystem root or a directory with a `pyproject.toml`.

## Example

```yaml
project_path: "."
discovery_paths: ["src/"]
discovery_languages: ["python"]
discovery_max_workers: 4

bundle_root: "agents"
bundle_mapping:
  function: "lint/bundle.yaml"
  class: "docstring/bundle.yaml"
  method: "docstring/bundle.yaml"
  file: "lint/bundle.yaml"

model_base_url: "http://remora-server:8000/v1"
model_api_key: "EMPTY"
model_default: "Qwen/Qwen3-4B"

swarm_root: ".remora"
swarm_id: "swarm"
max_concurrency: 4
max_turns: 8
truncation_limit: 1024
timeout_s: 300.0
max_trigger_depth: 5
trigger_cooldown_ms: 1000

workspace_ignore_patterns:
  - ".git"
  - "__pycache__"
workspace_ignore_dotfiles: false

nvim_enabled: false
nvim_socket: ".remora/nvim.sock"
```

## Configuration Keys

### Discovery

- `project_path`: Root of the project (default: `.`).
- `discovery_paths`: A list of relative paths that Remora should scan.
- `discovery_languages`: Optional list of languages to restrict parsing.
- `discovery_max_workers`: Thread pool size for parsing (default: `4`).

### Bundles

- `bundle_root`: Directory where agent bundles live (default: `"agents"`).
- `bundle_mapping`: Mapping from node types (e.g., `function`, `class`)
  to bundle YAML files.

### Model

- `model_base_url`: Base URL of the OpenAI-compatible model endpoint.
- `model_api_key`: API key/token (use `"EMPTY"` for local servers).
- `model_default`: Default model identifier (e.g., `"Qwen/Qwen3-4B"`).

### Swarm

- `swarm_root`: Directory housing swarm state (default: `.remora`).
- `swarm_id`: Identifier for the reactive swarm instance.
- `max_concurrency`: Maximum concurrent agent executions.
- `max_turns`: Max turns per agent kernel run.
- `truncation_limit`: Maximum output truncation length for prompts.
- `timeout_s`: Per-agent timeout (seconds).
- `max_trigger_depth`: Maximum recursion depth for trigger chains.
- `trigger_cooldown_ms`: Cooldown in milliseconds between triggers.

### Workspace

- `workspace_ignore_patterns`: List of path parts to ignore when syncing
  project files into Cairn (defaults include `.git`, `__pycache__`, etc.).
- `workspace_ignore_dotfiles`: Whether to skip dotfiles (default: `true`).

### Neovim

- `nvim_enabled`: Whether to start a Neovim server when running
  `remora swarm start`.
- `nvim_socket`: Socket path for the Neovim server.
