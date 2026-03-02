# Event-Based Architecture — Phase 2 Code Review

**Date:** 2026-03-02
**Scope:** All source code in `src/remora/` and all tests in `tests/` (excluding `remora_demo/`)
**Reference:** `docs/EventBased_Concept.md` (authoritative vision)

---

## 1. Executive Summary

### Assessment

The Remora codebase is **architecturally sound in its core event pipeline** — EventStore, AgentNode, projections, subscriptions, and the EventBus form a clean, well-tested foundation that faithfully implements the EventBased vision. The Phase 1 LSP→EventStore unification was a significant success: the entire LSP subsystem now reads node state from EventStore projections, and the old `ASTAgentNode`, `lsp/extensions.py`, and `remora_id` concepts have been cleanly removed.

However, the codebase is **not yet fully unified**. Two critical architectural splits remain:

1. **Triple agent identity**: AgentNode (EventStore), AgentState (JSONL), and AgentMetadata (SwarmState SQLite) all coexist and store overlapping data. The vision explicitly states that the `nodes` table row IS the agent's state — there should be no separate AgentState file and no duplicate `agents` table in SwarmState.

2. **Dual agent runner**: `core/agent_runner.py` and `lsp/runner.py` are two completely independent implementations of the agent execution loop. They share no code, use different state backends, and implement different tool systems. The vision describes ONE reactive loop.

These are not minor issues — they represent the last major barrier between the current codebase and the vision's promise of "a single, unified event-driven system."

### Key Metrics

| Metric | Value |
|--------|-------|
| Source files reviewed | 71 |
| Source lines of code | ~10,562 |
| Test files reviewed | 66 |
| Test lines of code | ~5,886 |
| Tests passing | 205 |
| Tests failing (pre-existing) | 1 |
| CRITICAL findings | 2 |
| HIGH findings | 3 |
| MEDIUM findings | 8 |
| LOW findings | 4 |
| Untested components | 6 (SwarmExecutor, ChatSession, service/, CLI, nvim/, ui/) |

### Verdict

**The foundation is excellent. The unification is incomplete.** The EventStore+AgentNode+Projection pipeline is the best part of this codebase — well-designed, well-tested, and closely aligned with the vision. The LSP subsystem migration proved this architecture works at scale. What remains is to extend this same discipline to the core agent runner and eliminate the pre-unification artifacts (AgentState, SwarmState agents table, dual event writes) that fragment the system's identity model.

---

## 2. Methodology

### Scope

**Included:**
- All Python source files in `src/remora/` (71 files, ~10,562 lines)
- All test files in `tests/` (66 files, ~5,886 lines)
- The testing module at `src/remora/testing/`
- The vision document at `docs/EventBased_Concept.md` (2,120 lines)

**Excluded:**
- `remora_demo/` and its associated tests (`test_graph_*.py`, `test_web_layout.py`) — being developed separately
- `tests/benchmarks/` — performance tests, out of scope for architecture review
- `tests/integration/cairn/` — cairn-specific tests with known pre-existing failures

### Review Process

1. **Full source read**: Every file in `src/remora/` (excluding `remora_demo/`) was read in its entirety, with findings recorded by severity.
2. **Full test read**: Every test file in `tests/` (excluding demo/benchmark/cairn) was read, with coverage gaps and quality issues recorded.
3. **Vision cross-reference**: The `EventBased_Concept.md` vision document was re-read and used as the authoritative reference for every architectural judgment.
4. **Cross-cutting analysis**: Findings were synthesized across all files to identify systemic patterns (identity fragmentation, dual writes, dead code clusters).

### Review Dimensions

- **Architecture alignment**: Does the implementation match the EventBased vision?
- **Code quality**: Bugs, dead code, duplication, naming, organization
- **Test coverage**: What's tested, what's not, and what's tested incorrectly
- **Integration coherence**: Do the subsystems work together as a unified whole?
- **Elegance**: Is the codebase the cleanest, most direct expression of the architecture?

---

## 3. Architecture Alignment with Vision

This section evaluates the codebase against each core concept defined in `docs/EventBased_Concept.md`.

### 3.1 EventLog as Single Source of Truth

**Vision says:** Every state change is recorded as an immutable event in the EventLog. The EventLog is the one authoritative record. All other state (node table, subscriptions, UI) is derived from it via projections.

**Reality:**

The EventStore (`core/event_store.py`, 508 lines) is well-implemented and faithfully represents this concept:
- Immutable append-only event log with `append()`, `replay()`, `count()`
- Graph-scoped isolation (events belong to a `graph_id`)
- SQLite-backed with proper schema
- Trigger mechanism for reactive dispatch (`register_trigger`, `_fire_triggers`)
- NodeProjection integration — appending events automatically materializes node state

**Gap — Dual event storage:** RemoraDB (`lsp/db.py:75-118`) maintains its own `events` table. The LSP server's `emit_event()` method writes to BOTH EventStore and RemoraDB. This dual-write violates the single-source-of-truth principle. If one write fails and the other succeeds, the stores diverge. The RemoraDB `events` table should be eliminated in favor of querying EventStore directly.

