# Remora V0.4.3 Refactoring Guide

Date: 2026-02-26
Target: V0.4.3
Scope: Fix all issues from V042_CODE_REVIEW.md and align with Grail v3.0.0, structured-agents v0.3.4, and Cairn runtime APIs.

## Goals
- Make the core graph execution functional end-to-end.
- Use Cairn as the workspace layer and avoid direct fsdantic usage in Remora.
- Update all agent bundles to structured-agents v0.3 format.
- Keep single-bundle-per-node-type mapping (no multi-bundle dispatch).
- Run Grail tools with workspace-backed virtual FS and external helpers.
- Clean up docs/tests to reflect the new API and config schema.

## Non-Goals
- Backwards compatibility with pre-v0.4.2 config, bundles, or APIs.
- Multi-bundle-per-node-type selection logic (not in scope).

## Key Decisions
- **Workspace layer:** Remora will only use Cairn APIs (no direct fsdantic imports). Any fsdantic usage stays inside Cairn modules.
- **Bundles:** structured-agents schema only (`initial_context`, `agents_dir`, `grammar` object). Remora-specific fields remain allowed.
- **Tool execution:** Remora provides a custom Grail tool runner that injects Cairn external helpers and a virtual filesystem per run.

## Target Architecture (High Level)
1) `GraphExecutor` builds per-agent workspace via Cairn workspace manager.
2) Grail tools execute with:
   - `files` dict (virtual FS) built from workspace contents.
   - `externals` from `cairn.runtime.external_functions.create_external_functions`.
3) Remora captures tool outcomes, emits structured events, and returns `ResultSummary`.

---

## Phase 0: Pre-Refactor Cleanup

### Actions
- Remove or update modules that reference legacy types:
  - `src/remora/client.py` uses `ServerConfig` (remove or update to `ModelConfig`).
  - `src/remora/__init__.py` exports `execute_agent` that does not exist.
- Bump version in `pyproject.toml` to `0.4.3`.

### Verification
- `python -c "import remora"` succeeds.

---

## Phase 1: Configuration Schema + Bundles (New Baseline)

### 1.1 Update `remora.yaml` and `remora.yaml.example`
Use the new schema from `src/remora/config.py`:

```yaml
bundles:
  path: agents
  mapping:
    function: lint/bundle.yaml
    class: docstring/bundle.yaml
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

workspace:
  base_path: ".remora/workspaces"
  cleanup_after: "1h"
```

### 1.2 Update `docs/CONFIGURATION.md` and README
- Replace legacy `server`, `operations`, `bundle_metadata` blocks with `bundles`, `model`, `execution`.
- Remove `remora analyze` and other outdated CLI commands from `docs/API_REFERENCE.md`.

### Verification
- `load_config()` parses the repo `remora.yaml` without errors.

---

## Phase 2: Cairn Workspace Bridge (No Direct Fsdantic)

### 2.1 Create a Cairn workspace service
New module: `src/remora/cairn_bridge.py`.

Responsibilities:
- Initialize a stable workspace (project snapshot) using Cairn APIs.
- Create per-agent workspaces for overlays.
- Build external helper map via Cairn.

Recommended approach:
- Use `cairn.runtime.workspace_manager.WorkspaceManager` for lifecycle.
- Use `cairn.runtime.external_functions.create_external_functions` for externals.
- Use Cairn `FileWatcher` or explicit file sync into the stable workspace (keep the choice explicit).

Pseudo-API:
```python
class CairnWorkspaceService:
    async def initialize(self, project_root: Path) -> None: ...
    async def get_agent_workspace(self, graph_id: str, agent_id: str) -> AgentWorkspace: ...
    async def get_externals(self, agent_id: str, agent_fs, stable_fs) -> ExternalTools: ...
    async def close(self) -> None: ...
```

**Important:** Remora should not import `fsdantic` directly. Treat any `Workspace` types as opaque from Cairn.

### 2.2 AgentWorkspace Wrapper
Update `src/remora/workspace.py` to wrap Cairn workspaces:
- Methods should use `workspace.files.*` instead of `workspace.read/write`.
- Provide `read`, `write`, `exists`, `list_dir` using Cairn `Workspace.files`.
- Drop `accept`/`reject` unless Cairn exposes overlay merge semantics via a stable API.

### Verification
- Creating a workspace and reading a file from it succeeds with Cairn APIs.

---

## Phase 3: Structured-Agents + Grail Tool Integration

### 3.1 Update bundle.yaml format
All bundles must conform to structured-agents v0.3 format.

Example:
```yaml
name: lint
model: qwen

initial_context:
  system_prompt: |
    You are a linting agent. Analyze the provided code and fix issues.

grammar:
  strategy: ebnf
  allow_parallel_calls: false
  send_tools_to_api: false

agents_dir: tools
max_turns: 8

# Remora extensions
node_types: [function, class]
priority: 10
requires_context: true
```

Notes:
- `system_prompt` moves under `initial_context`.
- `grammar` must be a dict.
- `agents_dir` should point at the `tools/` directory.

### 3.2 Custom Grail tool runner
Structured-agents’ `GrailTool` does not accept externals/files. Implement a Remora-specific tool wrapper:

**Requirements:**
- Load scripts with `grail.load()` (v3) and run with `files` and `externals`.
- Pass `externals` from Cairn `create_external_functions`.
- Pass `files` dict built from the workspace and target node.

