# Remora V0.4.3 Code Review Report

Date: 2026-02-26
Reviewer: Codex

## Scope
- Runtime core: `src/remora` (graph, executor, event bus, context, workspace, cairn bridge, tools)
- Discovery and indexing: `src/remora/discovery.py`, `src/remora/indexer/*`
- Dashboard and CLI: `src/remora/dashboard/*`, `src/remora/cli.py`
- Agent bundles and Grail tools: `agents/*`
- Tests: `tests/*` and `docs/TESTING_GUIDELINES.md`
- Docs and specs: `README.md`, `docs/*`, `remora.yaml`

## Executive Summary
The core architecture (event bus + graph executor + Cairn workspace + Grail tools) is solid and much more cohesive than earlier refactors, but there are several functional gaps that will block real-world runs. The most serious issues are: (1) tool outputs that indicate file changes are never persisted into Cairn workspaces, (2) path normalization between discovery and workspaces is inconsistent and will break whenever absolute paths are used, and (3) prompt construction uses stale discovery text instead of workspace content, so agents cannot "see" prior modifications. The indexer also has a type mismatch that will prevent ingestion of tree-sitter results. The dashboard works, but repeated graph runs accumulate duplicate context subscriptions, which will skew context and memory over time.

Testing is currently dominated by unit tests and micro-benchmarks. There is no end-to-end coverage of graph execution, Grail tools, Cairn workspaces, or the real vLLM server. The test suite needs a large expansion focused on "in-use" behavior with real Grail execution, real Cairn workspaces, and real vLLM calls (remora-server:8000). That integration suite should become the primary coverage signal, with unit tests retained only for deterministic components.

## Findings (Ordered by Severity)

### Critical
1) Tool results that indicate file changes are never persisted to Cairn workspaces.
   - Evidence: `src/remora/executor.py:218` uses Grail tools but never processes their outputs; `src/remora/tools/grail.py:69` simply returns the tool output; `src/remora/workspace.py:149` defines `CairnResultHandler` but nothing calls it. Grail scripts frequently return `written_file` + `content` (e.g., `agents/docstring/tools/write_docstring.pym:112`, `agents/test/tools/write_test_file.pym:19`, `agents/lint/tools/apply_fix.pym:66`).
   - Impact: The system reports "success" but no actual code changes happen. This breaks the core "agent writes code in workspace" promise.
   - Recommendation: Wire a result handler into tool execution. Options: (a) make `RemoraGrailTool.execute` parse tool output and call `AgentWorkspace.write` when `written_file`/`content` are present, (b) use `CairnResultHandler` from `GraphExecutor` and update it to support both `written_file`/`content` and `written_files`/`modified_file`, or (c) update tools to call Cairn externals directly (`write_file`, `apply_patch`) so writes happen inside the tool. The current mix of output keys and unused handler needs a unified contract.

2) Workspace file path normalization is inconsistent and fails when discovery yields absolute paths.
   - Evidence: `src/remora/cairn_bridge.py:125` syncs project files into the stable workspace using paths relative to `project_root`. `src/remora/workspace.py:129` loads files using `node.file_path` exactly as discovered. If the discovery path is absolute (common with CLI arguments), the workspace lookup will fail because the stable workspace is indexed by relative paths.
   - Impact: Agents will not receive file contents in prompts or Grail virtual FS, and tools that rely on file reads will fail or see empty content. This creates a silent failure mode for any user invoking Remora with absolute paths.
   - Recommendation: Normalize all `CSTNode.file_path` values to project-relative paths at discovery time, or add a workspace-aware resolver that maps absolute paths to workspace-relative paths before reads/writes. This should be centralized (e.g., in `CairnDataProvider` or a new `PathResolver`).

3) Agents use stale discovery text instead of current workspace content.
   - Evidence: `src/remora/executor.py:342` inserts `node.target.text` into the prompt, even though the workspace file content is already loaded into `files` in `src/remora/executor.py:222`.
   - Impact: Downstream agents do not see changes applied by earlier agents (or by external tools), which leads to conflicting edits, duplicated work, and incorrect summaries. This is especially harmful when running chained agents or multi-pass operations.
   - Recommendation: Use the workspace-loaded content for the code section (e.g., `files[node.target.file_path]`), and fall back to `node.target.text` only if the workspace read fails.

