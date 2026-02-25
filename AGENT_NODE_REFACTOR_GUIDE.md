# AgentNode Refactor Guide

## 1. Background and Goals

The new Remora experience is built around **AgentGraphs** and **AgentNodes**. The hub already exposes:
- Auto-generated `graph_id` when none is supplied
- Optional `target_path` (file or directory) to snapshot code
- Workspace metadata and `/graph/list` to let the frontend resume any graph

Our next step is to **align the CLI and tests with this AgentNode-centric stack**:
1. Either rewrite the CLI commands so they construct and execute graphs using the AgentNode APIs (no deprecated analyzer toolchain), or remove the commands completely if they are not needed for the new UI interaction.
2. Clean up or replace any tests that depend on the deprecated modules (`remora.analyzer`, `remora.kernel_runner`, `remora.events`, etc.) so the suite reflects the modern dispatcher.
3. Because the UI relies on the hub features above, add targeted tests that verify the new behaviors (auto graph creation, file/directory launches, workspace listing) instead of the old analyzer expectations.

This guide walks through both the CLI refactor/removal and the resulting test cleanup so a junior developer can execute the work step-by-step.

## 2. CLI Refactor or Removal Strategy

### 2.1 Evaluate Current CLI Surface

Inspect `src/remora/cli.py` and answer:
- Which commands depend on deprecated modules? (`analyze`, `watch`, `list-agents` currently import `RemoraAnalyzer`, `ResultPresenter`, `RemoraFileWatcher`, `GrailToolRegistry`).
- Which commands (e.g., `metrics`, `serve`) already work with the modern Hub/AgentGraph stack? Keep these unchanged.

### 2.2 Decide on Outcome

We will proceed with **Option B: Rebuild the commands on AgentNode APIs**. The deprecated modules stay only long enough for reference, and the goal is to replace `RemoraAnalyzer`, `RemoraFileWatcher`, and `GrailToolRegistry` with modern equivalents. Below is the updated strategy:

1. Keep `list-agents`, but implement it by iterating `config.operations` / manifest files, verifying adapters with `_fetch_models()` (if still relevant), and summarizing readiness (enabled status, file presence, last run metadata).
2. Preserve the CLI options (paths, operations, overrides, event stream settings), but route them through the new AgentGraph helper function for consistent behavior.
3. Remove unused deprecated modules and shim exports only once the refactor is fully wired up and tested.
4. Update CLI tests to exercise the new flow (mock AgentGraph execution, assert outputs, etc.).

### 2.3 Practical Steps for Rebuild
... (rest unchanged)
### 2.3 Practical Steps for Rebuild (if Option B)

1. **Graph Construction Helper**:
   - Create a helper that accepts CLI inputs (paths, operations, bundle name, target) and returns a configured `AgentGraph` plus optional metadata.
   - Use `AgentGraph.agent()` to register nodes with the chosen bundle and target.
   - Capture `workspace` from `GraphWorkspace` and metadata for CLI output.
2. **Execution Flow**:
   - Use `AgentGraph.execute(config)` within `asyncio.run` to run the graph as the CLI currently does.
   - Hook into the `EventBus` or use returned results to determine success/failure counts for exit codes.
3. **Reporter**:
   - Implement a simple formatter in `cli.py` (or a new module) that prints summary results (status, number of agents, any errors). No need to rely on deprecated `ResultPresenter`.
4. **Watch Mode**:
   - Integrate a watcher (watchfiles or simple polling) that triggers the helper from step 1 on change events.
   - Keep `debounce` logic from previous CLI but ensure it wraps the AgentGraph execution.
5. **List Agents (see 2.4 below)**
6. **Testing**:
   - Update CLI tests to reflect the new flow (mock `AgentGraph` execution, inspect logs, etc.).

### 2.4 Rebuilding `list_agents` via AgentNode APIs

> The legacy command iterated over Grail bundles and relied on `RemoraAnalyzer`/`GrailToolRegistry`. The new AgentNode-focused CLI should instead reflect what the hub and UI care about: available bundles/operations configured for the project, their execution status, and whether required artifacts (YAML/agent directories) exist.

Steps:
1. **Load the same configuration** you already use elsewhere in `cli.py` (`load_config(config_path)`).
2. **Iterate `config.operations`**:
   - Each entry already maps an operation name to a YAML manifest (`op_config.subagent`), whether it's enabled, and what bundle it points to.
   - Use `config.agents_dir` / `op_config.subagent` to resolve the manifest file for each operation and check whether it exists on disk.
