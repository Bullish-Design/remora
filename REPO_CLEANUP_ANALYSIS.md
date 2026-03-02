# Repo Cleanup Analysis

> **Date:** 2026-03-02
> **Purpose:** Comprehensive review of every directory and file in the remora repo, evaluating applicability to the EventBased architecture.
> **Reference:** `docs/EventBased_Concept.md` (authoritative target architecture)
> **Shadow tree:** `.scratch/repo_cleanup/` (detailed per-directory notes)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
   - Current repo state overview, total file/directory counts, disk usage
   - High-level verdict: what percentage is keep/remove/modify

2. [Methodology](#2-methodology)
   - How each item was evaluated (against EventBased_Concept.md)
   - Classification system: KEEP / REMOVE / MODIFY / MOVE

3. [Source Code: src/remora/core/](#3-source-code-srcremora-core)
   - Phase 1 EventBased files (KEEP)
   - Pre-EventBased modules (MODIFY/REMOVE during Option A)
   - core/tools/ subdirectory

4. [Source Code: src/remora/lsp/](#4-source-code-srcremora-lsp)
   - LSP server, handlers, DB, watcher, graph
   - Option A migration status and remaining work

5. [Source Code: src/remora/ (other packages)](#5-source-code-srcremora-other-packages)
   - adapters, cli, extensions, models, nvim, service, testing, ui, utils
   - queries (tree-sitter), fixtures

6. [Tests: tests/](#6-tests-tests)
   - Unit tests (Phase 1 vs old)
   - Integration tests (cairn, LSP, pipeline)
   - Test infrastructure

7. [Agent Bundles: agents/](#7-agent-bundles-agents)
   - Old grail/cairn bundles — full removal rationale

8. [Documentation: docs/](#8-documentation-docs)
   - Current/relevant docs
   - Outdated docs
   - Plans directory
   - Training examples

9. [Demo Application: remora_demo/](#9-demo-application-remora_demo)
   - Current graph/web viewers (KEEP)
   - Old .v1/ workspace cruft (REMOVE)

10. [Supporting Directories](#10-supporting-directories)
    - server/ (deployment)
    - scripts/ (utilities)
    - examples/ (reference)
    - training/ (training data)
    - plugin/ (neovim)
    - _review_notes/ (old)
    - tmp_test_runner/ (temp)

11. [Dot-Directories](#11-dot-directories)
    - .context/ (vendored reference code)
    - .grail/ (runtime artifacts)
    - .hidden/ (archive — 2GB!)
    - .remora/ (runtime — 5.9GB!)
    - .worktrees/, .hypothesis/, .benchmarks/, .cache/, .claude/, .scratch/

12. [Root-Level Files](#12-root-level-files)
    - Config files (KEEP)
    - Temp files (REMOVE)
    - Old markdown docs at root (MOVE/REMOVE)

13. [.gitignore Recommendations](#13-gitignore-recommendations)
    - Missing patterns to add
    - Patterns to verify

14. [Recommended Cleanup Order](#14-recommended-cleanup-order)
    - Phase 1: Immediate cleanup (zero-risk removals)
    - Phase 2: Reorganization (moves, renames)
    - Phase 3: Option A completion (code modifications)
    - Phase 4: Documentation refresh

15. [Target State: Post-Cleanup Repo Structure](#15-target-state-post-cleanup-repo-structure)
    - Ideal directory tree after all cleanup is done

---

## 1. Executive Summary

The remora repo has accumulated significant cruft over multiple architecture iterations (grail/cairn agent bundles, AST summary system, old demo workspaces, vendored reference codebases). The working tree contains ~8GB of data, most of which is runtime artifacts and archived material that should not be tracked.

### Repo Statistics

| Category | Files | Disk Usage | Notes |
|----------|-------|------------|-------|
| `src/` | 84 source files | ~500KB | Core codebase |
| `tests/` | 85 test files | ~300KB | Test suite |
| `docs/` | 44 files | ~2MB | Documentation |
| `agents/` | 87 files | ~200KB | Old bundles (gitignored) |
| `remora_demo/` | 188 files | ~50MB | Demo app + old .v1/ cruft |
| `server/` | 13 files | ~50KB | Deployment |
| `scripts/` | 13 files | ~100KB | Utilities |
| `examples/` | 22 files | ~100KB | Reference material |
| `.context/` | 642 files | 10MB | Vendored reference code |
| `.grail/` | 126 files | 616KB | Runtime artifacts |
| `.hidden/` | 1067 files | **2.0GB** | Archive |
| `.remora/` | 747 files | **5.9GB** | Runtime artifacts |
| Root files | ~25 files | ~500KB | Mixed keep/remove |

### High-Level Verdict

| Action | Estimated % of tracked files | Description |
|--------|------------------------------|-------------|
| **KEEP** | ~40% | Phase 1 core, LSP layer, service, UI, tests, current docs |
| **MODIFY** | ~25% | LSP handlers (Option A), old core modules, some tests |
| **REMOVE** | ~25% | Old agent bundles, temp files, old demo workspace, archive docs |
| **MOVE** | ~10% | Root-level docs to `docs/`, training example dedup |

### Disk Savings Potential

Cleaning up `.hidden/` (2GB) and ensuring `.remora/` (5.9GB) stays gitignored would recover nearly 8GB from the working tree. The `.v1/` demo workspace in `remora_demo/` adds another ~50MB of dead weight.

---

## 2. Methodology

Each directory and file was evaluated against the **EventBased Architecture** as described in `docs/EventBased_Concept.md`. The core principle: **the EventLog is the single source of truth**. Everything should either serve this architecture or be removed.

### Classification System

| Label | Meaning |
|-------|---------|
| **KEEP** | Directly serves EventBased architecture or is a stable utility. No changes needed. |
| **MODIFY** | Relevant to EventBased but needs updating (e.g., LSP handlers using old ASTAgentNode). |
| **REMOVE** | Pre-EventBased artifact with no path to the new architecture. Safe to delete. |
| **MOVE** | Correct content, wrong location. Needs relocation for repo hygiene. |

### Evaluation Criteria

1. **Does it reference AgentNode/EventStore/NodeProjection?** If yes, it's part of the new architecture.
2. **Does it reference ASTAgentNode/RemoraDB.nodes/lsp/extensions.py?** If yes, it's old architecture that needs migration (Option A) or removal.
3. **Does it reference grail bundles/cairn tools/bundle.yaml?** If yes, it's the old agent system being replaced by AgentExtension configs.
4. **Is it a runtime artifact?** (.db files, .db-wal, __pycache__, .coverage) Should be gitignored, not tracked.
5. **Is it documentation?** Evaluated for currency — does it describe the EventBased architecture or the old one?

---

## 3. Source Code: `src/remora/core/`

The core package is the heart of Remora. It contains both the new Phase 1 EventBased implementation and older modules that are being migrated via Option A.

### 3.1 Phase 1 EventBased Files (KEEP)

These files were implemented during Phase 1 and are the foundation of the new architecture. All have comprehensive test coverage (120 tests passing).

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `agent_node.py` | ~150 | `AgentNode` Pydantic model + `ToolSchema` dataclass | KEEP |
| `events.py` | ~120 | Unified event hierarchy (`RemoraEvent`, `NodeDiscoveredEvent`, etc.) | KEEP |
| `event_store.py` | ~350 | SQLite-backed EventStore with append, query, subscription matching | KEEP |
| `projections.py` | ~100 | `NodeProjection` — events into `nodes` table | KEEP |

### 3.2 Core Infrastructure (KEEP, stable)

| File | Lines | Purpose | Status |
|------|-------|---------|--------|
| `config.py` | ~200 | `Config` loading from `remora.yaml` + `bundle.yaml` | KEEP |
| `discovery.py` | ~300 | `TreeSitterDiscoverer`, `CSTNode`, `discover()` | KEEP |
| `errors.py` | ~50 | `RemoraError` hierarchy | KEEP |
| `event_bus.py` | ~150 | In-memory pub/sub (Observer protocol) | KEEP (may merge into EventStore later) |
| `subscriptions.py` | ~250 | `SubscriptionRegistry` for reactive routing | KEEP |
| `vcs.py` | ~50 | VCS adapter (jujutsu commit) | KEEP |

### 3.3 Pre-EventBased Modules (MODIFY during Option A)

These modules predate the EventBased architecture. They work but use patterns that Option A is replacing (file-based agent state, separate SwarmState registry, cairn workspace management).

| File | Lines | Purpose | Action | Notes |
|------|-------|---------|--------|-------|
| `agent_state.py` | ~200 | `AgentState` dataclass with file-based save/load | REMOVE | Replaced by EventStore nodes table |
| `agent_runner.py` | ~200 | `AgentRunner` for reactive execution | MODIFY | Already uses EventStore; update to read AgentNode from it |
| `cairn_bridge.py` | ~150 | `CairnWorkspaceService` | KEEP | Cairn dependency is legitimate |
| `cairn_externals.py` | ~100 | `CairnExternals` for Grail | KEEP | Needed for tool execution |
| `chat.py` | ~200 | Chat session wrapper | MODIFY | Uses old workspace pattern |
| `reconciler.py` | ~200 | Startup reconciliation | MODIFY | Needs to emit events to EventStore |
| `swarm_state.py` | ~150 | `SwarmState` registry | REMOVE | Replaced by EventStore + NodeProjection |
| `swarm_executor.py` | ~200 | `SwarmExecutor` | MODIFY | Update to use AgentNode from EventStore |
| `workspace.py` | ~150 | `AgentWorkspace` | KEEP | Cairn integration |

### 3.4 core/tools/ Subdirectory

| File | Purpose | Status |
|------|---------|--------|
| `grail.py` | `RemoraGrailTool`, `discover_grail_tools()` | KEEP |
| `swarm.py` | Swarm-level tools | KEEP |
| `__init__.py` | Re-exports | KEEP |

---

## 4. Source Code: `src/remora/lsp/`

The LSP subsystem provides the Neovim integration. It's the primary user-facing interface for the EventBased architecture. Option A migration is partially complete — `ASTAgentNode` and `lsp/extensions.py` have been deleted, but handlers still reference old patterns.

### 4.1 File-by-File Analysis

| File | Purpose | Action | Notes |
|------|---------|--------|-------|
| `server.py` | `RemoraLanguageServer` | MODIFY | Already imports `AgentNode` from core. Needs `AgentRunner` import fix, `EventStore` integration |
| `db.py` | `RemoraDB` (SQLite) | MODIFY | Keep LSP-specific tables (proposals, cursor_focus, events, activation_chain, edges, command_queue). Remove nodes table references |
| `models.py` | `RewriteProposal`, `AgentEvent` | KEEP | ASTAgentNode already removed. Remaining models are LSP-specific |
| `graph.py` | `LazyGraph` | MODIFY | Currently may use old node queries. Update to use EventStore |
| `watcher.py` | `ASTWatcher` | MODIFY | Should emit `NodeDiscoveredEvent` to EventStore instead of writing to RemoraDB |
| `runner.py` | LSP runner (startup) | KEEP | Entry point orchestration |
| `notifications.py` | LSP notifications to client | MODIFY | May reference old node types |
| `__main__.py` | Entry point | KEEP | |
| `__init__.py` | Exports | MODIFY | Still exports `ASTAgentNode` and `ToolSchema` (broken imports) |
| `py.typed` | PEP 561 marker | KEEP | |

### 4.2 handlers/ Subdirectory

| File | Purpose | Action | Notes |
|------|---------|--------|-------|
| `actions.py` | Code actions (quick fixes) | MODIFY | References `ASTAgentNode`, `db.get_node_at_position()` |
| `capabilities.py` | LSP capabilities | KEEP | Pure protocol |
| `commands.py` | Custom commands | MODIFY | References `ASTAgentNode` |
| `documents.py` | Document sync (open/save/change) | MODIFY | Watcher integration |
| `hover.py` | Hover information | MODIFY | Likely references old node type |
| `lens.py` | Code lenses | MODIFY | Likely references old node type |
| `__init__.py` | Exports | KEEP | |

### 4.3 nvim/ Subdirectory (bundled Lua)

| File | Purpose | Status |
|------|---------|--------|
| `lua/remora/init.lua` | Core Neovim plugin | KEEP |
| `lua/remora/log.lua` | Logging | KEEP |
| `lua/remora/panel.lua` | Side panel | KEEP |

### 4.4 Current Import Errors

The LSP layer has several broken imports after Phase 1 cleanup:
- `lsp/__init__.py` still exports `ASTAgentNode` and `ToolSchema` (deleted from models)
- `handlers/actions.py` references `ASTAgentNode` and `db.get_node_at_position()`
- `handlers/commands.py` references `ASTAgentNode`
- `server.py` references undefined `AgentRunner`

These are all part of the remaining Option A migration tasks.

---

## 5. Source Code: `src/remora/` (Other Packages)

### 5.1 Top-Level Files

| File | Purpose | Status |
|------|---------|--------|
| `__init__.py` | Public API surface (re-exports from core) | KEEP, update after cleanup |
| `__main__.py` | CLI entry point | KEEP |
| `extensions.py` | `AgentExtension` base class | KEEP (Phase 1) |

### 5.2 Packages

| Package | Files | Purpose | Status |
|---------|-------|---------|--------|
| `adapters/` | 2 | Starlette ASGI adapter | KEEP |
| `cli/` | 2 | CLI commands (click/typer) | KEEP |
| `models/` | 1 | Service API models (`ConfigSnapshot`, `InputResponse`, etc.) | KEEP |
| `nvim/` | 2 | Neovim JSON-RPC server, uses EventStore | KEEP |
| `service/` | 5 | Service layer (API, handlers, datastar SSE, chat) | KEEP |
| `testing/` | 2 | Test fakes/mocks | KEEP |
| `ui/` | 7 | UI projector + iocraft components | KEEP (iocraft dep broken but code is correct) |
| `utils/` | 5 | `PathResolver`, `normalize_path`, text utils, types | KEEP |
| `queries/` | 7 | Tree-sitter `.scm` query files (Python, TOML, Markdown) | KEEP |
| `fixtures/` | 3 | `multilang_project/` test fixture | KEEP |

All of these packages are either stable utilities or directly serve the EventBased architecture. No removals needed.

---

## 6. Tests: `tests/`

### 6.1 Unit Tests (`tests/unit/`)

#### Phase 1 EventBased Tests (KEEP)

| File | Tests | Purpose |
|------|-------|---------|
| `test_agent_node.py` | AgentNode model tests | Phase 1 |
| `test_event_store.py` | EventStore tests | Phase 1 |
| `test_event_store_projection.py` | Projection pipeline tests | Phase 1 |
| `test_event_store_nodes_query.py` | Nodes query API tests | Phase 1 |
| `test_node_events.py` | Event type tests | Phase 1 |
| `test_nodes_table.py` | Nodes table schema tests | Phase 1 |
| `test_extensions.py` | AgentExtension tests | Phase 1 |
| `test_projections.py` | NodeProjection tests | Phase 1 |

#### Core Infrastructure Tests (KEEP)

| File | Purpose | Status |
|------|---------|--------|
| `test_event_bus.py` | EventBus pub/sub | KEEP |
| `test_subscriptions.py` | SubscriptionRegistry | KEEP |
| `test_swarm_state.py` | SwarmState | REMOVE after Option A (SwarmState being deleted) |

#### LSP Tests (MODIFY)

| File | Purpose | Status |
|------|---------|--------|
| `test_lsp_db.py` | RemoraDB | MODIFY (remove nodes table tests) |
| `test_lsp_graph.py` | LazyGraph | MODIFY |
| `test_lsp_models.py` | LSP models | MODIFY (ASTAgentNode references) |
| `test_lsp_notifications.py` | Notifications | MODIFY |
| `test_lsp_runner.py` | LSP runner | MODIFY |
| `test_lsp_server.py` | RemoraLanguageServer | MODIFY |
| `test_lsp_watcher.py` | ASTWatcher | MODIFY |

#### UI/Graph Tests (KEEP)

| File | Purpose |
|------|---------|
| `test_graph_app.py` | Graph viewer app |
| `test_graph_cli.py` | Graph CLI |
| `test_graph_integration.py` | Graph integration |
| `test_graph_shell.py` | Graph shell |
| `test_graph_sidebar.py` | Graph sidebar |
| `test_graph_state.py` | Graph state |
| `test_web_layout.py` | Web layout |

#### Other Unit Tests (KEEP)

| File | Purpose |
|------|---------|
| `test_command_polling.py` | Command polling |
| `test_command_queue.py` | Command queue |

### 6.2 Integration Tests (`tests/integration/`)

| File | Purpose | Status |
|------|---------|--------|
| `test_agent_node_pipeline.py` | Phase 1 full pipeline | KEEP |
| `test_event_store_integration.py` | EventStore integration | KEEP |
| `test_lsp_integration.py` | LSP integration | MODIFY |
| `test_agent_runner.py` | AgentRunner | MODIFY |
| `test_reconcile_real.py` | Reconciliation | MODIFY |
| `test_swarm_store.py` | SwarmState store | REMOVE after Option A |
| `test_cli_real.py` | CLI integration | KEEP |
| `test_vllm_real.py` | vLLM integration | KEEP |
| `test_multilanguage_discovery_real.py` | Multi-language discovery | KEEP |
| `test_real_code_discovery_real.py` | Real code discovery | KEEP |

#### Cairn Integration Tests (`tests/integration/cairn/`)

10 test files covering cairn workspace operations (agent isolation, concurrent safety, error recovery, KV operations, lifecycle, merge, path resolution, read/write semantics, workspace isolation). **KEEP** — cairn is a legitimate dependency.

### 6.3 Root-Level Tests

| File | Purpose | Status |
|------|---------|--------|
| `test_discovery.py` | Discovery tests | KEEP |
| `test_main.py` | Main module tests | KEEP |
| `test_tool_script_fuzzing.py` | Grail script fuzzing | KEEP |

### 6.4 Test Infrastructure (KEEP)

| Path | Purpose |
|------|---------|
| `conftest.py` | Root conftest | KEEP, update |
| `helpers.py` | Test helpers | KEEP |
| `fixtures/` | Test fixtures (sample files, mock LLM) | KEEP |
| `utils/` | Test utilities (grail runtime, tool contract) | KEEP |
| `roundtrip/` | Roundtrip test harness | KEEP |
| `benchmarks/` | Performance benchmarks | KEEP |
| `snapshots/` | Syrupy snapshot tests | KEEP |

---

## 7. Agent Bundles: `agents/`

**Verdict: REMOVE (entire directory)**

The `agents/` directory contains 87 files organized as old-style grail/cairn agent bundles. These are the pre-EventBased way of defining agent behavior.

### What's in there

| Bundle | Type | Contents |
|--------|------|----------|
| `apply_fix/` | Cairn tool | `check.json`, `externals.json`, `inputs.json`, `monty_code.py`, `stubs.pyi` |
| `article_section/` | Grail bundle | `bundle.yaml`, `tools/submit_result.pym` |
| `article_summary/` | Grail bundle | `bundle.yaml`, `tools/*.pym` |
| `.cairn/docstring_style/` | Cairn tool | Standard cairn tool structure |
| `.cairn/ruff_config/` | Cairn tool | Standard cairn tool structure |
| `chat/` | Grail bundle | `bundle.yaml` |
| `docstring/` | Grail bundle | `bundle.yaml`, context and tool `.pym` files |
| `harness/` | Grail bundle | Test harness |
| `lint/` | Grail bundle | Linting agent |
| `sample_data/` | Grail bundle | Sample data generation |
| `test/` | Grail bundle | Test writing agent |
| Various `*_style/`, `*_config/` | Cairn tools | Standalone cairn tools |

### Why REMOVE

1. **Already gitignored**: `agents/**` is in `.gitignore`. Not tracked.
2. **Replaced by AgentExtension**: In EventBased, agent behavior is defined by `AgentExtension` configs in `.remora/models/`, not by grail bundles.
3. **No migration path**: These bundles use `bundle.yaml` + `.pym` tool scripts. The new architecture uses Python classes with `matches()` and `get_extension_data()`.
4. **Dependency on grail/cairn runtime**: The bundle format is tightly coupled to the grail execution engine, which is an implementation detail of the tool execution layer, not the agent definition layer.

If any bundle logic needs to be preserved, it should be re-implemented as an `AgentExtension` subclass.

---

## 8. Documentation: `docs/`

### 8.1 Current/Relevant (KEEP)

| File | Purpose |
|------|---------|
| `EventBased_Concept.md` | **Authoritative** architecture document |
| `SPEC.md` | Specification |
| `INSTALLATION.md` | Installation guide |
| `CONFIGURATION.md` | Configuration reference |
| `TESTING_GUIDELINES.md` | Testing guidelines |
| `TROUBLESHOOTING.md` | Troubleshooting |
| `REMORA_UI_API.md` | UI API documentation |
| `Dockerfile.ollama.quickstart` | Docker quickstart |

### 8.2 Needs Update (MODIFY)

| File | Issue |
|------|-------|
| `ARCHITECTURE.md` | Describes pre-EventBased architecture. Rewrite to match `EventBased_Concept.md`. |
| `CONCEPT.md` | Used as `pyproject.toml` readme. Update to reflect EventBased. |
| `API_REFERENCE.md` | API surface has changed. Update. |
| `HOW_TO_CREATE_AN_AGENT.md` | Describes old grail bundle approach. Rewrite for AgentExtension. |

### 8.3 Keep for Reference

| File | Notes |
|------|-------|
| `HOW_TO_USE_GRAIL.md` | Grail is still a dependency for tool execution |
| `HOW_TO_USE_STRUCTURED_AGENTS.md` | structured-agents is still a dependency |
| `STRUCTURED_AGENTS-HOW_TO_USE_QWEN_MODEL.md` | Model-specific, still relevant |

### 8.4 Plans Directory (`docs/plans/`)

| File | Status | Notes |
|------|--------|-------|
| `2026-03-02-agentnode-design.md` | KEEP | Phase 1 design (reference) |
| `2026-03-02-agentnode-implementation.md` | KEEP | Phase 1 plan (reference) |
| `EVENT_ARCHITECTURE_ALIGNMENT.md` | KEEP | Alignment decisions |
| `2026-03-01-architectural-unification.md` | KEEP | Pre-Phase 1 planning |
| `2026-03-01-graph-viewer-v2-design.md` | KEEP | Graph viewer design |
| `2026-03-01-panel-redesign.md` | KEEP | Panel design |
| `2026-03-01-panel-redesign-impl.md` | KEEP | Panel implementation |
| `2026-03-01-web-graph-view-design.md` | KEEP | Web view design |
| `2026-03-01-zoom-to-cursor.md` | KEEP | Feature design |
| `2026-02-27-ground-up-analysis.md` | MOVE | Older — move to archive |
| `2026-02-26-contract-touchpoints-step-guides.md` | MOVE | Older |
| `2026-02-26-remora-v040-refactor-design.md` | MOVE | Older |
| `2026-02-26-remora-v041-*.md` | MOVE | Older |

### 8.5 Training Examples (`docs/training_examples/`)

**REMOVE** — duplicated in `scripts/training_examples/`. Keep one copy (in `scripts/` makes more sense since they're data, not documentation). Alternatively, move both to a top-level `training/` directory.

### 8.6 Reports (`docs/reports/`)

| File | Status |
|------|--------|
| `cairn_test_coverage.md` | REMOVE (outdated report) |

---

## 9. Demo Application: `remora_demo/`

### 9.1 Current Demo App (KEEP)

The graph viewer and web demo are valuable for demonstrating the EventBased architecture.

| Path | Purpose | Status |
|------|---------|--------|
| `graph/` | iocraft-based TUI graph viewer | KEEP |
| `graph/app.py` | Graph application | KEEP |
| `graph/shell.py` | Interactive shell | KEEP |
| `graph/sidebar.py` | Sidebar component | KEEP |
| `graph/state.py` | State management | KEEP |
| `web/` | Web-based graph viewer | KEEP |
| `web/app.py` | Web application | KEEP |
| `web/layout.py` | Layout components | KEEP |
| `web/render.py` | Rendering | KEEP |
| `web/state.py` | Web state | KEEP |
| `nvim/` | Neovim demo configs | KEEP |
| `__main__.py` | Entry point | KEEP |
| `README.md` | Documentation | KEEP |

### 9.2 Old Demo Workspace (REMOVE)

**`remora_demo/.v1/`** — 150+ files of old v1 demo artifacts:

- **~50 `demo_workspaces/` directories**: Each with `metadata.json` and sometimes Python source files. These are snapshots from old demo runs.
- **`one_stop_shop/`**: A complete demo project with `workspaces/one-stop-shop/` containing **60+ `.db-wal` files**. This is the largest single source of bloat in the demo directory.
- **Old scripts**: `api_demo.py`, `run_agent.py`, `setup_demo.py` — pre-EventBased demo runners.
- **`DEMO_DEVELOPMENT_LOG.md`** — Historical log.

Total estimated size: ~50MB. No path to EventBased architecture. Safe to delete entirely.

---

## 10. Supporting Directories

### 10.1 `server/` — KEEP

Deployment infrastructure for running Remora as a service.

| File | Purpose | Status |
|------|---------|--------|
| `adapter_manager.py` | Server adapter management | KEEP |
| `agents_server.py` | Agent server | KEEP |
| `docker-compose.yml` | Docker orchestration | KEEP |
| `Dockerfile` | Main Dockerfile | KEEP |
| `Dockerfile.agents` | Agents Dockerfile | KEEP |
| `Dockerfile.tailscale` | Tailscale Dockerfile | KEEP |
| `entrypoint.sh` | Container entrypoint | KEEP |
| `update.sh` | Update script | KEEP |
| `.env.example` | Environment template | KEEP |
| `README.md` | Server docs | KEEP |
| `SERVER_DEV_GUIDE.md` | Dev guide | KEEP |
| `test_connection.py` | Connection test | KEEP |
| `tool_chat_template_functiongemma.jinja` | Chat template | KEEP |

### 10.2 `scripts/` — KEEP (mostly)

| File | Purpose | Status |
|------|---------|--------|
| `jsonl_to_readable.py` | JSONL conversion utility | KEEP |
| `migrate_bundles.py` | Bundle migration | REMOVE (bundles being deleted) |
| `remora_tui.py` | TUI script | KEEP |
| `start_lsp.sh` | LSP launcher | KEEP |
| `training_examples/` | Training data | REMOVE (duplicate of `docs/training_examples/`) |

### 10.3 `examples/` — KEEP

| Path | Purpose | Status |
|------|---------|--------|
| `article_summary_demo/` | Working example with `remora.yaml` | KEEP |
| `stario_reference/` | Stario reference app | KEEP |
| `treesitter_swarm/` | Treesitter swarm example | KEEP |
| `*.md` concept files | Future concept documents | KEEP or MOVE to `docs/concepts/` |

The concept markdown files in `examples/` are conceptual designs, not runnable examples:
- `COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md`
- `CONTINUOUS_HEALTH_CONCEPT.md`
- `DOMAIN_BOOTSTRAP_CONCEPT.md`
- `FEATURE_ASSEMBLY_LINE_CONCEPT.md`
- `LEARNING_ASSISTANT_CONCEPT.md`
- `LINKED_EMBEDDINGS_SWARM_CONCEPT.md`
- `SWARM_DOCUMENTATION_CONCEPT.md`
- `TREESITTER_AGENT_SWARM_CONCEPT.md`

Consider moving these to `docs/concepts/` for better organization.

### 10.4 `training/` — KEEP

| Path | Purpose | Status |
|------|---------|--------|
| `demo_project/` | Demo project for training data generation | KEEP |
| `docstring/` | Empty `.gitkeep` placeholder | KEEP |
| `lint/` | Empty `.gitkeep` placeholder | KEEP |
| `sample_data/` | Empty `.gitkeep` placeholder | KEEP |
| `test/` | Empty `.gitkeep` placeholder | KEEP |

### 10.5 `plugin/` — KEEP

| File | Purpose | Status |
|------|---------|--------|
| `remora_nvim.lua` | Neovim plugin | KEEP |

### 10.6 `_review_notes/` — REMOVE

| File | Purpose | Status |
|------|---------|--------|
| `00_core_library.md` | Old core library review | REMOVE (predates EventBased) |
| `01_lsp_layer.md` | Old LSP layer review | REMOVE (predates EventBased) |

Superseded by `EVENT_BASED_PHASE_1_CODE_REVIEW.md`.

### 10.7 `tmp_test_runner/` — REMOVE

| File | Purpose | Status |
|------|---------|--------|
| `events.db` | Leftover test database | REMOVE |
| `subscriptions.db` | Leftover test database | REMOVE |

Runtime artifacts from test runs. Should never be committed.

---

## 11. Dot-Directories

### 11.1 `.context/` (10MB) — Add to .gitignore

Vendored reference codebases for AI-assisted development:

| Subdirectory | Contents |
|--------------|----------|
| `cairn/` | Cairn source code |
| `fsdantic/` | Fsdantic source code |
| `grail_v3.0.0/` | Grail v3 source code |
| `structured-agents_v0.3.4/` | Structured-agents source code |
| `datastar-python-develop/` | Datastar Python SDK |
| `stario/` | Stario source code |
| `templateer/` | Templateer source code |
| `xgrammar-0.1.29/` | XGrammar source code |
| `functiongemma_examples/` | FunctionGemma examples |
| `remora-demo/` | Demo reference |
| `ty_lsp/` | Type LSP reference |
| Various `.md` files | Analysis notes |

**Verdict:** Useful for development but should NOT be tracked in git. Add `.context/` to `.gitignore`. These are easily re-created by checking out the relevant repos.

### 11.2 `.grail/` (616KB) — Add to .gitignore

Compiled Grail tool artifacts (26 directories). Generated at runtime by the Grail execution engine. Not explicitly in `.gitignore` (covered only partially by `agents/**`).

**Verdict:** Add `.grail/` to `.gitignore`.

### 11.3 `.hidden/` (2.0GB!) — Already gitignored, consider deleting

Archive of old documents, code reviews, plans, and working notes from before EventBased. Already gitignored (`.hidden/**`).

Contents include:
- Old code reviews (`CODE_REVIEW.md`, etc.)
- Architecture plans (`CAIRN_INTEGRATION_REFACTOR.md`, etc.)
- AST MVP demo files
- Error analysis documents
- Future concept documents
- Git fix scripts
- Archive subdirectory

**Verdict:** Already gitignored. Consider deleting from working tree entirely to reclaim 2GB. If historical preservation is needed, create a separate archive branch or repo.

### 11.4 `.remora/` (5.9GB!) — Runtime, already gitignored

Runtime artifacts for the Remora system:

| Path | Size | Contents |
|------|------|----------|
| `agents/` | Large | 245 cached agent directories |
| `events/` | Small | Event database files |
| `hub.db` | 4.7MB | Hub database |
| `indexer.db` | 1.6MB | Indexer database |
| `logs/` | Varies | Log files |
| `swarm/` | Small | Swarm state |

Already gitignored (`.remora/**`). These are legitimate runtime artifacts.

**Verdict:** KEEP `.gitignore` pattern. These are generated at runtime.

### 11.5 Other Dot-Directories

| Directory | Size | gitignored? | Verdict |
|-----------|------|-------------|---------|
| `.worktrees/` | 14MB | Yes | KEEP gitignore entry |
| `.hypothesis/` | 1.8MB | Yes | KEEP gitignore entry |
| `.benchmarks/` | Empty | No | Add to .gitignore |
| `.cache/` | Small | Yes (`.cache`) | KEEP gitignore entry |
| `.claude/` | Small | No | Add to .gitignore |
| `.scratch/` | Small | No | Add to .gitignore |
| `.ruff_cache/` | Varies | Yes | KEEP gitignore entry |
| `.pytest_cache/` | Varies | Yes | KEEP gitignore entry |

---

## 12. Root-Level Files

### 12.1 Config Files (KEEP)

| File | Purpose | Status |
|------|---------|--------|
| `pyproject.toml` | Package configuration | KEEP, update |
| `devenv.nix` (if exists) | Nix dev environment | KEEP |
| `devenv.yaml` | Devenv config | KEEP |
| `remora.yaml` | Project-level Remora config | KEEP |
| `.gitignore` | Git ignore patterns | KEEP, update |
| `.gitattributes` | Git attributes | KEEP |
| `.tmuxp.yaml` | Tmux session config | KEEP |
| `README.md` | Project readme | KEEP, update |

### 12.2 Temp Files (REMOVE)

| File | Notes |
|------|-------|
| `tmp_test_add.pym` | Temp Grail test file (49 bytes) |
| `tmp_test_input.pym` | Temp Grail test file (100 bytes) |
| `tmp_test_input2.pym` | Temp Grail test file (99 bytes) |
| `tmp_test_name.pym` | Temp Grail test file (57 bytes) |
| `demo-trigger.py` | Old demo trigger script (1.5KB) |
| `load.vim` | Old vim config (162 bytes, replaced by `plugin/remora_nvim.lua`) |
| `.ast_summary_events.jsonl` | Runtime artifact (648KB!) |

### 12.3 Markdown Files at Root (MOVE or REMOVE)

Several markdown files are scattered at the root level. They should be organized:

| File | Size | Action | Destination |
|------|------|--------|-------------|
| `CODE_REVIEW.md` | 28KB | REMOVE | Superseded by `EVENT_BASED_PHASE_1_CODE_REVIEW.md` |
| `CUSTOM_NVIM_DEVENV_GUIDE.md` | 31KB | MOVE | `docs/` |
| `CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md` | 5KB | MOVE | `docs/` |
| `EventBased_Demo.md` | 42KB | MOVE | `docs/` |
| `EVENT_BASED_DEMO_PLAN.md` | 166KB | MOVE | `docs/plans/` |
| `EVENT_BASED_PHASE_1_CODE_REVIEW.md` | 31KB | MOVE | `docs/reviews/` |
| `EVENT_BASED_TEST_PLAN.md` | 45KB | MOVE | `docs/plans/` |
| `HOW_TO_USE_REMORA.md` | 3KB | MOVE | `docs/` (and update) |
| `NEOVIM_DEMO_V21_FINAL_CONCEPT.md` | 59KB | REMOVE | Superseded by `docs/EventBased_Concept.md` |
| `NEOVIM_DEMO_V24_CODE_REVIEW.md` | 20KB | REMOVE | Old review |

---

## 13. .gitignore Recommendations

### 13.1 Patterns to Add

```gitignore
# AI/dev context (not for repo)
.context/
.claude/
.scratch/

# Runtime artifacts
.grail/
.benchmarks/
.ast_summary_events.jsonl
tmp_test_runner/

# Temp files
tmp_test_*.pym
demo-trigger.py
load.vim

# Old review notes
_review_notes/
```

### 13.2 Existing Patterns to Verify

| Pattern | Currently In .gitignore | Status |
|---------|------------------------|--------|
| `__pycache__/` | Yes | OK |
| `*.py[codz]` | Yes | OK |
| `.remora/**` | Yes | OK |
| `agents/**` | Yes | OK |
| `.hidden/**` | Yes | OK |
| `.worktrees/` | Yes | OK |
| `.hypothesis/` | Yes | OK |
| `**/**.db**` | Yes | OK (catches all .db, .db-wal, .db-shm) |
| `.coverage` | Yes | OK |
| `.devenv/**` | Yes | OK |
| `.direnv/**` | Yes | OK |
| `scripts/training_examples/**` | Yes | OK |

### 13.3 Patterns to Consider Removing

| Pattern | Notes |
|---------|-------|
| `scripts/training_examples/**` | If we remove the duplicate, this pattern is unnecessary |

---

## 14. Recommended Cleanup Order

### Phase 1: Immediate Cleanup (Zero-Risk Removals)

These items can be deleted right now with zero risk to the codebase:

1. **Delete temp files at root:**
   ```
   rm tmp_test_add.pym tmp_test_input.pym tmp_test_input2.pym tmp_test_name.pym
   rm demo-trigger.py load.vim .ast_summary_events.jsonl
   ```

2. **Delete `tmp_test_runner/`:**
   ```
   rm -rf tmp_test_runner/
   ```

3. **Delete `_review_notes/`:**
   ```
   rm -rf _review_notes/
   ```

4. **Delete `remora_demo/.v1/`:**
   ```
   rm -rf remora_demo/.v1/
   ```

5. **Delete old root-level docs:**
   ```
   rm NEOVIM_DEMO_V21_FINAL_CONCEPT.md
   rm NEOVIM_DEMO_V24_CODE_REVIEW.md
   rm CODE_REVIEW.md
   ```

6. **Update `.gitignore`** with new patterns from Section 13.

**Estimated disk savings:** ~50MB tracked + 2GB if `.hidden/` is also cleaned.

### Phase 2: Reorganization (Moves)

These are safe file moves to improve repo organization:

1. **Move root-level docs to `docs/`:**
   ```
   mv EVENT_BASED_DEMO_PLAN.md docs/plans/
   mv EVENT_BASED_PHASE_1_CODE_REVIEW.md docs/reviews/
   mv EVENT_BASED_TEST_PLAN.md docs/plans/
   mv EventBased_Demo.md docs/
   mv HOW_TO_USE_REMORA.md docs/
   mv CUSTOM_NVIM_DEVENV_GUIDE.md docs/
   mv CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md docs/
   ```

2. **Move concept docs from `examples/` to `docs/concepts/`:**
   ```
   mkdir -p docs/concepts
   mv examples/*_CONCEPT.md docs/concepts/
   mv examples/COMPREHENSIVE_EMBEDDINGS_MODEL_SUITE.md docs/concepts/
   ```

3. **Deduplicate training examples:**
   ```
   rm -rf docs/training_examples/  # Keep scripts/training_examples/
   ```
   OR
   ```
   rm -rf scripts/training_examples/  # Keep docs/training_examples/
   ```

4. **Archive old plans:**
   ```
   mkdir -p docs/plans/archive
   mv docs/plans/2026-02-26-*.md docs/plans/archive/
   mv docs/plans/2026-02-27-*.md docs/plans/archive/
   ```

5. **Delete old report:**
   ```
   rm docs/reports/cairn_test_coverage.md
   rmdir docs/reports/
   ```

### Phase 3: Option A Completion (Code Modifications)

These require code changes and are part of the ongoing Option A migration:

1. **Fix `lsp/__init__.py`** — Remove broken `ASTAgentNode`/`ToolSchema` exports
2. **Update LSP handlers** — Replace `ASTAgentNode` references with `AgentNode` from EventStore
3. **Update `lsp/watcher.py`** — Emit `NodeDiscoveredEvent` to EventStore
4. **Update `lsp/db.py`** — Remove nodes table, keep LSP-specific tables
5. **Delete `core/agent_state.py`** — After all references migrated
6. **Delete `core/swarm_state.py`** — After all references migrated
7. **Update `core/reconciler.py`** — Use EventStore instead of file-based AgentState
8. **Update tests** — Fix/remove tests for deleted modules

### Phase 4: Documentation Refresh

After code cleanup is complete:

1. **Rewrite `docs/ARCHITECTURE.md`** to describe EventBased architecture
2. **Update `docs/CONCEPT.md`** (pyproject.toml readme)
3. **Rewrite `docs/HOW_TO_CREATE_AN_AGENT.md`** for AgentExtension pattern
4. **Update `docs/API_REFERENCE.md`** for new API surface
5. **Update `README.md`** at root
6. **Update `docs/CONFIGURATION.md`** if config has changed

---

## 15. Target State: Post-Cleanup Repo Structure

After all cleanup phases are complete, the repo should look like this:

```
remora/
├── .gitignore
├── .gitattributes
├── .tmuxp.yaml
├── devenv.yaml
├── devenv.nix
├── pyproject.toml
├── remora.yaml
├── README.md
│
├── src/remora/
│   ├── __init__.py              # Public API
│   ├── __main__.py              # CLI entry
│   ├── extensions.py            # AgentExtension base class
│   │
│   ├── core/
│   │   ├── agent_node.py        # AgentNode + ToolSchema
│   │   ├── agent_runner.py      # AgentRunner (reactive execution)
│   │   ├── cairn_bridge.py      # Cairn workspace bridge
│   │   ├── cairn_externals.py   # Cairn external functions
│   │   ├── chat.py              # Chat session wrapper
│   │   ├── config.py            # Config loading
│   │   ├── discovery.py         # TreeSitter discovery
│   │   ├── errors.py            # Error hierarchy
│   │   ├── event_bus.py         # In-memory pub/sub
│   │   ├── event_store.py       # EventStore (SQLite)
│   │   ├── events.py            # Event types
│   │   ├── projections.py       # NodeProjection
│   │   ├── reconciler.py        # Startup reconciliation
│   │   ├── subscriptions.py     # SubscriptionRegistry
│   │   ├── swarm_executor.py    # SwarmExecutor
│   │   ├── vcs.py               # VCS adapter
│   │   ├── workspace.py         # AgentWorkspace
│   │   └── tools/               # Grail + swarm tools
│   │
│   ├── lsp/
│   │   ├── server.py            # RemoraLanguageServer
│   │   ├── db.py                # RemoraDB (LSP tables only)
│   │   ├── models.py            # RewriteProposal, AgentEvent
│   │   ├── graph.py             # LazyGraph
│   │   ├── watcher.py           # ASTWatcher (emits to EventStore)
│   │   ├── runner.py            # LSP runner
│   │   ├── notifications.py     # Notifications
│   │   ├── handlers/            # LSP protocol handlers
│   │   └── nvim/                # Bundled Lua plugin
│   │
│   ├── adapters/                # ASGI adapter
│   ├── cli/                     # CLI commands
│   ├── models/                  # Service API models
│   ├── nvim/                    # Neovim JSON-RPC server
│   ├── service/                 # Service layer
│   ├── testing/                 # Test fakes
│   ├── ui/                      # UI projector + components
│   ├── utils/                   # Utilities
│   ├── queries/                 # Tree-sitter queries
│   └── fixtures/                # Test fixtures
│
├── tests/
│   ├── unit/                    # Unit tests
│   ├── integration/             # Integration tests (incl. cairn/)
│   ├── benchmarks/              # Performance benchmarks
│   ├── roundtrip/               # Roundtrip harness
│   ├── snapshots/               # Snapshot tests
│   ├── fixtures/                # Test fixtures
│   └── utils/                   # Test utilities
│
├── docs/
│   ├── EventBased_Concept.md    # Authoritative architecture
│   ├── ARCHITECTURE.md          # Updated architecture overview
│   ├── CONCEPT.md               # Project concept (pyproject readme)
│   ├── CONFIGURATION.md
│   ├── INSTALLATION.md
│   ├── SPEC.md
│   ├── API_REFERENCE.md
│   ├── HOW_TO_CREATE_AN_AGENT.md  # Updated for AgentExtension
│   ├── HOW_TO_USE_GRAIL.md
│   ├── HOW_TO_USE_STRUCTURED_AGENTS.md
│   ├── HOW_TO_USE_REMORA.md
│   ├── REMORA_UI_API.md
│   ├── TESTING_GUIDELINES.md
│   ├── TROUBLESHOOTING.md
│   ├── EventBased_Demo.md
│   ├── CUSTOM_NVIM_DEVENV_GUIDE.md
│   ├── CUSTOM_NVIM_DEVENV_IMPLEMENTATION.md
│   ├── Dockerfile.ollama.quickstart
│   ├── plans/
│   │   ├── EVENT_BASED_DEMO_PLAN.md
│   │   ├── EVENT_BASED_TEST_PLAN.md
│   │   ├── EVENT_ARCHITECTURE_ALIGNMENT.md
│   │   ├── 2026-03-02-agentnode-*.md
│   │   ├── 2026-03-01-*.md
│   │   └── archive/              # Older plans
│   ├── reviews/
│   │   └── EVENT_BASED_PHASE_1_CODE_REVIEW.md
│   └── concepts/                 # Concept docs (moved from examples/)
│
├── remora_demo/
│   ├── graph/                   # TUI graph viewer
│   ├── web/                     # Web graph viewer
│   ├── nvim/                    # Neovim demo config
│   └── README.md
│
├── server/                      # Deployment artifacts
├── scripts/                     # Utility scripts
├── examples/                    # Working examples (no concept docs)
├── training/                    # Training data
├── plugin/                      # Neovim plugin
│
├── .scratch/                    # Dev working notes (gitignored)
└── .remora/                     # Runtime artifacts (gitignored)
```

### Key Differences from Current State

| What | Before | After |
|------|--------|-------|
| Root-level .md files | 10 scattered docs | 1 (README.md) |
| `agents/` directory | 87 old bundle files | Deleted |
| `_review_notes/` | 2 old reviews | Deleted |
| `tmp_test_runner/` | 2 leftover DBs | Deleted |
| `remora_demo/.v1/` | 150+ old demo files | Deleted |
| Temp files at root | 7 files | Deleted |
| `core/agent_state.py` | File-based agent state | Deleted (EventStore) |
| `core/swarm_state.py` | Separate registry | Deleted (EventStore) |
| Concept docs | In `examples/` | In `docs/concepts/` |
| Training examples | Duplicated in 2 places | Single copy |
| `.gitignore` | Missing patterns | Complete coverage |
