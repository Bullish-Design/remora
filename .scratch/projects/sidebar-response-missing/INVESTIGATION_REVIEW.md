# Investigation Review: Sidebar Response Missing

Date: 2026-03-09
Reviewer: Independent pass over codebase + report

---

## Summary Verdict

The root cause analysis in `INVESTIGATION_REPORT.md` is correct. The architectural direction (Option C) is the right long-term answer. However, the proposed implementation is more complex than necessary in several places, and there are additional simplification opportunities visible in the code that the report doesn't capture. This review restates the architecture more precisely, scales down the implementation scope, and calls out areas where we can simplify the codebase as part of the fix.

---

## Confirming the Root Cause

The chain is exactly as reported:

1. `emit_agent_event()` in `server.py` emits `AgentEvent(event_type="AgentTextResponse", agent_id="...", ...)`.
2. `EventStore.append()` extracts `from_agent = getattr(event, "from_agent", None)` → `None`, `to_agent` → `None`. The `agent_id` is stored only inside the JSON payload blob, not as a DB column.
3. `fetch_recent_event_rows` queries `WHERE from_agent = ? OR to_agent = ?` — both are null, so the event is invisible.
4. Panel history load (when panel was closed during run) returns 1 event instead of 9.

The fix is unambiguous: `agent_id` must be a first-class DB column, not a payload-only field.

---

## Where the Report Is Right

1. **Do not broaden the existing query with `json_extract(payload, '$.agent_id')`**. JSON-extracted queries have no index support, they silently change semantics for all callers, and they're a maintenance trap.

2. **Split query intent**. `get_recent_events` is currently used for two incompatible purposes: "what messages has this agent exchanged?" (chat history in `turn_context`) and "what events involve this agent?" (UI panel/hover timeline). These have different semantics and different callsites that will diverge further over time.

3. **Canonical envelope parity matters**. Live events and replay events reaching the panel have different shapes right now, and the panel compensates with fragile `ev.X or ev.payload.X` fallback reads.

---

## Where the Report Overcomplicates

### The `event_participants` table is not needed

The report proposes a separate `event_participants(event_id, agent_id, role)` projection table for timeline lookups. This is overkill for the current event model:

- Events currently have at most one `agent_id` (subject), one `from_agent`, and one `to_agent`. No event has multiple subject agents.
- The union query `WHERE agent_id = ? OR from_agent = ? OR to_agent = ?` with three separate indexed columns is already fast and correct.
- A separate participant table introduces a write-time join and a read-time join for zero practical benefit at current scale.

The right solution is simpler: add `agent_id` as a proper DB column, index it, and update the query. Done. Reserve the `event_participants` table for when events genuinely have multiple agent subjects (bootstrap coordination patterns, multi-agent parallel execution) — and even then, evaluate whether a normalized relation is needed or whether the column approach still suffices.

### The envelope parity fix is simpler than described

The report describes this as requiring a "canonical serializer/deserializer utility" and a pipeline overhaul. In practice, two targeted changes fix the shape mismatch:

