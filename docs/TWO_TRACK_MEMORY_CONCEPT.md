# Two‑Track Memory Concept

## Purpose

Two‑track memory is a **core runner primitive** that keeps FunctionGemma decision context small while preserving a full, auditable trace of tool activity. Every FunctionGemma run produces:

1. **Short Track (Decision Packet)** — compact, structured context used for model decisions.
2. **Long Track (Event Trace)** — full tool outputs and raw logs stored for audits, reports, and escalation.

This makes agent behavior consistent, observable, and safe at scale.

---

## Core Principles

- **Bounded context**: the model never sees raw tool output.
- **Deterministic summarization**: tools output full data; summarizers emit short‑track deltas.
- **Trace first**: every action is logged and replayable.
- **Schema‑driven**: short‑track and long‑track data are validated.

---

## Architecture

### Execution Flow

1. **Build decision packet** from current short‑track state.
2. **FunctionGemma chooses** a tool call based on packet + constraints.
3. **Tool executes** in Cairn workspace.
4. **Trace entry is appended** with raw + parsed output.
5. **Summarizer emits packet delta** to update short track.

### Storage Strategy (Remora/Cairn KV)

Use a **per‑operation trace log** as the primary write path, then build aggregate views via KV indexes.

**Primary trace keys**
- `trace:{run_id}:{operation}:{node_id}:{turn}` → trace entry (JSON)

**Index keys**
- `index:node:{node_id}` → list of trace keys
- `index:run:{run_id}` → list of trace keys
- `index:operation:{operation}` → list of trace keys

This keeps writes simple while enabling fast regrouping per node or per run.

---

## Short Track (Decision Packet)

The decision packet is the **only** context the model sees.

```json
{
  "session_id": "dbg_abc123",
  "turn": 6,
  "node": {"id": "func_process", "type": "function"},
  "state_summary": "Assertion failed in process_data; local var result=None",
  "diagnostics": ["AssertionError", "result is None"],
  "candidate_actions": [
    {"tool": "print_var", "args": {"name": "result"}, "reason": "Check None value"},
    {"tool": "list_frames", "args": {}, "reason": "Inspect call stack"}
  ],
  "recent_results": [
    {"tool": "list_frames", "summary": "3 frames; user code at frame 1"}
  ],
  "constraints": {"max_turns": 20, "safety": ["no_eval_exec"]}
}
```

**Schema approach**
- **Hybrid core + extensions**: a shared base schema with optional per‑agent extensions.

---

## Long Track (Event Trace)

The long track is an append‑only log of actions and outputs.

```json
{
  "turn": 6,
  "timestamp": "2026-02-19T15:42:10Z",
  "tool": "print_var",
  "args": {"name": "result"},
  "raw_output": "None",
  "parsed_output": {"value": null},
  "packet_delta": {"diagnostics": ["result is None"]}
}
```

**Schema approach**
- Stored as JSONL or KV records keyed by turn.
- Raw output is preserved for audits and escalation.

---

## Summarizers

Summarizers translate tool output into short‑track deltas.

**Preferred strategy**: tool‑specific summarizers for high‑value tools, with generic fallbacks for new tools.

---

## Benefits

- **Predictable context size**: safe for small models.
- **Full traceability**: decisions can be audited and replayed.
- **LLM escalation ready**: long track becomes a context blob for larger models.
- **Reporting‑friendly**: easy to generate standardized summaries.

---

## Integration with Remora

### Runner
- Add a **TraceStore** and **PacketBuilder** to `FunctionGemmaRunner`.
- Enforce packet size limits and short‑track schemas.

### Tools
- Tools remain unchanged, but outputs are captured by the trace layer.
- Optional per‑tool summarizers can be registered in subagent YAML.

### Configuration Sketch

```yaml
runner:
  memory:
    enabled: true
    packet_size_limit: 3000
    trace_store: "kv"
    summarizer_mode: "tool_specific"
    trace_indexing: ["node", "run", "operation"]
```

---

## Open Questions

1. **Packet extension rules**: how per‑agent fields are registered and validated.
2. **Summarizer defaults**: which tools require custom summarizers first.
3. **Trace retention**: how long to keep full logs and when to compact.
