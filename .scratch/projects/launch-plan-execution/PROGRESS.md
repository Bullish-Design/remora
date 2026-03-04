# PROGRESS — Launch Plan Execution

## Summary
- **Total items:** 75+ (launch plan) + 6 (Pydantic consolidation)
- **Completed:** Batches 1, 2, 3, 7, 8, 4, 5, 6.1, 6.2, 6.3, 6.4, 6.5, 6.6 + Pydantic Consolidation Refactor — ALL DONE
- **In progress:** None
- **Remaining:** None
- **Test suite:** 659 passed, 2 xfailed

---

## Batch 1: Track A Quick Fixes — COMPLETE (commit `597a550`)

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

## Batch 2: Track B Medium Items — COMPLETE (commits `a69957c` through `4eceb4c`)

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 2.1 | 1.4 | RemoraDB dual-write elimination | done |
| 2.2 | 1.6 | SubscribeTool self-referencing bug | done |
| 2.3 | 1.7 | Hardcoded LLM configs — short-term fix | done |
| 2.4 | 1.8 | Reconciler stale metadata bug | done |
| 2.5 | 2.2 | Widen `AgentExtension.matches()` API | done |
| 2.6 | 2.7 | Populate/remove `last_trigger_event` | done |
| 2.7 | 2.8 | Add `start_byte`/`end_byte` to NodeDiscoveredEvent | done |
| 2.8 | 2.10 | Parameterize language in system prompt | done |
| 2.9 | 2.11 | Subscription index for O(1) lookup | done |
| 2.10 | 4.2 | Write ChatSession tests | done |
| 2.11 | 4.4 | Write service/ package tests | done |
| 2.12 | 4.6 | Phase 1 testing gaps T1-T7 | done |

---

## Batch 3: Critical Path — Runner Merge (1.2) — COMPLETE (commit `59cb192`)

| Step | Description | Status |
|------|-------------|--------|
| 3.1 | Read and understand both runners | done |
| 3.2 | Write failing tests (27 tests) | done |
| 3.3 | Port cascade safety from core runner | done |
| 3.4 | Port EventStore bridge | done |
| 3.5 | Implement create_headless() factory | done |
| 3.6 | Update CLI to use unified runner | done |
| 3.7 | Delete `core/agent_runner.py` | done |
| 3.8 | Update `__init__.py` re-exports | done |
| 3.9 | Update integration tests | done |
| 3.10 | Verify all tests pass | done |

---

## Batch 7: Testing — COMPLETE (commit `81f851e`)

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 7.1 | 4.1 | SwarmExecutor / unified executor tests (30 tests) | done |
| 7.2 | 4.3 | Unified runner loop tests (39 tests) | done |
| 7.3 | 4.5 | CLI command tests (18 tests) | done |
| 7.4 | Q2 | Extract shared `_make_node()` to conftest | done |

---

## Batch 8: Quality & Polish — COMPLETE (commits `4038a02`, `595ceb9`)

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 8.1 | P1 | LLM client connection pooling | done |
| 8.2 | P2 | Incremental workspace sync | done |
| 8.3 | P3 | Lightweight `list_nodes()` queries | done |
| 8.4 | L1 | Fix monkey-patched `_notify_agents_updated` | done |
| 8.5 | L2 | Fix module-level server singleton | done |
| 8.6 | L3 | Document Qwen XML tag parser | done |
| 8.7 | L5 | Fix `ensure_file_synced` stub | done |
| 8.8 | L6 | Fix `did_save` disk read race | done |
| 8.9 | S1 | Fix `get_subscriptions` name collision | done |
| 8.10 | S2 | Fix `total_agents` counter bug | done |
| 8.11 | S3 | Fix ChatServiceState singleton | done |
| 8.12 | S4 | Fix DatastarResponse content type | done |
| 8.13 | S5 | Fix duplicate prompt context | done |
| 8.14 | S6 | Make chat history limit configurable | done |
| 8.15 | R1 | Deduplicate ignore patterns | done |
| 8.16 | R2 | Fix cascade correlation IDs | done |
| 8.17 | R3 | Configurable event bus error policy | done |
| 8.18 | R4 | Fix `build_virtual_fs` duplicates | done |
| 8.19 | R5 | Fix `_find_config_file` sentinel | done |
| 8.20 | R6 | Fix `_to_jsonable` type mismatch | done |
| 8.21 | R7 | Fix XSS in `BlockedAgentCard` | done |
| 8.22 | R8 | Fix extension cache global state | done |

---

## Batch 4: Identity Unification — COMPLETE (commit `e546588`)

| Step | Description | Status |
|------|-------------|--------|
| 4.1 | TDD tests for identity unification (19 tests) | done |
| 4.2 | Reconciler rewrite → NodeDiscoveredEvent/NodeRemovedEvent | done |
| 4.3 | SwarmExecutor rewrite → AgentNode, no swarm_state | done |
| 4.4 | CLI update → EventStore/NodeProjection, no SwarmState | done |
| 4.5 | Service handlers/API/LSP server → no SwarmState | done |
| 4.6 | Update all existing tests (7 test files) | done |
| 4.7 | Remove AgentState/AgentMetadata/SwarmState from re-exports | done |
| 4.8 | Full test suite green (502 passed, 2 xfailed) | done |
| 4.9 | Commit | done |

---

## Batch 5: Post-Unification Cleanup — COMPLETE (commit `9b9171a`)

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 5.1 | D1 | Delete `agent_state.py` | done |
| 5.2 | D2 | Remove SwarmState `agents` table | done |
| 5.3 | D13 | Clean `remora/__init__.py` re-exports | done (completed in Batch 4) |
| 5.4 | D14 | Clean `core/__init__.py` re-exports | done (completed in Batch 4) |

---

## Batch 6: Architecture Alignment

| # | Ref | Description | Status |
|---|-----|-------------|--------|
| 6.1 | 2.1 | Unify event models → frozen Pydantic | done (commit `b4f54d9`) |
| 6.2 | 2.3 | Pydantic Config (BaseSettings) | done (commit `b4f54d9`) |
| 6.3 | 2.4 | Single SQLite database | done |
| 6.4 | 2.5 | Typed externals protocol (AgentContext) | done (commit `b4f54d9`) |
| 6.5 | 2.6 | Kernel factory | done (commit `b4f54d9`) |
| 6.6 | D9 | Delete stdlib dataclass models | done |

---

## Pydantic Consolidation Refactor — COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 1 | ToolSchema → BaseModel | done |
| 2 | SubscriptionPattern/Subscription → BaseModel + simplify to_row() | done |
| 3 | ToolCall/LLMResponse → BaseModel | done |
| 4 | Message/ChatConfig/AgentResponse → BaseModel + remove dead import | done |
| 5 | CSTNode → BaseModel (frozen, preserved __hash__) + 3 regression tests | done |
| 6 | Serialization cleanup (projections.py + projector.py) | done |

**Test suite:** 659 passed, 2 xfailed (6 new TDD tests added)
