# Gap Refactoring Plan

> **Project:** event-concept-gap-analysis  
> **Input:** `GAP_ANALYSIS.md` (13 gaps across 11 sections)  
> **Goal:** Detailed plan for closing every gap, organized into dependency-ordered workstreams  
> **Date:** 2026-03-03

---

## Table of Contents

### 1. Executive Summary
Brief overview of the refactoring strategy: what changes, why, and the key architectural insight (LSP delegates to core, not the other way around).

### 2. Workstream A — Wire the Reactive Loop (Gap #10)
**Quickest high-value fix.** Add `FileSavedEvent` and `ContentChangedEvent` emission to the `did_save` handler. This is a standalone change with no dependencies on other workstreams. Covers exactly what to add, where, and the expected behavior after.

### 3. Workstream B — Unify the Runners (Gaps #6, #7, #8, #9)
**The core architectural change.** Extract a shared execution layer from `SwarmExecutor` and make the LSP `AgentRunner` delegate to it instead of reimplementing agent execution. Covers:
- 3.1 Extract `AgentExecutionCore` from `SwarmExecutor`
- 3.2 Make `AgentRunner.execute_turn()` delegate to `AgentExecutionCore`
- 3.3 Wire bundle resolution into the LSP path (Gap #7)
- 3.4 Wire `_EventStoreObserver` into the LSP path (Gap #8)
- 3.5 Unify tool sets (Gap #9)
- 3.6 What gets removed from `AgentRunner`

### 4. Workstream C — Unify Discovery (Gaps #3, #4, #5)
**Eliminate the dual-discovery problem.** Make `ASTWatcher` delegate to `core.discovery` functions, and optionally introduce `.scm` query files for extensibility. Covers:
- 4.1 Make `ASTWatcher` call `core.discovery.discover_file()` instead of its own tree-sitter traversal
- 4.2 Add Markdown/TOML decomposition to the LSP path (Gap #5)
- 4.3 Optional: introduce `queries/` directory with `.scm` files (Gap #3)

### 5. Workstream D — LSP Event Completeness (Gaps #12, #13)
**Incremental improvements.** Add `textDocument/didChange` handler and debounce cursor tracking. Covers:
- 5.1 Add `didChange` handler with debounced re-parse (Gap #12)
- 5.2 Debounce cursor tracking and emit `CursorFocusEvent` to EventLog (Gap #13)

### 6. Workstream E — AgentNode Completeness (Gap #11)
**Smallest change.** Verify and finalize `last_trigger_event` / `last_completed_at` fields on `AgentNode` and ensure they are populated by the unified runner.

### 7. Dependency Graph & Execution Order
Which workstreams depend on which, recommended sequencing, and what can be parallelized.

### 8. Post-Refactoring Developer Experience
What the library looks like to use after all workstreams are complete. Walkthrough of the reactive loop from file-save to agent execution, showing how every component participates.

### 9. Risk Assessment & Mitigations
Breaking change risks, backward compatibility, testing strategy, and rollback plan for each workstream.

---

## 1. Executive Summary

### The Problem

The codebase has **two independent agent execution paths** that diverged from a single concept design:

| Aspect | Core/CLI (`SwarmExecutor`) | LSP (`AgentRunner`) |
|--------|---------------------------|---------------------|
| Bundle resolution | `bundle_mapping[node_type]` | Skipped entirely |
| Manifest loading | `load_manifest(bundle_path)` | None |
| Workspace isolation | `CairnWorkspaceService` CoW | None |
| Tools | Grail (`.pym`) + 5 swarm tools | `rewrite_self`, `message_node`, `read_node` |
| Kernel | `structured_agents.kernel` | Custom `LLMClient` + tool loop |
| Event audit trail | `_EventStoreObserver` writes all kernel events | `LspAgentEvent` for UI only — nothing to EventLog |
| Subscription matching on kernel events | Works | Broken (no events to match) |
| `did_save` → agent trigger | N/A (CLI path) | Missing — no `FileSavedEvent`/`ContentChangedEvent` |

The concept doc (`docs/EventBased_Concept.md`) describes a **single unified reactive loop**. The core/CLI path (`SwarmExecutor`) is ~85% aligned with that design. The LSP path (`AgentRunner`) reimplements execution from scratch and misses critical pieces, meaning **the reactive loop — the central architectural concept — only works in CLI mode**.

### The Strategy

**Make the LSP path delegate to the core, not reimplement it.**

The refactoring follows a principle of **convergence toward `SwarmExecutor`**: extract the execution logic from `SwarmExecutor` into a shared layer, then make `AgentRunner` become a thin orchestration shell (queue management, cascade safety, UI events) that delegates actual agent execution to that shared layer.

### Five Workstreams

| Workstream | Gaps Closed | Effort | Impact |
|------------|-------------|--------|--------|
| **A: Wire the Reactive Loop** | #10 | Small (1 file, ~30 lines) | Unblocks the primary file-save trigger |
| **B: Unify the Runners** | #6, #7, #8, #9 | Large (new shared module + refactor of 2 runners) | Fixes the core architecture split |
| **C: Unify Discovery** | #3, #4, #5 | Medium (refactor `ASTWatcher` to use `core.discovery`) | Eliminates parsing duplication, adds non-Python decomposition to LSP |
| **D: LSP Event Completeness** | #12, #13 | Small-Medium (2 new handlers/features) | Live editing updates + cursor events |
| **E: AgentNode Completeness** | #11 | Trivial (verify fields exist, wire population) | Metadata completeness |

### Recommended Order

```
A → B → C → E → D
```

- **A first**: standalone, immediate value, no dependencies.
- **B next**: the core architectural change — everything else benefits from unified execution.
- **C after B**: discovery unification is independent of runner unification, but doing B first means the unified runner naturally picks up `core.discovery` results.
- **E after B**: the unified runner is the right place to populate `last_trigger_event`/`last_completed_at`.
- **D last**: `didChange` and cursor debouncing are incremental improvements that don't block anything.

### What the Library Looks Like Afterwards

After all five workstreams:

1. **One execution path.** Both CLI and LSP trigger the same `run_agent()` logic with the same bundle resolution, same tools, same kernel, same event audit trail.
2. **The reactive loop works end-to-end in LSP mode.** File save → `ContentChangedEvent` → subscription matching → agent trigger → kernel execution → kernel events to EventLog → subscription matching → cascade.
3. **One discovery implementation.** `ASTWatcher` delegates to `core.discovery`, which means Markdown sections and TOML tables get proper decomposition in the LSP path.
4. **Live editing.** `didChange` enables incremental re-parsing without waiting for save.
5. **Full audit trail.** Every agent turn, in both CLI and LSP mode, writes kernel events to the EventStore. SSE subscribers see everything.

---

## 2. Workstream A — Wire the Reactive Loop (Gap #10)

**Gap:** `did_save` handler in `src/remora/lsp/handlers/documents.py` emits `NodeDiscoveredEvent` / `NodeRemovedEvent` but does NOT emit `FileSavedEvent` or `ContentChangedEvent`. This means the "source file changes" default subscription never fires — the reactive loop's primary trigger is not wired.

**Effort:** Small — ~30 lines in one file, no structural changes.

**Dependencies:** None. This is the first thing to do.

### What Changes

**File:** `src/remora/lsp/handlers/documents.py` — `did_save()` function (line 91)

After the existing `NodeDiscoveredEvent` / `NodeRemovedEvent` emission block (lines 117-140), and before `await server.db.update_edges(new_dicts)` (line 143), add:

1. **Import** `FileSavedEvent` and `ContentChangedEvent` from `remora.core.events` (line 7).
2. **Emit `FileSavedEvent`** with `path=uri` to the `"files"` stream (or the swarm stream).
3. **Emit `ContentChangedEvent`** with `path=uri` to the same stream. The `diff` field can be `None` initially (computing diffs adds complexity for minimal value at this stage).

### Pseudocode

```python
# At top of file, add to imports:
from remora.core.events import NodeDiscoveredEvent, NodeRemovedEvent, FileSavedEvent, ContentChangedEvent

# Inside did_save(), after NodeDiscoveredEvent emission loop, before update_edges:
if server.event_store:
    await server.event_store.append("files", FileSavedEvent(path=uri))
    await server.event_store.append("files", ContentChangedEvent(path=uri))
```

### Why This Works

The `EventStore.append()` method already runs subscription matching on every append (see `event_store.py` `append()` → `_match_subscriptions()`). The default subscriptions registered for each agent include a "source file changes" pattern that matches `ContentChangedEvent` where `path` matches the agent's file. So:

1. `ContentChangedEvent(path=uri)` is appended to EventStore.
2. `_match_subscriptions()` finds agents whose file matches `uri`.
3. Those agents are added to the trigger queue.
4. `AgentRunner` (or the unified runner after Workstream B) picks them up.

### What It Looks Like After

```
User saves file.py in editor
  → LSP did_save fires
    → NodeDiscoveredEvent/NodeRemovedEvent (existing — maintains nodes table)
    → FileSavedEvent(path="file.py")         ← NEW
    → ContentChangedEvent(path="file.py")    ← NEW
      → Subscription matching runs
        → Agent "func_foo" has default sub matching ContentChangedEvent on file.py
          → Trigger enqueued for func_foo
            → AgentRunner.execute_turn() runs the agent
```

### Pros

- **Immediate value.** The reactive loop's primary trigger starts working in LSP mode.
- **Zero risk.** Additive change — existing behavior is untouched.
- **Validates the architecture.** If subscriptions are wired correctly, this change alone proves the reactive loop works end-to-end (even though the agent execution is still the old LSP path until Workstream B).

### Cons / Caveats

- **Agent execution is still the old LSP path.** The triggered agents run via `AgentRunner.execute_turn()` with its own tool loop and no kernel event audit trail. Workstream B fixes this.
- **No diff computation.** `ContentChangedEvent.diff` is `None`. Could be added later by comparing old vs new text (the handler already has both).
- **Potential for noise.** Every save triggers subscriptions. If a user saves frequently, agents could be triggered often. Cascade safety (cooldown, depth limit) mitigates this, but it's worth monitoring.

### Testing

1. Unit test: mock `EventStore.append()`, call `did_save()`, assert `FileSavedEvent` and `ContentChangedEvent` were appended.
2. Integration test: set up an agent with a default "source file changes" subscription, trigger `did_save`, verify the agent appears in the trigger queue.

---

## 3. Workstream B — Unify the Runners (Gaps #6, #7, #8, #9)

**Gaps addressed:**
- **#6** — Two separate runner implementations that don't share code
- **#7** — LSP runner doesn't use `bundle_mapping`
- **#8** — LSP runner doesn't write kernel events to EventLog
- **#9** — LSP runner has different tools than core runner

**Effort:** Large — new shared module, refactoring of two existing modules.

**Dependencies:** None hard (can be done before or after Workstream A), but A is faster to ship so do it first.

### 3.1 The Core Insight

`SwarmExecutor.run_agent()` (in `src/remora/core/swarm_executor.py:91-260`) already does the right thing:

1. Resolves bundle via `bundle_mapping[node_type]` → loads manifest
2. Gets workspace via `CairnWorkspaceService`
3. Builds prompt via `_build_prompt()` with code, chat history, trigger event, scaffold context
4. Discovers Grail tools + swarm tools
5. Creates `_EventStoreObserver` and passes it to the kernel
6. Runs `structured_agents.kernel` with observer attached
7. Kernel events flow to EventStore via observer → subscription matching fires

`AgentRunner.execute_turn()` (in `src/remora/lsp/runner.py:393-496`) reimplements all of this differently:

1. Applies extensions directly (no bundle)
2. Uses `agent.to_system_prompt()` (no manifest system prompt)
3. Has its own tool loop with `LLMClient.chat()` (not `structured_agents.kernel`)
4. Provides `rewrite_self`/`message_node`/`read_node` (not Grail + swarm tools)
5. Emits `LspAgentEvent` for UI (not kernel events to EventStore)

The fix is **not** to merge these into one class. The fix is to **extract the execution logic from `SwarmExecutor.run_agent()` into a reusable function**, then call it from both places.

### 3.2 Extract `AgentExecutionCore`

Create a new module: `src/remora/core/execution.py`

This module contains a single async function (or small class) that encapsulates steps 1-7 from `SwarmExecutor.run_agent()`:

```python
# src/remora/core/execution.py

@dataclass
class ExecutionResult:
    response_text: str
    kernel_events: list[Any]  # for callers that want them

async def execute_agent_turn(
    node: AgentNode,
    config: Config,
    event_store: EventStore,
    subscriptions: SubscriptionRegistry,
    swarm_id: str,
    project_root: Path,
    *,
    trigger_event: Any = None,
    workspace_service: CairnWorkspaceService | None = None,
    extra_tools: list[Any] | None = None,
    on_kernel_event: Callable | None = None,  # hook for LSP UI events
) -> ExecutionResult:
    """Run a single agent turn using the unified execution pipeline.
    
    This is the ONE place where agent execution happens. Both SwarmExecutor
    and AgentRunner delegate here.
    """
    # 1. Resolve bundle
    bundle_path = _resolve_bundle_path(node, config)
    manifest = load_manifest(bundle_path)
    
    # 2. Get workspace (lazy-init if needed)
    workspace = ...
    
    # 3. Build prompt
    prompt = _build_prompt(node, ...)
    
    # 4. Discover tools (Grail + swarm + extra_tools)
    tools = discover_grail_tools(...) + (extra_tools or [])
    
    # 5. Create observer that writes to EventStore AND optionally notifies LSP UI
    observer = _CompositeObserver(event_store, swarm_id, on_kernel_event)
    
    # 6. Run kernel
    result = await _run_kernel(manifest, prompt, tools, observer, ...)
    
    # 7. Return result
    return ExecutionResult(response_text=..., kernel_events=observer.events)
```

**Key design decisions:**

- **Function, not class.** The current `SwarmExecutor` is stateful (holds `_client`, `_workspace_service`, etc.) but most of that state can be injected. A function with explicit dependencies is easier to test and reason about.
- **`on_kernel_event` callback.** This is how the LSP path gets its `LspAgentEvent` emissions. The observer writes to EventStore AND calls the callback. This means the LSP path gets both: audit trail (EventStore) + UI events (callback).
- **`extra_tools` parameter.** The LSP path needs `rewrite_self`, `message_node`, `read_node` in addition to (or instead of) Grail tools. These are passed in.

### 3.3 Wire Bundle Resolution into LSP Path (Gap #7)

**Current state:** `AgentRunner.execute_turn()` calls `self.apply_extensions(agent)` then uses `agent.to_system_prompt()` directly. No bundle resolution, no manifest loading.

**After:** `AgentRunner.execute_turn()` calls `execute_agent_turn()`, which resolves the bundle via `config.bundle_mapping[node.node_type]` and loads the manifest. The manifest's `system_prompt` becomes the system message, not `agent.to_system_prompt()`.

**Implication:** Extensions still apply — they modify the `AgentNode` before it's passed to `execute_agent_turn()`. But the bundle system prompt comes from the manifest, and `agent.to_system_prompt()` provides the agent-specific context (code, graph position, etc.) as a user message or appended to the system prompt.

**Migration note:** Bundles must exist for all node types used in LSP mode. If `bundle_mapping` doesn't have an entry for a node type, the system needs a sensible default (the current `SwarmExecutor._resolve_bundle_path()` returns `bundle_root` as fallback — this works).

### 3.4 Wire `_EventStoreObserver` into LSP Path (Gap #8)

**Current state:** `AgentRunner.execute_turn()` emits `LspAgentEvent` objects via `emit_event()` for UI display. These are NOT written to the EventStore. Kernel events (`ToolCallEvent`, `ModelResponseEvent`, etc.) are not captured at all.

**After:** `execute_agent_turn()` creates an `_EventStoreObserver` (or a composite observer) that:

1. Writes every kernel event to EventStore via `event_store.append(swarm_id, event)` — this triggers subscription matching.
2. Optionally calls `on_kernel_event(event)` for the LSP path to convert to `LspAgentEvent` and send to the UI.

This means:
- **Audit trail works.** All kernel events are in the EventStore.
- **Subscription matching on kernel events works.** If agent A's `ToolCallEvent` matches agent B's subscription, B gets triggered.
- **SSE stream sees everything.** The SSE adapter reads from EventStore, so all kernel events flow to SSE subscribers.
- **LSP UI still works.** The `on_kernel_event` callback converts kernel events to `LspAgentEvent` format for the existing SSE/panel display.

### 3.5 Unify Tool Sets (Gap #9)

**Current state:**
- Core runner: Grail tools (`.pym` scripts) + 5 swarm tools (`send_message`, `subscribe`, `unsubscribe`, `broadcast`, `query_agents`)
- LSP runner: `rewrite_self`, `message_node`, `read_node` + `agent.extra_tools`

These are fundamentally different capabilities. The LSP tools (`rewrite_self`, `message_node`, `read_node`) are the "editor-integrated" tools — they produce proposals, send messages to other agents, and read agent source. The core tools (Grail + swarm) are the "execution" tools — they manipulate files, run scripts, and manage subscriptions.

**Strategy: Union, not replacement.**

The unified execution path should provide:

1. **Grail tools + swarm tools** (from the manifest's `agents_dir`) — these are the execution backbone.
2. **LSP-specific tools** (`rewrite_self`, `message_node`, `read_node`) — these are added when running in LSP mode.

The `extra_tools` parameter on `execute_agent_turn()` is how LSP-specific tools get injected:

```python
# In AgentRunner.execute_turn():
lsp_tools = self._build_lsp_tools(agent)  # rewrite_self, message_node, read_node

result = await execute_agent_turn(
    node=agent,
    config=self.config,
    event_store=self.server.event_store,
    ...,
    extra_tools=lsp_tools,
    on_kernel_event=self._handle_kernel_event,
)
```

**Important:** The LSP tools (`rewrite_self`, `message_node`, `read_node`) need to be converted from the current inline dict format to proper tool objects that the kernel can call. Currently they're defined as raw dicts in `AgentRunner.get_agent_tools()` (runner.py:731-783). They need to become proper tool classes (similar to the swarm tools in `core/tools/swarm.py`), or the kernel needs to support raw dict tool schemas with a dispatch callback.

**Decision to make:** Should `rewrite_self`/`message_node`/`read_node` be implemented as Grail scripts (`.pym` files in a bundle) or as built-in tool classes? Grail scripts would be more aligned with the architecture, but built-in classes are simpler and don't require a bundle directory.

**Recommendation:** Implement them as built-in tool classes in `src/remora/core/tools/lsp.py`, similar to the swarm tools. They are conceptually part of the LSP integration, not agent-specific behavior. The unified execution function includes them when the `lsp_tools` parameter is provided.

### 3.6 What Gets Removed from `AgentRunner`

After this refactoring, `AgentRunner` becomes a thin orchestration layer:

**Keeps:**
- Trigger queue (`asyncio.Queue[Trigger]`)
- `run_forever()` / `stop()` — queue consumption loop
- `trigger()` — cascade safety checks (depth, cooldown, cycle detection)
- `execute_turn()` — but now it's ~20 lines: apply extensions, call `execute_agent_turn()`, handle result
- `poll_command_queue()` / `_dispatch_command()` — command dispatch from web UI
- `create_proposal()` — proposal creation + diagnostics (LSP-specific)
- `message_node()` — inter-agent messaging (delegates to event emission)

**Removes:**
- `LLMClient` class — no longer needed; the kernel handles LLM communication
- `LLMResponse` / `ToolCall` models — replaced by kernel's built-in response handling
- `get_agent_tools()` — the hardcoded tool dicts; replaced by proper tool classes
- `handle_response()` — the match/case tool dispatch loop; replaced by kernel's tool execution
- `_extract_text_tool_calls()` — the Qwen XML workaround; the kernel handles this
- `apply_extensions()` — can stay, but might move to `execute_agent_turn()` for consistency

**Net reduction:** `runner.py` goes from ~818 lines to ~300-400 lines. The removed code is replaced by delegation to `execute_agent_turn()`.

### What It Looks Like After

```
AgentRunner.execute_turn(trigger)
  │
  ├── agent = event_store.get_node(trigger.agent_id)
  ├── agent = self.apply_extensions(agent)
  ├── lsp_tools = self._build_lsp_tools(agent)  # rewrite_self, message_node, read_node
  │
  └── result = execute_agent_turn(
  │       node=agent,
  │       config=config,
  │       event_store=event_store,
  │       subscriptions=subscriptions,
  │       swarm_id=swarm_id,
  │       project_root=project_root,
  │       trigger_event=trigger_event,
  │       extra_tools=lsp_tools,
  │       on_kernel_event=self._emit_lsp_event,
  │   )
  │
  └── # Handle result: update status, refresh code lenses
```

And `SwarmExecutor.run_agent()` becomes:

```
SwarmExecutor.run_agent(node, trigger_event)
  │
  └── result = execute_agent_turn(
  │       node=node,
  │       config=self.config,
  │       event_store=self._event_store,
  │       subscriptions=self._subscriptions,
  │       swarm_id=self._swarm_id,
  │       project_root=self._project_root,
  │       trigger_event=trigger_event,
  │       workspace_service=self._workspace_service,
  │   )
  │
  └── return truncate(result.response_text, max_len=config.truncation_limit)
```

### Pros

- **One execution path.** Same bundle, same tools, same kernel, same audit trail, regardless of entry point.
- **LSP gets workspace isolation for free.** `CairnWorkspaceService` is wired into `execute_agent_turn()`.
- **Audit trail is complete.** Every agent turn, CLI or LSP, writes kernel events to EventStore.
- **SSE works fully.** All events flow through EventStore → SSE adapter.
- **`runner.py` gets much simpler.** Queue management + cascade safety + delegation. No more tool dispatch loop.

### Cons / Risks

- **Large refactor.** Touches `swarm_executor.py`, `runner.py`, and creates a new `execution.py`. Many integration points.
- **Kernel dependency.** The LSP path currently uses `structured_agents.client.build_client()`. After this change, it uses `structured_agents.kernel`. The kernel has a different API and may have different behavior (e.g., `max_turns`, tool dispatch).
- **LSP tool compatibility.** `rewrite_self`/`message_node`/`read_node` need to work with the kernel's tool execution model. The kernel calls tools differently than the current `handle_response()` match/case loop.
- **Bundle requirement.** The LSP path now requires bundles to exist. If a node type doesn't have a bundle mapping, it needs a sensible default. Currently the core runner falls back to `bundle_root` — this needs to work for LSP too.
- **`_HeadlessServer` adapter.** The `AgentRunner.create_headless()` path needs to work with the new execution function. Since `execute_agent_turn()` takes explicit dependencies (not a server object), this should be cleaner, not harder.

### Testing Strategy

1. **Unit test `execute_agent_turn()` in isolation.** Mock EventStore, mock kernel, verify: bundle resolution, tool discovery, observer wiring, result extraction.
2. **Integration test via `AgentRunner`.** Set up `AgentRunner` with real EventStore, trigger an agent, verify kernel events appear in EventStore.
3. **Integration test via `SwarmExecutor`.** Verify existing CLI tests still pass (regression).
4. **LSP-specific test.** Verify `rewrite_self` produces a proposal, `message_node` triggers the target, `read_node` returns source.
5. **Cross-path test.** Trigger an agent from CLI, verify the same events appear as when triggered from LSP.

---

## 4. Workstream C — Unify Discovery (Gaps #3, #4, #5)

**Gaps addressed:**
- **#3** — No `.scm` query files exist (hardcoded AST traversal in both paths)
- **#4** — Two separate discovery implementations (`core.discovery` vs LSP `ASTWatcher`)
- **#5** — Markdown/TOML decomposition incomplete in LSP path (file-level only for non-Python)

**Effort:** Medium — refactor `ASTWatcher`, remove duplicated parsing logic.

**Dependencies:** Independent of Workstreams A and B. Can be done in parallel. However, doing B first simplifies things because the unified runner naturally uses `core.discovery` results via the nodes table.

### The Problem

Two independent tree-sitter parsing implementations:

| Aspect | `core.discovery` (`discovery.py`) | LSP `ASTWatcher` (`watcher.py`) |
|--------|-----------------------------------|----------------------------------|
| Location | `src/remora/core/discovery.py` | `src/remora/lsp/watcher.py` |
| Query mechanism | `.scm` files via `_load_queries()` (line 96) | Hardcoded AST traversal (line 46+) |
| Python support | Functions, classes, methods, file | Functions, classes, methods, file |
| Markdown support | Sections (via `.scm` queries) + frontmatter notes/todos | File-level node only |
| TOML support | Tables (via `.scm` queries) | File-level node only |
| Node ID scheme | `SHA256(file_path:name:start:end)[:16]` | `generate_id()` (random) with stability via old_nodes lookup |
| Runs | CLI batch scan (`discover()` with thread pool) | Per-file on `did_open`/`did_save` |

The core `discovery.py` already supports `.scm` query files and has the `_load_queries()` infrastructure. It's the more complete and extensible implementation. The LSP `ASTWatcher` was written independently and uses hardcoded tree-sitter traversal.

### 4.1 Make `ASTWatcher` Delegate to `core.discovery`

**Strategy:** Replace `ASTWatcher.parse_and_inject_ids()` internals with a call to `core.discovery._parse_file()` (or a new public `parse_text()` variant that accepts text content instead of reading from disk).

**Why a `parse_text()` variant?** The LSP path receives file content from the editor via `params.text_document.text` or `params.text`. It doesn't need to read from disk. But `core.discovery._parse_file()` reads from disk via `file_path.read_text()`. We need a variant that accepts text content directly.

**New function in `core.discovery`:**

```python
def parse_content(file_path: str, content: str, language: str | None = None) -> list[CSTNode]:
    """Parse text content and return CSTNode list.
    
    Like _parse_file() but accepts content directly instead of reading from disk.
    Used by the LSP path where content comes from the editor.
    """
    if language is None:
        suffix = Path(file_path).suffix.lower()
        language = LANGUAGE_EXTENSIONS.get(suffix)
    if language is None:
        return [_create_file_node_from_content(file_path, content)]
    
    parser = _get_parser(language)
    if parser is None:
        return [_create_file_node_from_content(file_path, content)]
    
    # Same logic as _parse_file() but using content instead of file_path.read_text()
    tree = parser.parse(content.encode())
    query_text = _load_queries(language)
    ...  # identical to _parse_file() from this point
```

**Then `ASTWatcher.parse_and_inject_ids()` becomes:**

```python
def parse_and_inject_ids(self, uri: str, text: str, old_nodes: list[dict] | None = None) -> list[dict]:
    from remora.core.discovery import parse_content
    
    cst_nodes = parse_content(uri, text)
    
    # Convert CSTNode objects to dicts, preserving old node IDs for stability
    return self._stabilize_ids(cst_nodes, old_nodes)
```

**Node ID stability:** The LSP path currently uses `generate_id()` (random UUIDs) and looks up `old_nodes` by `(name, node_type)` key to reuse existing IDs. The core path uses deterministic `SHA256(file_path:name:start:end)[:16]`. After unification, the LSP path should adopt the deterministic scheme. This means node IDs change on first save after the migration, but they stabilize immediately after (same content → same hash). The `old_nodes` lookup becomes unnecessary except for backward compatibility during migration.

**Decision:** Adopt deterministic IDs from `core.discovery.compute_node_id()`. Accept the one-time ID change on migration. The `_stabilize_ids()` method can provide a temporary migration bridge that maps old random IDs to new deterministic IDs.

### 4.2 Add Markdown/TOML Decomposition to LSP Path (Gap #5)

**Current state:** `ASTWatcher._parse_file_only()` creates a single file-level node for non-Python files. This means Markdown files don't get section-level agents and TOML files don't get table-level agents in LSP mode.

**After:** Since `parse_content()` delegates to `core.discovery` which uses `.scm` queries, Markdown files automatically get `section` nodes (from `queries/markdown/remora_core/section.scm`) and TOML files get `table` nodes (from `queries/toml/remora_core/table.scm`).

**This gap is closed for free by adopting `core.discovery`.** No additional work needed beyond 4.1.

**Caveat:** The `.scm` query files must exist and work. Currently `core.discovery._load_queries()` (line 96) looks in `remora/queries/{language}/remora_core/*.scm`. Let me verify these exist:

The `_get_query_dir()` function (discovery.py:88-93) returns `importlib.resources.files("remora") / "queries"`. If the package doesn't include a `queries/` directory, `_load_queries()` returns `None` and `_parse_file()` falls back to `_create_file_node()`. This means Gap #3 (no `.scm` query files) must be addressed for this to fully work.

### 4.3 Introduce `queries/` Directory with `.scm` Files (Gap #3)

**Current state:** The `queries/` directory doesn't exist in the package. `_load_queries()` always returns `None`, so `_parse_file()` falls back to `_create_file_node()` for non-Python files. For Python, the fallback is still file-level only unless hardcoded traversal is used.

Wait — re-reading `discovery.py` more carefully: if `_load_queries()` returns `None`, `_parse_file()` returns `[_create_file_node(file_path, content)]`. This means **`core.discovery` currently also only produces file-level nodes when `.scm` files don't exist**. The `.scm` query infrastructure exists but has no query files to load.

**Action:** Create the query directory and populate it with `.scm` files for Python, Markdown, and TOML:

```
src/remora/queries/
  python/
    remora_core/
      function.scm     # matches function_definition, class_definition
      file.scm         # matches module (whole file)
  markdown/
    remora_core/
      section.scm      # matches atx_heading sections
      file.scm         # matches document
  toml/
    remora_core/
      table.scm        # matches table, array_of_tables
      file.scm         # matches document
```

**Python `function.scm` example:**
```scheme
(function_definition
  name: (identifier) @function.name) @function.def

(class_definition
  name: (identifier) @class.name) @class.def
```

**Markdown `section.scm` example:**
```scheme
(atx_heading
  heading_content: (_) @section.name) @section.def
```

**This is the most work-intensive part of Workstream C** — writing correct `.scm` queries, testing them against real files, and ensuring the capture-to-CSTNode mapping in `_parse_file()` handles them correctly.

**Alternatively:** Since `core.discovery` already has hardcoded Python traversal that works, and the `.scm` infrastructure is aspirational, this sub-task can be deferred. The immediate priority is unifying the two discovery paths (4.1) and getting non-Python decomposition working (4.2). The `.scm` migration can come later as a separate project.

**Recommendation:** Split this into two phases:
- **Phase 1 (this workstream):** Unify `ASTWatcher` to delegate to `core.discovery`. For Python, use the existing hardcoded traversal in `core.discovery`. For Markdown/TOML, write minimal `.scm` queries for section/table extraction.
- **Phase 2 (future project):** Migrate Python discovery from hardcoded traversal to `.scm` queries. This is a larger effort that requires testing across diverse Python codebases.

### What Gets Removed from `ASTWatcher`

After this refactoring:

**Keeps:**
- `parse_and_inject_ids()` — but now delegates to `core.discovery.parse_content()`
- `inject_ids()` — the function that writes `# remora:id=...` comments into Python files (this is LSP-specific behavior)
- ID stability logic (temporary, for migration)

**Removes:**
- `_parse_python_tree()` — replaced by `core.discovery` Python parsing
- `_parse_file_only()` — replaced by `core.discovery` file-level node creation
- `_parse_fallback()` — the regex fallback; `core.discovery` handles parser-not-available
- Direct tree-sitter `Parser` and `Language` imports — only `core.discovery` needs these
- `_PYTHON_SUFFIXES` / `_SUPPORTED_SUFFIXES` — consolidated into `core.discovery.LANGUAGE_EXTENSIONS`

**Net reduction:** `watcher.py` goes from ~293 lines to ~100-120 lines.

### Pros

- **Single source of truth for parsing.** One set of queries, one set of capture-to-node mapping rules.
- **Non-Python decomposition in LSP for free.** Markdown sections, TOML tables, etc.
- **Extensibility.** Adding a new language or node type means adding a `.scm` file, not editing code.
- **Consistent node IDs across CLI and LSP.** Deterministic SHA256-based IDs everywhere.

### Cons / Risks

- **Node ID migration.** Existing LSP sessions have random-UUID-based node IDs. After migration, they become SHA256-based. Any external system storing node IDs (e.g., the web UI, cursor tracking DB) needs to handle the change. The EventStore `nodes` table will see `NodeRemovedEvent` for old IDs and `NodeDiscoveredEvent` for new IDs — effectively a full re-discovery on first save.
- **`.scm` query correctness.** Tree-sitter queries are subtle. A wrong query can miss nodes or produce duplicates. Requires careful testing.
- **tree-sitter grammar versions.** Different versions of `tree_sitter_markdown`, `tree_sitter_toml`, etc. may have different node types. Queries need to be compatible with the installed grammar versions.

### Testing Strategy

1. **Unit test `parse_content()`.** Feed it known Python/Markdown/TOML content, verify correct CSTNode output.
2. **Regression test `ASTWatcher`.** The existing behavior (Python function/class extraction) must produce the same nodes (with different IDs).
3. **New test: Markdown section extraction.** Feed a Markdown file with headings, verify section-level CSTNodes.
4. **New test: TOML table extraction.** Feed a TOML file with tables, verify table-level CSTNodes.
5. **Integration test: `did_save` with Markdown file.** Verify section-level agents appear in EventStore.

---

## 5. Workstream D — LSP Event Completeness (Gaps #12, #13)

**Gaps addressed:**
- **#12** — No `textDocument/didChange` handler (live editing doesn't update agents until save)
- **#13** — Cursor tracking not debounced, no EventLog event

**Effort:** Small-Medium.

**Dependencies:** None hard, but best done after Workstream A (so `ContentChangedEvent` emission pattern is established) and Workstream C (so `parse_content()` is available for incremental re-parsing).

### 5.1 Add `didChange` Handler (Gap #12)

**Current state:** The LSP server registers `textDocument/didOpen` and `textDocument/didSave` but not `textDocument/didChange`. This means tree-sitter re-parsing only happens when a file is opened or saved. During live editing, the agent nodes, code lenses, and hover data are stale until the next save.

**What to add:**

A new handler in `src/remora/lsp/handlers/documents.py`:

```python
@server.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
async def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
    uri = params.text_document.uri
    # Apply incremental changes to get current text
    # (full sync: params.content_changes[0].text)
    text = params.content_changes[-1].text  # assuming full sync
    
    # Debounce: don't re-parse on every keystroke
    await server.schedule_reparse(uri, text, delay_ms=500)
```

**Debounce mechanism:** Add a `_reparse_timers: dict[str, asyncio.TimerHandle]` to the server. Each `did_change` cancels the previous timer for that URI and schedules a new one. When the timer fires, it runs `parse_and_inject_ids()` (via `core.discovery.parse_content()` after Workstream C) and updates the nodes table.

**Server capability registration:** Must declare `textDocumentSync` as `TextDocumentSyncKind.Full` (or `Incremental` if incremental parsing is desired). Currently, the server likely uses `Full` sync for `did_open`/`did_save`. Verify and adjust.

**What NOT to do during `didChange`:**
- Do NOT emit `ContentChangedEvent` on every change. Only emit on `did_save`. (The concept doc says `didChange` is for "incremental tree-sitter re-parsing", not for triggering the reactive loop.)
- Do NOT inject IDs into the file. ID injection happens on save only.
- Do NOT update edges in RemoraDB. Edge updates happen on save only.

**What TO do:**
- Re-parse and update the in-memory/EventStore nodes table so code lenses and hover data reflect current edits.
- Refresh code lenses after re-parse.

### 5.2 Debounce Cursor Tracking and Emit `CursorFocusEvent` (Gap #13)

**Current state:** `notifications.py:on_cursor_moved()` (line 8) runs on every `$/remora/cursorMoved` notification. It queries `event_store.get_node_at_position()` and stores the result in `server.db.update_cursor_focus()` directly. No debouncing. No EventLog event.

**What the concept says:** "Debounced (200ms stable) -> cursor focus event to EventLog."

**Changes:**

1. **Add debouncing.** Use the same timer pattern as `didChange`: cancel previous timer, schedule new one with 200ms delay. Only process cursor movement after 200ms of stability.

2. **Emit `CursorFocusEvent` to EventLog.** Create a new event type:

```python
# In core/events.py
class CursorFocusEvent(_FrozenEvent):
    """Cursor moved to focus on a specific agent."""
    agent_id: str | None
    file_path: str
    line: int
    timestamp: float = Field(default_factory=time.time)
```

3. **Append to EventStore** after the debounce fires:

```python
async def _on_cursor_stable(agent_id: str | None, uri: str, line: int):
    await server.db.update_cursor_focus(agent_id, uri, line)  # existing behavior
    if server.event_store:
        event = CursorFocusEvent(agent_id=agent_id, file_path=uri, line=line)
        await server.event_store.append("cursor", event)
```

**Why this matters:** With cursor events in the EventLog, agents can subscribe to "user is looking at me" events. This enables use cases like "agent explains itself when the user hovers over it" or "agent proactively offers help when the user's cursor stays on it for N seconds."

### Pros

- **Live editing responsiveness.** Code lenses and hover data update as you type (with debounce).
- **Cursor awareness in the reactive loop.** Agents can subscribe to cursor focus events.

### Cons / Risks

- **Performance.** `didChange` fires on every keystroke. Even with debouncing, frequent re-parses could be expensive for large files. Mitigation: only re-parse Python files (where node granularity matters); for non-Python, skip until save.
- **Event noise.** `CursorFocusEvent` could generate many events in the EventLog. Mitigation: use a dedicated stream name (`"cursor"`) and ensure subscription patterns don't accidentally match cursor events unless explicitly subscribed.
- **Sync mode.** Full-document sync on `didChange` sends the entire file content on every change. For large files, this is bandwidth-intensive. Incremental sync would be better but requires maintaining a content buffer and applying incremental edits. Start with full sync, optimize later.

---

## 6. Workstream E — AgentNode Completeness (Gap #11)

**Gap addressed:**
- **#11** — `last_trigger_event` and `last_completed_at` fields missing from `AgentNode`

**Effort:** Trivial.

**Dependencies:** Best done after Workstream B (unified runner), since that's where the fields get populated.

### Current State

The gap analysis noted these fields were missing. However, re-reading `agent_node.py`, I noted in the compaction summary that lines 95-96 may already have these fields, and `event_store.py` lines 121-122 may have the corresponding columns.

Let me state precisely what needs to happen:

1. **Verify fields exist on `AgentNode`.** If `last_trigger_event: str | None = None` and `last_completed_at: float | None = None` are already present, this is already partially addressed.

2. **Verify columns exist in the `nodes` table schema.** Check `event_store.py` CREATE TABLE statement for the `nodes` table.

3. **Wire population in the unified runner.** After Workstream B, `execute_agent_turn()` should:
   - Set `last_trigger_event` to `type(trigger_event).__name__` before execution.
   - Set `last_completed_at` to `time.time()` after execution completes.
   - Persist these via `event_store.update_node()` or equivalent.

4. **Wire population in `AgentRunner.execute_turn()`.** Even before Workstream B, the LSP runner should update these fields:
   - Before: `await server.event_store.set_node_status(agent_id, "running")` — also set `last_trigger_event`.
   - After: `await server.event_store.set_node_status(agent_id, "idle")` — also set `last_completed_at`.

### What It Enables

- **Hover info.** `agent.to_hover()` can show "Last triggered by: ContentChangedEvent, 30s ago."
- **Stale agent detection.** Agents that haven't been triggered recently can be visually dimmed in code lenses.
- **Debugging.** When investigating why an agent didn't fire, `last_trigger_event` shows what last activated it.

### Effort

If fields and columns already exist: ~10 lines of code in the runner to populate them.
If fields/columns need to be added: ~30 lines total (model fields + schema migration + runner population).

---

## 7. Dependency Graph & Execution Order

### Dependencies

```
Workstream A (Wire Reactive Loop)
  └── No dependencies
  └── Enables: validates subscription matching works end-to-end

Workstream B (Unify Runners)
  └── No hard dependencies (but A should ship first for quick value)
  └── Enables: E (AgentNode field population in unified runner)
  └── Enables: better D (didChange re-parse uses unified discovery after C)

Workstream C (Unify Discovery)
  └── No hard dependencies (independent of A and B)
  └── Enables: better D (didChange uses parse_content() from core.discovery)

Workstream D (LSP Event Completeness)
  └── Soft dependency on A (ContentChangedEvent emission pattern)
  └── Soft dependency on C (parse_content() for didChange re-parse)

Workstream E (AgentNode Completeness)
  └── Soft dependency on B (unified runner is where fields get populated)
```

### Recommended Execution Order

```
Phase 1:  A ──────────────────────────── (1-2 days)
Phase 2:  B ──────────────────────────── (5-8 days)
          C ──────── (parallel if two devs) (3-5 days)
Phase 3:  E ──────────────────────────── (0.5 day)
Phase 4:  D ──────────────────────────── (2-3 days)
```

**Total estimated effort:** 12-18 developer-days.

**Rationale:**
- **A first** because it's the smallest change with the biggest immediate impact (the reactive loop trigger starts working).
- **B is the critical path.** It's the largest workstream and the one that fundamentally fixes the architecture. Start it as soon as A ships.
- **C can run in parallel with B** if there's a second developer. It touches different files (`watcher.py`, `discovery.py`) than B (`runner.py`, `swarm_executor.py`, new `execution.py`).
- **E after B** because the unified runner is where `last_trigger_event`/`last_completed_at` should be populated.
- **D last** because `didChange` and cursor debouncing are incremental improvements. They benefit from having `parse_content()` (from C) and the unified runner (from B) available.

### What Can Be Shipped Independently

Each workstream produces a shippable increment:

| Workstream | Ships as | User-visible change |
|------------|----------|-------------------|
| A | 1 PR | File saves trigger agents in LSP mode |
| B | 1-2 PRs | Unified agent execution; kernel events in EventStore; full SSE stream |
| C | 1 PR | Non-Python files get section/table agents; consistent node IDs |
| D | 1-2 PRs | Live editing updates agents; cursor focus events |
| E | Can fold into B's PR | Hover shows last trigger info |

---

## 8. Post-Refactoring Developer Experience

After all five workstreams are complete, here's what the system looks like.

### The Reactive Loop (End-to-End)

```
1. Developer saves file.py in their editor (Neovim via LSP)

2. LSP did_save handler fires:
   a. Parses file via core.discovery.parse_content()  [Workstream C]
   b. Emits NodeDiscoveredEvent for each node         [existing]
   c. Emits NodeRemovedEvent for orphaned nodes        [existing]
   d. Emits FileSavedEvent(path="file.py")             [Workstream A]
   e. Emits ContentChangedEvent(path="file.py")        [Workstream A]

3. EventStore.append() runs subscription matching:
   a. ContentChangedEvent matches default sub for agents in file.py
   b. Agent IDs added to trigger queue

4. AgentRunner.execute_turn() dequeues trigger:
   a. Cascade safety checks (depth, cooldown, cycle)   [existing]
   b. Applies extensions                                [existing]
   c. Delegates to execute_agent_turn()                 [Workstream B]

5. execute_agent_turn() runs:
   a. Resolves bundle via bundle_mapping[node_type]     [Workstream B]
   b. Loads manifest                                    [Workstream B]
   c. Gets workspace via CairnWorkspaceService          [Workstream B]
   d. Builds prompt with code, history, trigger event   [Workstream B]
   e. Discovers Grail tools + swarm tools + LSP tools   [Workstream B]
   f. Creates composite observer (EventStore + LSP UI)  [Workstream B]
   g. Runs structured_agents.kernel                     [Workstream B]

6. During kernel execution:
   a. Every kernel event (ToolCallEvent, ModelResponseEvent, etc.)
      is written to EventStore via observer             [Workstream B]
   b. LSP UI callback converts to LspAgentEvent        [Workstream B]
   c. SSE stream sees all events in real-time           [existing]
   d. Subscription matching runs on kernel events       [Workstream B]
      → may trigger other agents (e.g., ToolCallEvent
        from agent A triggers agent B's subscription)

7. Agent completes:
   a. AgentCompleteEvent written to EventStore          [Workstream B]
   b. last_trigger_event + last_completed_at updated    [Workstream E]
   c. Status set to "idle"                              [existing]
   d. Code lenses refresh                               [existing]

8. If agent called rewrite_self:
   a. Proposal created + diagnostics published          [existing]
   b. User reviews in editor → accept/reject            [existing]

9. If agent called message_node:
   a. AgentMessageEvent written to EventStore           [Workstream B]
   b. Target agent's subscription matches               [existing]
   c. Target agent triggered → goto step 4              [existing]
```

### Live Editing (Between Saves)

```
1. Developer types in file.py

2. LSP didChange handler fires (debounced, 500ms):     [Workstream D]
   a. Re-parses via core.discovery.parse_content()
   b. Updates nodes table
   c. Refreshes code lenses
   (No ContentChangedEvent — only on save)

3. Code lenses and hover info reflect current edits
```

### Cursor Awareness

```
1. Developer moves cursor to line 42 in file.py

2. $/remora/cursorMoved fires (debounced, 200ms):      [Workstream D]
   a. Finds agent at position
   b. Updates cursor_focus table
   c. Emits CursorFocusEvent to EventStore
   d. Agents subscribed to cursor events are triggered
```

### CLI/Core Path (Unchanged but Simplified)

```
1. SwarmExecutor.run_agent(node, trigger_event)
   → delegates to execute_agent_turn()                  [Workstream B]
   → same bundle resolution, same tools, same kernel
   → same EventStore audit trail
   → subscription matching triggers further agents
```

### Developer Adding a New Language

```
1. Create queries/rust/remora_core/function.scm         [Workstream C]
2. Add ".rs": "rust" to LANGUAGE_EXTENSIONS (if not already present)
3. Install tree_sitter_rust
4. Done — Rust functions get agents automatically
```

### Developer Adding a Custom Tool

```
1. Write a .pym Grail script in the bundle's agents_dir [existing]
2. The unified execute_agent_turn() discovers it         [Workstream B]
3. Available in both CLI and LSP modes                   [Workstream B]
```

---

## 9. Risk Assessment & Mitigations

### Workstream A — Wire the Reactive Loop

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Subscription matching produces unexpected triggers | Low | Medium | Default subscriptions are already tested; add integration test |
| Cascade on frequent saves | Low | Low | Cascade safety (cooldown 1000ms) already handles this |
| EventStore stream name mismatch | Low | Low | Use consistent stream name; verify in tests |

**Rollback:** Remove the two `append()` calls. Zero side effects.

### Workstream B — Unify the Runners

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Kernel API incompatibility | Medium | High | Spike: run a single agent turn through the kernel from LSP context before committing to the full refactor |
| LSP tool dispatch breaks | Medium | High | Keep `rewrite_self`/`message_node`/`read_node` as proper tool classes with tests; verify kernel calls them correctly |
| `_HeadlessServer` adapter breaks | Low | Medium | Test headless path explicitly |
| Performance regression (kernel heavier than LLMClient) | Low | Medium | Benchmark before/after; kernel should be similar since it wraps the same LLM client |
| Bundle missing for LSP node types | Medium | Medium | Add sensible default bundle; log warnings for unmapped types |

**Rollback:** Feature-flag the delegation. `AgentRunner.execute_turn()` can check a config flag and fall back to the old code path. Remove the flag once stable.

### Workstream C — Unify Discovery

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Node ID migration causes UI disruption | Medium | Medium | Accept one-time re-discovery; document in changelog |
| `.scm` queries produce wrong/missing nodes | Medium | Medium | Extensive test coverage against real files; keep hardcoded Python fallback initially |
| tree-sitter grammar version mismatch | Low | High | Pin grammar versions in `pyproject.toml` |
| Performance regression (query-based parsing slower) | Low | Low | Benchmark; queries should be similar speed to traversal |

**Rollback:** `ASTWatcher` can keep its old implementation behind a flag. If `parse_content()` produces bad results, fall back to the old path.

### Workstream D — LSP Event Completeness

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `didChange` performance on large files | Medium | Medium | Debounce aggressively (500ms+); skip non-Python initially |
| Full-sync bandwidth | Low | Low | Monitor; switch to incremental sync if needed |
| Cursor event noise in EventStore | Low | Low | Dedicated stream; subscription patterns must explicitly opt in |

**Rollback:** Remove handler registration. No side effects.

### Workstream E — AgentNode Completeness

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schema migration fails | Very Low | Low | SQLite ALTER TABLE is simple; test against existing DB files |

**Rollback:** Remove the two field assignments in the runner. Fields become NULL but that's harmless.

### Cross-Cutting Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Multiple workstreams create merge conflicts | Medium | Low | Clear file ownership per workstream; A and E touch different files than B and C |
| Existing tests break | Medium | Medium | Run full test suite after each workstream; fix regressions before merging |
| `structured_agents` API changes | Low | High | Pin version in `pyproject.toml`; test against pinned version |
| EventStore performance under increased event volume | Low | Medium | SQLite WAL mode handles concurrent writes well; monitor append latency |

---

