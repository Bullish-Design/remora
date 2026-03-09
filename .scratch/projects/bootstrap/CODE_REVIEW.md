# Bootstrap Implementation Code Review

**Date:** 2026-03-08
**Scope:** `src/remora/bootstrap/`, `src/remora/core/store/node_store.py` (graph extension),
`bootstrap/tools/*.pym`, `bootstrap/agents/*.yaml`,
`tests/unit/bootstrap/`, `tests/integration/test_bootstrap_loop.py`
**Status:** All 39 bootstrap tests pass.

---

## Table of Contents

1. [Overall Assessment](#1-overall-assessment)
2. [bedrock.py](#2-bedrockpy)
3. [schema_loader.py](#3-schema_loaderpy)
4. [turn_executor.py](#4-turn_executorpy)
5. [activation.py](#5-activationpy)
6. [coordinator.py](#6-coordinatorpy)
7. [seed_graph.py](#7-seed_graphpy)
8. [runner.py](#8-runnerpy)
9. [node_store.py (graph extension)](#9-node_storepy-graph-extension)
10. [bootstrap/tools/*.pym](#10-bootstraptoolspym)
11. [bootstrap/agents/*.yaml](#11-bootstrapagentsyaml)
12. [__init__.py](#12-initpy)
13. [Test Suite Review](#13-test-suite-review)
14. [Issues Summary](#14-issues-summary)
15. [Conceptual Alignment (v3 Philosophy)](#15-conceptual-alignment-v3-philosophy)
16. [Structural Alignment (Shared Code & Mental Model)](#16-structural-alignment-shared-code--mental-model)

---

## 1. Overall Assessment

The implementation is **functionally correct, well-structured, and demonstrates good engineering judgment** throughout. The architecture is cohesive: every module fulfils exactly one role in the bootstrap pipeline, and the data flow from `NodeDiscoveredEvent` → coordinator → `AgentNeededEvent` → activation → workspace writes → subscriptions → graph registration is traceable end-to-end.

The test suite is **above average** for a project of this complexity. Real components are used wherever feasible — the seed, coordinator, and system-tool tests are particularly strong. The integration test is a genuine near-end-to-end exercise. The mocked tests are appropriately constrained and test orchestration logic, not mock wiring.

A small number of non-critical issues are documented below. None require immediate action, but several are worth addressing before this becomes a load-bearing production path.

---

## 2. bedrock.py

### Correctness

**`BootstrapEvent` is a plain dataclass (not inheriting `StructuredEvent`).**
The implementation guide specified `BootstrapEvent(StructuredEvent)`. The actual code is:

```python
@dataclass
class BootstrapEvent:
    event_type: str
    node_id: str | None = None
    ...
```

This works at runtime because `EventStore.append` uses `getattr`-based serialization. However, it means type checkers won't catch places that pass a `BootstrapEvent` where a `StructuredEvent` or `CoreEvent` is expected. Since `EventStore` is typed to accept `StructuredEvent | CoreEvent`, this is a silent type contract violation. Low risk today, potential silent failure vector tomorrow.

**Recommendation:** Either add `StructuredEvent` as base class (preferred — explicit contract), or add a comment documenting why the structural subtyping is intentional.

---

**`_make_files_provider` is flat — it only lists the root `.` directory:**

```python
paths = await cairn_externals.list_dir(".")
```

`list_dir` returns immediate children only. Workspace files in subdirectories (other than `tools/`, which is handled separately by `_extract_workspace_tools`) are invisible to Grail's files provider. For the current bootstrap use case this is fine — agents only write to the root. But if a future agent writes structured files (e.g., `memory/index.md`), Grail won't see them via this provider.

**Recommendation:** Document this limitation in a comment, and implement a recursive listing via a flag for future experimentation.

---

**`__all__` in `bedrock.py` exposes private implementation functions:**

```python
__all__ = [
    "BootstrapEvent",
    "build_bedrock",
    "_make_files_provider",      # private
    "_extract_workspace_tools",  # private
]
```

These are in `__all__` because `activation.py` and `__init__.py` import them. The right fix is to drop the underscore prefix to make them genuinely public, or keep them private and remove them from `__all__`. The underscore + `__all__` combination sends mixed signals.

**Recommendation:** Rename to `make_files_provider` and `extract_workspace_tools` (public).

---

**Bedrock alias pattern is well-handled and correctly documented:**

```python
# Grail currently cannot resolve external names that start with "_".
# Provide underscore-free aliases for .pym tool declarations.
"cairn_read": _cairn_read,
"cairn_write": _cairn_write,
...
```

This is the right solution for a Grail engine limitation. The comment explains the reason clearly. The `.pym` files correctly use the unprefixed names.

---

**`_event_write` correctly wraps arbitrary payloads as `BootstrapEvent`.**
`_event_read` uses `agent_id` or `node_id` from the selector (with fallback to the calling `agent_id`) — sensible and symmetric with bootstrap event semantics.

**`_cairn_write` returns `"ok"` (string) rather than `bool`** — intentional and correct for tool output. Matches what `write_file.pym` documents.

### Elegance

Clean, minimal. Each closure captures only what it needs. No dead code.

---

## 3. schema_loader.py

### Correctness

**Async `load_schema` correctly reads from Cairn VFS.** Bytes fallback is handled:

```python
if isinstance(content, bytes):
    content = content.decode("utf-8", errors="replace")
```

Good defensive handling.

**`_merge_schemas` shallow-merges with list concatenation** (`context`, `tools`, `subscriptions` extend; all other keys override). The `extends` key is stripped from child before merging — preventing recursive or self-referential loops.

**`SubscriptionSpec.node_id` is optional and may be `None`** — consistent with the NOTE in `activation.py` that documents this field is currently informational only.

### Elegance

Clean pydantic models with sensible defaults. `DEFAULT_SCHEMA_YAML` is defined as a module-level constant rather than a file read — avoids I/O at import time. Good.

`_load_yaml` returns `{}` on non-dict YAML — safe fallback that prevents downstream crashes.

One minor style note: `TurnSchema` has `termination: str = "DONE"` — this forces all schemas to declare a termination string. The test `test_bootstrap_agent_schema_files_validate` asserts `schema.termination == "DONE"` for all agent YAML files. This is an implicit protocol constraint that could be more explicit (e.g., a validator).

---

## 4. turn_executor.py

### Correctness

**Client lazy initialization is correct:**

```python
if self._client is None:
    self._client = build_client(...)
```

This supports injection for tests and lazy production creation. `create_kernel` is called with `client=self._client`, correctly reusing the built client across turns. This was a bug in the original guide (dead client) that was fixed in the implementation.

**`_run_context_pipeline` correctly handles missing tools and step exceptions.** `optional=True` steps silently set `""` on failure; non-optional steps log a warning. The failure handling correctly continues through the pipeline rather than aborting early.

**`resolve_node_vars` is an instance method** (needs `self._node_attrs`) — correct, and appropriately named as a public method (tests can call it).

**`_build_user_prompt` is minimal** — just emits event type + node ID. This is intentional: the rich context comes from the context pipeline (role.md, notes.md, source file), not the activation prompt. Good separation.

**`_extract_response` handles multiple result shapes** — `final_message.content`, `result.content`, then `str(result)`. This defensive handling is appropriate given the abstraction boundary with `structured_agents`. The `final_message` → `content` branch path is covered by the shape of real kernel results; the fallback `str(result)` is a last resort.

### Elegance

Clean and focused. Does one thing: load schema, build context, assemble messages, run kernel, return result.

No dead code. No workspace path references (these were correctly removed from the original guide).

---

## 5. activation.py

### Correctness

**Full activation flow is correct and complete:**
1. `workspace_service.initialize(sync_mode=SyncMode.NONE)` — idempotent
2. `get_agent_workspace(agent_id)` → CairnExternals construction
3. `_ensure_direct_subscription` (idempotent)
4. `build_bedrock` → `_make_files_provider` → tool file diff (before)
5. `_extract_workspace_tools` → `discover_grail_tools` → `TurnExecutor.run`
6. Tool file diff (after) → `_emit_tool_synthesized_events`
7. `load_schema` → `_register_schema_subscriptions`
8. `write_graph("add_node")` + `write_graph("add_edge")`

**`workspace_service._stable_workspace` private attribute access** — this is unavoidable given the current CairnWorkspaceService API:

```python
stable_workspace = getattr(workspace_service, "_stable_workspace", None)
if stable_workspace is None:
    raise RuntimeError("Workspace service stable workspace is not initialized")
```

The `getattr` + explicit RuntimeError is reasonable mitigation. The comment at this line acknowledges the coupling. If CairnWorkspaceService gains a public `stable_workspace` property, this should be updated.

**`workspace_service.initialize()` is called on each `handle_agent_needed` invocation.** The method is idempotent (guarded by `_initialized` flag in BootstrapRunner, and presumably also internally). Not a bug, but a mild inefficiency when `run_for_file` activates multiple agents in parallel.

**`_register_schema_subscriptions` correctly documents its limitation:**

```python
"""
NOTE: v1 SubscriptionPattern has no node_id selector, so schema node_id
fields are currently informational and ignored here.
"""
```

Honest, correct.

**`_ensure_direct_subscription` + `_register_schema_subscriptions` both call `get_subscriptions(agent_id)`** — two separate reads from the subscriptions DB for the same agent. Minor efficiency concern; could be merged if performance becomes an issue.

**No idempotency guard on `_emit_tool_synthesized_events`.** On a crash-and-restart scenario where the agent was activated but the graph node write failed, `handle_agent_needed` would be called again. The tool file diff would be `before=set()` (workspace now has tools) → `after=set(with tools)` → duplicate `ToolSynthesizedEvent` would be emitted. The graph writes also use `INSERT OR REPLACE` (idempotent), but the event emission is not. Low risk for the current use case but worth adding notes to the docstrings where this will impact.

### Elegance

Well-structured, cleanly separated helper functions. The before/after tool file diff pattern is elegant for capturing synthesized tools.

The `_pattern_key` function for deduplication is clean and handles all SubscriptionPattern fields correctly.

---

## 6. coordinator.py

### Correctness

**`find_unassigned_nodes` is the general API; `find_unassigned_modules` delegates to it with `node_types={"file"}`** — clean layering.

**`_read_assigned_node_ids` has a slightly cryptic comprehension:**

```python
return {
    str(attrs.get("assigned_node_id"))
    for row in agent_rows
    if isinstance(row, dict)
    for attrs in [row.get("attrs")]           # ← list-of-one as optional binding
    if isinstance(attrs, dict) and attrs.get("assigned_node_id")
}
```

The `for attrs in [row.get("attrs")]` pattern is a Python idiom for optional binding (avoids a nested `if` + assignment). It works correctly but is harder to read than an explicit `if` block with a named variable. Minor style point.

**Double graph read in `run_once` (via `BootstrapRunner`):**

```python
plans = await find_unassigned_modules(self.event_store)           # read 1
await emit_agent_needed_events(self.event_store, ...)             # read 2 (internally calls find_unassigned_nodes again)
return await self._activate_plans(plans, parallel=False)
```

`emit_agent_needed_events` calls `find_unassigned_nodes` internally, then emits events. `run_once` already has the plans from the first call. The plans from the first call are what drive `_activate_plans`. The second call in `emit_agent_needed_events` might find a different (slightly out-of-date or stale) set if concurrent changes occur — though this is protected by `_activation_lock`. In single-runner usage, this is harmless but wastes one graph read per cycle.

**Recommendation:** Refactor so `emit_agent_needed_events` accepts an optional `plans` argument (or split emit logic from query logic), removing the duplicate read.

**Deterministic ordering in `find_unassigned_nodes`:**

```python
key=lambda node: (node.file_path, node.start_line, node.end_line, node.node_type, node.node_id)
```

Good — deterministic activation order prevents non-deterministic agent assignment across runs.

### Elegance

Clean module. Good use of `AgentNeededPlan` dataclass to avoid raw tuples.

---

## 7. seed_graph.py

### Correctness

**Uses `NodeDiscoveredEvent` + `NodeProjection` rather than `write_graph("add_node")`.** This is a correct and better choice than the original guide's approach — seeded nodes become first-class nodes in the `nodes` table, visible to the LSP scanner and properly projected. The guide specified `write_graph` which would have put them in `graph_nodes` (wrong table, wrong projection).

**`seed_modules_if_empty` correctly checks for existing nodes:**

```python
existing = await event_store.nodes.read_graph({"match": {"kind": "module"}})
if existing and existing != "[]":
    return 0
```

The `"module"` kind routes via `MODULE_KIND_ALIAS` to `list_nodes(node_type="file")` in NodeStore — this correctly detects existing file nodes. The `!= "[]"` string check is slightly fragile (depends on JSON serialization format) but works because `read_graph` always returns valid JSON from `json.dumps`.

**`_module_full_name` correctly strips `src/` prefix:**

```python
if module_path.startswith("src/"):
    module_path = module_path[len("src/"):]
```

Matches the project layout convention.

**`_SKIP_DIRS` covers the expected set.** No `node_modules` (irrelevant for Python projects).

**Minor efficiency note:** Source bytes are encoded twice:

```python
source_hash = hashlib.sha1(source.encode("utf-8")).hexdigest()
byte_count = len(source.encode("utf-8"))  # second encode
```

One `encoded = source.encode()` at the top would suffice.

### Elegance

Clean and minimal. The `_main()` entry point for standalone seeding is a nice addition.

---

## 8. runner.py

### Correctness

**Lifecycle management is correct and complete.** Constructor accepts pre-built stores (for testing) or creates them (for production), tracking `_owns_*` flags for cleanup responsibility. `close()` correctly suppresses exceptions via `contextlib.suppress` and nulls the references.

**`_activation_lock` prevents concurrent activation runs within the same runner.** This is critical for SQLite write safety — without it, two concurrent `run_once` calls would both detect the same unassigned modules and attempt to activate the same agents twice.

**`run_for_file` uses `parallel=True` (asyncio.gather) for fan-out.** Concurrently activating multiple nodes in the same file is correct — each agent operates on its own workspace (separate Cairn DB rows). The gather uses `return_exceptions=True` so one failure doesn't abort others.

**`run_forever` doesn't sleep when `run_once` returns > 0** — immediately continues to the next pass. This prevents artificial latency when there's still work to do. Correct.

**`run_once` calls `initialize()` at the start — redundant if the caller already called `initialize()`.** The guard prevents double-initialization, so this is harmless. The dual initialization path (explicit + implicit) is a common Python pattern.

**`_build_agent_needed_event` is a private helper on the runner.** This is appropriate — the runner builds synthetic events to drive activation without going through the store's replay path. These events are not written to the store; they're transient activation triggers.

Actually — wait. `run_once` calls both `emit_agent_needed_events` (which writes events to the store) AND `_activate_plans` (which builds ephemeral events and calls `handle_agent_needed` directly). The store-written events are for consumption by other subscribers (e.g., the coordinator agent running in a separate process). The direct activation is the local fast path. This design is intentional and correct, but could be more clearly documented.

### Elegance

Well-structured. The separation between `run_once`, `run_for_file`, and `run_forever` gives callers appropriate granularity. The private `_activate_plans` correctly abstracts the sequential vs. parallel difference.

`run_forever` is appropriately simple — poll, sleep-if-idle, repeat.

---

## 9. node_store.py (graph extension)

### Correctness

**`MODULE_KIND_ALIAS = "module"` routing is correct:**
- `read_graph({"match": {"kind": "module"}})` → `list_nodes(node_type="file")` + `kind_override="module"` projection
- Also merges with `graph_nodes` rows for compatibility
- `_graph_add_node` blocks writing code/module kinds via the graph API — preserves the invariant that these nodes only enter via `NodeDiscoveredEvent`

**`UNION ALL` in the "both" direction neighbor query:**

```sql
SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
FROM graph_edges e
JOIN graph_nodes n ON (e.to_id = n.id AND e.from_id = ?)
UNION ALL
SELECT n.id, n.kind, n.attrs_json, e.kind AS edge_kind
FROM graph_edges e
JOIN graph_nodes n ON (e.from_id = n.id AND e.to_id = ?)
```

If node A has two edges to node B (same from/to, different edge kinds), both rows appear in the result. This is correct for multi-edge graphs. If the caller expects unique neighbors by ID, deduplication must happen at the call site. The `graph_neighbors.pym` tool returns whatever this query returns — the LLM can handle duplicate rows, but it's worth documenting.

**`_graph_add_node` auto-generates UUID if no `id` provided.** The `graph_add_node.pym` tool doesn't expose an `id` input, so bootstrap agents always get auto-generated IDs for custom nodes. This is intentional (prevents ID collisions) and correct. `activation.py` creates the agent node directly via `write_graph` (not via the tool) and provides a specific `agent_id`.

**`INSERT OR REPLACE`** semantics for both nodes and edges — upsert behavior. Correct for the bootstrap use case where re-activation of an existing agent should update its record.

**`_write_backend()` raises `RuntimeError` if write connection not initialized.** This is the right defensive pattern — fail fast rather than silently operating on a None connection.

### Elegance

The `MODULE_KIND_ALIAS` routing logic is a necessary complexity given the dual-table architecture (nodes + graph_nodes). It's adequately commented. The `_agent_node_to_graph_dict` helper correctly maps from `AgentNode` (LSP projection model) to the generic graph dict format.

---

## 10. bootstrap/tools/*.pym

Ten tools covering the full bedrock surface: `read_file`, `write_file`, `graph_node`, `graph_neighbors`, `graph_find_nodes`, `graph_add_node`, `graph_add_edge`, `read_recent_events`, `emit_event`, `user_question`.

### Correctness

Each tool correctly:
- Declares `@external` with the unprefixed bedrock name (`cairn_read`, `graph_write`, etc.)
- Declares `Input(...)` for each parameter
- Has a docstring explaining semantics and return format
- Calls the external and returns its result

**`graph_add_node.pym` doesn't expose an `id` parameter.** Since NodeStore auto-generates UUIDs, agents using this tool will always get system-assigned IDs. They cannot name their own nodes via this tool. This is the correct design for avoiding collisions. The docstring documents `"Returns JSON: {\"id\": str, \"kind\": str} with the generated ID."` — the agent can use the returned ID in subsequent `graph_add_edge` calls.

**`user_question.pym` emits `HumanInputRequestEvent` with a `request_id`.** The response mechanism (how the human's answer reaches the agent) is not part of the bootstrap package — it's an external integration point. The tool correctly focuses only on emitting the request.

**`read_recent_events.pym` passes `node_id` as the selector key.** The bedrock `_event_read` function uses `selector.get("node_id") or agent_id` — this works correctly.

### Elegance

All tools follow a consistent structure. Docstrings are informative and describe the return format. The `user_question.pym` is a nice addition — enables human-in-the-loop bootstrap without the agent needing to know the UI integration details.

---

## 11. bootstrap/agents/*.yaml

Three schemas: `DEFAULT_SCHEMA.yaml`, `base_code_agent.yaml`, `coordinator.yaml`.

### Correctness

**`DEFAULT_SCHEMA.yaml` is correctly minimal** — only `read_file` + `write_file`, max 5 turns. The system prompt gives clear, numbered instructions for the bootstrap self-assignment task. This is the right "empty workspace" prompt.

**`base_code_agent.yaml`** — extends nothing (standalone). Uses the context pipeline for `role.md`, `notes.md`, and `{node.file_path}` source read. The `{node.file_path}` template reference correctly uses the node var substitution pattern. Tools include `emit_event` for self-initiated events.

**`coordinator.yaml`** — subscribes to `AgentNeededEvent` and `ToolSynthesizedEvent`. Includes `graph_find_nodes` to survey module coverage and `graph_add_node` / `graph_add_edge` / `emit_event` to coordinate. This is the right tool set for a coordinator role.

**`test_agent_schemas.py` validates all three schemas** — any future schema file added to `bootstrap/agents/` will be validated automatically. Good.

### One concern: The `coordinator.yaml` lists subscriptions

```yaml
subscriptions:
  - event_type: AgentNeededEvent
  - event_type: ToolSynthesizedEvent
```

These subscriptions are only registered when the coordinator itself is activated via `handle_agent_needed`. In the current `BootstrapRunner`, the coordinator is seeded as a graph node but is NOT activated through the activation path — it's a logical coordinator (drives `find_unassigned_modules` + `emit_agent_needed_events` via code, not via LLM turn). So these subscription specs in `coordinator.yaml` are never registered. This is not a bug — the coordinator schema is aspirational (for a future fully-agent-driven coordinator) — but it could be confusing. A comment to this effect would help.

---

## 12. __init__.py

**Exports private functions in `__all__`:**

```python
"_make_files_provider",
"_extract_workspace_tools",
```

These are in `__all__` because `activation.py` imports them directly. The underscore prefix + `__all__` export is contradictory. Either:
- Remove the underscore (make them public) — preferred since they're legitimately useful to callers
- Or remove them from `__all__` and let callers import from `remora.bootstrap.bedrock` directly

This applies to both `bedrock.py`'s `__all__` and `__init__.py`'s re-export.

---

## 13. Test Suite Review

### Grading Scale
- **REAL** — uses real components, high confidence
- **PARTIAL** — some real components, targeted mocks for external boundaries
- **MOCKED** — primarily mocked, tests orchestration logic

### test_seed_graph.py — REAL ✓✓

Uses real `EventStore` + `NodeProjection`. Tests:
- Filesystem seeding creates correct module nodes (skips `.venv`, visits subdirs)
- `seed_modules_if_empty` skips when nodes already exist
- `seed_coordinator_node` creates correct graph node

**High quality.** The coordinator node test reads back from the real graph store and validates `kind` and `attrs.name`. Missing: test that `_SKIP_DIRS` members are reliably skipped (e.g., test with `__pycache__` subdir).

### test_coordinator.py — REAL ✓✓

Uses real `EventStore` + `NodeProjection`. Tests:
- `find_unassigned_modules` returns plans, then correctly filters after agent assignment
- `emit_agent_needed_events` produces exactly one event, with correct payload and generated `agent_id`

**High quality.** Tests the full state transition: node exists → unassigned plan → emit event → agent assigned → empty plan. The assignment step uses `write_graph` directly (as activation.py would), confirming the data flow.

**Missing:** Direct tests for `find_unassigned_nodes` with `file_path` filter (the new general API introduced alongside `find_unassigned_modules`), and `emit_agent_needed_events_for_nodes`.

### test_system_tools.py — REAL ✓✓

Uses real `grail.load()` and executes `.pym` files with real (but minimal) externals. Tests:
- All 10 expected tool files exist and compile
- All tools declare only known bedrock external names
- `read_file` calls `cairn_read` with correct path
- `graph_find_nodes` routes to `graph_read` with correct selector shape, parses JSON result
- `user_question` emits `HumanInputRequestEvent` with correct payload

**High quality.** The external functions in per-tool tests are real async functions (not `AsyncMock`) that return typed values. This correctly exercises the full Grail execution path including input binding and external resolution. The `graph_find_nodes` test validates both the selector passed to the external AND the JSON output parsing — testing the full roundtrip.

**Missing:** Execution tests for the remaining 7 tools (only 3 have execution tests). Adding real-function externals and result assertions for `write_file`, `graph_node`, `graph_neighbors`, `graph_add_node`, `graph_add_edge`, `read_recent_events`, and `emit_event` would provide full coverage.

### test_schema_loader.py — PARTIAL ✓

Mocks `CairnExternals.read_file` (appropriate — CairnExternals requires a real workspace). Tests:
- Default schema returned when `read_file` returns `None`
- Schema parsed correctly from workspace YAML
- `extends` merge loads base YAML from real filesystem (`tmp_path`)
- `resolve_context_vars` substitution

**Good.** The `extends` test creates a real YAML file on disk, making that path genuinely tested. The mock for `read_file` is the minimal boundary mock needed.

### test_turn_executor.py — PARTIAL ✓

Monkeypatches `load_schema`, `build_client`, `create_kernel`. Uses `FakeTool` and `FakeKernel`. Tests:
- System prompt correctly assembled from schema system text + context values + node vars
- Context pipeline calls tools with resolved args
- Client is reused across runs (not rebuilt)
- Termination detection based on schema

**Acceptable.** The kernel is the external LLM boundary — right to mock. `FakeKernel` returns `SimpleNamespace(final_message=None, content="DONE")` which exercises the `content` branch of `_extract_response` but not the `final_message` branch.

**Missing:** Test for `_build_user_prompt` (it's simple but untested), `_extract_response` with `final_message` shape, and `_run_context_pipeline` with missing non-optional tool (should log warning, set `""`).

### test_bedrock.py — MOCKED ✓

Tests bedrock delegation and alias exposure. All externals are `AsyncMock`. Tests:
- Each of the six bedrock functions delegates to the correct underlying API
- Both `_`-prefixed and unprefixed alias keys are present in the returned dict

**Appropriate level** for a pure delegation layer. The alias presence test (`assert "cairn_read" in result`) is particularly valuable as a regression guard for the Grail compatibility requirement.

### test_activation.py — MOCKED ✓

Mocks CairnExternals, TurnExecutor, build_bedrock, discover_grail_tools, _make_files_provider, _extract_workspace_tools, load_schema. Three tests:
1. Full orchestration: subscription registration count, graph write args, result fields
2. Agent ID generation when `agent_id` missing from payload
3. Tool synthesis event emission (uses side_effect on `_list_workspace_tool_files`)

**Necessarily mocked** — CairnExternals requires a real Cairn workspace, and TurnExecutor requires a real LLM. Tests orchestration logic well, including:
- Correct number of `subscriptions.register` calls (direct + schema-based)
- Correct `write_graph` call arguments (add_node + add_edge)
- Correct `event_store.append` call with `BootstrapEvent` + `"ToolSynthesizedEvent"`

The tool synthesis test (test #3) correctly uses `side_effect=[set(), {"node_context.pym"}]` to simulate before/after divergence without needing real workspace I/O.

### test_runner.py — MOCKED ✓

Mocks CairnWorkspaceService, seed functions, find/emit/handle at module level. Tests:
- Default path derivation from Config
- `run_once` orchestration: correct event passed to `handle_agent_needed`
- `run_forever` stops cleanly after `stop()` call
- `run_for_file` fans out to N agents in parallel, passes correct `file_path` args

**Appropriately mocked** — tests the runner's orchestration logic without running real bootstrap activation. The path derivation test is a useful regression guard.

**Good detail:** `test_run_for_file_fans_out_unassigned_nodes` verifies both the call count AND the specific `node_id` values in the event payloads — not just "it was called twice" but "it was called with the right data."

### test_agent_schemas.py — REAL ✓

Validates all agent YAML files with the real `TurnSchema` pydantic model. Tests existence, parseability, `termination == "DONE"`, and coordinator subscription correctness.

**Good smoke test.** Catches broken YAML and schema contract violations on every test run.

### test_bootstrap_loop.py (integration) — MOSTLY REAL ✓✓

Uses real: `EventStore`, `NodeProjection`, `SubscriptionRegistry`, `CairnWorkspaceService`. Monkeypatches only `TurnExecutor.run` — the LLM boundary.

The monkeypatched `_fake_run` performs real Cairn workspace writes (role.md, notes.md, schema.yaml, tools/node_context.pym), making the subscription registration and tool synthesis paths exercise real code.

Tests the full cycle:
1. `NodeDiscoveredEvent` → projection into `nodes` table
2. `emit_agent_needed_events` → 1 event in store
3. `handle_agent_needed` → workspace writes → subscription registration → graph node + edge → ToolSynthesizedEvent

**Near-end-to-end.** The only stub is the LLM call itself. All three stores (event store, subscription registry, Cairn workspace) are real. This is about as realistic as a test can be without a live model server.

---

## 14. Issues Summary

### Must Fix
None. The implementation is functionally correct.

### Should Fix

| # | Location | Issue |
|---|----------|-------|
| S1 | `bedrock.py`, `__init__.py` | Private functions in `__all__` — drop underscore or remove from `__all__` |
| S2 | `coordinator.py` + `runner.py` | `run_once` double-queries for unassigned modules (once via `find_unassigned_modules`, once inside `emit_agent_needed_events`) — refactor to share the plan list |
| S3 | `bedrock.py` | `BootstrapEvent` lacks `StructuredEvent` inheritance — type contract violation; add base class or document intentional structural subtyping |

### Nice to Fix

| # | Location | Issue |
|---|----------|-------|
| N1 | `coordinator.py` | `_read_assigned_node_ids` comprehension uses `for attrs in [...]` optional-binding idiom — replace with explicit `if` block for readability |
| N2 | `bedrock.py` | `_make_files_provider` only lists root (flat, not recursive) — document this limitation in a comment |
| N3 | `node_store.py` | `UNION ALL` in "both" neighbors query may return duplicates — document in `graph_neighbors.pym` docstring |
| N4 | `seed_graph.py` | Source string encoded twice (hash + byte_count) — one `encoded = source.encode()` suffices |
| N5 | `coordinator.yaml` | Subscription specs are never registered (coordinator not activated via LLM path) — add a comment explaining this is aspirational |

### Missing Test Coverage

| # | Gap | Priority |
|---|-----|----------|
| T1 | `find_unassigned_nodes` with `file_path` filter | Medium — new general API, untested |
| T2 | `emit_agent_needed_events_for_nodes` | Medium — new general API, untested |
| T3 | Remaining 7 `.pym` tool execution tests (beyond `read_file`, `graph_find_nodes`, `user_question`) | Medium — compile tested, execution not |
| T4 | `_extract_response` `final_message` branch in `TurnExecutor` | Low |
| T5 | `_build_user_prompt` in `TurnExecutor` | Low — trivial function |
| T6 | `_SKIP_DIRS` exhaustiveness in `seed_graph` | Low |
| T7 | NodeStore `read_graph`/`write_graph` graph methods directly | Low — covered transitively by coordinator + bootstrap loop tests |

---

## 15. Conceptual Alignment (v3 Philosophy)

The v3 philosophy: *"specify the substrate (cairn workspace, graph, event bus), let structure emerge from bootstrapping. Do NOT pre-specify node kinds, edge kinds, protocol state machines, or memory models."*

### Where the implementation honors v3

**Bedrock as pure substrate primitives.** The six functions — `cairn_read`, `cairn_write`, `graph_read`, `graph_write`, `event_read`, `event_write` — are exactly the substrate interface. No business logic, no domain assumptions. An agent can write whatever it wants into its workspace and the graph, unconstrained.

**Agent schemas are workspace-resident and agent-authored.** The bootstrap default prompt instructs the agent to write its own `schema.yaml`. All future activations of that agent use the schema it wrote, not one a developer pre-specified. This is the v3 self-description principle in action.

**Graph is open-ended.** `graph_add_node` accepts arbitrary `kind` + `attrs`. Bootstrap agents can create whatever node kinds make sense for their role. The substrate doesn't impose "agent must be kind X with fields Y".

**Tool synthesis detection is emergent.** The before/after `tools/` diff in `activation.py` is a substrate-level observation — the system notices *that* a tool was created, not *which* tools are valid. This enables capability growth without pre-registration.

**`user_question.pym` is a first-class substrate primitive.** It emits a `HumanInputRequestEvent` as a regular event — the same mechanism any agent uses to communicate. There's no special human-input channel; humans are just another subscriber.

### Where the implementation creates v3 tension

**`find_unassigned_modules` hard-codes `node_types={"file"}`.** The coordinator's job is to survey unassigned nodes, but the current implementation specifically filters for `node_type="file"`. This leaks a v1 NodeStore convention (file/module nodes are stored as `node_type="file"`) into the bootstrap coordinator. From a pure v3 perspective, the coordinator should be agnostic to internal node classification. The current design makes "file = the thing that gets an agent" an implicit contract rather than an explicit configuration.

**`_SKIP_DIRS` hard-codes Python project conventions.** The `seed_graph.py` skip list (`.venv`, `dist`, `__pycache__`) bakes in assumptions about Python project structure. A v3-pure seeder would read these from config. Minor, but consistent with the pattern.

**`coordinator.yaml` describes an LLM coordinator that doesn't exist yet.** The coordinator schema defines tools, subscriptions, and a system prompt for an LLM-driven coordinator. But the current code path runs coordinator logic in Python. This is an honest phasing — the schema is aspirational, documenting what the coordinator *will* become. But until that transition happens, the schema creates a gap between documentation and reality (see structural issue S-5 below).

**`DEFAULT_SCHEMA_YAML` is both a constant and a file.** The string constant in `schema_loader.py` and `bootstrap/agents/DEFAULT_SCHEMA.yaml` must be kept in sync manually. This contradicts the v3 "substrate stores everything" philosophy — the authoritative default schema should be in one place only. If they ever diverge, new agents get different behavior depending on whether the workspace schema was never written (hits the constant) vs. an explicit default was installed.

**Bootstrap runner is not itself bootstrapped.** The coordinator pattern — scan graph, emit events, activate agents — is hard-coded in Python. This is the right pragmatic choice at this stage (the system needs to bootstrap itself before it can be agent-driven), but it should be explicitly framed as "phase 1 scaffolding that will be replaced" rather than just "the coordinator". The `coordinator.yaml` hints at this but isn't the whole story.

### Summary

The implementation is well-aligned with v3. The tensions above are mostly pragmatic decisions for a functioning v1-of-bootstrap, not architectural mistakes. The key one worth addressing explicitly: the hard dependency on `node_types={"file"}` in the coordinator leaks a classification assumption that should either be configurable or abstracted.

---

## 16. Structural Alignment (Shared Code & Mental Model)

### The parallel execution pipelines

The most significant structural observation: **bootstrap has a parallel agent execution pipeline to v1**.

**v1 path:**
```
execute_agent_turn() → build_turn_context() → load_manifest() → discover_grail_tools()
    → build_client() → create_kernel() → kernel.run()
```

**Bootstrap path:**
```
handle_agent_needed() → TurnExecutor.run() → load_schema() → discover_grail_tools()
    → build_client() → create_kernel() → kernel.run()
```

These are structurally identical at the kernel level, which is correct — both use `create_kernel` (shared), `build_client` (shared), `discover_grail_tools` (shared), and the same `kernel.run()` call signature. The divergence is intentional and appropriate at the configuration layer (`manifest.yaml` → `schema.yaml`) and context assembly (`build_turn_context` vs `TurnExecutor._run_context_pipeline`).

**Correctly shared:**
- `create_kernel` — same function, same interface
- `build_client` — same function
- `discover_grail_tools` — same function, different `externals=` dict
- `CairnExternals` — same class
- `CairnWorkspaceService` — same class
- `RuntimePaths` — new shared utility for path derivation, used by both LSP startup and `BootstrapRunner`

**Intentionally diverged** (and that's fine):
- `load_manifest` vs `load_schema` — manifest is filesystem/bundle-resident (developer-authored); schema is workspace-resident (agent-authored). Different storage, different mutability, different semantics. No convergence needed right now.
- `TurnContext` vs `TurnExecutor` — v1 context is a rich dataclass built by `build_turn_context`; bootstrap uses a simpler class with direct CairnExternals access. Bootstrap doesn't need v1's bundle mapping, CST node conversion, or prompt builder.
- Observer: v1 uses `_CompositeObserver` to record every kernel event to EventStore. Bootstrap passes `observer=None` — bootstrap LLM interactions are **unobserved** (no kernel-level audit trail).

### Duplicated: response extraction logic

`TurnExecutor._extract_response` (bootstrap) and the response extraction block in `execute_agent_turn` (v1) are functionally identical code:

```python
# Both have this exact logic:
if hasattr(result, "final_message") and result.final_message:
    msg = result.final_message
    if hasattr(msg, "content") and msg.content:
        return msg.content
    return str(result)
if hasattr(result, "content") and result.content:
    return result.content
return str(result)
```

This should be a shared `extract_response_text(result) -> str` helper in `remora.core.agents.kernel_factory` or a new `remora.core.agents.result_utils` module. Both callers import from `core.agents` already, so the dependency is available.

**This is the clearest opportunity for code consolidation in the current implementation.**

### Unobserved bootstrap turns

v1 records every kernel event (tool calls, model responses, errors) via `_CompositeObserver` → `EventStore`. Bootstrap passes `observer=None`. This means:

- Bootstrap agent LLM activations leave **no per-turn trace** in the event store
- You can replay the event stream and see `AgentNeededEvent`, `ToolSynthesizedEvent`, and any `emit_event` calls — but not the model's reasoning or tool call sequence
- Debugging a failed bootstrap activation requires log inspection, not event replay

This is likely an intentional tradeoff (bootstrap turns are setup-time, not steady-state), but it's an implicit decision. A comment in `TurnExecutor.run` noting `observer=None` is intentional would help future developers.

### BootstrapEvent type annotation gap

`BootstrapEvent` is a plain dataclass. `EventStore.append` is typed `event: StructuredEvent | CoreEvent`. `EventBus.emit` is also typed `event: StructuredEvent | CoreEvent`. Passing `BootstrapEvent` to either violates the static type contract.

**At runtime, everything works correctly:**
- `EventStore` uses `getattr`-based serialization, accepting any object with the expected fields
- `EventBus._resolve_handlers` uses `type(event).__mro__`, so `subscribe(BootstrapEvent, handler)` correctly matches emitted `BootstrapEvent` instances

The `user_question.pym` → `HumanInputRequestEvent` → EventBus → LSP bridge works correctly in production. The LSP startup subscribes `event_bus.subscribe(BootstrapEvent, _forward_user_question)` and the EventBus finds it via `BootstrapEvent.__mro__ = [BootstrapEvent, object]`.

The consequence is **mypy errors**, not runtime failures. But it does mean `BootstrapEvent` objects are invisible to any code that does `isinstance(event, StructuredEvent)` — they'll silently fall through. This is the real risk vector. Adding `StructuredEvent` as base class resolves all of it cleanly.

### DEFAULT_SCHEMA_YAML duplication

The default bootstrap schema exists in two places:
1. `schema_loader.py` — as a module-level string constant (`DEFAULT_SCHEMA_YAML`)
2. `bootstrap/agents/DEFAULT_SCHEMA.yaml` — as a file

`load_schema` uses the string constant as fallback. `test_agent_schemas.py` validates the file. They are currently in sync, but nothing enforces this.

**Recommendation:** `load_schema` should read the default from `bootstrap/agents/DEFAULT_SCHEMA.yaml` using `system_agents_dir` if available. The in-code constant becomes redundant. If `system_agents_dir` is not provided, the constant remains as a true last-resort fallback. This would make the file the single source of truth.

### LSP wiring: redundant path parameters

In `lsp/__main__.py`, `BootstrapRunner` is created with both injected stores and their paths:

```python
bootstrap_runner = BootstrapRunner(
    config,
    project_root=runtime_paths.project_root,
    bootstrap_root=runtime_paths.bootstrap_root,
    event_store_path=runtime_paths.event_store_path,      # ignored — event_store provided
    subscriptions_path=runtime_paths.subscriptions_path,  # ignored — subscriptions provided
    event_store=event_store,
    subscriptions=subscriptions,
    workspace_service=cairn_service,
)
```

The `BootstrapRunner` correctly uses the injected stores (`_owns_event_store = False`), so the path parameters are computed but never used. This is confusing to read — it looks like the runner might create its own stores. The paths should either be omitted (accepting `BootstrapRunner`'s defaults from `RuntimePaths`) or the constructor should document that paths are ignored when stores are injected.

### coordinator.yaml aspirational gap

`coordinator.yaml` defines a full LLM agent schema with subscriptions to `AgentNeededEvent` + `ToolSynthesizedEvent`. But the coordinator is run as Python code (`BootstrapRunner.run_once`), not as an LLM agent. The coordinator's schema subscriptions are never registered. The schema is aspirational documentation of what the coordinator *will* become.

This is fine as a design artifact, but it creates confusion: a developer reading `coordinator.yaml` would expect the coordinator to respond to `AgentNeededEvent` via LLM. A comment in both `runner.py` and `coordinator.yaml` explaining this is a phase-1 bridge would close the gap.

### bootstrap/src/remora_bootstrap/

A separate package exists at `bootstrap/src/remora_bootstrap/` with `primitives.py`, `runtime.py`, `bootstrap.py`, `contracts.py`, `registry.py`, and subpackages. This appears to be an earlier implementation attempt. Nothing in the current codebase imports from it. It is **dead code** and adds cognitive overhead — a developer exploring the codebase would encounter it and wonder about its relationship to `src/remora/bootstrap/`.

**Recommendation:** Remove it, given that it is an archived exploration.

### Developer mental model assessment

The current state of the codebase supports a reasonably clean mental model:

```
BootstrapRunner (entry point / lifecycle)
    → coordinator (find gaps) → emit AgentNeededEvent
    → activation (handle event) → TurnExecutor (run LLM)
        → bedrock (substrate functions) → [cairn, graph, events]
        → schema_loader (agent schema from workspace)
    → seed_graph (initial data)
```

The main **mental model hazard** is the split between `src/remora/bootstrap/` (the real implementation) and `bootstrap/` (tools, agents, and the dead `src/remora_bootstrap/` package). A new developer faces ambiguity about which `bootstrap/` is authoritative. The `bootstrap/tools/*.pym` and `bootstrap/agents/*.yaml` files are runtime data (like config), not code — this distinction should be clearer in the top-level README or a `bootstrap/README.md`.

The second hazard is the dual-path conceptualization of the coordinator: (a) Python code in `coordinator.py` / `runner.py` and (b) `coordinator.yaml` as an LLM agent definition. Until the LLM coordinator replaces the code coordinator, these two representations create a split mental model.