### Major
4) Indexer produces node types that violate `NodeState` schema.
   - Evidence: `src/remora/indexer/scanner.py:67` uses `discover()` and forwards `node.node_type` (e.g., `file`, `method`, `section`) into the node data. `src/remora/indexer/models.py:28` restricts `node_type` to `Literal["function", "class", "module"]`.
   - Impact: Tree-sitter discovery will emit node types that cannot be stored, causing validation errors and dropped index updates during Grail-based extraction (via `src/remora/indexer/rules.py:62`).
   - Recommendation: Either filter discovery results to function/class nodes for indexing or expand `NodeState.node_type` to include the actual discovery node types. The current mismatch will consistently break indexing in real usage.

5) ContextBuilder is subscribed repeatedly in dashboard runs, causing duplicated context and memory growth.
   - Evidence: `src/remora/executor.py:131` subscribes `context_builder.handle` to the event bus each time a `GraphExecutor` is created. The dashboard creates a new executor on each `/run` call while reusing the same context builder (`src/remora/dashboard/views.py:523`).
   - Impact: Each run adds another subscription. Over time, the same event will be processed multiple times, inflating "recent actions" and knowledge summaries and causing prompts to drift. This also leaks memory in a long-running dashboard server.
   - Recommendation: Make subscription idempotent or explicitly unsubscribe on completion. Alternatively, let the dashboard own the subscription and pass a context builder that is not re-subscribed by the executor, or refactor `GraphExecutor` to accept a flag to skip auto-subscription.

6) Grail tool schema generation drops non-primitive input types, which misleads the model.
   - Evidence: `src/remora/tools/grail.py:23` maps only primitive types; complex inputs such as `list[dict[str, Any]]` in `agents/lint/tools/run_linter.pym:9` or `dict[str, Any]` in `agents/test/tools/run_tests.pym:10` become plain strings in the tool schema.
   - Impact: The model receives inaccurate tool schemas and is more likely to produce malformed tool calls, increasing error rates in real executions.
   - Recommendation: Expand `_build_parameters` to handle lists, dicts, and nested schemas based on Grail input annotations, or let Grail provide JSON schema directly if supported.

7) Graph dependency construction depends on input ordering, which can silently drop file-level dependencies.
   - Evidence: `src/remora/graph.py:62` iterates nodes in input order and only adds file-level upstreams if the file node is already in `existing_agents`. If the input list is not pre-sorted with file nodes first, upstream edges will be omitted.
   - Impact: Execution order can become nondeterministic, and file-level prerequisites may be skipped. This is subtle and can lead to incorrect agent ordering for some discoverers.
   - Recommendation: Build a separate map of file nodes first (or compute upstream dependencies without relying on `existing_agents`).

8) Dashboard progress never completes when agents fail.
   - Evidence: `src/remora/dashboard/state.py:66` increments `completed_agents` only for `AgentCompleteEvent`, not for `AgentErrorEvent`.
   - Impact: The UI can show "incomplete" progress forever if any agent fails, even though the graph finished.
   - Recommendation: Count failures as completed for progress (or track separate failed count and display both).

### Moderate
9) Bundle-level execution settings are ignored by the executor.
   - Evidence: Bundles declare fields like `max_turns`, `termination`, and `requires_context` (e.g., `agents/lint/bundle.yaml:15`, `agents/lint/bundle.yaml:16`, `agents/lint/bundle.yaml:22`), but `GraphExecutor._run_agent` uses only `RemoraConfig.execution.max_turns` and always adds context (`src/remora/executor.py:323` and `src/remora/executor.py:348`).
   - Impact: Per-bundle tuning is not honored; graph execution behavior is global and cannot be adjusted per tool/operation.
   - Recommendation: Merge bundle-level settings with config defaults (e.g., use bundle `max_turns` if set; skip context if `requires_context` is false).