**Suggested API:**
```python
class RemoraGrailTool(Tool):
    def __init__(self, script_path: Path, workspace: AgentWorkspace, externals: ExternalTools, files_provider: FilesProvider): ...
    async def execute(self, arguments: dict[str, Any], context: ToolCall | None) -> ToolResult: ...
```

**Virtual FS strategy:**
- Build a `files` dict keyed by project-relative path with a leading `/`.
- Always include the target file and any related files (limit to N files).
- Provide this dict to `script.run(files=...)`.

### 3.3 Agent/kernel construction
Replace `Agent.from_bundle` usage with explicit kernel wiring:
- Use structured-agents `load_manifest` to read `bundle.yaml`.
- Build `ModelAdapter` and `AgentKernel` explicitly.
- Inject Remora tools list and the event bus observer.
- Use `build_client` with explicit base_url and api_key (no env reliance).

### Verification
- A bundle loads with tools and system prompt.
- A tool run sees `externals` and can access virtual FS files.

---

## Phase 4: Graph Executor + Result Flow

### 4.1 Executor uses Cairn workspace service
- Replace `WorkspaceManager` in `GraphExecutor` with `CairnWorkspaceService`.
- Build `externals` once per agent and pass to tool runner.
- Enforce `ExecutionConfig.timeout` via `asyncio.wait_for` on `kernel.run()`.

### 4.2 ResultSummary and submit_result
- Use Cairn `SubmissionRecord` from `cairn.orchestrator.lifecycle` to read the `submit_result` payload after tool execution.
- Prefer `submit_result` summary if available; otherwise fall back to model output.
- Emit `AgentCompleteEvent` with a short summary string.

### 4.3 Graph event consistency
- Ensure `GraphStartEvent` and `GraphCompleteEvent` counts are correct.
- Add `TurnCompleteEvent` re-export to `remora.events` for full structured-agents coverage.

### Verification
- A full graph run completes with non-empty summaries and events.

---

## Phase 5: Context Builder Fixes

### Actions
- Update pattern matching in `ContextBuilder.handle`:
  - Use `ToolResultEvent(tool_name=..., output_preview=...)`.
  - Use `AgentCompleteEvent.result_summary`.
- Add getters for recent actions and knowledge if tests depend on them.

### Verification
- Recent actions show up in prompt context after tool calls.

---

## Phase 6: Dashboard Fixes

### Actions
- Only record events in one place (remove double record in `views.py`).
- Use `result_summary` for results panel.
- Emit SSE JSON payloads with `json.dumps`.
- Consider using `GraphStartEvent.node_count` to set total agent count.

### Verification
- Dashboard results list displays summaries.
- SSE stream is valid JSON.

---

## Phase 7: Indexer Strategy (Options + Decision)

### Option A: Keep Indexer First-Class in Remora
**Pros**
- Single package and version; simpler user install.
- Easier shared configuration and event bus integration.
- Keeps close coupling with Remora workflows.

**Cons**
- Keeps long-running daemon inside core runtime.
- Adds dependencies and operational complexity to the base package.

**Implications**
- Maintain indexer config under `RemoraConfig`.
- Must ensure indexer Grail scripts are shipped in-repo and path-resolved.

### Option B: Split Indexer into Separate Package/Service
**Pros**
- Cleaner Remora core with fewer dependencies.
- Independent release cycle and operational model.
- Can scale or deploy separately.

**Cons**
- Requires shared schema/IPC contract.
- Extra operational overhead for users.

**Implications**
- Define an explicit interface for Remora to read indexer outputs (file paths + metadata).
- Remove indexer modules from Remora core or guard them behind optional extras.

### Option C: Hybrid (Optional Plugin)
**Pros**
- Default lightweight core; optional indexer install.
- Preserves ability to run in-process for dev.

**Cons**
- More conditional code paths.

**Recommendation**
Pick Option C if you want a lightweight core with optional power features. Otherwise choose Option A for simplicity in the short term.

---

## Phase 8: Tests + Docs Alignment

### Tests
- Replace pre-refactor tests in `tests/` with API-aligned tests:
  - Config parsing with new schema.
  - Discovery returning `CSTNode` list.
  - Graph build with single-bundle-per-node-type.
  - Executor run with a mocked Grail tool and fake model client.
- Remove or update fuzzing/benchmark tests that use obsolete APIs.

### Docs
- Update `README.md`, `docs/ARCHITECTURE.md`, `docs/API_REFERENCE.md` to match new flow and CLI commands.

### Verification
- `pytest -q` passes with refactored tests.

---

## Final Verification Checklist
- [ ] `remora.yaml` is parseable with `load_config()`.
- [ ] Bundles load with structured-agents format and tools are discovered.
- [ ] Grail tools run with virtual FS and Cairn externals.
- [ ] Workspace operations work via Cairn API (no fsdantic imports in Remora).
- [ ] Graph execution completes and emits events.
- [ ] Dashboard shows correct summaries and valid SSE JSON.
- [ ] Tests and docs reflect the new architecture.

---

## Appendix: Suggested File Changes (High Level)

- Replace `src/remora/workspace.py` with Cairn-based wrapper.
- Add `src/remora/cairn_bridge.py` (workspace + externals + virtual FS builder).
- Update `src/remora/executor.py` to build kernels explicitly and enforce timeout.
- Update bundles under `agents/*/bundle.yaml` to structured-agents schema.
- Update `remora.yaml`, `remora.yaml.example`, and docs to new schema.
- Remove or fix legacy modules and exports (`client.py`, `execute_agent`).