**Gap — AgentState JSONL bypass:** The core `AgentRunner` (`core/agent_runner.py`) reads and writes agent state via `AgentState` JSONL files in `.remora/agents/`, completely bypassing the EventStore. State changes made through this path are invisible to the event log.

**Alignment: ~70%** — The EventStore itself is solid. The two parallel state stores (RemoraDB events, AgentState JSONL) undermine the "single source of truth" guarantee.

### 3.2 AgentNode as the Universal Node Model

**Vision says:** There is one `AgentNode` model. Every code node (function, class, method, file) is represented as an AgentNode row in the `nodes` table. Specialization is data-driven via `AgentExtension`, not subclasses. The vision (Section 5) explicitly states: *"There is no separate AgentState file. The nodes table row IS the agent's state."*

**Reality:**

The `AgentNode` model (`core/agent_node.py`, 254 lines) is cleanly implemented:
- Single Pydantic `BaseModel`, no subclasses (per REPO_RULES)
- Rich field set: identity, location, content, LSP output, status, metadata
- `AgentExtension` support for data-driven specialization
- Proper `from_event()` factory and `to_lsp_dict()` output method
- The Phase 1 unification successfully removed `ASTAgentNode` and centralized on this model

**Gap — Triple identity:** Three separate systems store agent/node identity:

| System | Storage | Used By |
|--------|---------|---------|
| AgentNode | EventStore `nodes` table (via projection) | LSP runner, LSP graph, notifications, handlers |
| AgentState | JSONL files in `.remora/agents/` | Core AgentRunner, SwarmExecutor |
| AgentMetadata | SwarmState SQLite `agents` table | Reconciler, CLI `swarm list` |

The fields overlap significantly — all three store name, file path, node type, and status. This means updating an agent's status requires updating up to three different stores, and they can (and will) diverge.

**Alignment: ~60%** — The AgentNode model itself is exactly what the vision describes. But the vision's promise that "the nodes table row IS the agent's state" is not yet realized because AgentState and SwarmState's agents table still exist and are actively used by the core runner and reconciler.

### 3.3 Subscriptions and Reactive Communication

**Vision says:** Agents communicate by subscribing to event patterns. Subscriptions are stored as events themselves. The SubscriptionRegistry materializes these into efficient lookup structures.

**Reality:**

The subscription system (`core/subscriptions.py`, 287 lines) is well-implemented:
- `SubscriptionPattern` with agent-scoped and type-scoped matching
- `SubscriptionRegistry` with `register()`, `matches()`, and pattern-based lookup
- Default subscriptions auto-created on node discovery
- Clean integration with EventStore and EventBus

**Gap — SubscribeTool self-referencing bug:** In `tools/swarm.py:140`, the `SubscribeTool` creates patterns with `to_agent=agent_id` — where `agent_id` is the subscribing agent itself. This means the subscription only matches events where `to_agent` equals the subscriber, which defeats the purpose. A subscription like "agent A subscribes to events about agent B" would instead create a pattern matching events sent TO agent A about agent B, which is backwards. The `to_agent` field should likely be omitted or set to a different value.

**Alignment: ~85%** — The subscription infrastructure is solid and closely matches the vision. The SubscribeTool bug is a localized issue that doesn't affect the core subscription machinery.

### 3.4 The Reactive Agent Loop

**Vision says:** Each agent runs a reactive loop: wake on subscribed event → load context from EventStore → invoke LLM → apply tool results → emit new events → sleep. There is ONE such loop, not per-subsystem implementations.

**Reality:**

There are TWO agent loop implementations:

**LSP Runner** (`lsp/runner.py`, 674 lines):
- Uses EventStore for node lookup (`_store.get_node()`)
- Has its own `LLMClient` wrapping `AsyncOpenAI`
- Implements tool dispatch: `rewrite`, `insert`, `ask_human`, `subscribe`, `emit_event`, `read_file`, `get_project_context`
- Proposal system for code changes (requires human approval)
- Well-integrated with the EventBased architecture

**Core AgentRunner** (`core/agent_runner.py`, 288 lines):
- Uses AgentState JSONL files (NOT EventStore)
- Delegates to `SwarmExecutor` for LLM communication
- Has its own trigger/dispatch system via EventStore triggers
- Cascade safety guards (depth limits, cooldowns, concurrency)

These share no code. The LSP runner is more aligned with the vision (it uses EventStore). The core runner is a pre-unification design that persists state outside the event system.

**Alignment: ~50%** — The LSP runner is a faithful implementation of the reactive loop. The core runner represents a parallel, pre-unification approach. Merging these into a single runner that uses EventStore is the highest-impact remaining work.

### 3.5 Cascade Safety and Depth Control

**Vision says:** Agent A's output event may trigger Agent B, whose output triggers Agent C, forming a cascade. The system must enforce depth limits, cooldowns, and concurrency guards to prevent runaway cascades.

**Reality:**