10) The CLI spec in docs does not match the implemented CLI commands.
    - Evidence: `docs/SPEC.md:5` documents `remora analyze/watch/list-agents/config` but the actual CLI only exposes `run`, `dashboard`, and `index` (`src/remora/cli.py:25`).
    - Impact: Users will attempt commands that do not exist or rely on options that are no longer wired. This increases support load and creates the perception of missing functionality.
    - Recommendation: Update the spec to reflect current commands or restore the documented CLI interface.

11) Path resolution for workspaces is tied to process CWD with no override in GraphExecutor.
    - Evidence: `CairnWorkspaceService` defaults `project_root` to `Path.cwd()` (`src/remora/cairn_bridge.py:49`). `GraphExecutor` does not allow injecting a different root when running on arbitrary paths (`src/remora/executor.py:156`).
    - Impact: In multi-project scenarios, running Remora from a different working directory will sync the wrong project into the stable workspace and provide incorrect context to tools.
    - Recommendation: Allow `GraphExecutor` to accept a project root override (or derive it from the config file location / discovery paths).

### Minor / Polish
12) `CairnResultHandler` supports output keys that do not match current tools.
    - Evidence: `src/remora/workspace.py:155` handles `written_files` and `modified_file`, while tools emit `written_file` + `content` (e.g., `agents/docstring/tools/write_docstring.pym:112`).
    - Impact: Even if result handling is added, it will not apply writes unless the formats are aligned.
    - Recommendation: Align tool outputs and handler expectations; add tests to lock this contract.

13) `EventBus.wait_for` uses `asyncio.get_event_loop`, which is deprecated in modern asyncio.
    - Evidence: `src/remora/event_bus.py:96`.
    - Impact: Minor warning risk in Python 3.11+; not a functional bug today.
    - Recommendation: Use `asyncio.get_running_loop()`.

14) Internal Cairn APIs are used directly.
    - Evidence: `src/remora/cairn_bridge.py:68` and `src/remora/workspace.py:102` call `cairn_workspace_manager._open_workspace` (private API).
    - Impact: Upgrade risk if Cairn changes internal signatures.
    - Recommendation: Add a small adapter or public API shim in Cairn, then depend on that stable interface.

## Test Suite Review

### Current Coverage (Observed)
- Unit tests for event bus, graph building, config loading, discovery, and context builder (`tests/unit/test_event_bus.py`, `tests/unit/test_agent_graph.py`, `tests/test_config.py`, `tests/test_discovery.py`, `tests/test_context_manager.py`).
- Utility tests for managed workspaces (`tests/utils/test_fs.py`).
- A fuzz test that does not exercise Remora's Grail integration (`tests/test_tool_script_fuzzing.py`).
- A discovery performance benchmark (`tests/benchmarks/test_discovery_performance.py`).

### Critical Gaps
- No end-to-end tests that exercise discovery -> graph build -> GraphExecutor -> Grail tools -> Cairn workspace writes.
- No tests that use the real vLLM server (remora-server:8000) or the actual Qwen model.
- No tests that validate the dashboard SSE endpoints with real graph runs.
- No tests for the indexer daemon, Grail extraction script, or NodeStateStore persistence.
- No tests that verify the Grail tool schema or the tool output contract used for workspace writes.

## Required Test Additions (Real-World, In-Use)
Below is a prioritized integration-first test plan that matches the stated goal: tests should run the system as an app, with real Grail calls, real vLLM calls, and real Cairn workspaces. Mock-based tests are listed as secondary support.

### 1) End-to-End Graph Execution (Real vLLM + Real Grail + Real Cairn)
Add a new `tests/integration/test_graph_executor_real.py` with `@pytest.mark.integration`:
- **Scenario: lint agent run on a real file.**
  - Create a temp project (simple Python file with a known lint issue).
  - Run discovery + build_graph + GraphExecutor with the real `agents/lint` bundle and a `RemoraConfig` targeting `http://remora-server:8000/v1`.
  - Assert: at least one `ToolCallEvent` and `ToolResultEvent` appears on the event bus; `AgentCompleteEvent` is emitted; a submission summary is recorded in Cairn (via `submit_result`).