1. **`row_to_event_dict`**: Add `"agent_id"` to the returned top-level dict, reading from the new DB column. Currently `agent_id` appears in `meta_keys` (so it's excluded from `nested_payload`) but is also not in the return dict — it disappears entirely in the replay path.

2. **`emit_event` in `server.py`**: `event_store.append()` already returns the DB row id. Merge it into the notification payload:
   ```python
   event_id = await self.event_store.append("swarm", event)
   self.protocol.notify("$/remora/event", {**event.model_dump(), "id": event_id})
   ```
   Live events then have a stable `id` that the panel can use for deduplication. This directly fixes the panel merge/dedupe fragility without any other changes.

These two changes bring live and replay event shapes into alignment at the fields the panel actually uses, without inventing a new envelope format.

---

## Complete Change Set (Precise Scope)

### 1. Schema: `event_store_schema.py`

Add `agent_id TEXT` column to `events` table (CREATE TABLE) and to `migrate()`:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    graph_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    timestamp REAL NOT NULL,
    created_at REAL NOT NULL,
    agent_id TEXT,          -- NEW: subject agent; null for routing-only events
    from_agent TEXT,
    to_agent TEXT,
    correlation_id TEXT,
    tags TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_agent_id ON events(agent_id);
```

### 2. Store write: `event_store.py`

In `append()` and `batch_append()`, extract and store `agent_id`:

```python
agent_id = getattr(event, "agent_id", None)
```

Include it in the `INSERT` statement.

### 3. Query: `event_store_queries.py`

Rename `fetch_recent_event_rows` to `fetch_agent_timeline_rows` and update predicate:

```sql
SELECT * FROM events
WHERE agent_id = ? OR from_agent = ? OR to_agent = ?
ORDER BY timestamp DESC, id DESC
LIMIT ?
```

Add a new `fetch_routed_message_rows` that preserves the existing `from_agent/to_agent` predicate (for chat history use).

Update `row_to_event_dict` to return `agent_id` at top level from the DB column.

### 4. EventStore API: `event_store.py`

Replace `get_recent_events(agent_id, limit)` with two explicit methods:

- `get_agent_timeline(agent_id, limit)` — panel, hover, bootstrap event_read
- `get_routed_messages(agent_id, limit)` — turn_context chat history assembly

### 5. Callsites

| File | Current call | New call |
|---|---|---|
| `lsp/handlers/commands.py` | `get_recent_events(agent.node_id, limit=50)` | `get_agent_timeline(agent.node_id, limit=50)` |
| `lsp/handlers/hover.py` | `get_recent_events(agent.node_id, limit=5)` | `get_agent_timeline(agent.node_id, limit=5)` |
| `core/agents/turn_context.py` | `get_recent_events(node.node_id, limit=...)` | `get_routed_messages(node.node_id, limit=...)` |
| `bootstrap/bedrock.py` | `get_recent_events(target_agent, limit=limit)` | `get_agent_timeline(target_agent, limit=limit)` |

### 6. LSP notify: `lsp/server.py`

```python
event_id = await self.event_store.append("swarm", event)
self.protocol.notify("$/remora/event", {**event.model_dump(), "id": event_id})
```

No event_store? Keep existing path (tests that don't wire up a store still work).

### 7. Tests: `tests/unit/test_event_store_queries.py`

- Rename `TestGetRecentEvents` → `TestGetAgentTimeline`, update to assert that `AgentStartEvent` (agent_id-only) **does** appear in timeline results (reversing the existing assertion in `test_matches_events_without_routing_fields`).
- Add `TestGetRoutedMessages` asserting `AgentStartEvent` does **not** appear.
- Add regression: emit `AgentTextResponse`-style event (AgentEvent with event_type="AgentTextResponse"), assert it appears in `get_agent_timeline` for the `agent_id`.

---

## Simplification Opportunities (Bonus Cleanup)

These are not required to fix the bug, but they're clean-up wins in the code we're touching:

### A. `BootstrapEvent` should use `agent_id`, not `node_id`

`bedrock.py` defines its own `BootstrapEvent` with `node_id: str | None`. The core event system uses `agent_id`. This is a divergence with no benefit — bootstrap agents have agent_ids. Change `BootstrapEvent.node_id` → `BootstrapEvent.agent_id` and populate it from `agent_id` in `_event_write`. This makes bootstrap events first-class citizens in the new `agent_id` column and timeline queries.

### B. `row_to_event_dict` meta_keys list is fragile

The current implementation scans the stored JSON, manually excludes a hardcoded `meta_keys` set, and puts the remainder into `nested_payload`. This is brittle: if a new field is added to any event model that happens to share a name with a meta key, it silently disappears.

A cleaner approach: read meta fields explicitly from DB columns (which are authoritative), and derive `nested_payload` only from the stored `payload` sub-dict (which exists on `AgentEvent` subclasses) plus any non-meta model fields for other event types. The current "build it from JSON minus meta_keys" approach is doing more work than necessary.

### C. `AgentEvent` is a stringly-typed event envelope

`AgentEvent` has an `event_type: str` field so callers can inject arbitrary type names like `"AgentTextResponse"`. This bypasses Python's type system — `AgentTextResponse` has no class, just a string. This is the exact pattern that caused the identity crisis in the first place: `AgentEvent` was designed as a "subject-scoped" event (identified by `agent_id`), while `AgentMessageEvent` is a "routing" event (identified by `from_agent`/`to_agent`), and they live in the same class hierarchy.

The cleanest long-term fix (separate from the bug fix) would be to make `AgentTextResponse` a proper frozen Pydantic class with `agent_id`, `content`, and `summary`. This makes the type explicit, enables static analysis, and removes the need for `emit_agent_event()` as a helper (the caller just constructs the typed event directly). Not required for this fix, but worth tracking.

### D. Chat history assembly in `turn_context` deserves scrutiny

`build_turn_context` currently fetches recent events via (currently) `get_recent_events`, then manually assembles chat history by filtering for `AgentMessageEvent` and checking `to_agent`/`from_agent`. A few observations:

1. After the API split, this should use `get_routed_messages` — it only cares about routed messages.
2. There's an open question: should `AgentTextResponse` events appear in the LLM's chat history as "assistant" turns? Currently they don't. The current code only counts `AgentMessageEvent` as assistant turns, which represents inter-agent messages, not the agent's own text responses. If an agent responds to a human chat via `AgentTextResponse`, the next turn won't have that response in its history. This may be intentional (the response is already in the workspace) or a gap. Worth a design decision.

---

## Implementation Order

1. **Schema migration** — add `agent_id` column and index (migrations are already wired)
2. **`append()` + `batch_append()`** — extract and store `agent_id`
3. **Query rename and update** — `fetch_agent_timeline_rows` + `fetch_routed_message_rows`
4. **`row_to_event_dict`** — add `agent_id` at top level from DB column
5. **EventStore API** — `get_agent_timeline` + `get_routed_messages` replacing `get_recent_events`
6. **`emit_event`** — include `id` in notification
7. **Callsites** — update 4 files to use correct new API
8. **`BootstrapEvent.node_id → agent_id`** (bonus, low risk)
9. **Tests** — update existing + add regression tests

This is a contained, linear change set. No new abstractions, no new tables, no new serialization utilities. The total diff is probably 150-200 lines across 8 files.

---

## What This Does NOT Fix (and Why That's OK)

- **`AgentEvent` stringly-typed pattern**: The pattern is awkward but not the root cause. The root cause is the missing DB column, not the event class hierarchy. Fixing the class hierarchy is a larger refactor that can happen independently.
- **`event_participants` table**: Not needed. The OR-query with indexed columns handles current requirements.
- **Full canonical envelope unification**: The targeted fixes to `row_to_event_dict` and `emit_event` bring the shapes into alignment without a full rewrite of the serialization layer.

---

## Regression Test Specification

After implementation, the following tests must pass:

1. **Panel-closed replay**: Emit `AgentEvent(event_type="AgentTextResponse", agent_id="X", ...)`, then fetch `get_agent_timeline("X")` → should return the event.

2. **Live/replay id parity**: `emit_event()` notification should include `id`; replayed `row_to_event_dict` should include `id`; both should be the same integer.

3. **`agent_id` top-level parity**: Both live (`event.model_dump()` + id) and replayed (`row_to_event_dict`) should have `agent_id` at the top level for AgentEvent subclasses.

4. **Chat history isolation**: `get_routed_messages` should NOT return `AgentStartEvent`, `AgentCompleteEvent`, or `AgentEvent` (agent_id-only events).

5. **Timeline inclusion**: `get_agent_timeline` SHOULD return `AgentStartEvent` for the matching `agent_id`.

6. **Bootstrap events**: `BootstrapEvent` written via `event_write` should appear in `get_agent_timeline(agent_id)` for the writing agent.
