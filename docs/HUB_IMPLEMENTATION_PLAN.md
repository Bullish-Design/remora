# Node State Hub (Sidecar) Implementation Plan

## Goal
Introduce a **sidecar hub daemon** that maintains node-level state + markdown artifacts in the background. The hub uses deterministic diffs and update tools, and a tiny triage model (FunctionGemma + LoRA) to decide which updates to run. It assumes the **two-track memory system already exists**.

Storage is **repo-local** under `.agentfs/`.

---

## High-Level Architecture
- **Hub Daemon** (separate process): watches for file changes, updates node state
- **Diff bundle**: deterministic change signals
- **Rules engine**: maps signals → candidate updates
- **Triage runner**: tiny model decides which updates to run
- **Update tools**: deterministic Grail scripts
- **Artifacts**: node KV state + markdown summaries

---

## Storage Layout (Repo-local)
- `.agentfs/`
  - `nodes/` → markdown node summaries
  - `hub_state/` → Fsdantic KV store for node state
  - `traces/` → long-track trace logs (from two-track memory)

**Node state KV key**:
- `node:{node_id}:state`

**Markdown output**:
- `.agentfs/nodes/{relative_file_path}/{node_name}.md`

---

## Phase 1 — Hub Core
### 1. Create hub package
**Files**: `remora/hub/__init__.py`, `remora/hub/daemon.py`
- `HubDaemon` class with:
  - file watcher
  - tree-sitter discovery
  - diff bundle builder
  - update scheduler

### 2. CLI entrypoint
**Files**: `remora/cli.py`
- Add `remora hub` command
- Options: `--watch`, `--once`, `--config`, `--output-dir`

**Acceptance**:
- `remora hub --once <path>` runs a single pass
- `remora hub --watch <path>` runs continuously

---

## Phase 2 — Node State Schema
### 3. Define node state model
**Files**: `remora/hub/state.py`
- `NodeState` schema:
  - id, type, name, file_path, hash
  - signature, complexity, related, tests, summary
  - timestamps for each update type

### 4. NodeStateStore
**Files**: `remora/hub/state_store.py`
- Backed by Fsdantic KV in `.agentfs/hub_state/`
- Methods:
  - `get(node_id)`
  - `set(node_id, state)`
  - `update(node_id, partial)`

---

## Phase 3 — Diff Bundle + Rules
### 5. Diff bundle builder
**Files**: `remora/hub/diffs.py`
- Compute:
  - `diff_standard`: line changes
  - `diff_structural`: signature/annotations
  - `diff_ast`: complexity/control flow changes
  - `diff_embedding`: semantic drift

### 6. Rules engine
**Files**: `remora/hub/rules.py`
- Deterministic mapping:
  - signature change → `extract_signature`
  - complexity delta → `compute_complexity`
  - semantic drift → `search_similar`
  - new function → `find_tests`, `generate_test_skeleton`

---

## Phase 4 — Update Tools (Grail)
### 7. Implement deterministic tools
**Files**: `remora/hub/tools/*.pym`
- `extract_signature.pym`
- `compute_complexity.pym`
- `find_callers.pym`
- `find_callees.pym`
- `find_tests.pym`
- `search_similar.pym`
- `generate_test_skeleton.pym`
- `run_single_test.pym`

### 8. Register tools
**Files**: `remora/hub/tool_registry.py`
- Schema loading and validation (reuse `GrailToolRegistry` patterns)

---

## Phase 5 — Triage Runner
### 9. Triage agent definition
**Files**: `remora/hub/triage_agent.yaml`
- Tiny FunctionGemma + LoRA
- Receives:
  - node state summary
  - diff bundle
  - candidate updates

### 10. Triage execution
**Files**: `remora/hub/triage.py`
- Uses two-track memory runner
- Output: approved update list + reasons

---

## Phase 6 — Markdown Rendering
### 11. Markdown generator
**Files**: `remora/hub/markdown.py`
- Renders markdown from node state
- Stored in `.agentfs/nodes/...`

**Acceptance**:
- Markdown regenerates whenever node state changes
- File layout mirrors repo structure

---

