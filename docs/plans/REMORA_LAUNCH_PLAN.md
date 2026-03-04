# Remora Launch Plan

> **Date:** 2026-03-02
> **Scope:** `src/remora/` library only (excludes `remora_demo/`)
> **Authority:** `docs/EventBased_Concept.md` — all decisions measured against this document
> **Sources:** CODE_REVIEW.md, EVENT_BASED_PHASE_1_CODE_REVIEW.md, EVENT_BASED_PHASE_2_CODE_REVIEW.md, NEOVIM_DEMO_V24_CODE_REVIEW.md

This document consolidates every issue, fix, and refactoring item from all code reviews into a single, deduplicated, prioritized action plan for making Remora launch-ready.

---

## Table of Contents

1. [Phase 1: Critical Blockers](#phase-1-critical-blockers) — Must fix before the library can be used reliably
   - 1.1 Triple agent identity → unify on AgentNode/EventStore
   - 1.2 Dual AgentRunner → merge into single EventStore-backed runner
   - 1.3 Transaction boundary bug in projections/EventStore
   - 1.4 RemoraDB dual-write elimination
   - 1.5 `__dict__` serialization bugs in projections.py and agent_node.py
   - 1.6 SubscribeTool self-referencing bug
   - 1.7 Hardcoded LLM configs across 3 files
   - 1.8 Reconciler stale metadata bug
   - 1.9 `_broadcast` NameError in SwarmExecutor
   - 1.10 Parser/model mismatch in SwarmExecutor
   - 1.11 `chat.py` AttributeError on cleanup

2. [Phase 2: Architecture Alignment](#phase-2-architecture-alignment) — Making the code match the EventBased Concept
   - 2.1 Unify event models (core frozen dataclasses vs LSP Pydantic)
   - 2.2 Widen `AgentExtension.matches()` API
   - 2.3 Unified Pydantic Config replacing stdlib dataclass Config
   - 2.4 Single SQLite database
   - 2.5 Typed externals protocol replacing `dict[str, Any]`
   - 2.6 Kernel factory to deduplicate client/adapter/kernel creation
   - 2.7 Populate or remove `last_trigger_event` dead schema
   - 2.8 Add `start_byte`/`end_byte` to NodeDiscoveredEvent
   - 2.9 Fix `AgentMessageEvent.tags` mutability
   - 2.10 Parameterize language in system prompt
   - 2.11 Subscription index for O(1) lookup

3. [Phase 3: Dead Code Removal](#phase-3-dead-code-removal) — Eliminate pre-unification artifacts
   - 3.1 High-impact removals (entire modules)
   - 3.2 Medium-impact removals (shims, enums, legacy wrappers)
   - 3.3 Stale re-exports and minor cleanup

4. [Phase 4: Testing Gaps](#phase-4-testing-gaps) — Must-have test coverage
   - 4.1 CRITICAL: SwarmExecutor (zero tests)
   - 4.2 CRITICAL: ChatSession (zero tests)
   - 4.3 AgentRunner run loop (untested dispatch)
   - 4.4 service/ package (zero tests, has bugs)
   - 4.5 CLI commands (no unit tests)
   - 4.6 Phase 1 testing gaps (ToolSchema, extensions, error paths, concurrency)
   - 4.7 Test infrastructure cleanup

5. [Phase 5: Quality & Polish](#phase-5-quality--polish) — Performance, UX, and remaining medium/low issues
   - 5.1 Performance improvements
   - 5.2 LSP layer fixes
   - 5.3 Service/UI layer fixes
   - 5.4 Neovim plugin fixes
   - 5.5 Remaining low-severity items

6. [Dependencies and Ordering](#dependencies-and-ordering) — What blocks what

7. [Constraints](#constraints) — Rules for execution

---

## Phase 1: Critical Blockers

These are bugs and architectural issues that prevent the library from functioning correctly. Each item either causes runtime crashes, data corruption/divergence, or fundamentally violates the EventBased architecture. Fix all of these before any other work.

### 1.1 Triple Agent Identity → Unify on AgentNode/EventStore

**Sources:** Phase 2 Review C1, Phase 2 Review H1
**Severity:** CRITICAL
**Files:**
- `src/remora/core/agent_state.py` (84 lines) — eliminate entirely
- `src/remora/core/swarm_state.py` — eliminate `agents` table
- `src/remora/core/swarm_executor.py` — reads/writes AgentState
- `src/remora/core/agent_runner.py` — reads/writes AgentState
- `src/remora/core/reconciler.py` — reads/writes AgentMetadata via SwarmState

**Problem:** Three separate systems store agent/node identity with overlapping fields:

| System | Model | Storage | Used By |
|--------|-------|---------|---------|
| AgentNode | Pydantic BaseModel | EventStore `nodes` table (via NodeProjection) | LSP runner, graph, notifications, handlers |
| AgentState | Frozen dataclass | JSONL files in `.remora/agents/` | Core AgentRunner, SwarmExecutor |
| AgentMetadata | Dataclass | SwarmState SQLite `agents` table | Reconciler, CLI `swarm list` |

All three store: name, file path, node type, and status. State changes in one system are invisible to the others. The vision (Section 5) explicitly states: *"There is no separate AgentState file. The nodes table row IS the agent's state."*

**Action:**
1. Eliminate AgentState JSONL persistence — all agent state lives in EventStore `nodes` table via AgentNode
2. Eliminate SwarmState `agents` table — reconciler and CLI query EventStore `list_nodes()` / `get_node()` directly
3. Update all consumers (core runner, executor, reconciler, CLI) to read/write via EventStore
4. Delete `agent_state.py` once no references remain

**Blocked by:** 1.2 (runner merge). Do 1.2 first, then this becomes straightforward.
**Estimate:** ~1 day after 1.2 is complete

---

### 1.2 Dual AgentRunner → Merge into Single EventStore-Backed Runner

**Sources:** Phase 2 Review C2
**Severity:** CRITICAL
**Files:**
- `src/remora/core/agent_runner.py` (288 lines) — pre-unification runner
- `src/remora/lsp/runner.py` (674 lines) — post-unification runner

**Problem:** Two completely independent agent execution loops exist. They share no code, no base class, no common interface.

| Runner | State Backend | Tool System | Cascade Safety |
|--------|---------------|-------------|----------------|
| Core AgentRunner | AgentState JSONL | SwarmExecutor → Grail tools | Yes (depth, cooldown, concurrency) |
| LSP Runner | EventStore | Built-in tools (rewrite, insert, etc.) | No |

Bug fixes, performance improvements, and features must be implemented twice. Cascade safety is only in the core runner — the LSP runner has no cascade protection.

**Action:**
1. Start with the LSP runner as the base (already uses EventStore)
2. Port cascade safety guards from core runner (depth limits, cooldowns, concurrency semaphore)
3. Add pluggable tool registry to support both LSP tools and Grail tools
4. Make the unified runner callable from both the LSP server and the swarm executor
5. Delete `core/agent_runner.py` and refactor `swarm_executor.py` into a tool provider

**Blocked by:** Nothing. This is the highest-priority change.
**Estimate:** ~2-3 days

---

### 1.3 Transaction Boundary Bug in Projections/EventStore

**Sources:** Phase 1 Review B2/#11/#16
**Severity:** HIGH
**Files:**
- `src/remora/core/projections.py` — every method calls `conn.commit()` individually
- `src/remora/core/event_store.py:186-200` — `append()` commits event, then calls projection

**Problem:** `EventStore.append()` commits the event INSERT first (line 195), then calls `self._projection.apply()` which does its own commit. If the projection fails mid-way, the event is committed but the nodes table is inconsistent. This violates the "EventLog is the single source of truth" principle — if an event exists, its projection should always be consistent.

**Action:**
1. Remove all `conn.commit()` calls from `NodeProjection` methods
2. Wrap both the event INSERT and projection in a single transaction in `EventStore.append()`
3. On projection failure, roll back both the event and the projection

```python
# Proposed fix in event_store.py append()
async with self._lock:
    await asyncio.to_thread(self._conn.execute, "BEGIN")
    try:
        cursor = await asyncio.to_thread(self._conn.execute, INSERT_SQL, params)
        if self._projection is not None:
            await asyncio.to_thread(self._projection.apply, self._conn, event)
        await asyncio.to_thread(self._conn.commit)
    except Exception:
        await asyncio.to_thread(self._conn.rollback)
        raise
```

**Blocked by:** Nothing.
**Estimate:** ~1 hour

---

### 1.4 RemoraDB Dual-Write Elimination

**Sources:** Phase 2 Review H3
**Severity:** HIGH
**Files:**
- `src/remora/lsp/db.py:75-118` — maintains its own `events` table
- LSP server `emit_event()` — writes to both EventStore and RemoraDB

**Problem:** The LSP server writes events to BOTH EventStore and RemoraDB. If one write fails and the other succeeds, the stores diverge silently. The RemoraDB `events` table is a pre-unification artifact.

**Action:**
1. Identify all RemoraDB `events` table readers (UI queries, event history display)
2. Replace those queries with EventStore `replay()` calls scoped by `graph_id`
3. Remove the `events` table from RemoraDB schema
4. Remove dual-write logic from LSP server's `emit_event()`

**Blocked by:** Nothing.
**Estimate:** ~1 day

---

### 1.5 `__dict__` Serialization Bugs

**Sources:** Phase 1 Review B1/#10, B3/#4/#5
**Severity:** HIGH
**Files:**
- `src/remora/core/projections.py:76` — `json.dumps(value, default=lambda o: o.__dict__)`
- `src/remora/core/agent_node.py:95-97` — `to_row()` uses `t.__dict__` for ToolSchema/SubscriptionPattern

**Problem:**
- `projections.py`: The `__dict__` lambda fails for slotted classes (`__slots__` have no `__dict__`) and produces wrong output for Pydantic models. Extension `get_extension_data()` returning Pydantic or slotted objects will crash or silently produce incorrect JSON.
- `agent_node.py`: `to_row()` uses `__dict__` for ToolSchema and SubscriptionPattern serialization. If these dataclasses ever get computed properties, class variables, or non-init fields, `__dict__` will include them and `ToolSchema(**t)` deserialization will reject them.

**Action:**
1. In `projections.py`, replace `lambda o: o.__dict__` with `dataclasses.asdict(o)` for dataclasses and `.model_dump()` for Pydantic models
2. In `agent_node.py`, replace `t.__dict__` with `dataclasses.asdict(t)` for both ToolSchema and SubscriptionPattern

**Blocked by:** Nothing.
**Estimate:** ~30 minutes

---

### 1.6 SubscribeTool Self-Referencing Bug

**Sources:** Phase 2 Review M2
**Severity:** MEDIUM
**File:** `src/remora/core/tools/swarm.py:140`

**Problem:** `SubscribeTool` creates patterns with `to_agent=agent_id` where `agent_id` is the subscribing agent itself. This means the subscription only matches events where `to_agent` equals the subscriber — the agent subscribes to events sent TO itself, not events FROM or ABOUT the target node. The semantics are backwards.

**Action:** The `to_agent` field should be omitted from the subscription pattern, or set to the target node's ID depending on the intended semantics. Requires a design decision on correct subscription behavior.

**Blocked by:** Nothing. Requires design decision.
**Estimate:** ~15 minutes (code change) + design decision

---

### 1.7 Hardcoded LLM Configs Across 3 Files

**Sources:** Original Review F-27, Phase 2 Review M3
**Severity:** MEDIUM
**Files:**
- `src/remora/core/config.py` — defaults to `Qwen/Qwen3-4B`
- `src/remora/core/chat.py` — defaults to `Qwen/Qwen3-4B-Instruct-2507-FP8`
- `src/remora/lsp/__main__.py` — hardcodes `Qwen/Qwen3-4B-Instruct-2507-FP8`

**Problem:** Three different default model configs with three different `model_base_url` defaults. Moving between contexts will cause silent failures. The LSP entry point hardcodes the URL instead of reading from Config.

**Action:**
1. Define a single canonical `LLMConfig` (see 2.3 for full Pydantic migration)
2. In the short term: make `lsp/__main__.py` read from `Config` instead of hardcoding
3. Ensure `chat.py` uses the same Config as everything else

**Blocked by:** Nothing for the short-term fix. Full resolution in 2.3.
**Estimate:** ~15 minutes (short-term), included in 2.3 (full fix)

---

### 1.8 Reconciler Stale Metadata Bug

**Sources:** Original Review F-17
**Severity:** HIGH
**File:** `src/remora/core/reconciler.py:130-161`

**Problem:** For existing agents, the reconciler only emits `ContentChangedEvent` — it does NOT update metadata (name, line range, etc.). If a function moves from line 10 to line 50, SwarmState retains old positions. CodeLens will point to wrong lines.

**Action:** When reconciling existing agents, also update metadata fields (name, start_line, end_line, file_path) if they've changed. With the AgentNode/EventStore unification (1.1), this should be a NodeProjection concern — re-discovery of a moved function should emit a new `NodeDiscoveredEvent` with updated positions, and the upsert in NodeProjection should update the row.

**Blocked by:** Partially blocked by 1.1 (identity unification). The fix approach depends on whether the reconciler still exists post-unification.
**Estimate:** ~1 hour

---

### 1.9 `_broadcast` NameError in SwarmExecutor

**Sources:** Original Review F-32
**Severity:** HIGH
**File:** `src/remora/core/swarm_executor.py:116`

**Problem:** `_broadcast` closure references bare `emit_event` variable not in scope — should be `_emit_event`. Will crash the first time broadcast is actually called at runtime.

**Action:** Fix the variable reference from `emit_event` to `_emit_event`.

**Blocked by:** Nothing.
**Estimate:** ~5 minutes

---

### 1.10 Parser/Model Mismatch in SwarmExecutor

**Sources:** Original Review F-12
**Severity:** HIGH
**File:** `src/remora/core/swarm_executor.py:270`

**Problem:** `get_response_parser(manifest.model)` selects a parser for the manifest's model, but `_resolve_model_name()` can override to a different model at runtime. The parser may not match the actual model response format, causing silent parse failures or crashes.

**Action:** Call `get_response_parser()` with the RESOLVED model name (after `_resolve_model_name()`), not the manifest model.

**Blocked by:** Nothing.
**Estimate:** ~15 minutes

---

### 1.11 `chat.py` AttributeError on Cleanup

**Sources:** Original Review F-21
**Severity:** HIGH
**File:** `src/remora/core/chat.py:209`

**Problem:** Calls `self._workspace.cleanup()` which doesn't exist on `CairnWorkspaceService` — the correct method is `close()`. This will crash at runtime when the chat session attempts cleanup.

**Action:** Change `self._workspace.cleanup()` to `self._workspace.close()`.

**Blocked by:** Nothing.
**Estimate:** ~5 minutes

---

## Phase 2: Architecture Alignment

These items bring the codebase into full alignment with `docs/EventBased_Concept.md`. They are not crashes or data-loss bugs, but they represent structural divergence from the vision that will cause increasing maintenance burden and confusion if left unaddressed.

### 2.1 Unify Event Models (Core Frozen Dataclasses vs LSP Pydantic)

**Sources:** Phase 2 Review H2
**Severity:** HIGH
**Files:**
- `src/remora/core/events.py` — frozen dataclass events
- `src/remora/lsp/models.py` (255 lines) — Pydantic event hierarchy with `to_core_event()` bridge

**Problem:** Every new event type requires two definitions — one in `core/events.py` (frozen dataclass) and one in `lsp/models.py` (Pydantic). The bridge methods (`to_core_event()`) add maintenance burden and can silently fall out of sync.

**Options:**
1. **Make core events Pydantic models** (recommended) — aligns with AgentNode being Pydantic. Eliminates the bridge layer entirely. Frozen Pydantic models (`model_config = ConfigDict(frozen=True)`) provide the same immutability guarantee as frozen dataclasses.
2. **Auto-generate Pydantic wrappers** from core dataclasses — keeps dataclasses for performance but adds code generation complexity.
3. **Accept the duplication** but add sync tests — lowest effort, highest ongoing cost.

**Action:** Option 1. Migrate core events to frozen Pydantic models. Delete `lsp/models.py` event hierarchy and bridge methods.

**Blocked by:** Nothing, but easier after 1.1/1.2 (fewer moving parts).
**Estimate:** ~1-2 days

---

### 2.2 Widen `AgentExtension.matches()` API

**Sources:** Phase 1 Review D1/#26
**Severity:** HIGH
**File:** `src/remora/extensions.py:27`

**Problem:** `matches()` only receives `node_type: str` and `name: str`. The concept doc describes extensions matching on decorators (`@app.route`), inheritance (`BaseModel`), and file context. The current 2-parameter API can only match by naming conventions, which is severely limiting.

**Action:** Add `file_path`, `source_code`, and optionally `parent_id` parameters:

```python
@staticmethod
def matches(
    node_type: str,
    name: str,
    *,
    file_path: str = "",
    source_code: str = "",
) -> bool:
```

This is a breaking change to all existing extensions. Do it before the extension ecosystem grows.

**Blocked by:** Nothing.
**Estimate:** ~1 hour (API change + update all callers + update projection)

---

### 2.3 Unified Pydantic Config Replacing Stdlib Dataclass Config

**Sources:** Original Review I-01, F-01
**Severity:** MEDIUM
**File:** `src/remora/core/config.py`

**Problem:** `Config` is `@dataclass(slots=True)` with manual `serialize_config()` that enumerates fields by hand. No validation, no env var override, no schema generation. Three separate model default configs (F-27) are a symptom of this.

**Action:** Replace with Pydantic `BaseSettings`:

```python
class LLMConfig(BaseModel):
    base_url: str = "http://localhost:8000/v1"
    model: str = "Qwen/Qwen3-4B"
    api_key: str = "EMPTY"

class RemoraSettings(BaseSettings):
    llm: LLMConfig = LLMConfig()
    # ... all other config
    model_config = SettingsConfigDict(env_prefix="REMORA_")
```

This eliminates `serialize_config()`, the manual field enumeration, and all three hardcoded model configs (1.7). The LSP `__main__.py` reads from settings instead of hardcoding.

**Blocked by:** Nothing.
**Estimate:** ~0.5 day

---

### 2.4 Single SQLite Database

**Sources:** Original Review I-02, F-07, F-08
**Severity:** MEDIUM
**Files:**
- `src/remora/core/event_store.py` — own SQLite + asyncio.Lock
- `src/remora/core/subscriptions.py` — own SQLite + asyncio.Lock
- `src/remora/core/swarm_state.py` — own SQLite + asyncio.Lock
- `src/remora/lsp/db.py` — own SQLite connection

**Problem:** 4 separate SQLite databases for the library. No cross-table queries. No transaction coordination. Three separate `asyncio.Lock` instances.

**Action:** Merge EventStore, SubscriptionRegistry, and RemoraDB into one database with separate tables. Share a single connection (with WAL mode). Cross-table queries become possible. Remove redundant locks.

**Note:** SwarmState's `agents` table is eliminated by 1.1, so only the `subscriptions` table needs migration.

**Blocked by:** 1.1 (identity unification) and 1.4 (RemoraDB dual-write elimination) should be done first.
**Estimate:** ~1-2 days

---

### 2.5 Typed Externals Protocol Replacing `dict[str, Any]`

**Sources:** Original Review I-03, F-31
**Severity:** MEDIUM
**File:** `src/remora/core/tools/swarm.py`

**Problem:** Swarm tools receive `externals: dict[str, Any]` and look up keys at runtime. No type checking, no interface contract. Tool dependencies are invisible at the type level.

**Action:** Replace with a typed protocol:

```python
class AgentContext(BaseModel):
    agent_id: str
    config: RemoraSettings
    emit_event: Callable
    workspace: CairnWorkspaceService
    subscriptions: SubscriptionRegistry
```

Tools declare dependencies as typed fields. SwarmExecutor constructs the typed context.

**Blocked by:** 2.3 (Pydantic Config) for the `config` field type.
**Estimate:** ~0.5 day

---

### 2.6 Kernel Factory to Deduplicate Client/Adapter/Kernel Creation

**Sources:** Original Review I-04
**Severity:** MEDIUM
**Files:**
- `src/remora/core/swarm_executor.py` — builds client/adapter/kernel
- `src/remora/core/chat.py` — builds client/adapter/kernel independently

**Problem:** Both `SwarmExecutor._run_kernel` and `ChatSession.send` construct their own LLM client, adapter, and kernel with ~30 lines of duplicate setup code. These will drift.

**Action:** Extract a shared factory:

```python
def create_kernel(config: LLMConfig, tools: list[ToolSchema]) -> Kernel:
    client = build_client(config.base_url, config.api_key)
    adapter = build_adapter(client, config.model)
    return Kernel(adapter=adapter, tools=tools)
```

**Blocked by:** 2.3 (Pydantic Config) for the `LLMConfig` type.
**Estimate:** ~1 hour

---

### 2.7 Populate or Remove `last_trigger_event` Dead Schema

**Sources:** Phase 1 Review D2/#14
**Severity:** MEDIUM
**Files:**
- `src/remora/core/agent_node.py` — has `last_trigger_event` field
- `src/remora/core/projections.py` — `nodes` table has column, but no projection method ever writes to it

**Problem:** The `last_trigger_event` field exists in the model and the database schema, but is always empty string. It's dead schema that misleads readers.

**Action:** Either:
1. Populate it in `_project_agent_start()` with the trigger event's ID/type (preferred — the concept doc implies agents track what triggered them)
2. Remove the field and column entirely if cascade tracking is handled differently

**Blocked by:** Design decision on cascade tracking approach.
**Estimate:** ~30 minutes

---

### 2.8 Add `start_byte`/`end_byte` to NodeDiscoveredEvent

**Sources:** Phase 1 Review D3/#22
**Severity:** LOW
**File:** `src/remora/core/events.py:139-153`

**Problem:** `CSTNode` (from `discovery.py`) includes `start_byte` and `end_byte` fields, but they're dropped when converting CSTNode → NodeDiscoveredEvent. This data loss means precise byte-offset LSP ranges are impossible.

**Action:** Add `start_byte: int` and `end_byte: int` fields to `NodeDiscoveredEvent`. Update the CSTNode → event conversion path to carry these values.

**Blocked by:** Nothing.
**Estimate:** ~30 minutes

---

### 2.9 Fix `AgentMessageEvent.tags` Mutability

**Sources:** Phase 1 Review B4/#23, Original Review F-04
**Severity:** LOW
**File:** `src/remora/core/events.py:103`

**Problem:** `AgentMessageEvent.tags` is `list[str]` on a frozen dataclass. `frozen=True` prevents reassignment of the field, but the list contents are still mutable: `event.tags.append("x")` succeeds. This violates the "immutable event" contract.

**Action:** Change `list[str]` to `tuple[str, ...]` with `default_factory=tuple`.

**Blocked by:** Nothing. If 2.1 (Pydantic events) happens first, use `frozen=True` on the Pydantic model which handles this automatically.
**Estimate:** ~15 minutes

---

### 2.10 Parameterize Language in System Prompt

**Sources:** Phase 1 Review D7/#8
**Severity:** LOW
**File:** `src/remora/core/agent_node.py:129`

**Problem:** `to_system_prompt()` hardcodes `"Python"` in the prompt template (`"a Python {self.node_type}"`). The concept doc supports non-Python languages via tree-sitter.

**Action:** Add a `language: str = "Python"` field to `AgentNode` (derived from file extension or tree-sitter grammar) and use it in the prompt template.

**Blocked by:** Nothing.
**Estimate:** ~30 minutes

---

### 2.11 Subscription Index for O(1) Lookup

**Sources:** Original Review I-08, F-15
**Severity:** LOW
**File:** `src/remora/core/subscriptions.py:243`

**Problem:** Pattern matching loads ALL subscriptions from SQLite every time. O(n) per event. Fine for small swarms, but will become a bottleneck with hundreds of agents.

**Action:** Cache subscriptions in memory with invalidation on register/unregister. Index by `event_type` for O(1) lookup instead of loading all rows on every event.

**Blocked by:** Nothing.
**Estimate:** ~1-2 hours

---

## Phase 3: Dead Code Removal

Eliminate pre-unification artifacts, stale shims, and unused code. These are zero-risk removals that reduce confusion and the maintenance surface. Ordering matters — high-impact items first.

### 3.1 High-Impact Removals (Entire Modules)

These are entire modules or subsystems that exist because the Option A unification was completed for the LSP layer but not yet for the core runner layer. Items marked "blocked" should wait for Phase 1 completion.

| # | File/Directory | Lines | Reason | Blocked By |
|---|----------------|-------|--------|------------|
| D1 | `src/remora/core/agent_state.py` | 84 | JSONL persistence for pre-unification AgentState. Vision says nodes table IS agent state. | 1.1 (identity unification) |
| D2 | `src/remora/core/swarm_state.py` `agents` table | ~100 | Duplicates EventStore `nodes` table. Reconciler and CLI should query EventStore directly. | 1.1 (identity unification) |
| D3 | `src/remora/nvim/` (`__init__.py`, `server.py`) | ~265 | Pre-LSP JSON-RPC `NvimServer` via Unix socket. Completely superseded by `lsp/`. | Nothing |
| D4 | `src/remora/core/vcs.py` | 35 | Only supports Jujutsu. Commented out in SwarmExecutor. Dead code. | Nothing |
| D5 | `plugin/remora_nvim.lua` | ~50 | Legacy pre-LSP plugin. References `remora_nvim.sidepanel`, `remora_nvim.chat` which don't exist. | Nothing |
| D6 | `load.vim` | ~10 | References `remora_nvim` (legacy plugin). | Nothing |

**Action:** Delete D3-D6 immediately (no dependencies). Delete D1-D2 after Phase 1 items 1.1 and 1.2 are complete.

**Estimate:** ~30 minutes for D3-D6. D1-D2 included in 1.1 estimate.

---

### 3.2 Medium-Impact Removals (Shims, Enums, Legacy Wrappers)

| # | File/Location | Lines | Reason | Blocked By |
|---|---------------|-------|--------|------------|
| D7 | `src/remora/core/discovery.py` `TreeSitterDiscoverer` class | ~25 | Legacy compatibility wrapper with dead `query_pack` parameter. | Nothing |
| D8 | `src/remora/core/discovery.py` `NodeType` enum | ~10 | Not used in any business logic. Only consumer is `tests/roundtrip/run_harness.py`. | Nothing |
| D9 | `src/remora/models/__init__.py` | ~80 | Stdlib dataclass models (`ConfigSnapshot`, etc.). Service layer uses these but should use Pydantic. | 2.3 (Pydantic Config) |
| D10 | `tests/helpers.py` | ~10 | Deprecated shim that re-exports from `remora.testing`. Emits deprecation warning. | Nothing |
| D11 | `tests/fixtures/mock_llm.py` | 10 | Superseded by `src/remora/testing/fakes.py` (`FakeAsyncOpenAI`). | Nothing |
| D12 | `src/remora/ui/view.py` `render_tag` | ~15 | Marked as "Legacy function" in the source. | Nothing |

**Action:** Delete D7, D8, D10, D11, D12 immediately. D9 after 2.3.

**Estimate:** ~30 minutes for immediate items.

---

### 3.3 Stale Re-exports and Minor Cleanup

| # | File | Action |
|---|------|--------|
| D13 | `src/remora/__init__.py` | Remove re-exports of `AgentState`, `SwarmState`, `compute_node_id`, `TreeSitterDiscoverer`. Export only current artifacts: `AgentNode`, `EventStore`, `EventBus`, `SubscriptionRegistry`, core events, discovery functions. |
| D14 | `src/remora/core/__init__.py` | Remove imports/exports of `AgentState`, `SwarmState`, `AgentMetadata` after 1.1. |
| D15 | `src/remora/lsp/__init__.py` | Verify exports are correct — repo cleanup planning found broken imports of deleted `ASTAgentNode` and `ToolSchema`. |
| D16 | `src/remora/core/config.py:85-87` | Remove duplicate inline `from .errors import ConfigError` import (already imported at module level). |

**Blocked by:** D13, D14 blocked by 1.1. D15, D16 can be done immediately.

**Estimate:** ~30 minutes total.

---

## Phase 4: Testing Gaps

The test suite has excellent coverage for the event pipeline and LSP subsystem (205 passing tests), but critical gaps exist in the execution layer and service layer. Several of these gaps hide known bugs (F-21, F-32). Write tests after Phase 1 changes land, since the runner merge will reshape the code being tested.

### 4.1 CRITICAL: SwarmExecutor — Zero Tests

**Sources:** Phase 2 Review Gap 1
**File:** `src/remora/core/swarm_executor.py` (375 lines)

**Problem:** Handles LLM communication, tool dispatch, Grail execution, and agent turns. Has no direct tests. In `test_agent_runner.py`, the executor is fully mocked out — we never verify that it correctly invokes the LLM, dispatches tools, or handles results.

**Action:** After the runner merge (1.2), write tests for whatever the post-merge execution engine looks like. Cover:
- LLM invocation with `FakeAsyncOpenAI`
- Tool dispatch (correct tool selected, correct parameters passed)
- Grail execution integration
- Error handling (LLM timeout, malformed response, tool failure)
- The `_broadcast` bug (1.9) should be caught by a broadcast test

**Blocked by:** 1.2 (runner merge).
**Estimate:** ~1 day

---

### 4.2 CRITICAL: ChatSession — Zero Tests

**Sources:** Phase 2 Review Gap 2
**File:** `src/remora/core/chat.py` (259 lines)

**Problem:** Manages conversation history, LLM interaction, and tool calling for the chat interface. No tests exist. This is user-facing functionality.

**Action:** Write unit tests covering:
- Message history management (add, truncate, persistence)
- Tool call dispatch and result handling
- LLM interaction using `FakeAsyncOpenAI`
- Error handling and retry logic
- The `cleanup()` AttributeError bug (1.11) should be caught

**Blocked by:** Nothing (chat.py is independent of runner merge).
**Estimate:** ~1 day

---

### 4.3 AgentRunner Run Loop — Untested Dispatch

**Sources:** Phase 2 Review Gap 3
**File:** `src/remora/core/agent_runner.py`

**Problem:** `test_agent_runner.py` tests cascade guards (depth limits, cooldowns, concurrency) but never tests the actual `run_forever()` event processing loop, `_dispatch_trigger` logic, or the AgentState load/save cycle.

**Action:** After the runner merge (1.2), write tests for the unified runner's core loop:
- Receive trigger → load agent → invoke executor → save result
- Event dispatch to correct agent
- Trigger filtering (only subscribed events)

**Blocked by:** 1.2 (runner merge).
**Estimate:** ~0.5 day

---

### 4.4 service/ Package — Zero Tests, Has Bugs

**Sources:** Phase 2 Review Gap 4
**Files:**
- `src/remora/service/api.py` (200 lines) — has duplicate `get_subscriptions` bug (M1/S-01)
- `src/remora/service/handlers.py` (147 lines)
- `src/remora/service/datastar.py` (68 lines)
- `src/remora/service/chat_service.py` (243 lines)

**Problem:** 658 lines of untested code. The `get_subscriptions` name collision (S-01) is a confirmed bug.

**Action:** Write unit tests for all four modules. The tests will also catch the S-01 bug.

**Blocked by:** Nothing.
**Estimate:** ~1-2 days

---

### 4.5 CLI Commands — No Unit Tests

**Sources:** Phase 2 Review Gap 5
**File:** `src/remora/cli/main.py` (338 lines)

**Problem:** Only `test_cli_real.py` does subprocess-level smoke tests. The `swarm start`, `swarm reconcile`, `swarm list`, and `swarm stop` commands are untested.

**Action:** Write unit tests for each CLI command. Mock the EventStore/SwarmState/etc. to test command logic in isolation.

**Blocked by:** Nothing (but CLI commands may change after 1.1/1.2).
**Estimate:** ~1 day

---

### 4.6 Phase 1 Testing Gaps

**Sources:** Phase 1 Review T1-T7

These are specific testing gaps identified during the Phase 1 code review:

| # | Gap | Priority | Estimate |
|---|-----|----------|----------|
| T1 | `ToolSchema.to_llm_tool()` — zero tests for LLM tool conversion | HIGH | 30 min |
| T2 | Extension with complex fields (`extra_tools`, `extra_subscriptions`) through projection round-trip | HIGH | 1 hour |
| T3 | Error paths for `from_row()` with malformed JSON (`extra_tools = "not-json"`) | MEDIUM | 30 min |
| T4 | Concurrency tests for multiple `append()` calls racing on same `node_id` | MEDIUM | 1 hour |
| T5 | CSTNode → NodeDiscoveredEvent conversion (doesn't exist yet, tracked) | MEDIUM | After conversion path is built |
| T6 | Extension `matches()` raising exceptions (error isolation) | MEDIUM | 30 min |
| T7 | `conftest.py` fixtures for new types (`make_agent_node()`, `make_discovered_event()`, `store_with_projection`) | LOW | 30 min |

**Action:** Address T1 and T2 immediately (they test critical conversion paths). T3-T7 can be done alongside other test work.

**Blocked by:** Nothing for T1-T4, T6-T7. T5 blocked by conversion path implementation.
**Estimate:** ~0.5 day total

---

### 4.7 Test Infrastructure Cleanup

**Sources:** Phase 2 Review Q2-Q6

| # | Issue | Action |
|---|-------|--------|
| Q2 | Duplicate `_make_node()` helper across 3 test files | Extract to `tests/conftest.py` or `src/remora/testing/fakes.py` |
| Q3 | `MockLLMClient` vs `FakeAsyncOpenAI` — two mock LLM implementations | Retire `MockLLMClient` (covered by D11 in Phase 3) |
| Q4 | `tests/helpers.py` deprecated shim | Delete (covered by D10 in Phase 3) |
| Q6 | Pre-existing test failure: `workspace/executeCommand` missing from capabilities | Add `workspace/executeCommand` to capabilities dict in the handler — one-line fix |

**Action:** Fix Q6 immediately (~5 min). Q2 during test work. Q3/Q4 covered by Phase 3 dead code removal.

**Blocked by:** Nothing.
**Estimate:** ~30 minutes total

---

## Phase 5: Quality & Polish

Performance improvements, UX fixes, and remaining medium/low severity items from all reviews. These are not blockers but improve the library's robustness and developer experience.

### 5.1 Performance Improvements

| # | Issue | Source | File | Action | Estimate |
|---|-------|--------|------|--------|----------|
| P1 | LLM client created per execution — no connection pooling | F-11, I-11 | `swarm_executor.py:273` | Create LLM client once per lifecycle, reuse across turns. HTTP client maintains connection pool. | 1 hour |
| P2 | Workspace sync reads entire project via `rglob("*")` — no incremental sync | F-18, I-05 | `cairn_bridge.py:138` | Add file mtime comparison on startup, `watchfiles` for runtime change detection, content-hash dedup. | 0.5 day |
| P3 | `list_nodes()` fetches all columns including `source_code` | Phase 1 P2 | `event_store.py` | Add optional `columns` parameter for lightweight queries (e.g., node_id + status + line range). | 1 hour |

---

### 5.2 LSP Layer Fixes

| # | Issue | Source | File | Action | Estimate |
|---|-------|--------|------|--------|----------|
| L1 | `_notify_agents_updated` monkey-patched onto `server` | I-12, L-02 | `lsp/__main__.py:26` | Make `notify_agents_updated` a proper method on `RemoraLanguageServer`. | 30 min |
| L2 | Module-level `server` singleton with import side effects | L-03 | `lsp/server.py:30` | Defer initialization — construct DB/Graph/Watcher lazily or in an explicit `init()` method. | 1 hour |
| L3 | `_extract_text_tool_calls` parses model-specific XML tags | L-07 | `lsp/runner.py:160-180` | Document the Qwen-specific workaround. Consider making it configurable. | 30 min |
| L4 | Watcher double-parse bug | V24 Review | `lsp/watcher.py:27-28` | `self.parser.parse(...)` called twice, first result discarded. Delete line 27. | 5 min |
| L5 | `ensure_file_synced` is a stub | F-19 | `cairn_bridge.py:164-166` | Implement actual file sync or remove the method entirely. | 30 min |
| L6 | `did_save` reads file from disk — races with editor buffer | V24 Review | `handlers/documents.py` | Use LSP-provided text content when available. | 30 min |

---

### 5.3 Service/UI Layer Fixes

| # | Issue | Source | File | Action | Estimate |
|---|-------|--------|------|--------|----------|
| S1 | `get_subscriptions` method name collision | S-01, M1 | `service/api.py:167,186` | Rename property to `subscription_registry`, method to `get_agent_subscriptions`. | 5 min |
| S2 | `total_agents` counter bug — stays at 1 forever | S-05 | `ui/projector.py:132-133` | Fix counter logic: increment properly on each new agent, not just the first. | 15 min |
| S3 | Module-level `state = ChatServiceState()` singleton | S-02 | `service/chat_service.py` | Use dependency injection instead of module-level singleton. Remove deprecated `@app.on_event("startup")`. | 30 min |
| S4 | `DatastarResponse` content type mismatch | S-03 | `adapters/starlette.py` | Fix type annotations: `AsyncIterator[str]` vs `DatastarEvents`. | 15 min |
| S5 | Duplicate prompt context — model sees history twice | F-14 | `swarm_executor.py:344` | Prompt includes last 5 chat entries AND kernel gets full history. Remove the redundant prompt inclusion. | 15 min |
| S6 | Chat history hardcoded to last 10 entries | F-13 | `swarm_executor.py:229` | Make configurable via Config. | 15 min |
| S7 | Code fences in prompts lack language tags | F-26 | `swarm_executor.py:333` | Add `python` language tag to code fences. | 5 min |

---

### 5.4 Neovim Plugin Fixes

| # | Issue | Source | File | Action | Estimate |
|---|-------|--------|------|--------|----------|
| N1 | `nui.popup` hard crashes without plugin | N-01, R6 | `panel.lua:2` | Wrap `require("nui.popup")` in `pcall` with graceful fallback message. | 5 min |
| N2 | `M.is_open` name collision (boolean vs function) | N-02, R7 | `panel.lua:120` | Rename function to `M.get_is_open()` or remove it — callers use `M.state.is_open` directly. | 5 min |
| N3 | `buf_options = { readonly = true }` is a window option | N-03 | `panel.lua` | Change to `wo = { readonly = true }` or use `modifiable = false` as a buffer option. | 5 min |
| N4 | `cmd` defaults to demo path, not `remora-lsp` | R8 | `init.lua` | Change default `cmd` to `{ "remora-lsp" }` (the pyproject.toml entrypoint). | 5 min |

---

### 5.5 Remaining Low-Severity Items

| # | Issue | Source | File | Action |
|---|-------|--------|------|--------|
| R1 | Duplicate ignore pattern definitions | F-03 | `config.py:22`, `discovery.py:307` | Discovery should read from Config's `workspace_ignore_patterns`. |
| R2 | Cascade prevention uses `"base"` fallback for uncorrelated events | F-10 | `agent_runner.py:80-82` | Use event-specific correlation IDs instead of shared depth counter. |
| R3 | Event bus handler errors swallowed (logged as warning) | F-06, I-06 | `event_bus.py:56-57` | Add configurable error policy: LOG (current), PROPAGATE (testing), DEAD_LETTER (production). |
| R4 | `build_virtual_fs` adds both `/path` and `path` entries | F-30 | `tools/grail.py:98-105` | Remove duplicate entry to halve memory usage. |
| R5 | `_find_config_file` returns non-existent sentinel path | F-28 | `config.py:92-103` | Document the behavior or return `None`. |
| R6 | `_to_jsonable` uses `asdict` with type mismatch | S-06 | `ui/projector.py` | Fix type annotation or add runtime type check. |
| R7 | `BlockedAgentCard` XSS concern — simple quote replacement | S-08 | `ui/components/dashboard.py` | Use proper HTML escaping library. |
| R8 | Extension cache is module-level mutable global state | Phase 1 D5 | `extensions.py:38` | Make `load_extensions` a method on a class that owns its cache, or accept a cache parameter. |
| R9 | Dead `hashlib` import in `agent_node.py` | Phase 1 B5 | `agent_node.py:9` | Delete the import. |

---

## Dependencies and Ordering

### Critical Path

```
1.2 (Runner Merge)
  └─→ 1.1 (Identity Unification)
        └─→ 3.1 D1/D2 (Delete agent_state.py, SwarmState agents table)
        └─→ 3.3 D13/D14 (Clean re-exports)
        └─→ 4.1 (Test unified executor)
        └─→ 4.3 (Test unified runner loop)
```

### Independent Tracks (can run in parallel)

These items have no dependencies on the critical path and can be done at any time:

**Track A — Quick Fixes (< 1 hour each):**
- 1.3 Transaction boundary bug
- 1.5 `__dict__` serialization
- 1.9 `_broadcast` NameError
- 1.10 Parser/model mismatch
- 1.11 `chat.py` cleanup bug
- 3.1 D3-D6 (delete nvim/, vcs.py, plugin/, load.vim)
- 3.2 D7, D8, D10, D11, D12 (shims, enums, legacy)
- 3.3 D15, D16 (broken LSP exports, duplicate import)
- 4.7 Q6 (workspace/executeCommand capability)
- 5.4 N1-N4 (Neovim plugin fixes)

**Track B — Medium Effort (0.5-1 day each):**
- 1.4 RemoraDB dual-write elimination
- 1.6 SubscribeTool bug (needs design decision)
- 1.7 Hardcoded LLM configs (short-term fix)
- 2.2 Widen extension matches() API
- 4.2 ChatSession tests
- 4.4 service/ package tests
- 4.6 Phase 1 testing gaps (T1-T7)

**Track C — Larger Effort (1+ days each):**
- 2.1 Event model unification
- 2.3 Pydantic Config
- 2.4 Single SQLite database
- 4.5 CLI tests
- 5.1 P2 (incremental workspace sync)

### Recommended Execution Order

1. **Immediate** (day 1): Quick fixes from Track A — all the 5-minute and 15-minute items
2. **Week 1**: Critical path (1.2 → 1.1 → D1/D2) + Track B items in parallel
3. **Week 2**: Architecture alignment (2.1-2.6) + Phase 4 testing
4. **Week 3**: Quality & polish (Phase 5) + remaining Phase 3 cleanup

---

## Constraints

1. **NO SUBAGENTS** — all work must be done directly. No delegation. No exceptions.
2. **Library only** — `remora_demo/` is excluded from this plan.
3. **AgentNode is THE model** — single Pydantic BaseModel, no subclasses anywhere. Specialization is data-driven via `AgentExtension`.
4. **EventStore is THE source of truth** — every state change is an event. All other state (nodes table, subscriptions, UI) is derived via projections.
5. **No `isinstance` in business logic** — projection dispatch (internal) is the exception.
6. **TDD** — write a failing test first, implement, verify the test passes.
7. **DRY/YAGNI** — no duplication, no speculative features.

---

*End of Remora Launch Plan*
