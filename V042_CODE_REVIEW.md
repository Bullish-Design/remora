# Remora V0.4.2 Code Review Report

Date: 2026-02-26
Reviewer: Codex

## Scope
- Core runtime: `src/remora` (graph, executor, workspace, events, dashboard, indexer, config)
- Bundles and tools: `agents/`
- Entry points: `src/remora/cli.py`, `src/remora/dashboard/cli.py`, `src/remora/indexer/cli.py`
- Tests and docs: `tests/`, `README.md`, `docs/*`, `remora.yaml`, `remora.yaml.example`
- Alignment references: `.context/grail_v3.0.0/HOW_TO_USE_GRAIL.md`, `.context/structured-agents_v0.3.4/HOW_TO_USE_STRUCTURED_AGENTS.md`

## Executive Summary
The refactor successfully consolidates the module layout and introduces a unified event bus and graph executor, but the core runtime does not currently function end-to-end. There are critical API mismatches with Cairn and structured-agents, the default config file and docs still use the pre-refactor schema, and the agent bundles are not in the format structured-agents expects. The result is that workspaces cannot be created, tools are not loaded, prompts are missing system context, and configuration is ignored. Tests and docs are largely pre-refactor and will fail or mislead users.

Below are the findings ordered by severity, with concrete file references and recommended fixes.

## Findings (Ordered by Severity)

### Critical
1) **Cairn workspace integration uses a non-existent API.**
   - `src/remora/workspace.py:14` imports `Workspace` from `cairn`, but Cairn v1.0.0 does not export this type. Methods like `create`, `read`, `write`, `accept`, and `reject` are not part of the fsdantic/Cairn API.
   - Impact: any code path touching workspaces raises `ImportError` or `AttributeError`, blocking graph execution.
   - Recommendation: replace the wrapper with the actual Cairn/fsdantic APIs (`fsdantic.Fsdantic.open`, `Workspace.files.read`, `Workspace.overlay`, etc.), or implement a small adapter that aligns with Cairn’s current runtime APIs.

2) **Structured-agents bundle format mismatch prevents tools/system prompts from loading.**
   - Bundles use top-level `system_prompt` and `tools` (`agents/lint/bundle.yaml:1`, `agents/docstring/bundle.yaml:1`), but structured-agents v0.3 expects `initial_context.system_prompt` and `agents_dir` with `.pym` files in that directory.
   - `src/remora/executor.py:259` uses `Agent.from_bundle`, which relies on the structured-agents loader and therefore silently loads zero tools and an empty system prompt.
   - Impact: agents run without tools, without system prompt context, and will not perform any structured tool calls or edits.
   - Recommendation: either update bundles to structured-agents v0.3 format (`initial_context`, `agents_dir`) or implement a Remora-specific loader that reads the current bundle schema and passes tools/system prompt into the kernel explicitly.

3) **Model server configuration is ignored.**
   - `src/remora/executor.py:259` passes `base_url` and `api_key` to `Agent.from_bundle`, but structured-agents only reads `STRUCTURED_AGENTS_BASE_URL` and `STRUCTURED_AGENTS_API_KEY` from the environment.
   - Impact: the configured model endpoint in `RemoraConfig` is never used; the default `http://localhost:8000/v1` is always selected.
   - Recommendation: either set the environment variables explicitly before agent creation or patch structured-agents to accept explicit overrides for `base_url` and `api_key`.

4) **Default configuration files and docs use the old schema; loading fails by default.**
   - `remora.yaml:1` and `remora.yaml.example:1` use legacy keys (`model_base_url`, `bundle_metadata`, `server`, `operations`). The new `load_config` only accepts `discovery`, `bundles`, `execution`, `indexer`, `dashboard`, `workspace`, `model` (`src/remora/config.py:125`).
   - Impact: `load_config()` raises `ConfigError` for the repo’s own `remora.yaml`, so CLI/dashboard startup fails without manual edits.
   - Recommendation: update `remora.yaml`, `remora.yaml.example`, and `docs/CONFIGURATION.md` to the new schema, or add a compatibility shim that maps old keys to the new dataclasses.

5) **No persistence or data flow between agents/tools and Cairn workspaces.**
   - `src/remora/executor.py:212` instantiates `CairnDataProvider` but only uses it to build a prompt; tool execution does not receive the data provider, and `CairnResultHandler` is never used (`src/remora/workspace.py:135`).
   - Impact: Grail tools do not receive file contents (unless the model manually supplies them), and tool outputs never persist to workspaces. This breaks the core “analyze + write” workflow.
   - Recommendation: integrate a data provider and result handler into tool execution (either by extending structured-agents or wrapping Grail tool execution in Remora). Also persist tool write results into the Cairn workspace and emit summaries back to the context builder.

### Major
6) **ContextBuilder pattern-matches the wrong structured-agents event fields.**
   - `src/remora/context.py:60` matches `ToolResultEvent(name=..., output=...)`, but structured-agents events use `tool_name` and `output_preview`.
   - Impact: recent actions are never recorded, short-track context stays empty, and prompts lose essential activity context.
   - Recommendation: update the match to `ToolResultEvent(tool_name=..., output_preview=...)` and adjust summaries accordingly.