The core `AgentRunner` (`core/agent_runner.py:40-70`) implements cascade safety well:
- `max_cascade_depth` (default 5) — tracked via event metadata
- `cascade_cooldown_seconds` (default 2.0) — prevents re-triggering too quickly
- `max_concurrent_agents` (default 3) — semaphore-based concurrency control
- These are tested in `tests/integration/test_agent_runner.py`

**Alignment: ~90%** — Cascade safety is implemented and tested. The only concern is that these guards live in the core runner, which is the pre-unification runner. When the runners are merged, these guards need to be preserved.

### 3.6 LSP Integration and the Editor Bridge

**Vision says:** The LSP server is the bridge between the editor and the agent swarm. It uses EventStore for all node state, emits events for editor actions (cursor movement, document changes), and presents agent output through LSP features (code lens, hover, code actions).

**Reality:**

The Phase 1 unification was a major success here:
- LSP server (`lsp/server.py`, 144 lines) initializes EventStore and wires it through handlers
- Document handlers (`handlers/documents.py`) emit `NodeDiscoveredEvent` and `NodeRemovedEvent` via the watcher
- Notification handler (`handlers/commands.py`, `lsp/notifications.py`) reads from EventStore, not RemoraDB
- Code lens, hover, and code actions all source data from EventStore projections
- LazyGraph (`lsp/graph.py`) reads from EventStore with invalidation on change

**Gap — LSP event model duplication:** `lsp/models.py` (255 lines) defines its own Pydantic event hierarchy (`AgentEvent`, `HumanChatEvent`, `ToolCallEvent`, etc.) with `to_core_event()` bridge methods. This parallel event model exists because the LSP layer needs Pydantic validation for JSON-RPC, while core events are frozen dataclasses. This is a design tension rather than a bug, but it means every new event type requires definitions in two places.

**Gap — RemoraDB dual-write:** As noted in 3.1, the LSP server writes events to both EventStore and RemoraDB. The RemoraDB `events` table should be retired.

**Gap — Hardcoded LLM config:** `lsp/__main__.py` hardcodes `base_url="http://remora-server:8000/v1"` and `model="Qwen/Qwen3-4B-Instruct-2507-FP8"` instead of reading from `Config`.

**Alignment: ~80%** — The LSP subsystem is the most vision-aligned part of the codebase, thanks to the Phase 1 unification. The remaining gaps are the dual-write pattern and event model duplication.

---

## 4. Source Code Findings

### CRITICAL

#### C1. Dual/Triple Agent Identity System

Three separate systems store agent/node identity with overlapping fields:

| System | Model | Storage | Used By |
|--------|-------|---------|---------|
| AgentNode | Pydantic BaseModel | EventStore `nodes` table (via NodeProjection) | LSP runner, graph, notifications, handlers |
| AgentState | Frozen dataclass | JSONL files in `.remora/agents/` | Core AgentRunner, SwarmExecutor |
| AgentMetadata | Dataclass | SwarmState SQLite `agents` table | Reconciler, CLI `swarm list` |

All three store: name, file path, node type, and status. The vision (Section 5) explicitly states: *"There is no separate AgentState file. The nodes table row IS the agent's state."*

**Impact:** State changes in one system are invisible to the others. An agent activated via the core runner (AgentState) won't show as active in the LSP view (AgentNode). The reconciler (AgentMetadata) may disagree with both.

**Recommendation:** Eliminate AgentState and SwarmState's `agents` table. All agent state should live in EventStore `nodes` table, accessed via AgentNode projections. The reconciler and CLI should query EventStore directly.

**Files:**
- `src/remora/core/agent_state.py` — entire file (84 lines) should be eliminated
- `src/remora/core/swarm_state.py` — `agents` table (197 lines; the `subscriptions` table may still be needed temporarily)
- `src/remora/core/swarm_executor.py` — reads/writes AgentState
- `src/remora/core/agent_runner.py` — reads/writes AgentState
- `src/remora/core/reconciler.py` — reads/writes AgentMetadata via SwarmState

#### C2. Two Separate AgentRunner Implementations

| Runner | File | Lines | State Backend | Tool System |
|--------|------|-------|---------------|-------------|
| Core AgentRunner | `src/remora/core/agent_runner.py` | 288 | AgentState JSONL | SwarmExecutor → Grail tools |
| LSP Runner | `src/remora/lsp/runner.py` | 674 | EventStore | Built-in tools (rewrite, insert, etc.) |

These share no code, no base class, no common interface. The vision describes ONE reactive loop where every agent — whether triggered by an LSP event or a swarm cascade — executes through the same pipeline.

**Impact:** Bug fixes, performance improvements, and new features must be implemented twice. Cascade safety (depth limits, cooldowns) is only in the core runner — the LSP runner has no cascade protection.

**Recommendation:** Merge into a single runner that:
1. Uses EventStore for all state (like the LSP runner)
2. Preserves cascade safety guards (from the core runner)
3. Supports both tool sets via a pluggable tool registry
4. Has one `execute_turn()` contract

### HIGH

#### H1. SwarmState `agents` Table Duplicates `nodes` Table

`src/remora/core/swarm_state.py` creates an `agents` table with columns: `agent_id`, `node_type`, `name`, `full_name`, `file_path`, `start_line`, `end_line`, `parent_id`, `status`. These are the same fields as the EventStore `nodes` table populated by NodeProjection.