## Phase 7 — Demo Implementations

### Demo 1: Pytest Failure Context Blob
- **Signal**: failing test output
- **Tools**: `find_tests`, `find_callers`, `find_callees`, `extract_signature`, `search_similar`
- **Output**: failure context bundle + markdown summary

### Demo 2: API Change Impact Summary
- **Signal**: public API change
- **Tools**: `find_callers`, `find_tests`, `list_exports`, `search_similar`
- **Output**: impact summary + callsite list

### Demo 3: Test Creation + Verification
- **Signal**: new/changed function without matching test
- **Rules**:
  - Detect missing test by naming convention
  - Generate runnable skeleton test
  - Run the test only and log output
- **Tools**:
  - `generate_test_skeleton`
  - `run_single_test`
- **Output**:
  - Test stub created
  - Test run log stored in long track
  - Markdown entry under node state

---

## Phase 8 — Context Providers
### 12. Hub context provider
**Files**: `remora/hub/context_provider.pym`
- Reads node state from `.agentfs/hub_state/`
- Injects into subagent prompts when requested

---

## Operational Notes
- `.agentfs/` should be ignored by file watcher.
- `hub` daemon must not block Remora workflows.
- All updates are deterministic unless explicitly marked LLM-powered.

---

## Success Criteria
- Hub runs independently and updates node state on change.
- Triage model controls which updates run.
- Node markdown artifacts regenerate correctly.
- Demos 1–3 run end-to-end with visible artifacts.

---

## Post-Hub Refactor: Two-Track + Hub Soft Coupling

This section describes a **safe, optional coupling** where two-track memory
**prefers hub context when fresh** but never depends on it. The goal is to
reuse canonical node metadata without risking stale or missing hub data.

### 1. Add a Central Hub Context Provider
**Files**: `remora/hub/context_provider.py` (runtime), `remora/hub/context_provider.pym` (tool)
- Implement a single hub context loader that:
  - Reads node state from `.agentfs/hub_state/`.
  - Emits a compact `HubContextBlob` for the current node.
- Include a **freshness policy**:
  - `fresh` if `now - last_updated <= freshness_threshold`.
  - `stale` if older but still present.
  - `missing` if no state exists yet.

**Why**: One centralized policy avoids duplicating staleness checks across tools.

### 2. Extend Decision Packet Schema
**Files**: `remora/memory/schemas.py`
- Add optional field: `hub_context`.
- Include metadata:
  - `hub_state_key`
  - `last_updated`
  - `freshness_status` (`fresh | stale | missing`)
  - `source_version`

**Why**: The model can trust hub context only when it’s fresh and visible.

### 3. PacketBuilder Integration
**Files**: `remora/memory/packet_builder.py`
- On packet build, attempt to fetch hub context for the node.
- If `fresh`, inject into decision packet.
- If `stale` or `missing`, add a **warning string** to the packet so the model
  knows it should fallback to tool-derived context.

**Why**: Guarantees the model never blindly trusts stale context.

### 4. Trace Store Linkage
**Files**: `remora/memory/trace_store.py`
- When hub context is used, append a trace entry:
  - `hub_state_key`
  - `hub_last_updated`
  - `freshness_status`

**Why**: Auditors can see exactly which hub state influenced decisions.

### 5. Summarizer Optimization
**Files**: `remora/memory/summarizers.py`
- If hub context already includes signatures/callers/tests, summarizers can:
  - Skip recomputation
  - Add `hub_used=true` in packet deltas

**Why**: Reduces redundant computation and keeps packet size smaller.

### 6. Optional Feedback Loop (Non-Blocking)
**Files**: `remora/hub/daemon.py`
- Allow agents to emit a “hub update hint” event if new facts are discovered.
- Hub daemon can pull these hints asynchronously and refresh state.
- No agent run should block on hub writes.

**Why**: Lets agents improve hub quality without introducing runtime coupling.

---

## Success Criteria (Soft Coupling)
- Decision packets include hub context only when fresh.
- Stale/missing hub state is clearly marked and safe.
- Trace logs show explicit hub usage with timestamps.
- Agents still run without hub being available.
