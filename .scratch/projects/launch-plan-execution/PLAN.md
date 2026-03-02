# PLAN — Launch Plan Execution

> **NO SUBAGENTS.** All work done directly. No Task tool. No delegation. No exceptions.

This project executes the `REMORA_LAUNCH_PLAN.md` — the consolidated action plan from all 4 code reviews. Work is organized into execution batches ordered by dependency and priority.

## Table of Contents

1. [Batch 1: Track A Quick Fixes](#batch-1-track-a-quick-fixes) — All items < 1 hour, no dependencies
2. [Batch 2: Track B Medium Items (Independent)](#batch-2-track-b-medium-items) — 0.5-1 day each, no critical-path dependencies
3. [Batch 3: Critical Path — Runner Merge (1.2)](#batch-3-critical-path-runner-merge) — Highest priority architectural change
4. [Batch 4: Critical Path — Identity Unification (1.1)](#batch-4-critical-path-identity-unification) — Depends on Batch 3
5. [Batch 5: Post-Unification Cleanup](#batch-5-post-unification-cleanup) — Dead code and re-exports that depend on 1.1/1.2
6. [Batch 6: Architecture Alignment](#batch-6-architecture-alignment) — Event model, config, DB merge
7. [Batch 7: Testing](#batch-7-testing) — Write tests for unified code
8. [Batch 8: Quality & Polish](#batch-8-quality-and-polish) — Performance, UX, remaining items
9. [Acceptance Criteria](#acceptance-criteria)

---

## Batch 1: Track A Quick Fixes

All items under 1 hour. No dependencies on other items. Do these first to reduce bug surface immediately.

**Approach:** For each item, follow TDD where applicable (write failing test, fix, verify). For pure deletions, verify tests still pass after removal.

| # | Launch Plan Ref | Description | Files | Est |
|---|-----------------|-------------|-------|-----|
| 1.1 | 1.9 | Fix `_broadcast` NameError — `emit_event` → `_emit_event` | `core/swarm_executor.py:116` | 5 min |
| 1.2 | 1.10 | Fix parser/model mismatch — use resolved model name | `core/swarm_executor.py:270` | 15 min |
| 1.3 | 1.11 | Fix `chat.py` cleanup — `.cleanup()` → `.close()` | `core/chat.py:209` | 5 min |
| 1.4 | 1.5 | Fix `__dict__` serialization → `dataclasses.asdict()` / `.model_dump()` | `core/projections.py:76`, `core/agent_node.py:95-97` | 30 min |
| 1.5 | 1.3 | Fix transaction boundary — wrap event+projection in single txn | `core/event_store.py:186-200`, `core/projections.py` | 1 hour |
| 1.6 | D3 | Delete `src/remora/nvim/` (pre-LSP server, superseded) | `src/remora/nvim/` | 5 min |
| 1.7 | D4 | Delete `src/remora/core/vcs.py` (dead Jujutsu code) | `core/vcs.py` | 5 min |
| 1.8 | D5 | Delete `plugin/remora_nvim.lua` (legacy plugin) | `plugin/remora_nvim.lua` | 5 min |
| 1.9 | D6 | Delete `load.vim` (legacy plugin loader) | `load.vim` | 5 min |
| 1.10 | D7 | Remove `TreeSitterDiscoverer` legacy wrapper | `core/discovery.py` | 10 min |
| 1.11 | D8 | Remove `NodeType` enum (unused in business logic) | `core/discovery.py` | 10 min |
| 1.12 | D10 | Delete `tests/helpers.py` deprecated shim | `tests/helpers.py` | 5 min |
| 1.13 | D11 | Delete `tests/fixtures/mock_llm.py` (superseded by FakeAsyncOpenAI) | `tests/fixtures/mock_llm.py` | 5 min |
| 1.14 | D12 | Remove `render_tag` legacy function | `ui/view.py` | 5 min |
| 1.15 | D15 | Fix broken LSP `__init__.py` exports | `lsp/__init__.py` | 10 min |
| 1.16 | D16 | Remove duplicate import in config.py | `core/config.py:85-87` | 5 min |
| 1.17 | Q6 | Fix pre-existing test failure — add `workspace/executeCommand` capability | LSP handlers | 5 min |
| 1.18 | N1 | Wrap `nui.popup` require in pcall | `lua/remora/panel.lua` | 5 min |
| 1.19 | N2 | Fix `M.is_open` name collision | `lua/remora/panel.lua` | 5 min |
| 1.20 | N3 | Fix `buf_options.readonly` → window option | `lua/remora/panel.lua` | 5 min |
| 1.21 | N4 | Fix `cmd` default to `remora-lsp` | `lua/remora/init.lua` | 5 min |
| 1.22 | R9 | Delete dead `hashlib` import | `core/agent_node.py:9` | 2 min |
| 1.23 | 2.9 | Fix `AgentMessageEvent.tags` mutability → `tuple[str, ...]` | `core/events.py:103` | 15 min |
| 1.24 | L4 | Fix watcher double-parse bug | `lsp/watcher.py:27-28` | 5 min |
| 1.25 | S7 | Add language tags to code fences | `core/swarm_executor.py:333` | 5 min |

**Run tests after each logical group of changes. Commit after the full batch.**

---

## Batch 2: Track B Medium Items

Independent items that take 0.5-1 day each. Can be done in any order. No critical-path dependencies.

| # | Launch Plan Ref | Description | Files | Est |
|---|-----------------|-------------|-------|-----|
| 2.1 | 1.4 | RemoraDB dual-write elimination | `lsp/db.py`, LSP server | 1 day |
| 2.2 | 1.6 | SubscribeTool self-referencing bug (needs design decision) | `core/tools/swarm.py:140` | 15 min + decision |
| 2.3 | 1.7 | Hardcoded LLM configs — short-term fix (read from Config) | `core/config.py`, `core/chat.py`, `lsp/__main__.py` | 15 min |
| 2.4 | 1.8 | Reconciler stale metadata bug | `core/reconciler.py:130-161` | 1 hour |
| 2.5 | 2.2 | Widen `AgentExtension.matches()` API | `extensions.py:27`, all callers | 1 hour |
| 2.6 | 2.7 | Populate or remove `last_trigger_event` dead schema | `core/agent_node.py`, `core/projections.py` | 30 min |
| 2.7 | 2.8 | Add `start_byte`/`end_byte` to NodeDiscoveredEvent | `core/events.py` | 30 min |
| 2.8 | 2.10 | Parameterize language in system prompt | `core/agent_node.py:129` | 30 min |
| 2.9 | 2.11 | Subscription index for O(1) lookup | `core/subscriptions.py:243` | 1-2 hours |
| 2.10 | 4.2 | Write ChatSession tests | `tests/` (new file) | 1 day |
| 2.11 | 4.4 | Write service/ package tests | `tests/` (new file) | 1-2 days |
| 2.12 | 4.6 | Phase 1 testing gaps T1-T7 | `tests/` | 0.5 day |

---

## Batch 3: Critical Path — Runner Merge (1.2)

**Launch Plan Ref:** 1.2
**This is the highest-priority architectural change.** Merge dual AgentRunner into single EventStore-backed runner.

### Steps
1. Read and understand both runners completely:
   - `src/remora/core/agent_runner.py` (288 lines) — pre-unification
   - `src/remora/lsp/runner.py` (674 lines) — post-unification
2. Write failing integration test for unified runner (TDD)
3. Start with LSP runner as base
4. Port cascade safety from core runner (depth limits, cooldowns, concurrency semaphore)
5. Add pluggable tool registry (LSP tools + Grail tools)
6. Make unified runner callable from both LSP server and swarm executor
7. Delete `core/agent_runner.py`
8. Refactor `swarm_executor.py` into tool provider
9. Verify all tests pass

### Acceptance Criteria
- Single runner implementation
- Both LSP and swarm execution paths work
- Cascade safety present in all execution paths
- All existing tests pass
- New integration tests for the unified runner

**Estimate:** 2-3 days

---

## Batch 4: Critical Path — Identity Unification (1.1)

**Launch Plan Ref:** 1.1
**Depends on:** Batch 3 (runner merge)

### Steps
1. Eliminate AgentState JSONL persistence — all state via EventStore `nodes` table
2. Eliminate SwarmState `agents` table — reconciler/CLI query EventStore directly
3. Update all consumers (executor, reconciler, CLI) to read/write via EventStore
4. Delete `agent_state.py`
5. Remove `agents` table from `swarm_state.py`
6. Write tests for the unified identity path
7. Verify all tests pass

### Acceptance Criteria
- No JSONL files written for agent state
- No `agents` table in SwarmState
- Single source of truth: EventStore `nodes` table
- CLI `swarm list` works via EventStore
- All existing tests pass

**Estimate:** 1 day after Batch 3

---

## Batch 5: Post-Unification Cleanup

**Depends on:** Batch 4 (identity unification)

| # | Launch Plan Ref | Description | Files |
|---|-----------------|-------------|-------|
| 5.1 | D1 | Delete `agent_state.py` (done in Batch 4) | `core/agent_state.py` |
| 5.2 | D2 | Remove SwarmState `agents` table (done in Batch 4) | `core/swarm_state.py` |
| 5.3 | D13 | Clean `remora/__init__.py` re-exports | `src/remora/__init__.py` |
| 5.4 | D14 | Clean `core/__init__.py` re-exports | `src/remora/core/__init__.py` |

---

## Batch 6: Architecture Alignment

Larger architectural changes. Best done after the critical path is complete.

| # | Launch Plan Ref | Description | Depends On | Est |
|---|-----------------|-------------|------------|-----|
| 6.1 | 2.1 | Unify event models → frozen Pydantic | Easier after 1.1/1.2 | 1-2 days |
| 6.2 | 2.3 | Pydantic Config (`BaseSettings`) | Nothing | 0.5 day |
| 6.3 | 2.4 | Single SQLite database | 1.1, 1.4 | 1-2 days |
| 6.4 | 2.5 | Typed externals protocol | 2.3 | 0.5 day |
| 6.5 | 2.6 | Kernel factory | 2.3 | 1 hour |
| 6.6 | D9 | Delete `models/__init__.py` stdlib dataclasses | 2.3 | Included in 6.2 |

---

## Batch 7: Testing

Write comprehensive tests for the unified codebase. Best done after Batches 3-6.

| # | Launch Plan Ref | Description | Depends On | Est |
|---|-----------------|-------------|------------|-----|
| 7.1 | 4.1 | SwarmExecutor / unified executor tests | Batch 3 | 1 day |
| 7.2 | 4.3 | Unified runner loop tests | Batch 3 | 0.5 day |
| 7.3 | 4.5 | CLI command tests | Batch 4 (CLI changes) | 1 day |
| 7.4 | Q2 | Extract shared `_make_node()` to conftest | Nothing | 30 min |

---

## Batch 8: Quality & Polish

Performance, UX, and remaining items from Phase 5.

| # | Launch Plan Ref | Description | Est |
|---|-----------------|-------------|-----|
| 8.1 | P1 | LLM client connection pooling | 1 hour |
| 8.2 | P2 | Incremental workspace sync | 0.5 day |
| 8.3 | P3 | Lightweight `list_nodes()` queries | 1 hour |
| 8.4 | L1 | Fix monkey-patched `_notify_agents_updated` | 30 min |
| 8.5 | L2 | Fix module-level server singleton | 1 hour |
| 8.6 | L3 | Document Qwen-specific XML tag parser | 30 min |
| 8.7 | L5 | Fix `ensure_file_synced` stub | 30 min |
| 8.8 | L6 | Fix `did_save` disk read race | 30 min |
| 8.9 | S1 | Fix `get_subscriptions` name collision | 5 min |
| 8.10 | S2 | Fix `total_agents` counter bug | 15 min |
| 8.11 | S3 | Fix module-level ChatServiceState singleton | 30 min |
| 8.12 | S4 | Fix DatastarResponse content type | 15 min |
| 8.13 | S5 | Fix duplicate prompt context | 15 min |
| 8.14 | S6 | Make chat history limit configurable | 15 min |
| 8.15 | R1 | Deduplicate ignore pattern definitions | 15 min |
| 8.16 | R2 | Fix cascade correlation IDs | 30 min |
| 8.17 | R3 | Configurable event bus error policy | 30 min |
| 8.18 | R4 | Fix `build_virtual_fs` duplicate entries | 15 min |
| 8.19 | R5 | Fix `_find_config_file` sentinel path | 15 min |
| 8.20 | R6 | Fix `_to_jsonable` type mismatch | 15 min |
| 8.21 | R7 | Fix XSS concern in `BlockedAgentCard` | 15 min |
| 8.22 | R8 | Fix extension cache global mutable state | 30 min |

---

## Acceptance Criteria

The project is DONE when:

1. **All 11 Phase 1 critical blockers are resolved** — no runtime crashes from known bugs
2. **Single runner implementation** — `core/agent_runner.py` deleted
3. **Single agent identity** — `agent_state.py` deleted, SwarmState `agents` table removed
4. **All dead code from Phase 3 removed** — D1 through D16 completed
5. **Architecture aligned** — events unified, config Pydantic, single DB
6. **Test coverage** — SwarmExecutor, ChatSession, CLI, service/ all have tests
7. **All tests pass** — `python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn -q` green
8. **No known pre-existing test failures** — Q6 fixed

---

> **NO SUBAGENTS.** All work done directly. No Task tool. No delegation. No exceptions.