The vision (Section 1.1) says SwarmState should be *"derived from the nodes table"* — not a parallel store.

**Recommendation:** Replace all SwarmState agent queries with EventStore `list_nodes()` / `get_node()`. If SwarmState needs to persist swarm-level metadata not captured in AgentNode (e.g., activation timestamps), add those as AgentNode fields or extensions rather than a separate table.

#### H2. LSP Event Model Duplication

`src/remora/lsp/models.py` (255 lines) defines a Pydantic event hierarchy:
- `AgentEvent`, `HumanChatEvent`, `ToolCallEvent`, `ToolResultEvent`, `AgentThinkingEvent`, `AgentResponseEvent`, `ErrorEvent`
- Each has a `to_core_event()` method bridging to `core/events.py` frozen dataclasses

This means every new event type requires two definitions — one in `lsp/models.py` (Pydantic) and one in `core/events.py` (dataclass). The bridge methods add maintenance burden and can silently fall out of sync.

**Recommendation:** Unify on one event representation. Options:
1. Make core events Pydantic models (preferred — aligns with AgentNode being Pydantic)
2. Auto-generate Pydantic wrappers from core dataclasses
3. Accept the duplication but add tests ensuring they stay in sync

#### H3. RemoraDB `events` Table — Dual Write

`src/remora/lsp/db.py:75-118` maintains its own `events` table. The LSP server writes to both EventStore and RemoraDB via `emit_event()`. This dual-write is fragile — if one write fails, the stores diverge silently.

**Recommendation:** Eliminate the RemoraDB `events` table. All event queries should go through EventStore. If RemoraDB needs to reference events (e.g., for UI queries), use EventStore's `graph_id` to scope queries.

### MEDIUM

#### M1. `service/api.py` — Duplicate `get_subscriptions` Method

`src/remora/service/api.py:167` defines `get_subscriptions` as a `@property` returning `SubscriptionRegistry | None`. Then `src/remora/service/api.py:186` redefines it as an `async def` taking `agent_id: str`. The second definition shadows the first, making the property permanently inaccessible.

**Recommendation:** Rename one of them — e.g., the property to `subscription_registry` and the method to `get_agent_subscriptions`.

#### M2. `tools/swarm.py` — SubscribeTool Self-Referencing Pattern

`src/remora/core/tools/swarm.py:140` creates subscription patterns with `to_agent=agent_id` where `agent_id` is the subscribing agent. This creates a pattern that only matches events where `to_agent` equals the subscriber — meaning the agent subscribes to events sent TO itself, not events FROM or ABOUT the target node.

**Recommendation:** The `to_agent` field should likely be omitted from the subscription pattern, or set to the target node's ID depending on the intended semantics.

#### M3. `lsp/__main__.py` — Hardcoded LLM Configuration

`src/remora/lsp/__main__.py:79` hardcodes `base_url="http://remora-server:8000/v1"` and `model="Qwen/Qwen3-4B-Instruct-2507-FP8"`. These should be read from `Config` or environment variables.

#### M4. `TreeSitterDiscoverer` Compatibility Shim

`src/remora/core/discovery.py` contains a `TreeSitterDiscoverer` wrapper class that appears to be a compatibility shim from before the discovery system was refactored. If no external code depends on this name, it should be removed.

#### M5. `NodeType` Enum Unused

`src/remora/core/discovery.py` defines a `NodeType` enum that is not used in any business logic. The only consumer is `tests/roundtrip/run_harness.py`. If this is not part of the public API, it should be removed.

#### M6. `render_tag` Legacy Function

`src/remora/ui/view.py` contains a `render_tag` function marked as legacy. If it has no consumers, remove it.

#### M7. Top-Level `__init__.py` Stale Re-exports

`src/remora/__init__.py` (117 lines) re-exports `TreeSitterDiscoverer`, `AgentState`, and `compute_node_id` — all of which are stale or pre-unification artifacts. The public API surface should be cleaned to reflect the current architecture.

#### M8. `isinstance` Usage in UI Layer

`src/remora/ui/projector.py:75-87` uses `isinstance` dispatch in `_event_kind()`. Per REPO_RULES, isinstance is prohibited in business logic but acceptable in projection dispatch. The UI categorization is a grey area — it's not business logic per se, but it could be replaced with a `kind` field on events.

### LOW

#### L1. CLI Duplicate Setup Code

`src/remora/cli/main.py` — `swarm start` and `swarm reconcile` both construct EventStore, SwarmState, and SubscriptionRegistry with ~30 lines of identical setup code. Should extract a shared `_create_swarm_context()` helper.

#### L2. Config Inline Import

`src/remora/core/config.py` — `load_config()` has an inline `from .errors import ConfigError` import alongside a module-level import of the same. Clean up the duplicate.

#### L3. Watcher Approximate `end_line`

`src/remora/lsp/watcher.py` — `_parse_fallback()` always sets `end_line` to `total_lines` for the file-level node, which is approximate. This is a documented limitation, not a bug.

