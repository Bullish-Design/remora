# Sidebar Response Missing: Deep Investigation + Fundamental Architecture Fix

Date: 2026-03-09

## Scope

Determine whether the prior fix proposal is a true root-cause fix, identify what else is impacted by a fundamental correction, and propose the cleanest long-term architecture (without backward-compat constraints).

## Executive Summary

The original diagnosis is correct for the observed failure:
- panel history query uses only `from_agent` / `to_agent`
- many UI-relevant events (including `AgentTextResponse`) are keyed by `agent_id` and have empty routing fields
- when the panel is closed during execution, live events are not accumulated, so history query correctness is critical

However, the recommended tactical patch (broadening the existing `get_recent_events` query) is **not** the cleanest system-wide fix because `get_recent_events` is semantically overloaded across callers with incompatible intent. A global semantic change there would introduce regressions and further ambiguity.

The clean architecture fix is:
1. Split event history APIs by intent (`routed_messages` vs `agent_timeline`).
2. Standardize a single canonical event envelope for both live notifications and DB replay.
3. Add an explicit participant index/projection for timeline queries.

## Fresh Environment Validation (Re-run)

Artifacts used:
- `/home/andrew/Documents/Projects/remora-example-workspace/.remora/logs/client-2026-03-09_171332.log`
- `/home/andrew/Documents/Projects/remora-example-workspace/.remora/logs/server-2026-03-09_171444.log`
- `/home/andrew/Documents/Projects/remora-example-workspace/.remora/events/events.db`

Validated chain:
1. Panel was closed, requestInput used fallback input path.
2. Server emitted full response events including `AgentTextResponse`.
3. Later panel open fetched only one event (`count=1`).
4. DB row-level evidence for correlation `corr_1_a554b116` shows:
- routed-column filter finds 1 event
- payload `agent_id` filter finds 9 events

Conclusion: this is a real query/schema mismatch, not a model (vLLM) failure.

## Root Cause (Precise)

### Immediate failure root cause

`cmd_get_agent_panel` calls `EventStore.get_recent_events(agent_id, limit=50)`, but current query is:
- `WHERE from_agent = ? OR to_agent = ?`

`AgentTextResponse` is emitted as `AgentEvent(event_type="AgentTextResponse", agent_id=...)` with no `from_agent` / `to_agent`, so it is excluded from panel history retrieval.

### Deeper architectural root cause

The system mixes two incompatible identity/routing models:

1. Routing model:
- `from_agent`, `to_agent`
- used for subscriptions and direct message triggering

2. Subject/timeline model:
- `agent_id`
- used by agent lifecycle/kernel/response UI events

A single retrieval API (`get_recent_events`) is currently used for both models, which creates ambiguity and drift.

## Additional Alignment Defects Found

These are separate from the immediate bug but tightly related:

1. Live event shape and replay event shape are different.
- Live notify path sends `event.model_dump()` directly.
- Replay path uses `row_to_event_dict()` normalization.
- Consumers (especially panel) compensate inconsistently with mixed top-level/payload reads.

2. Replay dict currently omits top-level `agent_id`.
- `row_to_event_dict()` excludes `agent_id` from returned top-level fields.
- This weakens identity consistency for replayed events.

3. Live events do not include persisted DB `id`.
- Panel merge/dedupe logic is id-based for server events.
- Missing IDs on live notifications creates duplicate/merge fragility.

4. Caller intent conflict on `get_recent_events`:
- Panel/hover want timeline-like events.
- `turn_context` chat history wants routed message history semantics and small limits.
- Bootstrap `event_read` currently inherits whichever semantics this API has.

5. Existing tests encode the mismatch as expected behavior.
- Current tests explicitly assert that `AgentStartEvent` (agent_id-only) does not appear in `get_recent_events`.

## Impact Analysis: What Changes If We “Fix It Properly”

### If we only broaden current query (`OR json_extract(payload,'$.agent_id')`)

Pros:
- fixes this panel symptom quickly.

