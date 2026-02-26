# Remora Codebase Analysis

## 1. What is Remora

Remora (v0.3.2) is an event-driven agent graph workflow framework for running structured code-analysis agents against tree-sitter-discovered code nodes, using vLLM-served models (Qwen3-4B, FunctionGemma) via the structured-agents kernel with isolated Cairn workspaces. Python >=3.13, MIT license, by Bullish Design.

**Core deps:** typer, rich, pydantic, pyyaml, jinja2, tree-sitter, grail, cairn, textual, datastar-py
**Optional extras:** `[frontend]` (uvicorn, httpx), `[backend]` (structured-agents, vllm, xgrammar, openai)
**Git-sourced deps:** fsdantic, grail, cairn, structured-agents (all from Bullish-Design GitHub)
**Entry points:** `remora` (cli), `remora-hub` (daemon), `remora-tui`, `remora-demo`, `remora-dashboard`

## 2. Directory Structure

```
src/remora/
  __init__.py, agent_graph.py, agent_state.py, backend.py, checkpoint.py,
  cli.py, client.py, config.py, constants.py, errors.py, event_bus.py,
  workspace.py, __main__.py

  hub/
    daemon.py, server.py, store.py, models.py, cli.py, views.py,
    state.py, registry.py, indexer.py, imports.py, metrics.py,
    rules.py, watcher.py, call_graph.py, test_discovery.py

  context/
    manager.py, models.py, hub_client.py, summarizers.py, contracts.py

  discovery/
    discoverer.py, models.py, match_extractor.py, query_loader.py, source_parser.py

  interactive/
    externals.py, coordinator.py

  frontend/
    __init__.py, state.py, registry.py

  testing/
    __init__.py, fakes.py

  utils/
    fs.py

  queries/
    python/remora_core/{function,class,file}.scm
    markdown/remora_core/{section,file}.scm
    toml/remora_core/{table,file}.scm

agents/
  lint/      bundle.yaml + tools/{run_linter,apply_fix,read_file,submit_result}.pym + context/ruff_config.pym
  docstring/ bundle.yaml + tools/{read_current_docstring,read_type_hints,write_docstring,submit_result}.pym + context/docstring_style.pym
  test/      bundle.yaml + tools/{analyze_signature,read_existing_tests,write_test_file,run_tests,submit_result}.pym + context/pytest_config.pym
  sample_data/ bundle.yaml + tools/{analyze_signature,write_fixture_file,submit_result}.pym + context/existing_fixtures.pym
  harness/   bundle.yaml + tools/{simple_tool,submit_result}.pym
```

## 3. Main Modules/Packages

### Core Modules

- **agent_graph.py**: `AgentState` (StrEnum: PENDING→CANCELLED), `AgentInbox` (ask_user, send_message, drain_messages), `AgentNode` (id, name, target, state, bundle, kernel, inbox, result, upstream/downstream, workspace), `AgentGraph` (agent(), discover(), after().run(), run_parallel(), run_sequential()), `GraphExecutor` (run(), _run_kernel(), _simulate_execution()), `GraphConfig` (max_concurrency, interactive, timeout, error_policy), `ErrorPolicy` (STOP_GRAPH, SKIP_DOWNSTREAM, CONTINUE)
- **event_bus.py**: `Event` (Pydantic frozen, category/action, convenience constructors), `EventBus` (publish, subscribe with wildcard patterns, stream), `EventStream` (async iterator)
- **workspace.py**: `WorkspaceKV` (file-backed JSON KV with async lock), `GraphWorkspace` (agent_space(), shared_space(), snapshot_original(), merge()), `WorkspaceManager` (create, get, list, delete, get_or_create)
- **config.py**: `RemoraConfig` (nested Pydantic: ServerConfig, RunnerConfig, DiscoveryConfig, CairnConfig, HubConfig, etc.), `load_config()` (YAML + overrides + validation)
- **errors.py**: `RemoraError` → ConfigurationError, DiscoveryError, ExecutionError (→ KernelTimeoutError, ToolExecutionError, ContextLengthError), SubagentError, HubError
- **agent_state.py**: `AgentKVStore` (messages, tool_results, metadata in workspace KV, snapshot/restore)
- **checkpoint.py**: `CheckpointManager` (workspace materialization + KV export, restore, list)
- **backend.py**: `require_backend_extra()` guard for structured-agents import
- **constants.py**: TERMINATION_TOOL="submit_result", HUB_DB_NAME="hub.db"