#### L4. Graph `_normalize_node` Compat Hack

`src/remora/lsp/graph.py` — `_normalize_node()` adds both `id` and `node_id` keys to the output dict for backward compatibility. Once all consumers are updated to use `node_id`, the `id` alias can be removed.

---

## 5. Test Suite Analysis

### Overview

The test suite comprises 66 files with ~5,886 lines of test code, producing 205 passing tests and 1 pre-existing failure. Tests are well-organized into `unit/`, `integration/`, `fixtures/`, `utils/`, and `roundtrip/` directories.

The test infrastructure includes:
- `tests/conftest.py` (177 lines) — shared fixtures for EventStore, EventBus, AgentNode, tmp dirs
- `src/remora/testing/fakes.py` (120 lines) — `FakeAsyncOpenAI`, `FakeChatCompletions`, `FakeGrailExecutor`
- `tests/fixtures/mock_llm.py` (10 lines) — minimal `MockLLMClient` (largely superseded by `testing/fakes.py`)

### What's Well-Tested

The core event pipeline has excellent coverage:

| Component | Test Quality | Notes |
|-----------|-------------|-------|
| AgentNode | Thorough | Creation, serialization, LSP output, extension matching |
| Events (core) | Good | NodeDiscoveredEvent, NodeRemovedEvent construction and fields |
| Projections | Good | Insert, upsert, extension matching, status transitions |
| EventStore | Thorough | CRUD, concurrent append, trigger delivery, graph scoping |
| EventBus | Good | Emit, stream, wait_for |
| Subscriptions | Good | Register, defaults, pattern matching, edge cases |
| LSP Watcher | Good | Parse functions/classes/methods, ID preservation |
| LSP Runner | Thorough | EventStore-based dispatch, execute_turn, proposals, tools |
| LSP Graph | Good | Lazy loading from EventStore, invalidation |
| LSP DB | Good | Events, proposals, cursor_focus, migration guards |
| LSP Models | Good | Schema validation, code actions, event construction |
| Command Queue | Good | Push/poll/mark_done roundtrip, ordering |
| Discovery | Thorough | compute_node_id, CSTNode, multi-language, real-world files |

### Critical Coverage Gaps

#### Gap 1: SwarmExecutor — Zero Tests

`src/remora/core/swarm_executor.py` (375 lines) handles LLM communication, tool dispatch, Grail execution, and agent turns. It has **no direct tests**. In `test_agent_runner.py`, the executor is fully mocked out — so we never verify that it correctly invokes the LLM, dispatches tools, or handles results.

This is the most concerning gap because SwarmExecutor is where agents actually *do things* — it's the runtime engine for the core runner.

#### Gap 2: ChatSession — Zero Tests

`src/remora/core/chat.py` (259 lines) manages conversation history, LLM interaction, and tool calling for the chat interface. No tests exist. Given that this is user-facing functionality, it should have unit tests for message history management and tool call handling at minimum.

#### Gap 3: AgentRunner Run Loop — Untested

`tests/integration/test_agent_runner.py` tests cascade guards (depth limits, cooldowns, concurrency) but never tests the actual `run_forever()` event processing loop, `_dispatch_trigger` logic, or the AgentState load/save cycle. The runner's core behavior — receive trigger, load agent, invoke executor, save result — is untested.

#### Gap 4: service/ Package — Zero Tests

All four files in `src/remora/service/` (658 lines total) have no tests:
- `api.py` (200 lines) — API class with the duplicate `get_subscriptions` bug
- `handlers.py` (147 lines) — Request handlers
- `datastar.py` (68 lines) — SSE streaming
- `chat_service.py` (243 lines) — Chat service with streaming

#### Gap 5: CLI — No Unit Tests

`src/remora/cli/main.py` (338 lines) has no unit tests. Only `test_cli_real.py` does subprocess-level smoke tests for `serve` and invalid config. The `swarm start`, `swarm reconcile`, `swarm list`, and `swarm stop` commands are untested.

#### Gap 6: Peripheral Packages — No Tests

- `src/remora/nvim/server.py` (265 lines) — Neovim integration, zero tests
- `src/remora/ui/` (projector.py, view.py, components/) — UI rendering, zero tests
- `src/remora/adapters/starlette.py` (138 lines) — HTTP adapter, zero tests

### Test Quality Issues

#### Q1. Pre-Unification Tests Still Active

`tests/integration/test_agent_runner.py` creates `AgentState` JSONL files via `_ensure_agent_state()`, testing the pre-unification code path. `tests/unit/test_swarm_state.py` and `tests/integration/test_swarm_store.py` test SwarmState — which should eventually be eliminated. These tests are correct for what they test, but they validate code that the vision says should not exist.

#### Q2. Duplicate `_make_node` Helper

The `_make_node()` helper function is duplicated across three test files:
- `tests/unit/test_lsp_models.py`
- `tests/unit/test_lsp_server.py`
- `tests/unit/test_lsp_notifications.py`

Should be extracted to `tests/conftest.py` or `src/remora/testing/fakes.py`.

#### Q3. `MockLLMClient` vs `FakeAsyncOpenAI`