Cons:
- silently changes semantics for all `get_recent_events` consumers.
- can degrade chat-history retrieval quality because non-message events can consume the limit window.
- perpetuates overloaded API ambiguity.
- relies on JSON extraction for core query behavior.

### If we implement explicit query intent + canonical envelope (recommended)

Directly impacted callsites:
- `src/remora/lsp/handlers/commands.py` (`cmd_get_agent_panel`)
- `src/remora/lsp/handlers/hover.py`
- `src/remora/core/agents/turn_context.py`
- `src/remora/bootstrap/bedrock.py`
- panel rendering assumptions in `src/remora/lsp/nvim/lua/remora/panel.lua`
- event serialization/notify path in `src/remora/lsp/server.py`
- event store schema/query/normalization in `src/remora/core/store/*`

Test impact:
- `tests/unit/test_event_store_queries.py` (major rewrite)
- `tests/unit/bootstrap/test_bedrock.py` (method name/intent updates)
- new integration/regression tests required for panel-closed replay correctness and live/replay envelope parity.

## Recommended Target Architecture (No Backward-Compat Mode)

### 1) Replace overloaded history API with intent-specific APIs

Remove `get_recent_events` and introduce:
- `get_recent_routed_messages(agent_id, limit=...)`
- `get_recent_agent_timeline(agent_id, limit=..., event_types=None)`

Policy:
- `turn_context` uses routed messages (or correlation-scoped history).
- panel and hover use agent timeline.
- bootstrap `event_read` should explicitly choose one (or expose selector flag).

### 2) Canonical event envelope for both live and replay

Define one canonical shape returned everywhere:
- `id`
- `graph_id`
- `event_type`
- `timestamp`
- `created_at`
- `correlation_id`
- `agent_id`
- `from_agent`
- `to_agent`
- `summary`
- `payload`

Requirements:
- live LSP `$/remora/event` notifications must use this same envelope.
- replay query output must be byte-for-byte schema-compatible.

### 3) Participant index/projection for timeline lookups

Create `event_participants` projection (or equivalent indexed projection) keyed by `(event_id, agent_id, role)`.

Why:
- avoids coupling timeline queries to ad-hoc JSON extraction or a single routing column pair.
- future-proofs event models with multiple agent relationships.
- enables simple, indexed timeline queries for UI.

### 4) Keep routing semantics explicit and separate

Subscriptions remain based on routing fields / event patterns.
Do not conflate trigger routing with UI timeline ownership.

### 5) Tighten consumer contracts

- panel renderer should use canonical top-level routing/identity fields, not mixed payload fallbacks for core metadata.
- merge/dedupe should use stable event IDs from both live and replay.
- hover should read canonical summary field, not payload-only summary assumptions.

## Proposed Implementation Roadmap

1. Event envelope + store core
- add canonical serializer/deserializer utilities.
- update append path to emit canonical envelope + return persisted `id`.
- update LSP notify path to publish canonical envelopes.

2. Schema + queries
- add `agent_id` column to events if missing.
- add `event_participants` table and indexes.
- add timeline and routed-message query helpers.

3. API split
- replace `get_recent_events` with two explicit methods.
- update all callsites.

4. UI alignment
- simplify panel event parsing to canonical envelope only.
- ensure dedupe/merge by `id`.

5. Testing and invariants
- regression: “panel closed during run, later open shows AgentTextResponse.”
- invariant: every live-emitted event is retrievable by corresponding history API.
- invariant: live and replay envelopes have same required fields.
- performance sanity: timeline query uses participant indexes.

## Why This Is Better Than the Tactical Patch

The tactical query patch solves one symptom but preserves a broken boundary:
- one method, multiple meanings
- one event stream, multiple incompatible shapes
- one UI relying on fallback heuristics

The recommended design creates clear contracts:
- explicit query intent
- explicit event ownership indexing
- explicit envelope consistency across transport and storage

This directly prevents recurrence of this class of bug.

## Final Recommendation

Proceed with the architectural fix (API split + canonical envelope + participant index), not a single-query patch.

This is the cleanest path to strong alignment and will eliminate this issue class systematically instead of episodically.