### Hub Package

- **daemon.py**: `HubDaemon` — filesystem watcher, cold-start indexer, concurrent change workers, rules engine, fsdantic Workspace
- **server.py**: `HubServer` — Starlette + datastar-py SSE dashboard, graph execution endpoints, WorkspaceInboxCoordinator
- **store.py**: `NodeStateStore` — fsdantic TypedKVRepository wrapper for NodeState/FileIndex/HubStatus
- **models.py**: `NodeState` (VersionedKVRecord: file_path, node_name, signature, docstring, imports, callers, callees, related_tests), `FileIndex`, `HubStatus`
- **rules.py**: `RulesEngine`, `UpdateAction` ABC, `ExtractSignatures`, `DeleteFileNodes`, `UpdateNodeState`

### Context Package

- **manager.py**: `ContextManager` — Decision Packet projector, apply_event routing, pull_hub_context for Hub integration
- **models.py**: `DecisionPacket` (Short Track: recent_actions rolling window, knowledge dict), `RecentAction`, `KnowledgeEntry`
- **contracts.py**: ToolResult schema (result, summary, knowledge_delta, outcome), make_success/error/partial helpers
- **hub_client.py**: `HubClient` — "Lazy Daemon" pattern, reads Hub workspace, falls back to ad-hoc indexing

### Discovery Package

- **discoverer.py**: `TreeSitterDiscoverer` — multi-language tree-sitter parsing with thread pool
- **models.py**: `CSTNode` (frozen dataclass: node_id, node_type, name, file_path, text, lines), `compute_node_id()` (SHA256-based)

### Interactive Package

- **externals.py**: `ask_user()` — synchronous KV-based IPC for Grail subprocesses
- **coordinator.py**: `WorkspaceInboxCoordinator` — polls workspace KV for outbox questions, publishes events

## 4. Relationship to structured-agents and Grail

**structured-agents:** Used in `_run_kernel()` — imports AgentKernel, KernelConfig, Message, QwenPlugin, GrailBackend, GrailBackendConfig, RegistryBackendToolSource, GrailRegistry, GrailRegistryConfig, GrammarConfig. Creates kernel with vLLM base_url, plugin, grammar config (EBNF mode), tool source from registry+backend. Optional dep behind `[backend]` extra.

**Grail:** .pym scripts are the tool implementations. `from grail import Input, external`. Input() declares typed parameters. @external declares sandbox-provided functions (read_file, write_file, file_exists, run_command, run_json_command). Scripts execute top-level async code and return result dicts.

## 5. What is Cairn

Workspace-aware orchestration runtime for sandboxed code execution with copy-on-write isolation and explicit human integration control. Provides: safe execution of untrusted code, isolated workspace management with CoW overlays, human-controlled integration via accept/reject gates, pluggable code providers. Used by Remora as the sandbox execution layer for .pym scripts. CairnConfig controls: max_concurrent_agents, timeout, limits_preset, pool_workers, snapshot settings.

## 6. Current Architecture

**Data Flow:**
1. TreeSitterDiscoverer scans source dirs with tree-sitter queries → CSTNode list
2. AgentGraph.discover() creates AgentNodes from CSTNodes, mapping node_type→bundle
3. GraphExecutor runs agents in dependency-ordered batches with semaphore concurrency
4. Each agent: load_bundle() → AgentKernel with QwenPlugin + GrailBackend + GrailRegistry → kernel.run()
5. .pym scripts execute in Cairn sandbox with externals for file I/O
6. EventBus publishes lifecycle events (started/blocked/completed/failed) + tool events
7. HubServer serves SSE dashboard, manages graph execution and interactive IPC
8. HubDaemon separately watches filesystem, indexes into NodeStateStore
9. Two-Track Memory: Long Track = full event stream; Short Track = DecisionPacket with rolling recent actions + knowledge entries