Two separate mock LLM implementations exist:
- `tests/fixtures/mock_llm.py` — returns empty tool_calls, no content (10 lines)
- `src/remora/testing/fakes.py` — `FakeAsyncOpenAI` with `FakeChatCompletions` (richer, configurable)

They're not interchangeable. The minimal `MockLLMClient` should be retired in favor of the richer `FakeAsyncOpenAI`.

#### Q4. `tests/helpers.py` Deprecated But Not Removed

The file emits a deprecation warning and re-exports from `remora.testing`. Since the canonical location is now `remora.testing`, this file should be deleted and its importers updated.

#### Q5. Migration Guard Tests in `test_lsp_db.py`

Several tests verify that methods/tables DON'T exist (e.g., `test_no_nodes_table`, `test_nodes_methods_removed`). These are migration guards from the Phase 1 unification. They serve a purpose (preventing regression), but should be explicitly labeled as migration guards and potentially moved to a separate file.

#### Q6. Pre-Existing Test Failure

`test_lsp_handlers_register_and_advertise_capabilities` fails because `workspace/executeCommand` is missing from the advertised capabilities. This has been pre-existing across the entire Phase 1 unification and should be fixed — it's a one-line addition to the capabilities dict in the handler.

### Coverage Summary Table

| Component | Unit | Integration | Assessment |
|-----------|------|-------------|------------|
| AgentNode | Thorough | Thorough | **Good** |
| Events (core) | Good | Good | **Good** |
| Projections | Good | Good | **Good** |
| EventStore | Good | Thorough | **Good** |
| EventBus | Good | — | **Adequate** |
| Subscriptions | Good | Good | **Good** |
| AgentRunner | Partial (guards) | Partial | **Gap: no run loop** |
| SwarmExecutor | None | None | **CRITICAL GAP** |
| ChatSession | None | None | **CRITICAL GAP** |
| SwarmState | Good | Good | Good (but may be dead code) |
| Discovery | Good | Thorough | **Good** |
| Extensions | Good | Good | **Good** |
| LSP Watcher | Good | — | **Good** |
| LSP Runner | Thorough | — | **Good** |
| LSP Graph | Good | — | **Good** |
| LSP DB | Good | — | **Good** |
| LSP Models | Good | — | **Good** |
| LSP Server | Basic | Good | **Adequate** |
| LSP Notifications | Good | — | **Good** |
| Command Queue | Good | — | **Good** |
| Reconciler | — | Good | **Adequate** |
| Service API | None | None | **CRITICAL GAP** |
| CLI | None | Basic subprocess | **Gap** |
| Nvim | None | None | **Gap** |
| UI | None | None | **Gap** |
| Adapters | None | None | **Gap** |

---

## 6. Dead Code and Stale Artifacts

This section catalogs code that should be removed or consolidated. Items are ordered by impact — removing high-impact items first will simplify the codebase significantly.

### High Impact — Pre-Unification Remnants

These are entire modules or subsystems that exist because the Option A unification was completed for the LSP layer but not yet for the core runner layer.

#### D1. `src/remora/core/agent_state.py` (84 lines) — REMOVE

The `AgentState` frozen dataclass and its JSONL persistence (`save()`, `load()`, `load_all()`). The vision says there is no separate AgentState file — the `nodes` table row IS the agent's state. This module exists solely to support the pre-unification core AgentRunner.

**Blocked by:** Runner unification (C2). Remove when the core runner is migrated to use EventStore.

#### D2. `src/remora/core/swarm_state.py` — `agents` table (portion of 197 lines) — REMOVE

The `agents` table duplicates the EventStore `nodes` table. The `subscriptions` table may still be needed if the subscription registry hasn't been fully migrated to EventStore events.

**Blocked by:** Runner unification (C2) and reconciler migration.

#### D3. `src/remora/core/swarm_executor.py` (375 lines) — MERGE OR REMOVE

The SwarmExecutor is the execution engine for the pre-unification core runner. When the runners are merged (C2), this code should be absorbed into the unified runner or replaced by the LSP runner's execution logic.

#### D4. `tests/helpers.py` — REMOVE

Deprecated shim that re-exports from `remora.testing`. Delete the file and update any remaining imports.

### Medium Impact — Unused Shims and Enums

#### D5. `TreeSitterDiscoverer` in `src/remora/core/discovery.py` — REMOVE

Compatibility wrapper class. If no external consumer depends on this name, remove it and update the `__init__.py` re-export.

#### D6. `NodeType` enum in `src/remora/core/discovery.py` — REMOVE

Not used in any business logic. Only consumer is `tests/roundtrip/run_harness.py:29`. Remove the enum and update the roundtrip harness to use string literals.

#### D7. `render_tag` in `src/remora/ui/view.py` — REMOVE

Marked as legacy. If no template or consumer calls it, delete.

#### D8. `tests/fixtures/mock_llm.py` (10 lines) — REMOVE

Superseded by `src/remora/testing/fakes.py` which provides `FakeAsyncOpenAI` with richer configurability. Update any tests that import `MockLLMClient` to use `FakeAsyncOpenAI` instead.

