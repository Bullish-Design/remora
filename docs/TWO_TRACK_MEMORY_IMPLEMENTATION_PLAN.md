# Two-Track Memory Implementation Plan

## Goal
Refactor Remora’s core runner to use two-track memory:
- **Short track**: compact decision packets only (model input).
- **Long track**: full trace of tool calls and outputs (audit/reporting).

This plan assumes **no hub exists yet**. Storage is **repo-local** under `.agentfs/`.

---

## High-Level Architecture
- **Short Track (Decision Packet)**
  - Built from a base schema + per-agent extensions.
  - Stored in memory for the active run; optionally persisted for debugging.
- **Long Track (Event Trace)**
  - Append-only trace entries stored in `.agentfs/traces/` (Fsdantic KV).
  - Indexed by `run`, `node`, and `operation` for fast lookups.

---

## Storage Layout (Repo-local)
- `.agentfs/` (new top-level folder)
  - `traces/` → Fsdantic KV database for long-track logs
  - (future) `nodes/` → hub state/markdown

**Key conventions** (KV):
- `trace:{run_id}:{operation}:{node_id}:{turn}` → `TraceEntry`
- `index:node:{node_id}` → list of trace keys
- `index:run:{run_id}` → list of trace keys
- `index:operation:{operation}` → list of trace keys

---

## Phase 1 — Schema & Config
### 1. Add config settings
**Files**: `remora/config.py`
- Add `RunnerMemoryConfig` to `RunnerConfig`:
  - `enabled: bool = True`
  - `packet_size_limit: int = 3000`
  - `trace_store: Literal["kv"] = "kv"`
  - `summarizer_mode: Literal["tool_specific", "fallback"] = "tool_specific"`
  - `trace_indexing: list[str] = ["node", "run", "operation"]`

### 2. Define schemas
**Files**: new module `remora/memory/schemas.py`
- `DecisionPacket` (base schema):
  - `session_id`, `turn`, `node`, `state_summary`, `diagnostics`,
    `candidate_actions`, `recent_results`, `constraints`
- `TraceEntry` schema:
  - `turn`, `timestamp`, `tool`, `args`, `raw_output`, `parsed_output`, `packet_delta`
- `PacketDelta` schema:
  - partial updates to short track

**Acceptance**:
- `pydantic` validation for all schemas.
- Unknown/agent-specific fields allowed via extensions.

---

## Phase 2 — Trace Store
### 3. Implement TraceStore
**Files**: `remora/memory/trace_store.py`
- Use `Fsdantic.open(path=".agentfs/traces/workspace.db")`.
- Methods:
  - `append(entry: TraceEntry)`
  - `index(entry)`
  - `list_by_node(node_id)`
  - `list_by_run(run_id)`
  - `list_by_operation(operation)`

### 4. Initialize storage
**Files**: `remora/orchestrator.py`, `remora/runner.py`
- Ensure `.agentfs/` exists (create at startup).
- Runner creates a `TraceStore` instance per agent run.

**Acceptance**:
- Trace entries are written during a run.
- KV index lists resolve to the correct trace entries.

---

## Phase 3 — Packet Builder & Summarizers
### 5. Implement PacketBuilder
**Files**: `remora/memory/packet_builder.py`
- Holds current `DecisionPacket` state.
- `apply_delta(delta: PacketDelta)` to update packet.
- Enforce size limit: truncate long lists or summaries.

### 6. Summarizer framework
**Files**: `remora/memory/summarizers.py`
- Registry for tool-specific summarizers.
- Default fallback summarizer:
  - Coerces tool output to a short summary string.
- Summarizers return `PacketDelta` objects.

**Acceptance**:
- Known tools produce structured deltas.
- Unknown tools still yield minimal, safe deltas.

---

## Phase 4 — Runner Refactor
### 7. Replace transcript usage
**Files**: `remora/runner.py`
- Build model input only from `DecisionPacket`.
- Remove raw tool outputs from `self.messages`.
- Store long-track tool output in trace store only.

### 8. Tool call lifecycle
- On tool call:
  1. Append trace entry (tool call + args)
  2. Execute tool (Grail)
  3. Append trace entry with raw output + parsed output
  4. Run summarizer → `PacketDelta`
  5. Update `DecisionPacket`

### 9. Event stream updates
**Files**: `remora/events.py`, `remora/runner.py`
- Emit a summary of the decision packet (not full tool output).
- Include trace key references for debugging.

**Acceptance**:
- Model never sees raw tool output.
- Tool outputs are fully preserved in long track.

---

## Phase 5 — Tests & Validation
### 10. Minimal unit tests
**Files**: `tests/`
- Validate packet size limits
- Validate trace append + index
- Validate summarizer fallback behavior

### 11. Integration test
- Run a single agent and confirm:
  - Decision packet remains bounded
  - Trace entries exist in `.agentfs/traces/`
  - Summaries match tool outputs

---

## Operational Notes
- `.agentfs/` should be added to watcher ignore patterns.
- Consider adding `.agentfs/` to `.gitignore` for dev usage.
- Long-track logs can be used for demos and audits.

---

## Success Criteria
- All models operate using short-track packets only.
- Every tool result is recorded in long track.
- Trace entries are queryable by run/node/operation.
- System runs end-to-end without backward compatibility concerns.