## 7. .pym Scripts Inventory

| Bundle | Script | Purpose |
|--------|--------|---------|
| lint | run_linter.pym | Runs ruff check with JSON output |
| lint | apply_fix.pym | Runs ruff --fix for specific issue |
| lint | read_file.pym | Reads target file contents |
| lint | submit_result.pym | Submits lint summary |
| lint | ruff_config.pym | Reads ruff configuration |
| docstring | read_current_docstring.pym | Extracts existing docstring |
| docstring | read_type_hints.pym | Parses parameter annotations |
| docstring | write_docstring.pym | Inserts/replaces docstring |
| docstring | submit_result.pym | Submits docstring result |
| docstring | docstring_style.pym | Provides style preference |
| test | analyze_signature.pym | Parses function signature |
| test | read_existing_tests.pym | Reads existing test files |
| test | write_test_file.pym | Writes pytest test file |
| test | run_tests.pym | Runs pytest with JUnit XML parsing |
| test | submit_result.pym | Submits test generation result |
| test | pytest_config.pym | Provides pytest configuration |
| sample_data | analyze_signature.pym | Parses function signature (duplicate of test) |
| sample_data | write_fixture_file.pym | Writes JSON/YAML fixtures |
| sample_data | submit_result.pym | Submits fixture result |
| sample_data | existing_fixtures.pym | Checks for existing fixtures |
| harness | simple_tool.pym | Echoes payload for testing |
| harness | submit_result.pym | Submits harness result |

## 8. Database/Storage Patterns

- **fsdantic:** External lib providing Fsdantic.open(), Workspace, TypedKVRepository, VersionedKVRecord. Used by Hub for NodeStateStore — three typed repos (node:, file:, hub: prefixes). Models inherit VersionedKVRecord for auto timestamps/versioning.
- **WorkspaceKV:** File-backed KV in GraphWorkspace. Keys split on ":" to path segments, stored as .json files. Async lock for thread safety. Used for agent-frontend IPC (outbox:question:*, inbox:response:*).
- **AgentKVStore:** Wraps workspace.kv for agent-specific state. Keys prefixed with `agent:{agent_id}:`. Stores messages, tool_results, metadata. Snapshot/restore for versioning.

## 9. Architectural Problems

1. **Hardcoded vLLM URL**: `http://remora-server:8000/v1` in `_run_kernel()` ignores config system entirely, with hardcoded model name `Qwen/Qwen3-4B-Instruct-2507-FP8`
2. **Duplicate .pym code**: Helper functions copy-pasted across scripts (test/analyze_signature.pym and sample_data/analyze_signature.pym are nearly identical)
3. **Mixed sync/async**: WorkspaceManager.get_or_create() calls asyncio.run() in sync method; ask_user() uses time.sleep() polling; TreeSitterDiscoverer.discover() is sync
4. **Two "Hub" concepts**: HubDaemon (filesystem watcher + indexer) and HubServer (web dashboard + agent executor) share hub/ package but are architecturally unrelated
5. **Orphaned workspaces**: No automatic cleanup, TTL, or GC for workspace directories
6. **Pervasive Any typing**: AgentNode.kernel, workspace, _kv_store all typed as Any despite mypy strict=true
7. **Global mutable singletons**: _event_bus, _hub_client — no reset for testing, no thread safety
8. **Fragile bundle path search**: 6 hardcoded paths relative to CWD with broken `or` condition
9. **Config loaded repeatedly**: HubDaemon reloads config (including DNS check) on every file change
10. **No workspace isolation between graphs**: Concurrent execute_graph calls share EventBus, events mix
11. **Interactive externals broken**: ContextVar mismatch between externals.py and agent_graph.py