### Low Impact — Stale Re-exports and Minor Cleanup

#### D9. `src/remora/__init__.py` — CLEAN UP

Re-exports `TreeSitterDiscoverer`, `AgentState`, and `compute_node_id`. Once D1, D5, and D6 are addressed, update the public API surface to export only current artifacts: `AgentNode`, `EventStore`, `EventBus`, `SubscriptionRegistry`, core events, and discovery functions.

#### D10. `DummyKernel` / `DummyResult` in `tests/conftest.py` — VERIFY AND REMOVE

Defined in conftest but may not be used by any current test. Verify and remove if orphaned.

---

## 7. Integration Coherence

This section evaluates how well the subsystems work together as a unified whole.

### 7.1 The Two Worlds Problem

The codebase currently operates as two loosely coupled systems:

**World 1 — LSP (post-unification):**
- EventStore is the source of truth for node state
- AgentNode (via NodeProjection) is the canonical model
- Events flow through EventStore → triggers → LSP runner
- State is queryable via `get_node()`, `list_nodes()`, `get_node_at_position()`
- Well-integrated, well-tested, vision-aligned

**World 2 — Core/Swarm (pre-unification):**
- AgentState JSONL files are the source of truth for agent state
- SwarmState SQLite duplicates node metadata in an `agents` table
- Events flow through EventStore triggers → core AgentRunner → SwarmExecutor
- State is read/written via file I/O and SQLite, bypassing EventStore projections
- Cascade safety guards are here but not in World 1

**The bridge between worlds** is thin: both use EventStore for event storage, and both register triggers on EventStore. But they diverge on where they read and write NODE STATE. This means:

1. An agent discovered via the LSP watcher gets an AgentNode in EventStore
2. The reconciler creates an AgentMetadata entry in SwarmState
3. The core runner creates an AgentState JSONL file
4. Now the same agent has three identity records that can diverge

### 7.2 Dual-Write Analysis

Three dual-write patterns exist in the codebase:

| Write Pattern | Stores Involved | Risk |
|---------------|----------------|------|
| Agent identity | EventStore nodes + SwarmState agents + AgentState JSONL | High — triple write, any can diverge |
| Event storage | EventStore + RemoraDB events table | Medium — dual write, silent divergence |
| Subscriptions | SubscriptionRegistry (in-memory) + SwarmState subscriptions table | Low — registry is rebuilt on startup |

The event dual-write is the most immediately dangerous because it can cause the LSP UI to show different event history than what the EventStore knows about. The agent identity triple-write is the most architecturally damaging because it prevents the system from having a single, consistent view of "what agents exist and what state are they in."

### 7.3 Data Flow Inconsistencies

**Discovery → Runner flow:**
1. Watcher discovers nodes → emits `NodeDiscoveredEvent` → EventStore appends → NodeProjection materializes AgentNode ✓
2. Reconciler reads EventStore, creates AgentMetadata in SwarmState ✗ (should read from EventStore directly)
3. Core runner loads AgentState from JSONL ✗ (should read from EventStore)

**Event → Notification flow:**
1. Agent produces output → LSP runner emits event to EventStore ✓
2. LSP runner ALSO writes to RemoraDB ✗ (dual write)
3. UI reads from... which store? (ambiguous)

**Subscription flow:**
1. Default subscriptions created on node discovery ✓
2. SubscribeTool creates subscriptions with self-referencing pattern ✗ (M2 bug)
3. Subscriptions stored in-memory (SubscriptionRegistry) + SQLite (SwarmState) — low risk, rebuilt on startup

### 7.4 What Works Well

Despite the integration gaps, several cross-cutting concerns are handled cleanly:

- **Event schema**: Core events (`events.py`) have a clean, consistent frozen dataclass design with proper field names and types
- **EventStore triggers**: The trigger mechanism reliably delivers events to registered listeners across both worlds
- **NodeProjection**: Cleanly materializes events into queryable node state, used consistently throughout the LSP layer
- **Graph scoping**: `graph_id` properly isolates events and nodes per project/workspace
- **Extension system**: `AgentExtension` provides clean data-driven specialization without subclassing

---

## 8. Prioritized Recommendations

Organized into three phases. Each phase builds on the previous one. Estimated scope is provided for planning purposes.

### Phase A: Critical — Identity Unification and Runner Merge

These address the two CRITICAL findings and should be done first, as they are the final barrier to achieving the vision's unified architecture.

#### A1. Merge Agent Runners into One (C2)

**Goal:** One runner implementation that handles both LSP-triggered and swarm-triggered agent execution.

**Approach:**
1. Start with the LSP runner as the base (it already uses EventStore)
2. Port cascade safety guards from core runner (depth limits, cooldowns, concurrency)
3. Add pluggable tool registry to support both LSP tools (rewrite, insert) and Grail tools
4. Make the runner callable from both the LSP server and the swarm executor
5. Delete `core/agent_runner.py` and refactor `swarm_executor.py` into a tool provider

**Scope:** ~2-3 days. This is the highest-impact change.

#### A2. Eliminate AgentState JSONL (C1, D1)