3. **Assess execution readiness**:
   - For each operation, check `op_config.enabled`.
   - Optionally ensure the YAML exists and consider calling (or mocking) whatever Asset loader the UI uses to parse manifest metadata (e.g., bundle name, inputs).
4. **Model availability (if still relevant)**:
   - Reuse `_fetch_models()` to decide whether the adapter referenced by the operation is available from the configured server.
5. **Build and display a summary**:
   - For each operation, print or output JSON with fields like `name`, `enabled`, `yaml_exists`, `adapter`, `model_available`, and `last_run` if you track it via workspace metadata.
   - There's no need to construct agents or run graphs; you are simply showing the configs the AgentNode graph would use.
6. **Testing**:
   - Write unit tests that stub `load_config()` and assert `list_agents` outputs the expected structure.

Because the UI now drives graph execution, `list_agents` only needs to be informative: it ensures users know which configurations exist before launching a graph via the hub. This avoids dragging the deprecated analyzer/tool registry code into the new stack.

## 3. Testing Cleanup and Refresh

### 3.1 Audit Existing Tests

1. List all tests importing the deprecated modules (use `rg -n 'from remora\.analyzer' tests`). Remove or rewrite each:
   - Acceptance/integration tests (`tests/acceptance/*`, `tests/integration/*`, `tests/test_*`) that import deprecated artifacts need to be reviewed.
2. If the test is solely validating the deprecated analyzer pipeline, drop it once the CLI is rewritten.
3. For essential behaviors (watch mode, agent execution), rewrite tests to exercise the new AgentGraph/hub APIs instead of the old analyzer.
4. Remove snapshot fixtures (if any) that rely on the old components.

### 3.2 Update or Remove Dependent Tests

Create a mapping for each problematic test file:
- `tests/test_cli.py`: update to assert new CLI commands produce expected outputs/exits. Use `CliRunner` or call `typer` app if commands exist.
- `tests/test_analyzer.py`, `tests/acceptance/*`: either delete or rework them to use `AgentGraph` directly with sample agents.
- `tests/test_kernel_runner.py`, `tests/test_event_bridge.py`, etc.: Deprecate these tests unless the new AgentNode implementation exposes similar behavior (in that case, create new tests for the equivalent components you actually maintain).
- `tests/test_tool_registry.py`: drop it if Grail tooling is no longer part of the project.
- `tests/test_watcher.py`: rewrite to test your chosen file-watching implementation (if still supported).

Track each file in a table (file, action: delete/replace, new target). Keeping tests up-to-date ensures `pytest` can run without `ModuleNotFoundError`.

### 3.3 Add New Coverage for AgentNode Flow

After CLI/test cleanup, add new tests aligned with the updated functionality:
1. **Hub-level tests**:
   - Verify `POST /graph/execute` auto-generates IDs and snapshots `target_path` (file and directory). Use `TestClient` hitting the Starlette app.
   - Test `GET /graph/list` returns metadata (graph_id, target_path, status). Mock workspace creation and metadata files if needed.
2. **Workspace tests**:
   - Exercise `WorkspaceManager.list_all()` to ensure it discovers on-disk workspaces and loads metadata.
   - Validate `GraphWorkspace.save_metadata()` and `load_metadata()` round-trip.
3. **CLI tests (if commands kept)**:
   - Invoke the rewritten CLI commands and assert they instantiate AgentGraphs and return exit codes.
   - Use dependency injection/mocking to avoid long-running agent executions.
4. **UI contract tests** (optional):
   - If you add APIs specific to the new UI (file/directory endpoints, list), write tests to confirm the JSON responses match expected schemas.

### 3.4 Post-Cleanup Checklist

After refactor:
- Run `pytest` and confirm there are no `ModuleNotFoundError` due to deleted deprecated modules.
- Confirm coverage metrics focus on the new AgentNode components (hub server, workspace, agent graph).
- Update documentation or README to describe the new CLI capabilities or the fact that old commands were removed.

## 4. Ongoing Maintenance Tips

- Keep the CLI slim: avoid reintroducing large legacy subsystems unless they directly unlock new UX flows.
- Always prefer writing tests that exercise AgentGraphs, not the deprecated analyzer pipeline.
- When onboarding future devs, point them to this guide to understand why the old modules were removed and where the new behavior lives.

Happy refactoring! If you need help drafting the new CLI helper or test skeletons, let me know and I can supply templates.