- **Scenario: docstring agent writes content.**
  - Use a function without a docstring; run the docstring bundle.
  - Assert: tool output indicates `written_file` + `content`, and the Cairn workspace contains the updated docstring. (This will currently fail until the write-handling bug is fixed, which is desired to expose the gap.)
- **Scenario: test agent generates tests.**
  - Use a small target module and run the test bundle.
  - Assert: test file output is written to the Cairn workspace and submission summary exists.

### 2) CLI "Run" Integration (Real vLLM + Grail + Cairn)
Add `tests/integration/test_cli_run_real.py`:
- Invoke `remora run` with a temp config file pointing to the real vLLM server.
- Validate exit code, ensure stdout includes "Completed X agents", and confirm that events were emitted (use a temporary event bus or output capture).
- This tests the CLI wiring and config parsing in an actual run.

### 3) Dashboard SSE Integration (Real Graph Runs)
Add `tests/integration/test_dashboard_real.py` using `starlette.testclient.TestClient`:
- Start `DashboardApp` via `create_app`.
- POST to `/run` with a temp project path and a known bundle.
- Stream from `/events` and assert receipt of `GraphStartEvent`, `AgentStartEvent`, and completion events.
- Verify `/input` sends `HumanInputResponseEvent` into the event bus when called.

### 4) Grail Tool Execution Contract (Real Grail + Cairn)
Add `tests/integration/test_grail_tools_real.py`:
- Use `RemoraGrailTool` to execute a real tool (e.g., `agents/docstring/tools/write_docstring.pym`).
- Provide real `files_provider` content and Cairn externals.
- Assert tool outputs match expectations, and verify that workspace writes occur once result handling is wired. This test should validate the JSON schema generation for list/dict parameters as part of the tool contract.

### 5) Cairn Workspace Behavior (Real API)
Add `tests/integration/test_cairn_workspace_real.py`:
- Initialize `CairnWorkspaceService` against a temp workspace root.
- Validate that project files are synced correctly, file reads work with relative and absolute paths, and externals (`write_file`, `read_file`, `run_command`) interact with the workspace.
- This test should explicitly verify the path normalization fix proposed in the findings.

### 6) Indexer Daemon + Grail Extraction (Real Grail)
Add `tests/integration/test_indexer_real.py`:
- Start `IndexerDaemon` with a temp store and watch path.
- Create or edit a Python file and assert NodeState records are persisted.
- This will surface the node_type mismatch; the test should enforce a contract for supported node types.

### 7) Event Stream + Context Builder Integration
Add `tests/integration/test_context_builder_real.py`:
- Run a real graph and assert `ContextBuilder` captures recent tool actions and knowledge summaries from live events.
- Validate that context does not duplicate across runs (after fixing subscription leak).

### 8) Minimal Mock-Based Tests (Secondary)
Keep or add a small set of mock-based tests to isolate deterministic failures:
- Error policies in `GraphExecutor` (skip_downstream, stop_graph) with injected tool failures.
- EventBus backpressure/stream filtering without hitting the model.
- Config env overrides and serialization.

## Suggested Test Infrastructure Improvements
- Add a `pytest` fixture to verify the vLLM server is reachable and skip integration tests if it is down.
- Introduce a shared temp-project fixture that writes a minimal `remora.yaml` and sample code files.
- Standardize `graph_id` and workspace paths in tests so artifacts are easy to inspect.
- Expand markers (`integration`, `acceptance`) to distinguish real-vLLM runs from mock-based runs.

## Open Questions / Assumptions
- Should agent bundles control execution parameters (max_turns, requires_context, termination) per bundle? The current executor ignores these.
- Is the intended tool-write contract "return `written_file` in output" or "call a `write_file` external"? A single standardized contract should be chosen and enforced.
- Should the indexer store only function/class nodes, or should it be expanded to include file/method nodes?

## Change Summary (This Review)
No code changes made. Report only.