**Goal:** All agent state lives in EventStore `nodes` table via AgentNode.

**Approach:**
1. After A1, the unified runner reads from EventStore — AgentState is no longer needed
2. Delete `core/agent_state.py`
3. Update `__init__.py` re-exports
4. Delete or update tests that create AgentState JSONL files

**Scope:** ~1 day (mostly test updates). Depends on A1.

#### A3. Eliminate SwarmState `agents` Table (H1, D2)

**Goal:** Reconciler and CLI query EventStore directly instead of maintaining a duplicate `agents` table.

**Approach:**
1. Update `reconciler.py` to use `event_store.list_nodes()` instead of `swarm_state.upsert_agent()`
2. Update CLI `swarm list` to query EventStore
3. Remove `agents` table from SwarmState schema
4. Evaluate whether the `subscriptions` table can also be removed (if SubscriptionRegistry is the canonical source)

**Scope:** ~1 day. Can be done in parallel with A2.

### Phase B: High Priority — Dual-Write Elimination and Dead Code

#### B1. Eliminate RemoraDB `events` Table (H3)

**Goal:** Single event store. No dual writes.

**Approach:**
1. Identify all RemoraDB `events` table readers (likely UI queries, event history display)
2. Replace those queries with EventStore `replay()` calls scoped by `graph_id`
3. Remove the `events` table from RemoraDB schema
4. Remove dual-write logic from LSP server's `emit_event()`

**Scope:** ~1 day.

#### B2. Unify Event Models (H2)

**Goal:** One event representation used everywhere.

**Recommended approach:** Make core events Pydantic models (aligns with AgentNode being Pydantic). This eliminates the `lsp/models.py` bridge layer entirely.

**Alternative:** Keep the dual representation but add sync tests ensuring `lsp/models.py` events and `core/events.py` events stay in lockstep.

**Scope:** ~1-2 days for the Pydantic migration; ~0.5 days for sync tests if keeping dual representation.

#### B3. Remove Dead Code (D4-D10)

**Goal:** Clean public API surface, no stale artifacts.

**Actions:**
1. Delete `tests/helpers.py` (D4)
2. Remove `TreeSitterDiscoverer` shim (D5)
3. Remove `NodeType` enum (D6)
4. Remove `render_tag` (D7)
5. Delete `tests/fixtures/mock_llm.py` (D8)
6. Clean `__init__.py` re-exports (D9)
7. Verify and remove `DummyKernel`/`DummyResult` (D10)

**Scope:** ~0.5 days. No dependencies.

### Phase C: Quality — Test Coverage and Bug Fixes

#### C1. Test SwarmExecutor and ChatSession

**Goal:** Cover the two CRITICAL test gaps.

**Note:** If A1 merges the runners, SwarmExecutor may be refactored or eliminated. Write tests for whatever the post-merge execution engine looks like, not the current SwarmExecutor.

For ChatSession, write unit tests covering:
- Message history management
- Tool call dispatch and result handling
- LLM interaction (using `FakeAsyncOpenAI`)
- Error handling and retry logic

**Scope:** ~2 days.

#### C2. Test service/ Package

Write unit tests for `api.py`, `handlers.py`, `datastar.py`, and `chat_service.py`. This will also catch the duplicate `get_subscriptions` bug (M1).

**Scope:** ~1-2 days.

#### C3. Fix Known Bugs

1. **M1 — Duplicate `get_subscriptions`:** Rename property to `subscription_registry` (~5 min)
2. **M2 — SubscribeTool self-ref:** Fix `to_agent` logic in `core/tools/swarm.py:140` (~15 min, needs design decision on correct semantics)
3. **M3 — Hardcoded LLM config:** Read from `Config` in `lsp/__main__.py:79` (~15 min)
4. **Q6 — Pre-existing test failure:** Add `workspace/executeCommand` to capabilities (~5 min)

**Scope:** ~1 hour total.

#### C4. CLI and Peripheral Package Tests

Lower priority. Write tests for:
- CLI commands (`swarm start`, `swarm reconcile`, `swarm list`, `swarm stop`)
- Neovim integration (basic smoke tests)
- UI rendering (snapshot tests for code lens, hover output)
- Starlette adapter (request/response cycle)

**Scope:** ~2-3 days.

---

## Summary

The Remora codebase has a strong architectural foundation. The EventStore, AgentNode, NodeProjection, and subscription system form a clean, well-tested core that faithfully implements the EventBased vision. The Phase 1 LSP unification proved this architecture works.

What remains is to extend the same unification to the core runner layer: merge the two runners, eliminate AgentState and SwarmState's agents table, and remove the dual-write patterns. This is a focused, well-scoped effort (Phase A, ~4-5 days) that will bring the entire codebase into alignment with the vision's promise of a single, unified event-driven system.

The test suite is solid where it covers — the event pipeline and LSP subsystem have excellent tests. The critical coverage gaps (SwarmExecutor, ChatSession, service/) should be addressed after the runner merge, since that merge will reshape the code being tested.

**Bottom line:** The architecture is right. The foundation is solid. The unification just needs to be finished.

