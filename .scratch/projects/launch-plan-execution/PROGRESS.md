# PROGRESS — Launch Plan Execution

## Summary
- **Total items:** 75+
- **Completed:** 29 (Batch 1 + items 2.3, 2.6, 2.7, 2.8)
- **In progress:** 0
- **Blocked:** ~8 (waiting on critical path)

---

## Batch 1: Track A Quick Fixes

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 1.1 | 1.9 | Fix `_broadcast` NameError | done |
| 1.2 | 1.10 | Fix parser/model mismatch | done |
| 1.3 | 1.11 | Fix `chat.py` cleanup bug | done |
| 1.4 | 1.5 | Fix `__dict__` serialization | done |
| 1.5 | 1.3 | Fix transaction boundary bug | done |
| 1.6 | D3 | Delete `src/remora/nvim/` | done |
| 1.7 | D4 | Delete `core/vcs.py` | done |
| 1.8 | D5 | Delete `plugin/remora_nvim.lua` | done |
| 1.9 | D6 | Delete `load.vim` | done |
| 1.10 | D7 | Remove `TreeSitterDiscoverer` wrapper | done |
| 1.11 | D8 | Remove `NodeType` enum | done |
| 1.12 | D10 | Delete `tests/helpers.py` | done |
| 1.13 | D11 | Delete `tests/fixtures/mock_llm.py` | done |
| 1.14 | D12 | Remove `render_tag` legacy function | done |
| 1.15 | D15 | Fix broken LSP `__init__.py` exports | done (verified correct, no fix needed) |
| 1.16 | D16 | Remove duplicate import in config.py | done |
| 1.17 | Q6 | Fix `workspace/executeCommand` test failure | done |
| 1.18 | N1 | Wrap `nui.popup` in pcall | done (N/A — lua dir already deleted) |
| 1.19 | N2 | Fix `M.is_open` name collision | done (N/A — lua dir already deleted) |
| 1.20 | N3 | Fix `buf_options.readonly` | done (N/A — lua dir already deleted) |
| 1.21 | N4 | Fix `cmd` default | done (N/A — lua dir already deleted) |
| 1.22 | R9 | Delete dead `hashlib` import | done |
| 1.23 | 2.9 | Fix tags mutability → tuple | done |
| 1.24 | L4 | Fix watcher double-parse | done (false positive — single parse at line 47) |
| 1.25 | S7 | Add language tags to code fences | done |

---

## Batch 2: Track B Medium Items

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 2.1 | 1.4 | RemoraDB dual-write elimination | pending |
| 2.2 | 1.6 | SubscribeTool self-referencing bug | pending |
| 2.3 | 1.7 | Hardcoded LLM configs — short-term fix | done |
| 2.4 | 1.8 | Reconciler stale metadata bug | pending |
| 2.5 | 2.2 | Widen `AgentExtension.matches()` API | pending |
| 2.6 | 2.7 | Populate/remove `last_trigger_event` | done |
| 2.7 | 2.8 | Add `start_byte`/`end_byte` to NodeDiscoveredEvent | done |
| 2.8 | 2.10 | Parameterize language in system prompt | done |
| 2.9 | 2.11 | Subscription index for O(1) lookup | pending |
| 2.10 | 4.2 | Write ChatSession tests | pending |
| 2.11 | 4.4 | Write service/ package tests | pending |
| 2.12 | 4.6 | Phase 1 testing gaps T1-T7 | pending |

---

## Batch 3: Critical Path — Runner Merge (1.2)

| Step | Description | Status |
|------|-------------|--------|
| 3.1 | Read and understand both runners | pending |
| 3.2 | Write failing integration test | pending |
| 3.3 | Start with LSP runner as base | pending |
| 3.4 | Port cascade safety from core runner | pending |
| 3.5 | Add pluggable tool registry | pending |
| 3.6 | Make unified runner callable from LSP + swarm | pending |
| 3.7 | Delete `core/agent_runner.py` | pending |
| 3.8 | Refactor `swarm_executor.py` into tool provider | pending |
| 3.9 | Verify all tests pass | pending |

---

## Batch 4: Critical Path — Identity Unification (1.1)

| Step | Description | Status |
|------|-------------|--------|
| 4.1 | Eliminate AgentState JSONL persistence | blocked (Batch 3) |
| 4.2 | Eliminate SwarmState `agents` table | blocked (Batch 3) |
| 4.3 | Update all consumers to use EventStore | blocked (Batch 3) |
| 4.4 | Delete `agent_state.py` | blocked (Batch 3) |
| 4.5 | Write tests for unified identity | blocked (Batch 3) |
| 4.6 | Verify all tests pass | blocked (Batch 3) |

---

## Batch 5: Post-Unification Cleanup

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 5.1 | D1 | Delete `agent_state.py` | blocked (Batch 4) |
| 5.2 | D2 | Remove SwarmState `agents` table | blocked (Batch 4) |
| 5.3 | D13 | Clean `remora/__init__.py` re-exports | blocked (Batch 4) |
| 5.4 | D14 | Clean `core/__init__.py` re-exports | blocked (Batch 4) |

---

## Batch 6: Architecture Alignment

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 6.1 | 2.1 | Unify event models → frozen Pydantic | pending |
| 6.2 | 2.3 | Pydantic Config (BaseSettings) | pending |
| 6.3 | 2.4 | Single SQLite database | blocked (1.1, 1.4) |
| 6.4 | 2.5 | Typed externals protocol | blocked (2.3) |
| 6.5 | 2.6 | Kernel factory | blocked (2.3) |
| 6.6 | D9 | Delete stdlib dataclass models | blocked (2.3) |

---

## Batch 7: Testing

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 7.1 | 4.1 | SwarmExecutor / unified executor tests | blocked (Batch 3) |
| 7.2 | 4.3 | Unified runner loop tests | blocked (Batch 3) |
| 7.3 | 4.5 | CLI command tests | pending |
| 7.4 | Q2 | Extract shared `_make_node()` to conftest | pending |

---

## Batch 8: Quality & Polish

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 8.1 | P1 | LLM client connection pooling | pending |
| 8.2 | P2 | Incremental workspace sync | pending |
| 8.3 | P3 | Lightweight `list_nodes()` queries | pending |
| 8.4 | L1 | Fix monkey-patched `_notify_agents_updated` | pending |
| 8.5 | L2 | Fix module-level server singleton | pending |
| 8.6 | L3 | Document Qwen XML tag parser | pending |
| 8.7 | L5 | Fix `ensure_file_synced` stub | pending |
| 8.8 | L6 | Fix `did_save` disk read race | pending |
| 8.9 | S1 | Fix `get_subscriptions` name collision | pending |
| 8.10 | S2 | Fix `total_agents` counter bug | pending |
| 8.11 | S3 | Fix ChatServiceState singleton | pending |
| 8.12 | S4 | Fix DatastarResponse content type | pending |
| 8.13 | S5 | Fix duplicate prompt context | pending |
| 8.14 | S6 | Make chat history limit configurable | pending |
| 8.15 | R1 | Deduplicate ignore patterns | pending |
| 8.16 | R2 | Fix cascade correlation IDs | pending |
| 8.17 | R3 | Configurable event bus error policy | pending |
| 8.18 | R4 | Fix `build_virtual_fs` duplicates | pending |
| 8.19 | R5 | Fix `_find_config_file` sentinel | pending |
| 8.20 | R6 | Fix `_to_jsonable` type mismatch | pending |
| 8.21 | R7 | Fix XSS in `BlockedAgentCard` | pending |
| 8.22 | R8 | Fix extension cache global state | pending |
