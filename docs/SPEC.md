# Remora Technical Specification

## 1. Command-Line Interface

### 1.1 `remora run`

Execute an agent graph on the specified paths.

```bash
remora run [PATHS...] [--config PATH]
```

**Arguments:**
- `PATHS`: Files or directories to analyze (default: `discovery.paths`).

**Options:**
- `--config`: Path to configuration file.

### 1.2 `remora serve`

Start the service server.

```bash
remora serve [--host HOST] [--port PORT]
```

### 1.3 `remora-index`

Start the indexer daemon.

```bash
remora-index [PATHS...]
```

## 2. Bundle Format

Bundles live under `agents/<operation>/bundle.yaml` and are loaded by `structured-agents`.

Key fields:
- `name`: Bundle name (e.g., `lint_agent`).
- `model`: Model adapter configuration (plugin, adapter, grammar).
- `initial_context`: `system_prompt` and `user_template`.
- `max_turns`: Maximum turns per run.
- `termination_tool`: Tool name used to terminate the run.
- `tools`: Tool catalog entries (name, registry, description, inputs_override, context_providers).
- `registries`: Registry configuration (typically `grail` with `agents_dir: tools`).

## 3. Data Models

### 3.1 CST Node

```python
class CSTNode:
    node_id: str
    node_type: str  # "file", "class", "function", "method", "table", "section", etc.
    name: str
    file_path: Path
    start_byte: int
    end_byte: int
    text: str
    start_line: int
    end_line: int
    full_name: str
```

### 3.2 Agent Result

```python
class AgentResult:
    status: Literal["success", "failed", "skipped"]
    workspace_id: str
    changed_files: list[str]
    summary: str
    details: dict[str, Any]
    error: str | None
```

### 3.3 Node Result

```python
class NodeResult:
    node_id: str
    node_name: str
    file_path: Path
    operations: dict[str, AgentResult]
    errors: list[dict[str, Any]]
```

### 3.4 Analysis Results

```python
class AnalysisResults:
    nodes: list[NodeResult]
    total_nodes: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    skipped_operations: int
```

## 4. Event Stream

Event emitters produce JSONL entries with fields such as:

- `event`: `agent_start`, `model_request`, `tool_call`, `tool_result`, `agent_complete`, etc.
- `agent_id`, `node_id`, `operation`
- `turn`, `duration_ms`, `status`

## 5. Workspace Lifecycle

Each agent run uses a unique workspace located under `~/.cache/remora/workspaces/<agent_id>` (or `cairn.home`). Successful workspaces can be merged into the project root via `RemoraAnalyzer.accept()` or `--auto-accept`.

## 6. Error Codes

Remora uses standardized error codes from `remora.errors`:

- `REMORA-CONFIG` for configuration issues.
- `REMORA-DISCOVERY` for discovery issues.
- `REMORA-AGENT` for bundle/tool issues.
- `REMORA-EXEC` for execution/runtime issues.
