# Configuration Schema

Remora uses a flat configuration in `remora.yaml`.

## File Resolution

- Default filename: `remora.yaml` in the current working directory.
- CLI commands accept `--config` where supported.

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

model_base_url: "http://localhost:8000/v1"
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
  - ".venv"
  - "node_modules"
  - "__pycache__"
workspace_ignore_dotfiles: true

nvim_enabled: false
nvim_socket: ".remora/nvim.sock"
```

## Configuration Keys

### Discovery

- `project_path`: Root of the project (default: ".")
- `discovery_paths`: List of paths to scan (default: ["src/"])
- `discovery_languages`: List of languages to parse (e.g., ["python"])
- `discovery_max_workers`: Thread pool size for parsing (default: 4)

### Bundles

- `bundle_root`: Base directory for agent bundles (default: "agents")
- `bundle_mapping`: Map from node type to bundle path

### Model

- `model_base_url`: OpenAI-compatible API base URL
- `model_api_key`: API token (use "EMPTY" for local servers)
- `model_default`: Default model identifier

### Swarm

- `swarm_root`: Directory for swarm state (default: ".remora")
- `swarm_id`: Swarm identifier (default: "swarm")
- `max_concurrency`: Max concurrent agent executions (default: 4)
- `max_turns`: Max turns for structured-agents kernel (default: 8)
- `truncation_limit`: Output truncation length (default: 1024)
- `timeout_s`: Per-agent timeout in seconds (default: 300.0)
- `max_trigger_depth`: Max recursion depth for trigger chains (default: 5)
- `trigger_cooldown_ms`: Cooldown between triggers (default: 1000)

### Workspace

- `workspace_ignore_patterns`: List of patterns to ignore
- `workspace_ignore_dotfiles`: Whether to ignore dotfiles (default: true)

### Neovim

- `nvim_enabled`: Enable Neovim server (default: false)
- `nvim_socket`: Socket path for Neovim server (default: ".remora/nvim.sock")