7) **Dashboard state and streaming logic are inconsistent with event types.**
   - `src/remora/dashboard/state.py:75` reads `event.result`, but `AgentCompleteEvent` only exposes `result_summary`.
   - `src/remora/dashboard/views.py:417` and `src/remora/dashboard/views.py:430` both call `dashboard_state.record(event)` even though `DashboardApp.initialize` already subscribes `record`, causing double-counting.
   - `src/remora/dashboard/views.py:438` emits SSE `data:` with a Python dict, not JSON.
   - Impact: results panel is empty or incorrect; totals drift; SSE consumers cannot parse events reliably.
   - Recommendation: use `event.result_summary`, record events once, and serialize SSE payloads with `json.dumps`.

8) **Indexer Grail scripts are referenced but not present, and the project root is ambiguous.**
   - `src/remora/indexer/rules.py:72` calls `hub/extract_signatures.pym`, but no such script exists in the repo.
   - `src/remora/indexer/daemon.py:183` sets `project_root=path.parent`, which may not be the repository root for relative paths or `.grail` lookup.
   - Impact: indexer actions either fail or silently do nothing.
   - Recommendation: either vendor the Grail scripts into a known location (and resolve paths relative to repo root) or remove the action until scripts are shipped.

9) **Test suite targets pre-refactor APIs; most tests will fail.**
   - Examples: `tests/test_config.py:1` references `remora.cli.app` and legacy config fields, `tests/test_discovery.py:1` imports symbols that no longer exist, `tests/unit/test_event_bus.py:1` uses a deprecated `EventBus.stream` interface.
   - Impact: CI will report widespread failures and give no confidence in new behavior.
   - Recommendation: delete or rewrite tests to match the refactored API, and add a minimal end-to-end smoke test that loads config, discovers nodes, and executes a single agent with mocked structured-agents/Grail execution.

### Moderate
10) **Public API exports reference missing symbols.**
    - `src/remora/__init__.py:114` exports `execute_agent`, but it is not defined or imported.
    - Impact: import-time confusion and broken public API.
    - Recommendation: remove the export or implement the function.

11) **`src/remora/client.py` references a non-existent `ServerConfig`.**
    - `src/remora/client.py:7` imports `ServerConfig` which no longer exists in `config.py`.
    - Impact: unused module, but it will fail if imported.
    - Recommendation: delete the file or update it to `ModelConfig`.

12) **`ExecutionConfig.timeout` is not enforced.**
    - `src/remora/config.py:58` defines a timeout but `GraphExecutor` never applies it (`src/remora/executor.py:269`).
    - Impact: hung agent runs can stall the entire graph.
    - Recommendation: wrap `agent.run()` in `asyncio.wait_for` or add timeout support in the agent/kernel layer.

13) **`RemoraEvent` does not re-export `TurnCompleteEvent`.**
    - `src/remora/events.py:99` omits `TurnCompleteEvent` from exports even though structured-agents emits it.
    - Impact: downstream consumers cannot pattern-match all structured-agents events consistently.
    - Recommendation: re-export or document that it is excluded.

### Minor / Polish
14) **`WorkspaceConfig.cleanup_after` is unused.**
    - `src/remora/config.py:85` defines it, but `WorkspaceManager` never uses it.
    - Recommendation: implement cleanup scheduling or remove the field.

15) **`ContextBuilder` has an unused `_store` placeholder.**
    - `src/remora/context.py:52` suggests hub integration but never provides a setter or injection point.
    - Recommendation: expose a `set_store()` method or remove the feature.

16) **Project metadata still indicates v0.3.3.**
    - `pyproject.toml:2` declares version `0.3.3` even though the refactor is targeting v0.4.2.
    - Recommendation: bump version and update README/docs accordingly.

## Recommendations (Architecture-Level)
- **Unify the contract between Remora and structured-agents.** Decide whether Remora will adopt structured-agents’ bundle schema or extend structured-agents to accept Remora’s schema. This is the single most impactful fix.
- **Fix Cairn integration at the API boundary.** Implement a small adapter that maps Remora’s `AgentWorkspace` operations to the actual fsdantic/Cairn API and wire data provider/result handling into tool execution.
- **Eliminate stale docs/tests.** Update `README.md`, `docs/CONFIGURATION.md`, and test modules to the new API, or remove them to avoid false confidence.
- **Add a minimal golden-path integration test.** For example: discover a sample file, load a bundle with a fake Grail tool, run the graph, and verify events + workspace writes.

## Open Questions / Assumptions
- Should Remora support multiple bundles per node type, or is v0.4.2 intentionally single-bundle-per-node-type?
- Is the intended tool execution model “pure Input-only” (no external functions), or should Grail scripts still receive external helpers and workspace-backed virtual FS?
- Is the indexer still a first-class part of v0.4.2, or should it be split into a separate package?

## Change Summary (This Review)
No code changes made. Report only.
