# PLAN — Scaffold Nodes (Phase 1)

> **ABSOLUTE RULE: NO SUBAGENTS (no Task tool). Do all work directly.**

## Overview

Add scaffold node support to Remora: nodes created empty that self-initialize by gathering context from their environment. Phase 1 covers the core mechanics — event, status, prompt enrichment, spawn tool, and extension config.

---

## Step 1: ScaffoldRequestEvent

**Goal:** New domain event type for triggering scaffold initialization.

### 1a. Write failing tests for ScaffoldRequestEvent
- Test event creation with all fields (node_id, node_type, parent_id, intent, timestamp)
- Test event is frozen (immutable)
- Test event is part of RemoraEvent union
- File: `tests/unit/test_scaffold_events.py`

### 1b. Implement ScaffoldRequestEvent
- Add to `src/remora/core/events.py`
- Add to `RemoraEvent` union type
- Add to `__all__`
- Verify tests pass

---

## Step 2: Scaffold Status in Projection

**Goal:** `NodeProjection` assigns `status = "scaffold"` when a `NodeDiscoveredEvent` has empty/stub source code.

### 2a. Write failing tests for scaffold status detection
- Test: `NodeDiscoveredEvent` with `source_code=""` → node gets `status = "scaffold"`
- Test: `NodeDiscoveredEvent` with `source_code="class Foo: pass"` → `status = "scaffold"`
- Test: `NodeDiscoveredEvent` with `source_code="def foo(): ..."` → `status = "scaffold"`
- Test: `NodeDiscoveredEvent` with real source code → `status = "idle"` (unchanged behavior)
- Test: Upsert preserves scaffold status when re-projected (doesn't overwrite to idle)
- File: `tests/unit/test_scaffold_projection.py`

### 2b. Implement scaffold status in projection
- Add `_is_stub(source_code: str) -> bool` helper in `projections.py`
- Modify `_project_node_discovered()` to set `status = "scaffold"` when `_is_stub()` returns True
- Ensure upsert logic preserves status for existing scaffold nodes
- Verify tests pass

---

## Step 3: Context-Enriched Prompt for Scaffold Nodes

**Goal:** When `SwarmExecutor._build_prompt()` builds a prompt for a scaffold node, it includes parent source, sibling info, and the scaffold intent.

### 3a. Write failing tests for scaffold prompt enrichment
- Test: scaffold node prompt includes parent source code
- Test: scaffold node prompt includes sibling names/types
- Test: scaffold node prompt includes intent from trigger event
- Test: non-scaffold node prompt is unchanged
- File: `tests/unit/test_scaffold_prompt.py`

### 3b. Implement scaffold prompt enrichment
- Add scaffold context section to `_build_prompt()` in `swarm_executor.py`
- When `node.status == "scaffold"`, fetch parent node and sibling nodes from event_store
- Include parent source, sibling summary, and intent in prompt
- Verify tests pass

---

## Step 4: spawn_child Tool

**Goal:** A tool that any agent can call to create a new scaffold child node.

### 4a. Write failing tests for spawn_child
- Test: spawn_child creates stub file on disk and returns node_id
- Test: spawn_child emits NodeDiscoveredEvent with stub content
- Test: spawn_child emits ScaffoldRequestEvent with intent
- Test: spawn_child for class creates `class Name: pass` stub in existing file
- Test: spawn_child for function creates `def name(): pass` stub in existing file
- Test: spawn_child for file creates empty file
- File: `tests/unit/test_spawn_child.py`

### 4b. Implement spawn_child tool
- Create `src/remora/core/tools/spawn_child.py`
- Tool function: `async def spawn_child(node_type, name, intent, file_path=None)`
- Writes stub to disk
- Emits NodeDiscoveredEvent + ScaffoldRequestEvent via agent context
- Returns new node_id
- Register in Grail tool discovery or as a built-in swarm tool

---

## Step 5: Scaffold Extension Config (Demo)

**Goal:** A demo extension that matches scaffold nodes and provides the initialization system prompt.

### 5a. Write failing tests for scaffold extension
- Test: extension matches nodes with stub source_code
- Test: extension does NOT match nodes with real source_code
- Test: extension provides scaffold-specific system prompt
- Test: extension provides ScaffoldRequestEvent subscription
- File: `tests/unit/test_scaffold_extension.py`

### 5b. Implement scaffold extension
- Create `remora_demo/project/.remora/models/scaffold_initializer.py`
- `matches()`: checks if source_code is empty or stub pattern
- `get_extension_data()`: returns scaffold-specific system prompt and subscriptions
- Verify tests pass

---

## Step 6: Stub Detection in Watcher

**Goal:** When ASTWatcher parses an empty/stub file or class/function, the resulting node dicts carry enough info for projection to detect them as scaffolds.

### 6a. Write failing tests for stub detection
- Test: empty .py file produces node with empty source_code
- Test: file with only `class Foo: pass` produces class node with stub source
- Test: file with only `def foo(): ...` produces function node with stub source
- File: `tests/unit/test_scaffold_watcher.py`

### 6b. Verify watcher behavior (likely already correct)
- ASTWatcher already captures source_code from tree-sitter output
- Stub classes/functions will naturally have minimal source_code
- May need no changes — just confirm via tests
- Verify tests pass

---

## Step 7: Integration Tests

**Goal:** End-to-end scaffold lifecycle: create stub → project as scaffold → trigger ScaffoldRequestEvent → agent gets enriched prompt.

### 7a. Write integration tests
- Test: Full cycle: NodeDiscoveredEvent with stub → projection sets scaffold status → ScaffoldRequestEvent matches subscription → correct agent triggered
- Test: spawn_child → NodeDiscoveredEvent + ScaffoldRequestEvent → scaffold node exists with correct parent
- Test: scaffold node prompt includes parent context and intent
- File: `tests/integration/test_scaffold_lifecycle.py`

### 7b. Fix any issues found during integration
- Debug and fix any issues surfaced by integration tests
- Verify all tests pass

---

## Step 8: Update PROGRESS.md and CONTEXT.md

- Mark all tasks complete
- Update CONTEXT.md with final state
- Run full test suite, confirm green

---

## Test Command

```bash
python -m pytest tests/ --ignore=tests/benchmarks --ignore=tests/integration/cairn --ignore=tests/unit/test_graph_app.py --ignore=tests/unit/test_graph_integration.py --ignore=tests/unit/test_graph_shell.py --ignore=tests/unit/test_graph_sidebar.py --ignore=tests/unit/test_graph_state.py --ignore=tests/unit/test_web_layout.py --ignore=tests/unit/test_graph_cli.py --ignore=tests/test_app.py --ignore=tests/test_bridge.py --ignore=tests/test_css.py --ignore=tests/test_entry_points.py --ignore=tests/test_integration_graph.py --ignore=tests/test_layout.py --ignore=tests/test_svg.py --ignore=tests/test_views.py -q --no-cov
```

---

> **REMINDER: NO SUBAGENTS. Do all work directly.**
