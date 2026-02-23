# Remora Technical Specification

## 1. Command-Line Interface

### 1.1 `remora analyze`

Analyze Python code and generate results.

```bash
remora analyze [PATHS...] [OPTIONS]
```

**Arguments:**
- `PATHS`: Files or directories to analyze (default: current directory).

**Options:**
- `--operations, -o`: Comma-separated list of operations (`lint,test,docstring` by default).
- `--config, -c`: Path to configuration file.
- `--format, -f`: `table`, `json`, or `interactive`.
- `--auto-accept`: Auto-merge successful results.
- `--query-pack`, `--agents-dir`: Discovery overrides.
- `--max-turns`, `--max-tokens`, `--temperature`, `--tool-choice`: Runner overrides.
- `--cairn-home`, `--max-concurrent-agents`, `--cairn-timeout`: Cairn overrides.
- `--event-stream`, `--event-stream-file`: Event stream overrides.

Exit codes:
- `0`: All operations succeeded.
- `1`: Partial failure.
- `2`: All operations failed or no results.

### 1.2 `remora watch`

Watch paths and re-run analysis on changes.

```bash
remora watch [PATHS...] [OPTIONS]
```

Additional option:
- `--debounce`: Debounce delay in milliseconds.

### 1.3 `remora list-agents`

List bundle definitions and model availability.

```bash
remora list-agents [--format table|json]
```

### 1.4 `remora config`

Print the merged configuration.

```bash
remora config [--format yaml|json]
```

### 1.5 `remora-hub`

Manage the Hub daemon:

```bash
remora-hub start [--project-root PATH] [--db-path PATH]
remora-hub status [--project-root PATH]
remora-hub stop [--project-root PATH]
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
